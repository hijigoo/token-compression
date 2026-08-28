"""토큰 계산과 API usage 정규화.

두 가지를 구분합니다.

  로컬 계산   tiktoken 이 있으면 정확, 없으면 문자 기준 근사.
              수백 건 × 스윕을 돌려야 하므로 오프라인 계산이 필요합니다.
  API 실측    응답의 usage. 과금 기준이지만 호출해야 나옵니다.

어느 쪽으로 쟀는지는 metrics.json 의 `token_backend` 에 남습니다.
이 값이 다르면 두 실행의 숫자를 나란히 놓으면 안 됩니다.
"""

from __future__ import annotations

import os

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

_ENC_BY_PREFIX = [
    ("gpt-5", "o200k_base"), ("gpt-4.1", "o200k_base"), ("gpt-4o", "o200k_base"),
    ("o1", "o200k_base"), ("o3", "o200k_base"), ("o4", "o200k_base"),
    ("gpt-4", "cl100k_base"), ("gpt-3.5", "cl100k_base"),
]
DEFAULT_ENCODING = "o200k_base"
_cache: Dict[str, Any] = {}

_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_CJK = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
_WORD = re.compile(r"[A-Za-z0-9]+")


def encoding_for(model: Optional[str] = None) -> str:
    m = (model or "").lower()
    for prefix, enc in _ENC_BY_PREFIX:
        if m.startswith(prefix):
            return enc
    return DEFAULT_ENCODING


def _encoder(name: str):
    if name not in _cache:
        try:
            import tiktoken
            _cache[name] = tiktoken.get_encoding(name)
        except Exception:
            _cache[name] = None
    return _cache[name]


def _fallback(text: str) -> int:
    """tiktoken 이 없을 때의 근사. 정확도가 아니라 '돌아가게' 하는 것이 목적입니다."""
    if not text:
        return 0
    hangul = len(_HANGUL.findall(text))
    cjk = len(_CJK.findall(text))
    words = _WORD.findall(text)
    word_tokens = sum(max(1, round(len(w) / 4)) for w in words)
    rest = max(0, len(text) - hangul - cjk - sum(len(w) for w in words))
    return int(round(hangul * 0.7 + cjk + word_tokens + rest * 0.28))


def count(text: str, model: Optional[str] = None) -> int:
    if not text:
        return 0
    enc = _encoder(encoding_for(model))
    if enc is None:
        return _fallback(text)
    try:
        return len(enc.encode(text, disallowed_special=()))
    except Exception:
        return _fallback(text)


def backend(model: Optional[str] = None) -> str:
    name = encoding_for(model)
    return f"tiktoken:{name}" if _encoder(name) is not None else "heuristic"


class LocalCounter:
    """tiktoken 또는 휴리스틱. 호출 비용 0, 대신 근사치입니다."""

    def __init__(self, model: Optional[str] = None):
        self.model = model

    @property
    def backend(self) -> str:
        return backend(self.model)

    def __call__(self, text: str, model: Optional[str] = None) -> int:
        return count(text, model or self.model)

    def save(self) -> None:
        pass

    def stats(self) -> Dict[str, int]:
        return {}

    def describe(self) -> str:
        if self.backend.startswith("heuristic"):
            return ("문자 기반 근사 — tiktoken 이 없습니다. "
                    "다른 실행과 비교하시려면 측정 방식이 같아야 합니다")
        return f"로컬 계산 ({self.backend}) — API 호출 없음"


class DualCounter:
    """API 실측을 기준값으로 쓰되, tiktoken 추정도 함께 재서 차이를 남깁니다.

    이 저장소의 **기본 측정 방식**입니다. 이유는 두 가지입니다.

      1. 과금 기준은 API 응답의 usage 입니다. 그 값을 기준으로 삼아야
         "얼마나 아꼈다" 가 실제 청구서와 맞습니다.
      2. 그렇다고 tiktoken 을 버리면, 추정이 얼마나 어긋나는지 알 수 없습니다.
         둘을 같이 재두면 나중에 "추정만으로 충분한가" 를 판단할 수 있습니다.

    ## 자격증명이 없으면

    로컬 계산으로 조용히 내려갑니다. 대신 **왜 내려갔는지 반드시 알려줍니다.**
    말없이 다른 방식으로 재면 과거 결과와 비교가 깨지기 때문입니다.

    ## 중간에 API 가 끊기면

    예외를 냅니다. 앞쪽은 실측, 뒤쪽은 추정으로 재면 한 실행 안에서 측정
    방식이 섞여서 합계가 아무 뜻도 없어집니다. 조용히 이어가는 것보다
    멈추는 편이 낫습니다.
    """

    def __init__(self, model: Optional[str] = None, deployment: Optional[str] = None,
                 cache: bool = True, refresh: bool = False,
                 endpoint: Optional[str] = None):
        self.local = LocalCounter(model)
        self.api = None
        self.fallback_reason: Optional[str] = None
        self._l_total = self._a_total = self._n = 0

        try:
            from .provider import ApiCounter
            api = ApiCounter(deployment=deployment or model or "",
                             endpoint=endpoint, cache=cache, refresh=refresh)
            # 실제로 되는지 짧은 문자열로 한 번 확인합니다. 여기서 걸러야
            # 실행 도중에 절반만 실측되는 일이 안 생깁니다.
            api("ping")
            self.api = api
        except Exception as e:
            self.fallback_reason = f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"

    @property
    def preloaded(self) -> int:
        return getattr(self.api, "preloaded", 0)

    @property
    def backend(self) -> str:
        if self.api is None:
            return self.local.backend
        return f"{self.api.backend}+{self.local.backend}"

    def __call__(self, text: str, model: Optional[str] = None) -> int:
        lv = self.local(text)
        if self.api is None:
            return lv
        try:
            av = self.api(text)
        except Exception as e:
            raise RuntimeError(
                f"실행 도중 API 측정이 끊겼습니다 — {type(e).__name__}: {e}\n"
                f"  여기서 로컬 계산으로 이어가면 앞쪽은 실측, 뒤쪽은 추정이 되어\n"
                f"  합계가 아무 뜻도 없어집니다. 그래서 멈춥니다.\n"
                f"  네트워크 없이 돌리시려면 tokenizer.mode 를 local 로 바꿔주세요."
            ) from e
        self._l_total += lv
        self._a_total += av
        self._n += 1
        return av

    @property
    def gap_pp(self) -> Optional[float]:
        """같은 텍스트를 두 방식으로 쟀을 때 몇 % 어긋났는지."""
        if not self._l_total or self.api is None:
            return None
        return round((self._a_total - self._l_total) / self._l_total * 100, 2)

    def save(self) -> None:
        if self.api is not None:
            self.api.save()

    def stats(self) -> Dict[str, Any]:
        if self.api is None:
            return {"mode": "local-fallback", "reason": self.fallback_reason or ""}
        s = dict(self.api.stats())
        s.update({"mode": "both", "local_total": self._l_total,
                  "api_total": self._a_total, "gap_pct": self.gap_pp})
        return s

    def describe(self) -> str:
        if self.api is None:
            return (f"tiktoken 추정만 사용 — API 를 쓸 수 없습니다 "
                    f"({self.fallback_reason}). 과금 기준과 다를 수 있습니다")
        gap = self.gap_pp
        gap_txt = "" if gap is None else f" · 추정과 {gap:+.1f}% 차이"
        return f"API 실측 기준 + tiktoken 추정 병행{gap_txt} · {self.api.describe()}"


def make_counter(spec: Optional[Dict[str, Any]] = None, model: Optional[str] = None):
    """설정에 따라 토큰 카운터를 만듭니다.

        tokenizer:
          mode: both             # both(기본) | api | local
          deployment: gpt-5.4    # 비우면 .env 의 AZURE_OPENAI_DEPLOYMENT
          cache: true            # 같은 텍스트는 한 번만 호출
          refresh: false         # true 면 캐시를 무시하고 다시 부릅니다

    ## 어느 것을 고를까요

    | mode | 기준값 | 언제 |
    |---|---|---|
    | `both` | API 실측 | **기본값.** 과금 기준으로 재면서 추정 오차도 같이 봅니다 |
    | `api` | API 실측 | 과금 값만 필요하고 tiktoken 계산을 아끼고 싶을 때 |
    | `local` | tiktoken | 네트워크·자격증명 없이, 또는 호출을 아예 막고 싶을 때 |

    `both` 는 자격증명이 없으면 로컬로 내려가되 **이유를 알려줍니다.**
    `api` 는 같은 상황에서 예외를 냅니다 — 반드시 실측이 필요하다고
    선언한 것이므로 조용히 다른 값을 주면 안 되기 때문입니다.
    """
    spec = dict(spec or {})
    mode = (spec.get("mode") or "both").lower()
    deployment = spec.get("deployment") or os.environ.get("AZURE_OPENAI_DEPLOYMENT")

    if mode == "local":
        return LocalCounter(model)

    if mode == "both":
        return DualCounter(
            model=model,
            deployment=deployment or model,
            endpoint=spec.get("endpoint"),
            cache=spec.get("cache", True),
            refresh=spec.get("refresh", False),
        )

    if mode == "api":
        from .provider import ApiCounter
        return ApiCounter(
            deployment=deployment or model or "",
            endpoint=spec.get("endpoint"),
            cache=spec.get("cache", True),
            api_version=spec.get("api_version", "preview"),
            refresh=spec.get("refresh", False),
        )

    raise ValueError(f"알 수 없는 tokenizer.mode: {mode} (both | api | local)")


def _get(obj: Any, *names: str) -> Any:
    for n in names:
        if isinstance(obj, dict):
            if obj.get(n) is not None:
                return obj[n]
        else:
            v = getattr(obj, n, None)
            if v is not None:
                return v
    return None


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


@dataclass
class Usage:
    """공급자마다 다른 usage 를 하나로 맞춘 것.

    압축 효과는 input_tokens 가 아니라 **billed_input** 으로 판단합니다.
    캐시가 잘 맞던 구간을 압축하면 토큰이 줄어도 비용은 오를 수 있습니다.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    model: Optional[str] = None
    schema: str = "unknown"

    @property
    def billed_input(self) -> int:
        return max(0, self.input_tokens - self.cached_tokens)

    @property
    def cache_hit_rate(self) -> float:
        return self.cached_tokens / self.input_tokens if self.input_tokens else 0.0

    def __add__(self, o: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + o.input_tokens, self.output_tokens + o.output_tokens,
            self.cached_tokens + o.cached_tokens, self.cache_write_tokens + o.cache_write_tokens,
            self.reasoning_tokens + o.reasoning_tokens, self.total_tokens + o.total_tokens,
            self.model or o.model, "sum",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_tokens": self.input_tokens, "cached_tokens": self.cached_tokens,
            "billed_input": self.billed_input, "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_tokens": self.total_tokens,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "model": self.model, "schema": self.schema,
        }

    @classmethod
    def from_response(cls, resp: Any, model: Optional[str] = None) -> "Usage":
        if resp is None:
            return cls()
        model = model or _get(resp, "model")

        gem = _get(resp, "usageMetadata", "usage_metadata")
        if gem is not None:
            return cls(
                input_tokens=_int(_get(gem, "promptTokenCount", "prompt_token_count")),
                output_tokens=_int(_get(gem, "candidatesTokenCount", "candidates_token_count")),
                cached_tokens=_int(_get(gem, "cachedContentTokenCount", "cached_content_token_count")),
                reasoning_tokens=_int(_get(gem, "thoughtsTokenCount", "thoughts_token_count")),
                total_tokens=_int(_get(gem, "totalTokenCount", "total_token_count")),
                model=model, schema="gemini")

        u = _get(resp, "usage") or resp

        if _get(u, "prompt_tokens") is not None:                       # Chat Completions
            d = _get(u, "prompt_tokens_details") or {}
            cd = _get(u, "completion_tokens_details") or {}
            return cls(_int(_get(u, "prompt_tokens")), _int(_get(u, "completion_tokens")),
                       _int(_get(d, "cached_tokens")), 0,
                       _int(_get(cd, "reasoning_tokens")), _int(_get(u, "total_tokens")),
                       model, "chat.completions")

        if _get(u, "cache_read_input_tokens") is not None or \
           _get(u, "cache_creation_input_tokens") is not None:          # Anthropic
            fresh = _int(_get(u, "input_tokens"))
            read = _int(_get(u, "cache_read_input_tokens"))
            write = _int(_get(u, "cache_creation_input_tokens"))
            out = _int(_get(u, "output_tokens"))
            return cls(fresh + read + write, out, read, write, 0,
                       fresh + read + write + out, model, "anthropic.messages")

        if _get(u, "input_tokens") is not None:                         # Responses API
            d = _get(u, "input_tokens_details") or {}
            od = _get(u, "output_tokens_details") or {}
            return cls(_int(_get(u, "input_tokens")), _int(_get(u, "output_tokens")),
                       _int(_get(d, "cached_tokens")), _int(_get(d, "cache_write_tokens")),
                       _int(_get(od, "reasoning_tokens")), _int(_get(u, "total_tokens")),
                       model, "responses")

        return cls(model=model, schema="unrecognized")


@dataclass
class Price:
    """1K 토큰당 단가(USD).

    cached·cache_write 는 input_tokens 에 이미 포함돼 있으므로
    일반 입력분을 구할 때 빼야 합니다. 안 그러면 이중 계산이 됩니다.
    """

    input_per_1k: float = 0.0
    output_per_1k: float = 0.0
    cached_input_per_1k: float = 0.0
    cache_write_per_1k: float = 0.0

    def cost(self, u: Usage) -> float:
        regular = max(0, u.input_tokens - u.cached_tokens - u.cache_write_tokens)
        return (regular * self.input_per_1k
                + u.cached_tokens * self.cached_input_per_1k
                + u.cache_write_tokens * (self.cache_write_per_1k or self.input_per_1k)
                + u.output_tokens * self.output_per_1k) / 1000.0

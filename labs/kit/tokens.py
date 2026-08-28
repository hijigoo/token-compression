"""토큰 계산과 API usage 정규화.

두 가지를 구분합니다.

  로컬 계산   tiktoken 이 있으면 정확, 없으면 문자 기준 근사.
              수백 건 × 스윕을 돌려야 하므로 오프라인 계산이 필요합니다.
  API 실측    응답의 usage. 과금 기준이지만 호출해야 나옵니다.

어느 쪽으로 쟀는지는 metrics.json 의 `token_backend` 에 남습니다.
이 값이 다르면 두 실행의 숫자를 나란히 놓으면 안 됩니다.
"""

from __future__ import annotations

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


def make_counter(spec: Optional[Dict[str, Any]] = None, model: Optional[str] = None):
    """설정에 따라 토큰 카운터를 만듭니다.

        tokenizer:
          mode: local            # local | api
          deployment: gpt-5.4    # mode=api 일 때 배포명
          cache: true            # 같은 텍스트는 한 번만 호출

    mode 를 생략하면 local 입니다. api 는 정확하지만 텍스트마다 호출이 붙습니다.
    """
    spec = dict(spec or {})
    mode = (spec.get("mode") or "local").lower()

    if mode == "local":
        return LocalCounter(model)

    if mode == "api":
        from .provider import ApiCounter
        return ApiCounter(
            deployment=spec.get("deployment") or model or "",
            endpoint=spec.get("endpoint"),
            cache=spec.get("cache", True),
            api_version=spec.get("api_version", "preview"),
        )

    raise ValueError(f"알 수 없는 tokenizer.mode: {mode} (local | api)")


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

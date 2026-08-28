"""nbtools — 노트북 공용 유틸.

`scripts/notebooks/` 안에서만 쓰는 모듈이다. 두 가지를 담는다.

  1) Usage / Price   API 응답의 usage 를 정규화하고 비용을 계산
  2) show_table      한글 정렬이 깨지지 않는 표 렌더링

토큰 수는 추정하지 않는다. **모델이 돌려준 실측값만** 쓴다.

왜 정규화가 필요한가
--------------------
같은 개념인데 이름과 의미가 제각각이다.

  Chat Completions  prompt_tokens / completion_tokens
  Responses API     input_tokens  / output_tokens  (+ cache_write_tokens)
  Anthropic         input_tokens 에 캐시 적중분이 **빠져** 있다
  Gemini            usageMetadata.promptTokenCount ...

정규화 없이 비교하면 Anthropic 만 입력이 1/7 로 보이는 식의 착시가 생긴다.

핵심 개념: billed_input
-----------------------
압축 효과를 판단할 때 보는 값은 input_tokens 가 아니라
**billed_input = input_tokens - cached_tokens** 다.
캐시가 잘 맞던 구간을 압축하면 토큰이 줄어도 비용은 오를 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


def _get(obj: Any, *names: str) -> Any:
    """dict 든 SDK 객체든 상관없이 첫 번째로 찾은 속성을 돌려준다."""
    for n in names:
        if isinstance(obj, dict):
            if n in obj and obj[n] is not None:
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


def _as_dict(o: Any) -> Optional[Dict[str, Any]]:
    if o is None:
        return None
    if isinstance(o, dict):
        return o
    for meth in ("model_dump", "to_dict", "dict"):
        f = getattr(o, meth, None)
        if callable(f):
            try:
                return f()
            except Exception:
                pass
    return {k: v for k, v in vars(o).items()} if hasattr(o, "__dict__") else None


@dataclass
class Usage:
    """공급자마다 다른 usage 스키마를 하나로 모은 것.

    input_tokens        전체 입력 토큰 (캐시 적중분 포함)
    cached_tokens       그중 캐시로 재사용된 분량 — 크게 할인되거나 무료
    cache_write_tokens  캐시를 새로 채운 분량 — 일부 모델은 할증
    output_tokens       생성 토큰
    reasoning_tokens    추론 모델의 내부 사고 토큰. output 에 포함되지만 눈에 안 보인다
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    model: Optional[str] = None
    schema: str = "unknown"
    raw: Optional[Dict[str, Any]] = None

    @property
    def billed_input(self) -> int:
        """정가가 붙는 입력 토큰. 압축 효과는 이 값으로 판단해야 한다."""
        return max(0, self.input_tokens - self.cached_tokens)

    @property
    def cache_hit_rate(self) -> float:
        return self.cached_tokens / self.input_tokens if self.input_tokens else 0.0

    def cost(self, price: "Price") -> float:
        return price.cost(self)

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            model=self.model or other.model,
            schema="sum",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "cached_tokens": self.cached_tokens,
            "billed_input": self.billed_input,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_tokens": self.total_tokens,
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "model": self.model,
            "schema": self.schema,
        }

    # -- 파서 ------------------------------------------------------------
    @classmethod
    def from_response(cls, resp: Any, model: Optional[str] = None) -> "Usage":
        """SDK 응답 객체(또는 dict)에서 usage 를 뽑아 정규화한다."""
        if resp is None:
            return cls()

        model = model or _get(resp, "model")

        # Gemini 는 usage 가 아니라 usageMetadata 에 들어온다
        gem = _get(resp, "usageMetadata", "usage_metadata")
        if gem is not None:
            return cls._from_gemini(gem, model)

        u = _get(resp, "usage")
        if u is None:
            u = resp  # usage 블록 자체가 넘어온 경우

        if _get(u, "prompt_tokens") is not None:
            return cls._from_chat_completions(u, model)

        if (
            _get(u, "cache_read_input_tokens") is not None
            or _get(u, "cache_creation_input_tokens") is not None
        ):
            return cls._from_anthropic(u, model)

        if _get(u, "input_tokens") is not None:
            return cls._from_responses(u, model)

        return cls(model=model, schema="unrecognized", raw=_as_dict(u))

    @classmethod
    def _from_chat_completions(cls, u: Any, model) -> "Usage":
        d = _get(u, "prompt_tokens_details") or {}
        cd = _get(u, "completion_tokens_details") or {}
        return cls(
            input_tokens=_int(_get(u, "prompt_tokens")),
            output_tokens=_int(_get(u, "completion_tokens")),
            cached_tokens=_int(_get(d, "cached_tokens")),
            reasoning_tokens=_int(_get(cd, "reasoning_tokens")),
            total_tokens=_int(_get(u, "total_tokens")),
            model=model,
            schema="chat.completions",
            raw=_as_dict(u),
        )

    @classmethod
    def _from_responses(cls, u: Any, model) -> "Usage":
        d = _get(u, "input_tokens_details") or {}
        od = _get(u, "output_tokens_details") or {}
        return cls(
            input_tokens=_int(_get(u, "input_tokens")),
            output_tokens=_int(_get(u, "output_tokens")),
            cached_tokens=_int(_get(d, "cached_tokens")),
            # Azure Responses API 는 캐시 '쓰기' 분량도 따로 준다.
            # 캐시를 새로 채우는 비용이라 일부 모델은 할증이 붙는다.
            cache_write_tokens=_int(_get(d, "cache_write_tokens")),
            reasoning_tokens=_int(_get(od, "reasoning_tokens")),
            total_tokens=_int(_get(u, "total_tokens")),
            model=model,
            schema="responses",
            raw=_as_dict(u),
        )

    @classmethod
    def _from_anthropic(cls, u: Any, model) -> "Usage":
        # Anthropic 은 input_tokens 에 캐시 적중분을 포함하지 않고 별도로 준다.
        # 다른 스키마와 맞추기 위해 여기서 합산한다.
        fresh = _int(_get(u, "input_tokens"))
        read = _int(_get(u, "cache_read_input_tokens"))
        write = _int(_get(u, "cache_creation_input_tokens"))
        out = _int(_get(u, "output_tokens"))
        return cls(
            input_tokens=fresh + read + write,
            output_tokens=out,
            cached_tokens=read,
            cache_write_tokens=write,
            total_tokens=fresh + read + write + out,
            model=model,
            schema="anthropic.messages",
            raw=_as_dict(u),
        )

    @classmethod
    def _from_gemini(cls, m: Any, model) -> "Usage":
        return cls(
            # Gemini 는 prompt 에 캐시분이 포함된다
            input_tokens=_int(_get(m, "promptTokenCount", "prompt_token_count")),
            output_tokens=_int(_get(m, "candidatesTokenCount", "candidates_token_count")),
            cached_tokens=_int(_get(m, "cachedContentTokenCount", "cached_content_token_count")),
            reasoning_tokens=_int(_get(m, "thoughtsTokenCount", "thoughts_token_count")),
            total_tokens=_int(_get(m, "totalTokenCount", "total_token_count")),
            model=model,
            schema="gemini",
            raw=_as_dict(m),
        )


@dataclass
class Price:
    """1K 토큰당 단가(USD).

    입력 토큰은 세 종류로 쪼개져 서로 다른 단가가 붙는다.

        input_tokens = 일반 입력 + 캐시 적중(cached) + 캐시 쓰기(cache_write)

      - 캐시 적중분은 보통 정가의 10~25%
      - 캐시 쓰기분은 새로 채우는 비용이라 할증이 붙기도 한다(모델마다 다름)

    cached_tokens 와 cache_write_tokens 는 input_tokens 안에 이미 포함되어 있으므로
    일반 입력분을 구할 때 반드시 빼야 한다. 안 그러면 이중 계산이 된다.
    """

    input_per_1k: float = 0.0
    output_per_1k: float = 0.0
    cached_input_per_1k: float = 0.0
    cache_write_per_1k: float = 0.0

    def cost(self, u: Usage) -> float:
        regular = max(0, u.input_tokens - u.cached_tokens - u.cache_write_tokens)
        return (
            regular * self.input_per_1k
            + u.cached_tokens * self.cached_input_per_1k
            + u.cache_write_tokens * (self.cache_write_per_1k or self.input_per_1k)
            + u.output_tokens * self.output_per_1k
        ) / 1000.0


# ---------------------------------------------------------------------------
# 표 렌더링
# ---------------------------------------------------------------------------
# 한글은 글자 폭이 ASCII 의 정확히 2배가 아니라서 공백 패딩으로는 정렬이 맞지 않는다.
# 노트북에서는 HTML 표로 그리고, 일반 파이썬으로 실행할 때는 텍스트로 떨어뜨린다.
try:
    from IPython.display import display, HTML
    from IPython import get_ipython

    _IPY = get_ipython() is not None
except Exception:
    _IPY = False


def show_table(headers, rows, foot=None, align=None, title=None, note=None):
    """헤더/행/푸터를 받아 표로 출력한다.

    align : 각 열의 정렬. 기본은 첫 열 왼쪽, 나머지 오른쪽.
    note  : 표 아래 붙는 설명.
    """
    align = align or ["left"] + ["right"] * (len(headers) - 1)

    if not _IPY:  # 텍스트 폴백
        if title:
            print(title)
        widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) + 2
                  for i, h in enumerate(headers)]

        def fmt(vs):
            return " ".join(str(v).rjust(w) if a == "right" else str(v).ljust(w)
                            for v, w, a in zip(vs, widths, align))

        print(fmt(headers))
        print("-" * sum(widths))
        for r in rows:
            print(fmt(r))
        if foot:
            print("-" * sum(widths))
            print(fmt(foot))
        if note:
            print(note)
        print()
        return

    def td(v, a, tag="td", extra=""):
        return (f'<{tag} style="text-align:{a};padding:5px 16px 5px 0;'
                f'white-space:nowrap;{extra}">{v}</{tag}>')

    head = "".join(td(h, a, "th",
                      "border-bottom:2px solid currentColor;font-weight:600;opacity:.85;")
                   for h, a in zip(headers, align))
    body = "".join("<tr>" + "".join(td(v, a) for v, a in zip(r, align)) + "</tr>"
                   for r in rows)
    if foot:
        body += "<tr>" + "".join(
            td(v, a, "td", "border-top:1px solid currentColor;font-weight:600;")
            for v, a in zip(foot, align)) + "</tr>"

    cap = f'<div style="font-weight:600;margin:6px 0 4px;">{title}</div>' if title else ""
    tail = (f'<div style="opacity:.75;margin-top:6px;font-size:12px;">{note}</div>'
            if note else "")
    display(HTML(
        f'<div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
        f'font-size:13px;line-height:1.5;">{cap}'
        f'<table style="border-collapse:collapse;">'
        f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{tail}</div>'))

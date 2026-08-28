"""LLM 요약기.

이 랩만 API 를 씁니다. 그래서 다른 랩에 없는 두 가지가 필요합니다.

    캐시    같은 입력을 두 번 부르지 않습니다. 없으면 비용이 실행 횟수에 비례합니다
    상한    실수로 큰 코퍼스를 돌렸을 때 멈춰 세웁니다

## 프롬프트 세 가지

압축률은 프롬프트가 정하는 게 아니라 **무엇을 지키라고 말했는지**가 정합니다.
세 가지를 나란히 놓고 무엇이 달라지는지 봅니다.

    plain            그냥 요약하라고 합니다
    question_aware   질문을 알려주고 그에 필요한 것만 남기라고 합니다
    preserve         숫자·식별자·부정어를 **글자 그대로** 남기라고 못 박습니다

`preserve` 가 중요한 이유는, 요약 모델이 "결제금액의 12%" 를 "일정 비율" 로
바꾸는 것을 요약이라고 생각하기 때문입니다. 사람이 읽기엔 자연스럽지만
그 숫자로 답해야 하는 질문에는 못 씁니다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

CACHE_DIR = Path(__file__).resolve().parent / ".cache"


# ══════════════════════════════════════════════════════════════════
# 프롬프트
#
# 목표 길이는 글자 수로 줍니다. 토큰 수로 주면 모델이 세지 못합니다.
# ══════════════════════════════════════════════════════════════════

PLAIN = """다음 문서를 한국어로 요약하세요.

조건:
- {target}자 이내로 줄이세요.
- 요약문만 출력하세요. 머리말이나 설명을 붙이지 마세요.

문서:
{text}"""

QUESTION_AWARE = """다음 문서를 한국어로 요약하세요.

이 요약은 아래 질문에 답하는 데 쓰입니다.
질문: {question}

조건:
- {target}자 이내로 줄이세요.
- 질문에 답하는 데 필요한 내용을 우선 남기세요.
- 요약문만 출력하세요. 머리말이나 설명을 붙이지 마세요.

문서:
{text}"""

PRESERVE = """다음 문서를 한국어로 요약하세요.

이 요약은 아래 질문에 답하는 데 쓰입니다.
질문: {question}

반드시 지킬 것:
- 숫자, 금액, 비율, 날짜, 기간은 **원문 그대로** 옮기세요.
  "12%" 를 "일정 비율" 로, "5일" 을 "며칠" 로 바꾸지 마세요.
- 식별자(주문번호, 코드, 호스트명, 계정명)는 **한 글자도 바꾸지 마세요.**
- 부정 표현("않습니다", "제외", "불가")은 **긍정으로 바꾸지 마세요.**
  뜻이 뒤집힙니다.
- 위 항목이 아닌 서술은 자유롭게 줄이세요.

조건:
- {target}자 이내로 줄이세요.
- 요약문만 출력하세요. 머리말이나 설명을 붙이지 마세요.

문서:
{text}"""

STYLES = {"plain": PLAIN, "question_aware": QUESTION_AWARE, "preserve": PRESERVE}


class BudgetExceeded(RuntimeError):
    """호출 상한에 걸렸습니다. 실수로 큰 코퍼스를 돌린 경우입니다."""


class Summarizer:
    """요약 호출 + 디스크 캐시 + 호출 상한.

    캐시 키에 프롬프트 전문을 넣습니다. 스타일이나 목표 길이를 바꾸면
    당연히 다시 불러야 하는데, 키를 원문으로만 잡으면 **조용히 옛 결과가
    나옵니다.** 결과가 안 바뀌는데 이유를 못 찾는 상황이 여기서 나옵니다.
    """

    def __init__(self, deployment: str, style: str = "preserve",
                 target_ratio: float = 0.4, cache: bool = True,
                 max_calls: int = 200, max_output_tokens: int = 2048):
        if style not in STYLES:
            raise ValueError(f"모르는 스타일: {style} (가능: {list(STYLES)})")
        self.deployment = deployment
        self.style = style
        self.target_ratio = target_ratio
        self.max_calls = max_calls
        self.max_output_tokens = max_output_tokens
        self.calls = 0
        self.hits = 0
        self.out_tokens = 0

        self.cache_path = (CACHE_DIR / f"summary-{deployment}.json") if cache else None
        self._mem: Dict[str, str] = {}
        if self.cache_path and self.cache_path.exists():
            try:
                self._mem = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                self._mem = {}

    def prompt_for(self, text: str, question: str = "") -> str:
        target = max(40, int(len(text) * self.target_ratio))
        return STYLES[self.style].format(
            text=text, question=question or "(질문 없음)", target=target)

    def _key(self, text: str, question: str = "") -> str:
        prompt = self.prompt_for(text, question)
        return hashlib.sha256(
            f"{self.deployment}\x00{prompt}".encode()).hexdigest()[:24]

    def cached(self, text: str, question: str = "") -> bool:
        """이미 캐시에 있나. 돌리기 전에 비용을 셀 때 씁니다."""
        return self._key(text, question) in self._mem

    def __call__(self, text: str, question: str = "") -> Tuple[str, dict]:
        prompt = self.prompt_for(text, question)
        key = self._key(text, question)

        if key in self._mem:
            self.hits += 1
            return self._mem[key], {"cached": True}

        if self.calls >= self.max_calls:
            raise BudgetExceeded(
                f"호출 상한 {self.max_calls} 회에 걸렸습니다. "
                f"--max-calls 로 올리거나 --limit 으로 케이스를 줄이세요.")

        from kit.provider import complete
        out, usage = complete(prompt, self.deployment,
                              max_output_tokens=self.max_output_tokens)
        self.calls += 1
        self.out_tokens += int(usage.get("output_tokens") or 0)
        self._mem[key] = out
        return out, {"cached": False,
                     "output_tokens": usage.get("output_tokens")}

    def save(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._mem, ensure_ascii=False),
                                   encoding="utf-8")

    def stats(self) -> Dict[str, int]:
        return {"summary_calls": self.calls, "summary_cache_hits": self.hits,
                "summary_output_tokens": self.out_tokens,
                "cached_entries": len(self._mem)}

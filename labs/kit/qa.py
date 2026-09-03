"""정답률 평가 — 압축된 컨텍스트로 실제로 답할 수 있는가.

## 왜 필요한가

지금까지 랩이 쓰는 **정답 보존율**은 문자열 검사입니다. 값싸고 빠르지만
두 방향으로 틀립니다.

    원문   주말 및 공휴일에는 접수되지 않습니다     must_include: ["않습니다"]
    요약   주말·공휴일 제외                       → 보존율 0%
           ↑ 뜻은 지켰는데 0% 로 셉니다 (과소평가)

    요약   총액 3,245만원                        must_include: ["32,450,000"]
           ↑ 같은 값인데 표기가 달라 0% 입니다

반대 방향도 있습니다. 숫자를 그대로 베끼면서 문맥을 뒤집는 요약은 100% 로
셉니다. 즉 보존율은 **하한**입니다 — 낮으면 확실히 문제지만 높다고 안전하지
않습니다.

이 모듈은 그 위쪽을 잽니다. 압축된 컨텍스트만 주고 실제로 질문에 답하게 한
뒤, **원문으로 낸 답**과 대조합니다.

## 판정 세 가지

    정답   원문으로 낸 답과 같은 내용입니다
    오답   다른 답을 했습니다 — 정보가 없는데 지어낸 경우입니다
    모름   정보가 없다고 인정했습니다

**오답과 모름을 반드시 나눠서 봐야 합니다.** 둘 다 답을 못 한 것이지만,
모름은 사용자가 알아챌 수 있는 안전한 실패이고 오답은 그렇지 않습니다.
압축률만 올리다 보면 모름이 오답으로 바뀌는 구간이 옵니다.

## 기준 답을 원문에서 뽑는 이유

사람이 정답을 미리 적어두면 표현이 조금만 달라도 틀렸다고 세게 됩니다.
같은 모델에게 원문을 통째로 주고 낸 답을 기준으로 삼으면, **압축 때문에
생긴 차이만** 남습니다. 모델 실력은 양쪽에서 상쇄됩니다.

그래서 이 지표는 "이 모델이 낼 수 있는 최선 대비 얼마나 지켰나" 입니다.
"절대적으로 옳은가" 가 아닙니다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

CACHE_DIR = Path(__file__).resolve().parent / ".cache"
UNKNOWN = "모름"

ANSWER_PROMPT = """아래 자료만 보고 질문에 답하세요.

지킬 것:
- 자료에 없는 내용은 지어내지 마세요.
- 답할 근거가 자료에 없으면 다른 말 없이 정확히 `{unknown}` 이라고만 쓰세요.
- 한 문장으로 짧게 답하세요. 숫자나 식별자는 자료에 적힌 그대로 옮기세요.

[자료]
{context}

[질문]
{question}"""

JUDGE_PROMPT = """같은 질문에 대한 두 답변이 **같은 내용**인지 판정하세요.

기준 답변은 원문 전체를 보고 작성된 것이고, 대상 답변은 압축된 자료만 보고
작성된 것입니다. 압축 과정에서 정보가 사라졌는지 확인하려는 것입니다.

판정 규칙:
- 표현이 달라도 **묻는 것에 대한 답이 같으면** 같다고 보세요.
  ("3,245만원" 과 "32,450,000원" 은 같습니다)
- 대상 답변이 **덜 구체적이어도 질문에는 답했다면** 같다고 보세요.
  ("리랭크 엔드포인트" 와 "/v1/rerank" 는 같습니다)
- 핵심 값이 **다르거나 빠졌으면** 다르다고 보세요.
  (금액·식별자·날짜가 틀리거나 없는 경우입니다)
- 부정이 뒤집혔으면 다르다고 보세요. ("가능" vs "불가")

다른 말 없이 `같음` 또는 `다름` 한 단어로만 답하세요.

[질문]
{question}

[기준 답변]
{reference}

[대상 답변]
{hypothesis}"""


class BudgetExceeded(RuntimeError):
    """호출 상한에 걸렸습니다."""


class Grader:
    """답변 생성 + 판정. 디스크 캐시와 호출 상한을 함께 관리합니다.

    캐시 키에 프롬프트 전문이 들어갑니다. 프롬프트를 고치면 당연히 다시
    불러야 하는데, 질문만으로 키를 잡으면 **조용히 옛 결과가 나옵니다.**
    """

    def __init__(self, deployment: str, cache: bool = True,
                 max_calls: int = 400, max_output_tokens: int = 512):
        self.deployment = deployment
        self.max_calls = max_calls
        self.max_output_tokens = max_output_tokens
        self.calls = 0
        self.hits = 0

        self.cache_path = (CACHE_DIR / f"qa-{deployment}.json") if cache else None
        self._mem: Dict[str, str] = {}
        if self.cache_path and self.cache_path.exists():
            try:
                self._mem = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                self._mem = {}
        self.preloaded = len(self._mem)

    def _ask(self, prompt: str) -> str:
        key = hashlib.sha256(f"{self.deployment}\x00{prompt}".encode()).hexdigest()[:24]
        if key in self._mem:
            self.hits += 1
            return self._mem[key]
        if self.calls >= self.max_calls:
            raise BudgetExceeded(
                f"호출 상한 {self.max_calls} 회에 걸렸습니다. "
                f"--max-calls 로 올리거나 --limit 으로 케이스를 줄여주세요.")
        from .provider import complete
        out, _ = complete(prompt, self.deployment,
                          max_output_tokens=self.max_output_tokens)
        self.calls += 1
        self._mem[key] = out
        return out

    def answer(self, question: str, context: str) -> str:
        return self._ask(ANSWER_PROMPT.format(
            unknown=UNKNOWN, context=context, question=question)).strip()

    def judge(self, question: str, reference: str, hypothesis: str) -> bool:
        v = self._ask(JUDGE_PROMPT.format(
            question=question, reference=reference, hypothesis=hypothesis))
        return "같음" in v

    def verdict(self, question: str, reference: str, compressed: str
                ) -> Tuple[str, str]:
        """(판정, 대상 답변) 을 돌려줍니다."""
        hyp = self.answer(question, compressed)
        if is_unknown(hyp):
            return UNKNOWN, hyp
        return ("정답" if self.judge(question, reference, hyp) else "오답"), hyp

    def save(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._mem, ensure_ascii=False),
                                   encoding="utf-8")

    def stats(self) -> Dict[str, int]:
        return {"qa_calls": self.calls, "qa_cache_hits": self.hits,
                "cached_entries": len(self._mem)}

    def describe(self) -> str:
        if self.calls and self.hits:
            return f"새로 호출 {self.calls}회 · 캐시 재사용 {self.hits}회"
        if self.calls:
            return f"새로 호출 {self.calls}회"
        return f"이번 실행은 호출 0회입니다 (캐시 {self.preloaded}건 재사용)"


def is_unknown(text: str) -> bool:
    """모델이 '모른다' 고 답했는지. 표현이 조금씩 달라서 넉넉히 봅니다."""
    t = text.strip().strip("`\"' .").lower()
    return (t == UNKNOWN or t.startswith(UNKNOWN)
            or "알 수 없" in t or "확인할 수 없" in t
            or "자료에 없" in t or "정보가 없" in t)


def score(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """판정 목록을 집계합니다."""
    n = len(rows)
    if not n:
        return {"n": 0}
    c = sum(1 for r in rows if r["verdict"] == "정답")
    w = sum(1 for r in rows if r["verdict"] == "오답")
    u = sum(1 for r in rows if r["verdict"] == UNKNOWN)
    by_kind: Dict[str, Dict[str, int]] = {}
    for r in rows:
        b = by_kind.setdefault(r.get("kind", "-"), {"n": 0, "정답": 0, "오답": 0, UNKNOWN: 0})
        b["n"] += 1
        b[r["verdict"]] += 1
    return {
        "n": n,
        "correct": c, "wrong": w, "unknown": u,
        "accuracy": round(c / n, 4),
        # 정보가 없는데 지어낸 비율. 사용자가 알아챌 수 없어 가장 위험합니다.
        "hallucination": round(w / n, 4),
        # 정보가 없다고 인정한 비율. 안전한 실패입니다.
        "abstain": round(u / n, 4),
        "by_kind": by_kind,
    }

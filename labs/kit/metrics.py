"""지표.

압축률과 survival 두 축만 봅니다.

  압축률          얼마나 줄었나
  정답 보존율     정답에 꼭 필요한 문자열(must_include) 중 압축 후에도 남은 비율
                  100% = 하나도 안 잃음. LLM 호출이 없어 비용 0.

집계에서 평균만 내지 않습니다. **최저값(survival_worst)과 유형별 분해**를 강제합니다.
평균 90% 여도 한 케이스가 0% 면 그 질문에는 아예 답할 수 없는데, 평균은 그걸 가립니다.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from . import tokens as T


def survival(text: str, must_include: Iterable[str]) -> Optional[float]:
    """정답 문자열이 압축 결과에 남아 있는 비율. must_include 가 없으면 None."""
    must = list(must_include)
    if not must:
        return None
    flat = text.replace(" ", "").replace(",", "")
    hit = sum(1 for m in must if m.replace(" ", "").replace(",", "") in flat)
    return hit / len(must)


def per_case(case_id: str, kind: str, before: str, after: str,
             must_include: Iterable[str], counter=None,
             extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """counter 는 text -> 토큰수 함수입니다.

    kit.tokens.make_counter() 로 만듭니다. 생략하면 로컬 계산을 씁니다.
    문자열(모델명)을 넘기면 예전 방식대로 로컬 계산합니다.
    """
    if counter is None:
        counter = T.LocalCounter()
    elif isinstance(counter, str):
        counter = T.LocalCounter(counter)
    tb, ta = counter(before), counter(after)
    s = survival(after, must_include)
    return {
        "id": case_id,
        "kind": kind,
        "chars_before": len(before),
        "chars_after": len(after),
        "tokens_before": tb,
        "tokens_after": ta,
        "ratio": round(ta / tb, 4) if tb else 1.0,          # 남은 비율
        "saved": round(1 - ta / tb, 4) if tb else 0.0,      # 절감률
        "survival": None if s is None else round(s, 4),
        "survived_all": None if s is None else s == 1.0,
        **(extra or {}),
    }


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    i = max(0, min(len(xs) - 1, int(round((len(xs) - 1) * p))))
    return xs[i]


def aggregate(records: List[Dict[str, Any]], counter=None) -> Dict[str, Any]:
    """counter 는 backend 이름을 얻는 데만 씁니다."""
    if counter is None:
        counter = T.LocalCounter()
    elif isinstance(counter, str):
        counter = T.LocalCounter(counter)
    if not records:
        return {"n": 0, "token_backend": counter.backend}

    tb = sum(r["tokens_before"] for r in records)
    ta = sum(r["tokens_after"] for r in records)
    surv = [r["survival"] for r in records if r["survival"] is not None]

    by_kind: Dict[str, Dict[str, Any]] = {}
    for r in records:
        b = by_kind.setdefault(r["kind"], {"n": 0, "tb": 0, "ta": 0, "surv": []})
        b["n"] += 1
        b["tb"] += r["tokens_before"]
        b["ta"] += r["tokens_after"]
        if r["survival"] is not None:
            b["surv"].append(r["survival"])

    out = {
        "n": len(records),
        "token_backend": counter.backend,
        "tokens_before": tb,
        "tokens_after": ta,
        "ratio": round(ta / tb, 4) if tb else 1.0,
        "saved": round(1 - ta / tb, 4) if tb else 0.0,
        "chars_before": sum(r["chars_before"] for r in records),
        "chars_after": sum(r["chars_after"] for r in records),
    }
    if surv:
        out.update({
            "survival_mean": round(sum(surv) / len(surv), 4),
            "survival_p5": round(_percentile(surv, 0.05), 4),   # 하위 5% — 평균이 가리는 것
            "survival_worst": round(min(surv), 4),
            "survived_all_rate": round(sum(1 for s in surv if s == 1.0) / len(surv), 4),
        })
    out["by_kind"] = {
        k: {
            "n": v["n"],
            "saved": round(1 - v["ta"] / v["tb"], 4) if v["tb"] else 0.0,
            "survival_mean": round(sum(v["surv"]) / len(v["surv"]), 4) if v["surv"] else None,
            "survival_worst": round(min(v["surv"]), 4) if v["surv"] else None,
        }
        for k, v in sorted(by_kind.items())
    }
    return out

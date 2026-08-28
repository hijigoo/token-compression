"""과금 기준으로 절감을 다시 재는 검증.

`tokens.py` 의 로컬 계산(tiktoken)은 **추정치**입니다. 실제로 돈이 나가는
기준은 API 응답의 `usage.input_tokens` 입니다. 둘은 대개 비슷하지만,
같다고 가정하면 안 되는 이유가 몇 가지 있습니다.

  1. 메시지 포맷 오버헤드 — 역할 구분자 등이 더해집니다 (보통 +6)
  2. 배포 모델의 토크나이저가 tiktoken 인코딩과 다를 수 있습니다
  3. 압축 결과에 제어문자나 특수 구분자가 섞이면 어긋나기 쉽습니다

3번이 특히 중요합니다. `01-lossless-structure` 는 표 구분자로 제어문자를
쓰는데, 이런 글자를 모델 토크나이저가 어떻게 쪼개는지는 실제로 불러봐야
알 수 있습니다. **추정으로 30% 줄었다고 나와도 과금은 다를 수 있습니다.**

그래서 랩마다 몇 건만 뽑아 실제로 불러보고 두 숫자를 나란히 놓습니다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import tokens as T


def billed(pairs: Sequence[Tuple[str, str, str]],
           deployment: Optional[str] = None,
           model: Optional[str] = None,
           limit: int = 3,
           cache: bool = True) -> Dict[str, Any]:
    """(id, 압축 전, 압축 후) 목록을 실제 API 로 재서 비교합니다.

    호출 수는 **케이스당 2회**(전·후)입니다. 그래서 기본 3건으로 제한합니다.
    같은 텍스트는 디스크에 캐시되므로 두 번째 실행부터는 0회입니다.

    반환:
        rows     케이스별 (id, 로컬 전/후, 실측 전/후, 절감 두 가지)
        totals   합계와 두 방식의 절감률 차이
        counter  ApiCounter (describe() 로 호출 내역을 볼 수 있습니다)
    """
    use = list(pairs)[:limit]
    if not use:
        raise ValueError("비교할 케이스가 없습니다")

    local = T.LocalCounter(model)
    api = T.make_counter(
        {"mode": "api", "deployment": deployment or model, "cache": cache}, model)

    rows: List[Dict[str, Any]] = []
    for cid, before, after in use:
        lb, la = local(before), local(after)
        ab, aa = api(before), api(after)
        rows.append({
            "id": cid,
            "local_before": lb, "local_after": la,
            "api_before": ab, "api_after": aa,
            "local_saved": round(1 - la / lb, 4) if lb else 0.0,
            "api_saved": round(1 - aa / ab, 4) if ab else 0.0,
        })
    api.save()

    lb = sum(r["local_before"] for r in rows)
    la = sum(r["local_after"] for r in rows)
    ab = sum(r["api_before"] for r in rows)
    aa = sum(r["api_after"] for r in rows)
    local_saved = 1 - la / lb if lb else 0.0
    api_saved = 1 - aa / ab if ab else 0.0

    return {
        "rows": rows,
        "totals": {
            "n": len(rows),
            "local_before": lb, "local_after": la,
            "api_before": ab, "api_after": aa,
            "local_saved": round(local_saved, 4),
            "api_saved": round(api_saved, 4),
            # 추정이 과금과 얼마나 어긋났는지. 부호까지 봐야 합니다 —
            # 추정이 절감을 과장했다면 양수입니다.
            "gap_pp": round((local_saved - api_saved) * 100, 2),
            "overhead_per_text": round((ab - lb) / len(rows), 1),
        },
        "counter": api,
    }


def verdict(totals: Dict[str, Any], tolerance_pp: float = 3.0) -> str:
    """추정을 믿어도 되는지 한 줄로 판단합니다."""
    gap = totals["gap_pp"]
    if abs(gap) <= tolerance_pp:
        return (f"추정과 실측이 {abs(gap):.1f}%p 차이입니다 — "
                f"이 정도면 tiktoken 값을 그대로 보셔도 됩니다")
    if gap > 0:
        return (f"추정이 절감을 {gap:.1f}%p **과장**했습니다 — "
                f"실제 과금은 생각보다 덜 줄어듭니다")
    return (f"추정이 절감을 {-gap:.1f}%p 낮게 봤습니다 — "
            f"실제로는 더 줄어듭니다")

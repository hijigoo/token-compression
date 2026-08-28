#!/usr/bin/env python3
"""00-baseline — 압축하지 않고 그대로 통과시킵니다.

기준선을 만들면서 동시에 하네스가 정상인지 확인합니다.
결과가 ratio 1.0 / saved 0.0 / survival 1.0 이 아니면 하네스가 고장 난 것입니다.

    python compress.py configs/noop.yaml
    python compress.py configs/noop.yaml --data ../data/docs-long --limit 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── kit 부트스트랩 ────────────────────────────────────────────────
# labs/ 를 경로에 넣어 `from kit import ...` 가 되게 합니다.
# 랩끼리는 서로를 import 하지 않습니다. kit 은 랩이 아니라 기반입니다.
LABS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LABS))

from kit import config as C          # noqa: E402
from kit import dataset, env, metrics, tokens as T   # noqa: E402
from kit.runner import Run           # noqa: E402

env.load()   # labs/.env → 루트 .env → scripts/explore/.env (셸 환경변수가 우선)


def compress(text: str, **params) -> tuple[str, dict]:
    """압축하지 않습니다. 다른 랩도 이 시그니처를 그대로 씁니다."""
    return text, {}


def main() -> int:
    ap = argparse.ArgumentParser(description="00-baseline — 압축 없음 (기준선)")
    ap.add_argument("config", help="configs/*.yaml")
    ap.add_argument("--data", help="코퍼스 경로 (config 값을 덮어씁니다)")
    ap.add_argument("--limit", type=int, help="케이스 수 제한")
    ap.add_argument("--refresh-tokens", action="store_true",
                    help="토큰 캐시를 무시하고 API 를 다시 부릅니다 (mode: api 일 때)")
    ap.add_argument("--out", default=str(LABS.parent / "runs"), help="결과 루트")
    args = ap.parse_args()

    cfg = C.load(args.config)
    path = args.data or cfg.dataset.get("path")
    if not path:
        print("코퍼스 경로가 없습니다. config 의 dataset.path 나 --data 를 지정하세요.",
              file=sys.stderr)
        return 2

    limit = args.limit if args.limit is not None else cfg.dataset.get("limit")
    cases = dataset.load(path, limit=limit)
    info = dataset.summarize(cases)
    print(f"코퍼스 {path}")
    print(f"  케이스 {info['n_cases']}건 · {info['n_chars']:,}자 · "
          f"must_include 있는 케이스 {info['with_must_include']}건")
    print(f"  유형 {info['kinds']}")

    tok_spec = dict(cfg.tokenizer)
    if args.refresh_tokens:
        tok_spec["refresh"] = True
    counter = T.make_counter(tok_spec, cfg.model)
    print(f"  토큰 측정 {counter.backend}")
    if getattr(counter, "preloaded", 0):
        print(f"    캐시 {counter.preloaded}건 보유 — 이미 잰 텍스트는 다시 부르지 않습니다")
        print(f"    강제로 다시 부르시려면 --refresh-tokens 를 붙여주세요")

    run = Run(cfg, args.out)
    for c in cases:
        after, extra = compress(c.text, **cfg.params)
        run.add(metrics.per_case(c.id, c.kind, c.text, after,
                                 c.must_include, counter, extra),
                before=c.text, after=after)

    m = metrics.aggregate(run.records, counter)
    notes = []

    counter.save()
    st = counter.stats()
    if st:
        m["token_calls"] = st
        notes.append(f"토큰을 모델 호출로 실측했습니다 "
                     f"(호출 {st.get('api_calls', 0)}회 · 캐시 적중 {st.get('cache_hits', 0)}회). "
                     f"메시지 포맷 오버헤드가 포함되므로 local 측정값과 섞지 마세요.")

    # 하네스 자가 점검 — 압축을 안 했으니 아래가 성립해야 합니다.
    problems = []
    if m["saved"] != 0.0:
        problems.append(f"절감률이 0 이 아닙니다 ({m['saved']:.2%}) — 로더가 원문을 바꾸고 있습니다")
    if m.get("survival_worst") not in (None, 1.0):
        problems.append(f"최저 보존율이 100% 가 아닙니다 ({m['survival_worst']:.1%}) — "
                        f"must_include 나 정규화를 확인하세요")
    if m["token_backend"].startswith("heuristic"):
        notes.append("tiktoken 이 없어 문자 기반 근사로 쟀습니다. "
                     "다른 실행과 비교하려면 측정 방식이 같아야 합니다.")

    notes.append("압축 없음. 다른 랩의 절감률은 이 결과를 기준으로 읽습니다.")
    out = run.finish(m, notes)

    print(f"\n절감 {m['saved']:.1%} · 토큰 {m['tokens_before']:,} → {m['tokens_after']:,}")
    if "survival_worst" in m:
        print(f"정답 보존율 평균 {m['survival_mean']:.1%} · 최저 {m['survival_worst']:.1%}")
    print(f"측정 방식 {m['token_backend']}")
    print(f"  {counter.describe()}")
    print(f"\n결과 {out}")

    if problems:
        print("\n하네스 점검 실패", file=sys.stderr)
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        return 1

    print("\n하네스 정상 — 다른 랩을 돌려도 됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

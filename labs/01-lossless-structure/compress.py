#!/usr/bin/env python3
"""01-lossless-structure — 의미를 하나도 버리지 않고 표현만 바꿉니다.

무손실 압축은 **표현의 중복**을 먹고 삽니다.

    JSON 배열   레코드마다 키를 반복합니다        → 헤더 한 줄로
    로그        줄마다 타임스탬프를 반복합니다     → 접두사 한 번만
    들여쓰기    사람이 보라고 넣은 것입니다        → 제거
    정렬 공백   표를 맞추려고 넣은 것입니다        → 접기

산문에는 그런 중복이 없습니다. 그래서 이 랩을 산문에 돌리면 **거의 0%** 가
나오고, 그게 오류가 아니라 결론입니다. 무손실로 얻을 게 있는지는 입력이
정합니다.

    python compress.py configs/structure.yaml            # 구조화 → 크게 절감
    python compress.py configs/prose.yaml                # 산문 → 거의 0%
    python compress.py configs/structure-lossy-ws.yaml   # 공백까지 접기

## 자가 점검

**검증할 수 있어야 무손실입니다.** 적용된 변환을 단계별로 확인합니다.

    되돌리기   after 를 풀어 원본과 글자 단위로 같은지 (log_dedup)
    정규형     양쪽을 정규형으로 바꿔 같은지 (json, xml, 표, 키값)

하나라도 어긋나면 **exit 1** 입니다. 검증할 수 없는 변환(`ws_collapse`)을
쓰면 그 횟수를 세서 "이 결과는 무손실이 아니다" 라고 밝힙니다.
검사가 조용히 생략되면 무손실이라는 말이 아무 의미가 없기 때문입니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ── kit 부트스트랩 ────────────────────────────────────────────────
LABS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LABS))

from kit import config as C                            # noqa: E402
from kit import dataset, env, metrics, tokens as T     # noqa: E402
from kit.runner import Run                             # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transforms as X                                 # noqa: E402

env.load()


def compress(text: str, pipeline=None, **params) -> tuple[str, dict]:
    """파이프라인을 순서대로 시도하고, 적용된 것만 기록합니다.

    각 변환은 자기가 다룰 수 없는 입력이면 조용히 건너뜁니다. JSON 변환기에
    산문을 주면 아무 일도 일어나지 않고, 그게 정상 동작입니다.
    """
    names = list(pipeline or X.DEFAULT_PIPELINE)
    applied, skipped, lossy = [], [], []
    steps = []                 # (변환명, 그 단계의 입력, 출력) — 검증에 씁니다
    cur = text

    while names:
        n = names.pop(0)
        t = X.REGISTRY.get(n)
        if t is None:
            raise KeyError(f"모르는 변환: {n} (가능: {list(X.REGISTRY)})")
        ok, out, meta = t.fn(cur)
        if not ok:
            skipped.append(f"{n}: {meta.get('reason', '건너뜀')}")
            continue
        steps.append((n, cur, out))
        cur = out
        applied.append(n)
        if not t.checkable:
            lossy.append(n)
        # 같은 대상을 노리는 뒤쪽 변환은 건너뜁니다. 두 번 바꾸면 검증이 꼬입니다.
        for skip in X.EXCLUSIVE.get(n, []):
            if skip in names:
                names.remove(skip)
                skipped.append(f"{skip}: {n} 이 이미 적용됨")

    return cur, {
        "applied": applied,
        "skipped": skipped,
        "lossy_steps": lossy,
        "verifiable": not lossy,
        "_steps": steps,
    }


def verify_steps(steps: list) -> tuple[bool, str, int]:
    """적용된 변환을 **하나씩** 검증합니다.

    파이프라인 전체를 한 번에 되돌리는 대신 단계별로 봅니다. 그래야 어느
    변환이 정보를 흘렸는지 바로 나오고, 되돌리기가 없는 변환이 섞여 있어도
    나머지는 계속 검증할 수 있습니다.

    반환: (통과 여부, 사유, 실제로 검증된 단계 수)
    """
    if not steps:
        return True, "변환 없음", 0

    checked = 0
    for name, src, dst in steps:
        t = X.REGISTRY[name]
        ok, why = t.verify(src, dst)
        if not ok:
            return False, why, checked
        if t.checkable:
            checked += 1

    unchecked = len(steps) - checked
    if unchecked:
        return True, f"{checked}단계 검증 · {unchecked}단계 검증 불가", checked
    return True, f"{checked}단계 모두 검증", checked


def main() -> int:
    ap = argparse.ArgumentParser(description="01-lossless-structure — 무손실 구조 변환")
    ap.add_argument("config", help="configs/*.yaml")
    ap.add_argument("--data", help="코퍼스 경로 (config 값을 덮어씁니다)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--tokenizer", choices=["both", "api", "local"],
                    help="토큰 측정 방식 (config 값을 덮어씁니다). "
                         "both=실측+추정 · api=실측만 · local=추정만")
    ap.add_argument("--refresh-tokens", action="store_true",
                    help="토큰 캐시를 무시하고 API 를 다시 부릅니다 (mode: api 일 때)")
    ap.add_argument("--out", default=str(LABS.parent / "runs"))
    args = ap.parse_args()

    cfg = C.load(args.config)
    path = args.data or cfg.dataset.get("path")
    if not path:
        print("코퍼스 경로가 없습니다.", file=sys.stderr)
        return 2

    limit = args.limit if args.limit is not None else cfg.dataset.get("limit")
    cases = dataset.load(path, limit=limit)
    info = dataset.summarize(cases)
    tok_spec = dict(cfg.tokenizer)
    if args.tokenizer:
        tok_spec["mode"] = args.tokenizer
    if args.refresh_tokens:
        tok_spec["refresh"] = True
    counter = T.make_counter(tok_spec, cfg.model)

    pipeline = cfg.params.get("pipeline") or X.DEFAULT_PIPELINE
    print(f"코퍼스 {path}")
    print(f"  케이스 {info['n_cases']}건 · {info['n_chars']:,}자 · 유형 {info['kinds']}")
    print(f"  파이프라인 {' → '.join(pipeline)}")
    print(f"  토큰 측정 {counter.backend}")
    if getattr(counter, "preloaded", 0):
        print(f"    캐시 {counter.preloaded}건 보유 — 이미 잰 텍스트는 다시 부르지 않습니다")
        print(f"    강제로 다시 부르시려면 --refresh-tokens 를 붙여주세요")

    run = Run(cfg, args.out)
    broken, applied_count, untouched = [], {}, 0
    n_checked, n_unchecked = 0, 0

    for c in cases:
        after, extra = compress(c.text, **cfg.params)
        steps = extra.pop("_steps")
        ok, why, checked = verify_steps(steps)
        extra["verified"] = why
        n_checked += checked
        n_unchecked += len(steps) - checked
        if not ok:
            broken.append((c.id, why))
        for n in extra["applied"]:
            applied_count[n] = applied_count.get(n, 0) + 1
        if not extra["applied"]:
            untouched += 1
        run.add(metrics.per_case(c.id, c.kind, c.text, after, c.must_include,
                                 counter, extra),
                before=c.text, after=after)

    m = metrics.aggregate(run.records, counter)
    m["applied_count"] = applied_count
    m["untouched"] = untouched
    m["steps_verified"] = n_checked
    m["steps_unverified"] = n_unchecked
    notes = []

    counter.save()
    if counter.stats():
        m["token_calls"] = counter.stats()

    # ── 무손실 점검 ────────────────────────────────────────────────
    problems = []
    if broken:
        problems.append(f"정보 손실 {len(broken)}건 — " +
                        "; ".join(f"{i}: {w}" for i, w in broken[:3]))
    if m.get("survival_worst") not in (None, 1.0):
        problems.append(f"최저 보존율이 100% 가 아닙니다 ({m['survival_worst']:.1%}) — "
                        f"무손실이라면 정답 문자열이 사라질 수 없습니다")

    lossy_used = sorted({s for r in run.records for s in r.get("lossy_steps", [])})
    if lossy_used:
        notes.append(f"검증할 수 없는 변환을 {n_unchecked}회 썼습니다: "
                     f"{', '.join(lossy_used)}. 이 단계에서 무엇을 잃었는지는 "
                     f"측정하지 못했습니다 — '무손실' 이라고 부르면 안 됩니다.")
    else:
        notes.append(f"적용된 {n_checked}개 단계를 전부 검증했습니다. "
                     f"되돌리거나 정규형을 비교해 원본과 같음을 확인했습니다.")
    if untouched:
        notes.append(f"{untouched}건은 적용할 변환이 없어 원문 그대로 나갔습니다. "
                     f"무손실 압축은 표현의 중복을 먹고 사는데, 산문에는 그 중복이 "
                     f"없어서 손댈 곳이 없습니다.")
    notes.append(f"적용 횟수: {applied_count or '없음'}")

    out = run.finish(m, notes)

    print(f"\n절감 {m['saved']:.1%} · 토큰 {m['tokens_before']:,} → {m['tokens_after']:,}")
    print(f"정답 보존율 평균 {m['survival_mean']:.1%} · 최저 {m['survival_worst']:.1%}")
    n_applied = sum(applied_count.values())
    print(f"변환 {n_applied}번 적용 · 그중 {n_checked}번 검증" +
          (f" · {n_unchecked}번 검증 못 함" if n_unchecked else ""))
    if applied_count:
        for name, cnt in sorted(applied_count.items(), key=lambda x: -x[1]):
            t = X.REGISTRY[name]
            how = ("되돌려서 원본과 글자 비교" if t.restore else
                   "파싱해서 값끼리 비교" if t.canon else "확인할 방법 없음")
            mark = "" if t.checkable else "  ← 검증 못 함"
            print(f"  {name:18s} {cnt}회 · {how}{mark}")
    if untouched:
        print(f"압축 못 한 케이스 {untouched}/{len(cases)}건 — 적용할 변환이 없었습니다")
    print(f"\n결과 {out}")

    if problems:
        print("\n무손실 점검 실패", file=sys.stderr)
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        return 1

    if n_unchecked:
        print(f"\n주의 — {n_unchecked}단계는 검증하지 못했습니다. "
              f"이 조건의 결과는 무손실이 아닙니다.")
    else:
        print("\n무손실 확인 — 적용한 모든 변환이 원본과 같음을 검증했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""02-handle-ref — 버리는 대신 밖에 두고, 필요할 때만 꺼냅니다.

무손실(`01`)은 표현의 중복까지가 천장입니다. 더 줄이려면 뭔가를 빼야 하는데,
빼는 방법이 두 가지입니다.

    03-summarize-llm   요약해서 **없애 버립니다** (되돌릴 수 없습니다)
    02-handle-ref      밖에 두고 **핸들만 남깁니다** (꺼내면 원문 그대로)

핸들 방식은 정보를 잃지 않습니다. 원문은 저장소에 그대로 있습니다.
대신 **꺼낼 것을 골라야** 하고, 잘못 고르면 답을 못 합니다.
그래서 이 랩의 실패는 전부 라우팅 실패입니다.

    python compress.py configs/k1.yaml
    python compress.py configs/k1.yaml --sweep 0,1,2,3,all

## 무엇을 재는가

컨텍스트에 실제로 들어가는 문자열을 잽니다.

    다이제스트(안 펼친 블록) + 원문(펼친 블록)

`expand_k=0` 이면 다이제스트만 남아 절감이 최대이고 보존율은 무너집니다.
`expand_k=all` 이면 원문 전체라 절감이 없고 보존율은 100% 입니다.
그 사이 어디가 쓸 만한지를 스윕으로 봅니다.

## 자가 점검

`expand_k=all` 은 **보존율 100%** 여야 합니다. 아니면 블록으로 쪼개는
과정에서 글자를 흘린 것이고, 그건 라우팅 문제가 아니라 버그입니다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── kit 부트스트랩 ────────────────────────────────────────────────
LABS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LABS))

from kit import config as C                            # noqa: E402
from kit import dataset, env, metrics, tokens as T     # noqa: E402
from kit.runner import Run                             # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blocks as B                                     # noqa: E402

env.load()


def compress(text: str, question: str = "", expand_k=1, split: str = "auto",
             digest_chars: int = 24, per_block: int = 2, route: str = "bigram",
             **params) -> tuple[str, dict]:
    """블록으로 쪼개고, 골라서 펼칩니다.

    expand_k 는 정수이거나 "all" 입니다. "all" 은 전부 펼치는 대조군입니다.
    route 는 무엇을 펼칠지 고르는 방식입니다 (bigram | first | last).
    """
    bs = B.make_blocks(text, split, per_block)
    ranked = B.rank(question, bs, route)

    if expand_k == "all":
        k = len(bs)
    else:
        k = max(0, min(int(expand_k), len(bs)))

    chosen = {b.handle for b, _ in ranked[:k]}
    out = B.render(bs, chosen, digest_chars, header=k < len(bs))

    top = ranked[0] if ranked else None
    return out, {
        "n_blocks": len(bs),
        "n_expanded": len(chosen),
        "expanded": sorted(chosen, key=lambda h: int(h[1:])),
        "expanded_titles": [b.title for b, _ in ranked[:k]],
        "top_score": round(top[1], 3) if top else 0.0,
    }


def evaluate(cases, cfg, counter, expand_k, out_root):
    """조건 하나를 돌리고 (결과경로, 지표) 를 돌려줍니다."""
    params = dict(cfg.params)
    params["expand_k"] = expand_k
    run = Run(cfg, out_root)

    hit_known, hit_ok = 0, 0
    for c in cases:
        after, extra = compress(c.text, question=c.question or "", **params)

        # 진단용: 정답 절을 **실제로 펼쳤는지**. 다이제스트에 제목이 남아
        # 있는 것과 본문을 펼친 것은 다릅니다 — 문자열 포함으로 세면
        # 아무것도 안 펼친 k=0 이 100% 로 나옵니다.
        want = c.meta.get("answer_section")
        if want:
            hit_known += 1
            if want in extra["expanded_titles"]:
                hit_ok += 1

        extra["expand_k"] = str(expand_k)
        run.add(metrics.per_case(c.id, c.kind, c.text, after, c.must_include,
                                 counter, extra),
                before=c.text, after=after)

    m = metrics.aggregate(run.records, counter)
    m["expand_k"] = str(expand_k)
    if hit_known:
        m["router_hit_rate"] = round(hit_ok / hit_known, 4)

    notes = [f"펼친 블록 {expand_k}개. 나머지는 다이제스트 한 줄로 남습니다.",
             "정보를 버린 게 아니라 밖에 둔 것입니다 — 핸들로 꺼내면 원문 그대로입니다.",
             "여기 절감률은 **꺼내기 전** 기준입니다. 꺼내는 순간 그만큼 되돌아옵니다."]
    if "router_hit_rate" in m:
        notes.append(f"라우터가 정답 절을 고른 비율 {m['router_hit_rate']:.1%} — "
                     f"보존율이 낮으면 원인은 대개 여기입니다.")
    return run.finish(m, notes), m


def main() -> int:
    ap = argparse.ArgumentParser(description="02-handle-ref — 참조 핸들")
    ap.add_argument("config", help="configs/*.yaml")
    ap.add_argument("--data")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--refresh-tokens", action="store_true",
                    help="토큰 캐시를 무시하고 API 를 다시 부릅니다 (mode: api 일 때)")
    ap.add_argument("--out", default=str(LABS.parent / "runs"))
    ap.add_argument("--sweep", help="expand_k 를 여러 값으로 (예: 0,1,2,3,all)")
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
    if args.refresh_tokens:
        tok_spec["refresh"] = True
    counter = T.make_counter(tok_spec, cfg.model)

    no_q = sum(1 for c in cases if not c.question)
    print(f"코퍼스 {path}")
    print(f"  케이스 {info['n_cases']}건 · {info['n_chars']:,}자 · 유형 {info['kinds']}")
    print(f"  분할 {cfg.params.get('split', 'auto')} · "
          f"라우팅 {cfg.params.get('route', 'bigram')} · "
          f"다이제스트 {cfg.params.get('digest_chars', 24)}자")
    print(f"  토큰 측정 {counter.backend}")
    if getattr(counter, "preloaded", 0):
        print(f"    캐시 {counter.preloaded}건 보유 — 이미 잰 텍스트는 다시 부르지 않습니다")
        print(f"    강제로 다시 부르시려면 --refresh-tokens 를 붙여주세요")
    if no_q:
        print(f"  주의: 질문 없는 케이스 {no_q}건 — 라우팅 없이 앞에서 자릅니다")

    ks = ([k.strip() for k in args.sweep.split(",")] if args.sweep
          else [cfg.params.get("expand_k", 1)])
    ks = [k if k == "all" else int(k) for k in ks]

    rows, last = [], None
    for k in ks:
        out, m = evaluate(cases, cfg, counter, k, args.out)
        rows.append((k, m, out))
        last = m

    counter.save()
    if counter.stats():
        print(f"\n토큰 API 호출 {counter.stats()['api_calls']}회 · "
              f"캐시 적중 {counter.stats()['cache_hits']}회")

    print()
    if len(rows) > 1:
        print(f"{'펼침':>5s} {'토큰':>7s} {'절감':>7s} {'평균보존':>8s} "
              f"{'최저보존':>8s} {'정답절적중':>9s}")
        print("-" * 52)
        for k, m, _ in rows:
            hit = ("—" if m.get("router_hit_rate") is None
                   else f"{m['router_hit_rate']:.1%}")
            print(f"{str(k):>5s} {m['tokens_after']:7,d} {m['saved']:7.1%} "
                  f"{m['survival_mean']:8.1%} {m['survival_worst']:8.1%} {hit:>9s}")
        print(f"\n원문 토큰 {rows[0][1]['tokens_before']:,}")
        print("절감과 보존율은 반대로 움직입니다. 어디서 꺾이는지가 이 표의 요점입니다.")
    else:
        k, m, out = rows[0]
        print(f"펼침 {k} · 절감 {m['saved']:.1%} · "
              f"토큰 {m['tokens_before']:,} → {m['tokens_after']:,}")
        print(f"정답 보존율 평균 {m['survival_mean']:.1%} · 최저 {m['survival_worst']:.1%}")
        if "router_hit_rate" in m:
            print(f"라우터 정답 절 적중 {m['router_hit_rate']:.1%}")
        print(f"\n결과 {out}")

    # ── 자가 점검 ─────────────────────────────────────────────────
    allrun = next((m for k, m, _ in rows if k == "all"), None)
    if allrun and allrun["survival_worst"] != 1.0:
        print(f"\n점검 실패", file=sys.stderr)
        print(f"  ✗ 전부 펼쳤는데 최저 보존율이 {allrun['survival_worst']:.1%} 입니다 — "
              f"블록으로 쪼개면서 글자를 흘렸습니다", file=sys.stderr)
        return 1
    if allrun:
        print("\n점검 통과 — 전부 펼치면 보존율 100%. 저장소는 아무것도 잃지 않습니다.")
    elif last and last["survival_worst"] < 1.0:
        print(f"\n보존율이 100% 가 아닙니다. `--sweep {ks[0]},all` 로 돌려서 "
              f"라우팅 문제인지 분할 버그인지 가르세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

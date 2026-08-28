#!/usr/bin/env python3
"""03-summarize-llm — 모델에게 요약시켜 실제로 버립니다.

앞의 두 랩과 결정적으로 다릅니다.

    01 무손실     아무것도 안 버립니다              되돌리기 가능
    02 참조핸들   밖에 두고 핸들만 남깁니다          꺼내면 원문 그대로
    03 요약       **버립니다**                      되돌릴 수 없습니다

버리는 만큼 많이 줄어듭니다. 문제는 **무엇을 버렸는지 모른다**는 것입니다.
요약 모델은 "결제금액의 12%" 를 "일정 비율" 로 바꾸는 걸 요약이라고 생각합니다.
사람이 읽기엔 자연스럽지만 그 숫자로 답해야 하는 질문에는 못 씁니다.

    python compress.py configs/preserve.yaml
    python compress.py configs/plain.yaml --limit 4       # 먼저 조금만
    python compress.py configs/preserve.yaml --max-calls 50

## 비용

이 랩만 API 를 씁니다. 케이스 N건이면 요약 호출 N회입니다.
같은 프롬프트는 디스크에 캐시되므로 두 번째 실행부터는 0회입니다.
`--max-calls` 로 상한을 걸어 두었습니다(기본 200).

## 자가 점검

여기서는 보존율이 낮아도 **실패가 아닙니다.** 그게 이 랩의 관찰 대상입니다.
대신 아래를 확인합니다.

    빈 요약이 나왔나        압축률 100% 라는 엉터리 결과를 막습니다
    원문보다 길어졌나        목표 길이를 무시한 경우입니다
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
from summarize import BudgetExceeded, Summarizer       # noqa: E402

env.load()


def compress(text: str, question: str = "", summarizer=None,
             **params) -> tuple[str, dict]:
    """요약합니다. summarizer 는 호출자가 만들어 넘깁니다.

    캐시와 호출 상한을 케이스 간에 공유해야 하므로 함수 안에서 만들지
    않습니다. 매번 새로 만들면 캐시가 비어서 매 실행이 유료가 됩니다.
    """
    if summarizer is None:
        raise ValueError("summarizer 가 필요합니다")
    out, meta = summarizer(text, question)
    return out, {"style": summarizer.style,
                 "target_ratio": summarizer.target_ratio,
                 "cached": meta.get("cached", False)}


def main() -> int:
    ap = argparse.ArgumentParser(description="03-summarize-llm — LLM 추상 요약")
    ap.add_argument("config", help="configs/*.yaml")
    ap.add_argument("--data")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default=str(LABS.parent / "runs"))
    ap.add_argument("--max-calls", type=int, help="API 호출 상한 (기본 200)")
    args = ap.parse_args()

    cfg = C.load(args.config)
    path = args.data or cfg.dataset.get("path")
    if not path:
        print("코퍼스 경로가 없습니다.", file=sys.stderr)
        return 2

    limit = args.limit if args.limit is not None else cfg.dataset.get("limit")
    cases = dataset.load(path, limit=limit)
    info = dataset.summarize(cases)
    counter = T.make_counter(cfg.tokenizer, cfg.model)

    deployment = (cfg.params.get("deployment")
                  or env.get("AZURE_OPENAI_DEPLOYMENT") or cfg.model)
    if not deployment:
        print("배포명이 없습니다. config 의 params.deployment 나 "
              ".env 의 AZURE_OPENAI_DEPLOYMENT 를 설정하세요.", file=sys.stderr)
        return 2

    smr = Summarizer(
        deployment=deployment,
        style=cfg.params.get("style", "preserve"),
        target_ratio=float(cfg.params.get("target_ratio", 0.4)),
        cache=cfg.params.get("cache", True),
        max_calls=args.max_calls or int(cfg.params.get("max_calls", 200)),
        max_output_tokens=int(cfg.params.get("max_output_tokens", 2048)),
    )

    print(f"코퍼스 {path}")
    print(f"  케이스 {info['n_cases']}건 · {info['n_chars']:,}자 · 유형 {info['kinds']}")
    print(f"  스타일 {smr.style} · 목표 {smr.target_ratio:.0%} · 배포 {deployment}")
    print(f"  토큰 측정 {counter.backend} · 호출 상한 {smr.max_calls}")
    print(f"  캐시 {len(smr._mem)}건 보유")

    no_q = sum(1 for c in cases if not c.question)
    if no_q and smr.style != "plain":
        print(f"  주의: 질문 없는 케이스 {no_q}건 — "
              f"{smr.style} 은 질문을 쓰는데 없으면 plain 과 비슷해집니다")

    run = Run(cfg, args.out)
    empty, longer = [], []

    try:
        for i, c in enumerate(cases, 1):
            after, extra = compress(c.text, question=c.question or "",
                                    summarizer=smr)
            if not after.strip():
                empty.append(c.id)
            if len(after) > len(c.text):
                longer.append(c.id)
            run.add(metrics.per_case(c.id, c.kind, c.text, after,
                                     c.must_include, counter, extra),
                    before=c.text, after=after)
            mark = "캐시" if extra["cached"] else "호출"
            print(f"  [{i:2d}/{len(cases)}] {c.id} {mark} "
                  f"{len(c.text):,}자 → {len(after):,}자", flush=True)
    except BudgetExceeded as e:
        smr.save()
        print(f"\n{e}", file=sys.stderr)
        return 3
    finally:
        smr.save()

    m = metrics.aggregate(run.records, counter)
    m.update(smr.stats())
    m["style"] = smr.style
    m["target_ratio"] = smr.target_ratio

    counter.save()
    if counter.stats():
        m["token_calls"] = counter.stats()

    notes = [
        f"프롬프트 스타일 {smr.style} · 목표 길이 원문의 {smr.target_ratio:.0%}",
        "요약은 **되돌릴 수 없습니다.** 보존율이 낮은 케이스는 그 정보가 사라진 것입니다.",
        f"API 호출 {smr.calls}회 · 캐시 적중 {smr.hits}회 · "
        f"출력 토큰 {smr.out_tokens:,}",
    ]

    problems = []
    if empty:
        problems.append(f"빈 요약 {len(empty)}건 ({', '.join(empty[:3])}) — "
                        f"max_output_tokens 를 늘리세요")
    if longer:
        notes.append(f"원문보다 길어진 케이스 {len(longer)}건 "
                     f"({', '.join(longer[:3])}) — 짧은 글은 요약할 게 없습니다")

    out = run.finish(m, notes)

    print(f"\n절감 {m['saved']:.1%} · 토큰 {m['tokens_before']:,} → {m['tokens_after']:,}")
    print(f"정답 보존율 평균 {m['survival_mean']:.1%} · 최저 {m['survival_worst']:.1%}")
    print(f"온전한 케이스 {m['survived_all_rate']:.1%}")
    print(f"API 호출 {smr.calls}회 · 캐시 적중 {smr.hits}회")

    worst = sorted((r for r in run.records if r["survival"] is not None),
                   key=lambda r: r["survival"])[:3]
    if worst and worst[0]["survival"] < 1.0:
        print("\n가장 많이 깨진 케이스")
        for r in worst:
            if r["survival"] < 1.0:
                print(f"  {r['id']} ({r['kind']}) 보존 {r['survival']:.0%} · "
                      f"절감 {r['saved']:.0%}")
        print("  records.jsonl 의 before/after 를 열어 무엇이 사라졌는지 보세요.")

    print(f"\n결과 {out}")

    if problems:
        print("\n점검 실패", file=sys.stderr)
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        return 1

    print("\n요약은 되돌릴 수 없습니다 — 보존율이 곧 이 조건의 상한입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

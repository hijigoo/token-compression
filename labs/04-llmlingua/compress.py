#!/usr/bin/env python3
"""04-llmlingua — 작은 모델이 토큰을 골라 버립니다.

앞선 랩들과 방식이 다릅니다.

    01 무손실     규칙으로 표현의 중복만 지웁니다        언어 무관
    02 참조핸들   블록 단위로 밖에 둡니다               언어 무관
    03 요약       **큰 모델**이 다시 씁니다             다국어에 강합니다
    04 프루닝     **작은 모델**이 토큰별로 판정합니다     ← 언어를 탑니다

작은 모델이 중요도를 매기므로, 그 모델이 잘 다루지 못하는 언어에서는
성능이 떨어집니다. 그래서 이 랩만 **한·영 이중언어 코퍼스**를 씁니다.

    python compress.py configs/v2-ko-en.yaml
    python compress.py configs/v2-ko-en.yaml --limit 2     # 먼저 조금만

## 처음 실행은 오래 걸립니다

모델을 내려받습니다. v2 는 약 700MB, v1/long 은 약 1GB 입니다.
`~/.cache/huggingface/` 에 남아 다음부터는 로딩만 합니다.

## 자가 점검

`rate=1.0` 은 아무것도 버리지 않으므로 **절감 0% · 보존율 100%** 여야
합니다. 어긋나면 압축기가 아니라 어댑터가 원문을 건드리고 있는 것입니다.
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
import lingua as L                                     # noqa: E402

env.load()


def compress(text: str, question: str = "", **params):
    return L.compress(text, question=question, **params)


def by_language(records):
    """언어별로 쪼갭니다. 이 랩의 핵심 질문이라 따로 냅니다."""
    out = {}
    for r in records:
        lang = r.get("lang", "-")
        b = out.setdefault(lang, {"n": 0, "tb": 0, "ta": 0, "surv": []})
        b["n"] += 1
        b["tb"] += r["tokens_before"]
        b["ta"] += r["tokens_after"]
        if r["survival"] is not None:
            b["surv"].append(r["survival"])
    return {
        k: {"n": v["n"],
            "tokens_before": v["tb"], "tokens_after": v["ta"],
            "saved": round(1 - v["ta"] / v["tb"], 4) if v["tb"] else 0.0,
            "survival_mean": round(sum(v["surv"]) / len(v["surv"]), 4) if v["surv"] else None,
            "survival_worst": round(min(v["surv"]), 4) if v["surv"] else None,
            # 문자당 토큰. 한국어가 비싼지 보려는 값입니다.
            "tokens_per_char": None}
        for k, v in sorted(out.items())
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="04-llmlingua — 토큰 프루닝")
    ap.add_argument("config", help="configs/*.yaml")
    ap.add_argument("--data")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default=str(LABS.parent / "runs"))
    ap.add_argument("--tokenizer", choices=["both", "api", "local"],
                    help="토큰 측정 방식 (config 값을 덮어씁니다)")
    ap.add_argument("--refresh-tokens", action="store_true")
    ap.add_argument("--device", default="cpu", help="cpu | mps | cuda")
    ap.add_argument("--sweep", help="rate 를 여러 값으로 (예: 0.3,0.5,0.7)")
    args = ap.parse_args()

    cfg = C.load(args.config)
    path = args.data or cfg.dataset.get("path")
    if not path:
        print("코퍼스 경로가 없습니다.", file=sys.stderr)
        return 2

    limit = args.limit if args.limit is not None else cfg.dataset.get("limit")
    cases = dataset.load(path, limit=limit)
    info = dataset.summarize(cases)

    params = dict(cfg.params)
    variant = params.pop("variant", "v2")
    model_name = params.pop("model_name", None)
    params["device"] = args.device

    # 설정을 읽자마자 확인합니다. 12건을 다 돌린 뒤에 알려주면 늦습니다.
    probe = dict(params)
    probe.pop("device", None)
    if variant == "long":
        probe.update(L.LONG_DEFAULTS)
    try:
        L.check_params(variant, probe)
    except ValueError as e:
        print(f"설정 오류\n  {e}", file=sys.stderr)
        return 2

    tok_spec = dict(cfg.tokenizer)
    if args.tokenizer:
        tok_spec["mode"] = args.tokenizer
    if args.refresh_tokens:
        tok_spec["refresh"] = True
    counter = T.make_counter(tok_spec, cfg.model)

    langs = {}
    for c in cases:
        langs[c.meta.get("lang", "-")] = langs.get(c.meta.get("lang", "-"), 0) + 1

    print(f"코퍼스 {path}")
    print(f"  케이스 {info['n_cases']}건 · {info['n_chars']:,}자 · 언어 {langs}")
    print(f"  변형 {variant} · 모델 {model_name or L.DEFAULT_MODEL[variant]}")
    print(f"  파라미터 {params}")
    print(f"  토큰 측정 {counter.backend}")
    if getattr(counter, "preloaded", 0):
        print(f"    캐시 {counter.preloaded}건 보유")
    print("  모델을 처음 받는 경우 몇 분 걸립니다…", flush=True)

    rates = ([float(x) for x in args.sweep.split(",")] if args.sweep
             else [params.get("rate", 0.5)])
    rows = []
    for rate in rates:
        params["rate"] = rate
        if len(rates) > 1:
            print(f"\n── rate={rate} ──", flush=True)
        m, out = evaluate(cases, cfg, counter, variant, model_name, params, args.out)
        rows.append((rate, m, out))

    counter.save()
    if len(rows) > 1:
        print(f"\n{'rate':>5s} {'절감':>7s} {'보존평균':>8s} {'보존최저':>8s} "
              f"{'한국어':>8s} {'영어':>8s}")
        print("-" * 50)
        for rate, m, _ in rows:
            ko = m["by_lang"].get("ko", {}).get("survival_mean")
            en = m["by_lang"].get("en", {}).get("survival_mean")
            print(f"{rate:5.2f} {m['saved']:7.1%} {m['survival_mean']:8.1%} "
                  f"{m['survival_worst']:8.1%} "
                  f"{(ko if ko is not None else 0):8.1%} "
                  f"{(en if en is not None else 0):8.1%}")
        print("\nrate 는 '남길 비율' 입니다. 낮출수록 많이 버립니다.")
    return 0


def evaluate(cases, cfg, counter, variant, model_name, params, out_root):
    run = Run(cfg, out_root)
    for i, c in enumerate(cases, 1):
        after, extra = compress(c.text, question=c.question or "",
                                variant=variant, model_name=model_name, **params)
        extra["lang"] = c.meta.get("lang", "-")
        rec = metrics.per_case(c.id, c.kind, c.text, after, c.must_include,
                               counter, extra)
        run.add(rec, before=c.text, after=after)
        print(f"  [{i:2d}/{len(cases)}] {c.id} ({extra['lang']}) "
              f"{rec['tokens_before']:4d}→{rec['tokens_after']:4d} "
              f"· 보존 {rec['survival']:.0%}", flush=True)

    m = metrics.aggregate(run.records, counter)
    m["variant"] = variant
    m["model"] = model_name or L.DEFAULT_MODEL[variant]
    m["rate"] = params.get("rate")
    m["by_lang"] = by_language(run.records)

    if counter.stats():
        m["token_calls"] = counter.stats()

    notes = [f"변형 {variant} · 모델 {m['model']}",
             "작은 모델이 토큰 중요도를 매깁니다. 그 모델이 약한 언어에서는 "
             "같은 설정이라도 결과가 나빠집니다."]

    problems = []
    if params.get("rate") == 1.0:
        # rate=1.0 은 "아무것도 버리지 않는다" 는 뜻이지, "원문을 그대로
        # 돌려준다" 는 뜻이 아닙니다. v2 는 토큰에서 텍스트를 다시 만들기
        # 때문에 숫자 서식이 바뀌고 토큰이 오히려 늘 수 있습니다.
        # 그래서 여기서는 **정보가 남았는지만** 봅니다.
        if m.get("survival_worst") not in (None, 1.0):
            problems.append(f"rate=1.0 인데 최저 보존율이 "
                            f"{m['survival_worst']:.1%} 입니다 — "
                            f"아무것도 안 버렸는데 정답이 사라졌습니다")
        if m["saved"] < 0:
            notes.append(
                f"rate=1.0 인데 토큰이 {-m['saved']:.1%} 늘었습니다. "
                f"토큰에서 텍스트를 재구성하면서 '32,450,000' 이 "
                f"'32, 450, 000' 처럼 벌어지기 때문입니다. "
                f"숫자가 많은 짧은 글에서는 압축이 손해일 수 있습니다.")

    out = run.finish(m, notes)

    print(f"\n절감 {m['saved']:.1%} · 토큰 {m['tokens_before']:,} → {m['tokens_after']:,}")
    print(f"정답 보존율 평균 {m['survival_mean']:.1%} · 최저 {m['survival_worst']:.1%}")
    print("\n언어별")
    for lang, v in m["by_lang"].items():
        print(f"  {lang}  절감 {v['saved']:6.1%} · 보존 평균 {v['survival_mean']:6.1%} "
              f"· 최저 {v['survival_worst']:6.1%}  ({v['n']}건)")
    print(f"\n결과 {out}")

    if problems:
        print("\n점검 실패", file=sys.stderr)
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        raise SystemExit(1)
    return m, out


if __name__ == "__main__":
    raise SystemExit(main())

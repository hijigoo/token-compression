#!/usr/bin/env python3
"""정답률 평가 — 이미 돌린 결과를 다시 압축하지 않고 채점합니다.

`runs/<랩>/<설정>/<시각>/records.jsonl` 에 압축 전(`before`)과 후(`after`)가
둘 다 남아 있습니다. 그래서 랩을 다시 돌릴 필요가 없습니다. 압축 코드가
바뀌지 않았는데 재실행하면 시간만 쓰고 결과는 같습니다.

    python compare/qa_eval.py --corpus sample
    python compare/qa_eval.py --corpus sample --limit 4      # 먼저 조금만
    python compare/qa_eval.py --corpus sample --max-calls 100

## 무엇을 답하려는 실험인가

랩이 쓰는 **정답 보존율**은 문자열 검사라서 두 방향으로 틀립니다.
뜻이 지켜졌는데 표현이 달라 0% 로 세거나, 숫자를 베끼면서 문맥을 뒤집어도
100% 로 셉니다. 즉 하한입니다.

여기서는 압축된 컨텍스트만 주고 **실제로 답하게** 한 뒤 원문으로 낸 답과
대조합니다. 그래서 두 가지를 봅니다.

    보존율은 낮은데 정답인 경우   지표가 실패를 과장하고 있었다
    보존율은 높은데 오답인 경우   지표가 놓치는 실패가 있다  ← 더 중요

## 비용

케이스당 기준 답변 1회 + 조건마다 (답변 1회 + 판정 1회) 입니다.
모름으로 끝나면 판정은 건너뜁니다. 전부 캐시되므로 두 번째 실행은 0회입니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "labs"))

from kit import dataset, env, qa                       # noqa: E402
from kit.display import table, pct                     # noqa: E402

env.load()


def corpus_of(run_dir: Path, metrics: Dict[str, Any]) -> Optional[str]:
    """이 실행이 어떤 코퍼스를 썼는지. 없으면 None.

    새 실행은 metrics 에 이름이 박혀 있고, 옛 실행은 설정 스냅샷에서
    경로를 읽습니다. **부분 문자열로 비교하면 안 됩니다** —
    "sample" 은 "sample-structured" 에도 들어 있습니다.
    """
    if metrics.get("dataset_name"):
        return metrics["dataset_name"]
    snap = run_dir / "config.snapshot.yaml"
    if not snap.exists():
        return None
    for line in snap.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("path:"):
            return Path(s.split(":", 1)[1].strip()).name
    return None


def latest_runs(runs_dir: Path, corpus: str) -> List[Tuple[str, str, Path]]:
    """(랩, 설정, 결과경로) 목록. 설정마다 가장 최근 실행만 씁니다.

    같은 코퍼스를 쓴 실행만 골라야 비교가 성립합니다. 서로 다른 텍스트로
    잰 숫자를 나란히 놓으면 아무 뜻이 없습니다.
    """
    found: Dict[Tuple[str, str], Tuple[str, Path]] = {}
    for m in runs_dir.glob("*/*/*/metrics.json"):
        if not (m.parent / "records.jsonl").exists():
            continue
        try:
            d = json.loads(m.read_text(encoding="utf-8"))
        except Exception:
            continue
        if corpus_of(m.parent, d) != corpus:
            continue
        lab, cfg, ts = m.parts[-4], m.parts[-3], m.parts[-2]
        key = (lab, cfg)
        if key not in found or ts > found[key][0]:
            found[key] = (ts, m.parent)
    return [(lab, cfg, p) for (lab, cfg), (_, p) in sorted(found.items())]


def load_records(path: Path) -> Dict[str, Dict[str, Any]]:
    out = {}
    for line in (path / "records.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["id"]] = r
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="압축된 컨텍스트로 실제 답할 수 있는지 평가")
    ap.add_argument("--corpus", default="sample", help="평가할 코퍼스 이름")
    ap.add_argument("--limit", type=int, help="케이스 수 제한 (먼저 조금만 볼 때)")
    ap.add_argument("--runs", default=str(ROOT / "runs"))
    ap.add_argument("--out", help="결과 json 경로. 생략하면 "
                                  "compare/results/qa-<코퍼스>.json 입니다")
    ap.add_argument("--max-calls", type=int, default=400, help="API 호출 상한")
    args = ap.parse_args()

    deployment = env.get("AZURE_OPENAI_DEPLOYMENT")
    if not deployment:
        print("AZURE_OPENAI_DEPLOYMENT 가 없습니다. labs/.env 를 확인해 주세요.",
              file=sys.stderr)
        return 2

    cases = dataset.load(ROOT / "labs" / "data" / args.corpus, limit=args.limit)
    cases = [c for c in cases if c.question]
    if not cases:
        print(f"{args.corpus} 에 question 이 있는 케이스가 없습니다.", file=sys.stderr)
        return 2

    runs = latest_runs(Path(args.runs), args.corpus)
    if not runs:
        print(f"{args.corpus} 를 쓴 실행 결과가 없습니다. 랩을 먼저 돌려주세요.",
              file=sys.stderr)
        return 2

    print(f"코퍼스 {args.corpus} · 케이스 {len(cases)}건")
    print(f"평가할 조건 {len(runs)}개")
    for lab, cfg, p in runs:
        print(f"  {lab}/{cfg}")

    g = qa.Grader(deployment, max_calls=args.max_calls)
    print(f"판정 모델 {deployment} · 캐시 {g.preloaded}건 보유\n")

    # ── 기준 답변: 원문을 통째로 주고 낸 답 ────────────────────────
    # 사람이 정답을 적어두면 표현 차이로 틀렸다고 세게 됩니다. 같은 모델에게
    # 원문을 주고 낸 답을 기준으로 삼으면 압축 때문에 생긴 차이만 남습니다.
    refs: Dict[str, str] = {}
    try:
        for i, c in enumerate(cases, 1):
            refs[c.id] = g.answer(c.question, c.text)
            print(f"  기준 답변 [{i:2d}/{len(cases)}] {c.id}", flush=True)
    except qa.BudgetExceeded as e:
        g.save(); print(f"\n{e}", file=sys.stderr); return 3

    results: List[Dict[str, Any]] = []
    try:
        for lab, cfg, path in runs:
            recs = load_records(path)
            rows = []
            for c in cases:
                r = recs.get(c.id)
                if r is None:
                    continue
                v, hyp = g.verdict(c.question, refs[c.id], r["after"])
                rows.append({"id": c.id, "kind": c.kind, "verdict": v,
                             "answer": hyp, "survival": r.get("survival"),
                             "saved": r.get("saved")})
            s = qa.score(rows)
            if not s.get("n"):
                print(f"  {lab}/{cfg:22s} 건너뜀 — 해당 케이스가 없습니다")
                continue
            s.update({"lab": lab, "config": cfg, "rows": rows,
                      "saved": sum(x["saved"] or 0 for x in rows) / len(rows),
                      "survival": sum(x["survival"] or 0 for x in rows) / len(rows)})
            results.append(s)
            print(f"  {lab}/{cfg:22s} 정답 {s['accuracy']:5.1%} · "
                  f"오답 {s['hallucination']:5.1%} · 모름 {s['abstain']:5.1%}", flush=True)
    except qa.BudgetExceeded as e:
        g.save(); print(f"\n{e}", file=sys.stderr); return 3
    finally:
        g.save()

    print(f"\n{g.describe()}\n")

    # ── 조건 비교 ────────────────────────────────────────────────
    table(
        ["랩 / 설정", "절감", "보존율", "정답률", "오답(환각)", "모름"],
        [[f'{s["lab"].split("-")[0]} {s["config"]}', pct(s["saved"]),
          pct(s["survival"]), pct(s["accuracy"]),
          pct(s["hallucination"]), pct(s["abstain"])] for s in results],
        align=["left", "right", "right", "right", "right", "right"],
        title=f"압축 조건별 실제 정답률 ({args.corpus} {len(cases)}건)",
        note="'오답' 은 정보가 없는데 지어낸 경우입니다. "
             "'모름' 은 없다고 인정한 안전한 실패입니다. 둘을 나눠서 보세요.",
    )

    # ── 지표가 어긋난 케이스 ─────────────────────────────────────
    gaps = []
    for s in results:
        for r in s["rows"]:
            sv = r["survival"]
            if sv is None:
                continue
            if sv < 1.0 and r["verdict"] == "정답":
                gaps.append([f'{s["config"]}', r["id"], pct(sv), "정답",
                             "지표가 실패를 과장했습니다"])
            elif sv == 1.0 and r["verdict"] != "정답":
                gaps.append([f'{s["config"]}', r["id"], pct(sv), r["verdict"],
                             "지표가 놓친 실패입니다"])

    if gaps:
        table(
            ["설정", "케이스", "보존율", "판정", "무슨 뜻인가"],
            gaps,
            align=["left", "left", "right", "left", "left"],
            title=f"보존율과 정답률이 어긋난 {len(gaps)}건",
            note="보존율은 문자열 검사라서 표현이 바뀌면 놓칩니다. "
                 "'지표가 놓친 실패' 쪽이 더 위험합니다.",
        )
    else:
        print("보존율과 정답률이 모든 케이스에서 일치했습니다.")

    # ── 하네스 점검 ──────────────────────────────────────────────
    base = next((s for s in results if s["lab"].startswith("00")), None)
    if base and base["accuracy"] < 1.0:
        print(f"\n점검 실패", file=sys.stderr)
        print(f"  ✗ 압축하지 않은 기준선의 정답률이 {base['accuracy']:.1%} 입니다.",
              file=sys.stderr)
        print(f"    원문과 같은 텍스트인데 답이 갈렸다면 채점이 불안정한 것입니다.",
              file=sys.stderr)
        return 1

    out_path = Path(args.out) if args.out else \
        ROOT / "compare" / "results" / f"qa-{args.corpus}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {"corpus": args.corpus, "n_cases": len(cases),
         "deployment": deployment, "results": results},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 {out_path}")

    if base:
        print("\n점검 통과 — 기준선은 원문 그대로라 정답률 100% 가 나와야 하고, 그렇습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""평가 결과를 arm 별로 집계한다.

    python analyze.py runs/agentic-eval/ratio-sweep/20260828-141500 \
        --jobs ~/pier/jobs/ratio-sweep

두 축을 함께 본다:
    ① 정확도  reward.json 의 reward==1 비율 (pass@1)
    ② 토큰    trajectory.json 의 실제 입력 토큰

⚠️ 절감률은 프록시 자기보고값을 쓰지 않는다.
   압축기가 자기가 얼마나 줄였는지 보고하면 검증이 순환한다.
   trajectory 의 n_input_tokens 로 교차검증한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def die(msg: str) -> None:
    print(f"\033[31m✗ {msg}\033[0m", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def find_trials(jobs_dir: Path) -> list[Path]:
    """reward.json 을 가진 디렉터리를 trial 로 본다."""
    return sorted({p.parent for p in jobs_dir.rglob("reward.json")})


def trial_base_url(trial: Path) -> str | None:
    """trial 이 어느 arm 소속인지 판별한다.

    pier 의 출력 레이아웃은 버전에 따라 다르므로, 경로 규칙에 기대지 않고
    trial 안에 기록된 OPENAI_BASE_URL 을 직접 찾는다.
    """
    for path in list(trial.rglob("*.json")) + list(trial.rglob("*.yaml")):
        if path.stat().st_size > 20_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        idx = text.find("OPENAI_BASE_URL")
        while idx != -1:
            seg = text[idx : idx + 300]
            for token in seg.replace('"', " ").replace("'", " ").split():
                if token.startswith("http"):
                    return token.rstrip(",}")
            idx = text.find("OPENAI_BASE_URL", idx + 1)
    return None


def trial_tokens(trial: Path) -> int | None:
    for name in ("trajectory.json", "traj.json"):
        for path in trial.rglob(name):
            data = load_json(path)
            if not isinstance(data, dict):
                continue
            stats = (data.get("info") or {}).get("model_stats") or {}
            for key in ("n_input_tokens", "input_tokens", "prompt_tokens"):
                if key in stats:
                    return int(stats[key])
    return None


def trial_reward(trial: Path) -> float | None:
    data = load_json(trial / "reward.json")
    if isinstance(data, dict):
        for key in ("reward", "score", "value"):
            if key in data:
                return float(data[key])
    elif isinstance(data, (int, float)):
        return float(data)
    return None


def proxy_reduction(run_dir: Path, arm_name: str) -> float | None:
    """프록시 자기보고 절감률 (참고용 — 교차검증 대상이지 근거가 아니다)."""
    path = run_dir / f"{arm_name}.jsonl"
    if not path.exists():
        return None
    before = after = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("event") == "compress":
            before += row.get("chars_before", 0)
            after += row.get("chars_after", 0)
    return round(1 - after / before, 4) if before else None


def main() -> int:
    p = argparse.ArgumentParser(description="arm 별 pass@1 / 토큰 집계")
    p.add_argument("run_dir", type=Path, help="launch.py 가 만든 runs/... 디렉터리")
    p.add_argument("--jobs", type=Path, required=True, help="pier jobs 출력 디렉터리")
    args = p.parse_args()

    arms_path = args.run_dir / "arms.json"
    if not arms_path.exists():
        die(f"arms.json 이 없습니다: {arms_path}")
    arms = json.loads(arms_path.read_text(encoding="utf-8"))
    by_url = {a["base_url"]: a["name"] for a in arms}

    if not args.jobs.exists():
        die(f"jobs 디렉터리가 없습니다: {args.jobs}")
    trials = find_trials(args.jobs)
    if not trials:
        die(f"reward.json 을 찾지 못했습니다: {args.jobs}")

    buckets: dict[str, list[dict]] = {a["name"]: [] for a in arms}
    unmatched = 0

    for trial in trials:
        url = trial_base_url(trial)
        name = by_url.get(url) if url else None
        if name is None:
            unmatched += 1
            continue
        buckets[name].append({
            "reward": trial_reward(trial),
            "tokens": trial_tokens(trial),
            "path": str(trial),
        })

    if unmatched:
        print(f"\033[33m! arm 을 판별하지 못한 trial {unmatched}개 (집계 제외)\033[0m")

    rows = []
    baseline_tokens = None
    for arm in arms:
        items = buckets[arm["name"]]
        graded = [i for i in items if i["reward"] is not None]
        toks = [i["tokens"] for i in items if i["tokens"] is not None]

        row = {
            "arm": arm["name"],
            "kind": arm["kind"],
            "ratio": arm.get("ratio"),
            "n_trials": len(items),
            "n_graded": len(graded),
            "pass_at_1": round(sum(1 for i in graded if i["reward"] == 1) / len(graded), 4) if graded else None,
            "mean_input_tokens": round(sum(toks) / len(toks)) if toks else None,
            "proxy_reported_reduction": proxy_reduction(args.run_dir, arm["name"]),
        }
        if arm["kind"] == "direct" and row["mean_input_tokens"]:
            baseline_tokens = row["mean_input_tokens"]
        rows.append(row)

    for row in rows:
        mt = row["mean_input_tokens"]
        row["measured_reduction"] = (
            round(1 - mt / baseline_tokens, 4) if baseline_tokens and mt else None
        )

    # ── 출력 ──────────────────────────────────────────────────
    hdr = f"{'arm':<24}{'trials':>8}{'pass@1':>10}{'입력토큰':>12}{'절감(실측)':>12}{'절감(자기보고)':>16}"
    print("\n" + hdr)
    print("─" * len(hdr))
    for row in rows:
        def f(v, pct=False):
            if v is None:
                return "-"
            return f"{v * 100:.1f}%" if pct else f"{v:,}"
        print(
            f"{row['arm']:<24}{row['n_graded']:>8}"
            f"{f(row['pass_at_1'], True):>10}{f(row['mean_input_tokens']):>12}"
            f"{f(row['measured_reduction'], True):>12}{f(row['proxy_reported_reduction'], True):>16}"
        )

    if any(r["n_graded"] == 0 for r in rows):
        print("\n\033[33m! 채점된 trial 이 0개인 arm 이 있습니다. "
              "프록시 장애로 중단된 trial 은 압축 품질과 무관하니 "
              "pier view 로 확인 후 제외하세요.\033[0m")

    out = args.run_dir / "metrics.json"
    out.write_text(json.dumps({"arms": rows, "unmatched_trials": unmatched},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n▸ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

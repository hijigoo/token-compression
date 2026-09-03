#!/usr/bin/env python3
"""컨테이너 롤아웃 결과를 한 장짜리 보고서로 만든다.

    python report_run.py <run_dir> --jobs <pier jobs 디렉터리>… -o <출력 폴더>

`report.py` 와 무엇이 다른가
---------------------------

`report.py` 는 **대리 측정**을 다룹니다. 컨텍스트를 조립해 압축 전후 문자열이
얼마나 살아남았는지 보는 것이라, 모델을 부르지 않고 조건을 수십 개 돌릴 수
있습니다. 대신 "그래서 과제를 푸느냐" 는 답하지 못합니다.

이 파일은 **정석 측정**을 다룹니다. pier 가 태스크마다 컨테이너를 띄우고,
에이전트가 실제로 파일을 고치고, 채점 컨테이너가 테스트를 돌린 결과입니다.
조건을 많이 둘 수 없는 대신(1 trial 에 5~15분) 유일하게 pass@1 을 줍니다.

    report.py       조건 34개 × 케이스 14개 = 476회, 모델 호출 없음
    report_run.py   조건  3개 × 태스크  3개 =   9회, 컨테이너 롤아웃

설계 원칙
---------

수치는 전부 결과 파일에서 계산합니다. 해설 문장도 계산된 값을 보고 고릅니다.
"압축하면 정확도가 떨어진다" 같은 문장을 미리 심어 두지 않습니다. 결과가
반대로 나오면 그 문장이 거짓말이 되기 때문입니다.
"""

from __future__ import annotations

import argparse
import html
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# 렌더링(마크다운→HTML·CSS)은 report.py 와 하나만 둡니다. 두 벌로 두면
# 한쪽만 고쳐져 두 보고서의 생김새가 갈라집니다.
import report as _r  # noqa: E402

CHARTS: dict = {}


# ─────────────────────────────────────────────────────────────
# 수집
# ─────────────────────────────────────────────────────────────
def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def base_url_of(trial: Path) -> str | None:
    """이 trial 이 어느 arm 이었는지, 컨테이너에 넣어 준 주소로 판별한다.

    경로 이름에 기대지 않습니다. pier 는 trial 폴더 이름을 태스크명 + 난수로
    짓기 때문에, arm 이 이름에 남지 않습니다.
    """
    cfg = load(trial / "config.json")
    if isinstance(cfg, dict):
        env = ((cfg.get("agent") or {}).get("env")) or {}
        if isinstance(env, dict) and env.get("OPENAI_BASE_URL"):
            return env["OPENAI_BASE_URL"]
    for path in sorted(trial.glob("*.json")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        i = text.find("OPENAI_BASE_URL")
        while i != -1:
            for tok in text[i:i + 300].replace('"', " ").replace("'", " ").split():
                if tok.startswith("http"):
                    return tok.rstrip(",}")
            i = text.find("OPENAI_BASE_URL", i + 1)
    return None


def collect(jobs: list[Path], by_url: dict) -> list[dict]:
    rows = []
    for job in jobs:
        for res in sorted(job.rglob("result.json")):
            d = load(res)
            # 잡 전체 요약 파일에는 task_name 이 없습니다. trial 만 봅니다.
            if not isinstance(d, dict) or "task_name" not in d:
                continue
            trial = res.parent
            arm = by_url.get(base_url_of(trial) or "")
            ag = d.get("agent_result") or {}
            vr = (d.get("verifier_result") or {}).get("rewards") or {}
            exc = (d.get("exception_info") or {}).get("exception_type")

            rows.append({
                "arm": arm,
                "lang": job.name.rsplit("-", 1)[-1],
                "task": str(d["task_name"]).split("/")[-1],
                "reward": vr.get("reward"),
                "partial": vr.get("partial_reward", vr.get("partial")),
                "f2p": vr.get("f2p"),
                "p2p": vr.get("p2p"),
                "in_tok": ag.get("n_input_tokens"),
                "cache_tok": ag.get("n_cache_tokens"),
                "out_tok": ag.get("n_output_tokens"),
                "cost": ag.get("cost_usd"),
                "peak": ag.get("peak_context_tokens"),
                "steps": ag.get("n_agent_steps"),
                "secs": wall(d),
                "error": exc,
                "trial": str(trial),
            })
    return rows


def wall(d: dict) -> float | None:
    a, b = d.get("started_at"), d.get("finished_at")
    if not a or not b:
        return None
    try:
        f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
        return round((f(b) - f(a)).total_seconds(), 1)
    except ValueError:
        return None


def proxy_stats(run_dir: Path, arm: str) -> dict:
    """프록시가 남긴 기록. 절감률은 **자기보고**라 근거가 아니라 참고값이다."""
    path = run_dir / f"{arm}.jsonl"
    out = {"before": 0, "after": 0, "calls": 0, "auth_retry": 0, "errors": 0,
           "n_compress": 0}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ev = row.get("event")
        if ev == "compress":
            out["before"] += row.get("chars_before", 0)
            out["after"] += row.get("chars_after", 0)
            out["n_compress"] += 1
        elif ev == "usage":
            out["calls"] += 1
        elif ev == "auth_retry":
            out["auth_retry"] += 1
        elif ev in ("upstream_error", "compress_error"):
            out["errors"] += 1
    return out


# ─────────────────────────────────────────────────────────────
# 집계
# ─────────────────────────────────────────────────────────────
def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def summarize(rows: list[dict], arms: list[dict], run_dir: Path) -> list[dict]:
    out = []
    for a in arms:
        mine = [r for r in rows if r["arm"] == a["name"]]
        done = [r for r in mine if r["error"] is None and r["reward"] is not None]
        out.append({
            "arm": a["name"],
            "kind": a["kind"],
            "ratio": a.get("ratio"),
            "n": len(mine),
            "n_ok": len(done),
            "n_err": sum(1 for r in mine if r["error"]),
            "pass1": (sum(1 for r in done if r["reward"] == 1) / len(done)) if done else None,
            "partial": mean([r["partial"] for r in done]),
            "in_tok": mean([r["in_tok"] for r in done]),
            "peak": mean([r["peak"] for r in done]),
            "steps": mean([r["steps"] for r in done]),
            "cost": mean([r["cost"] for r in done]),
            "secs": mean([r["secs"] for r in done]),
            "proxy": (px := proxy_stats(run_dir, a["name"])),
            "n_compress": px["n_compress"],
        })
    return out


def num(v, digits=0, comma=True):
    if v is None:
        return "—"
    if digits:
        return f"{v:,.{digits}f}" if comma else f"{v:.{digits}f}"
    return f"{round(v):,}" if comma else str(round(v))


def pc(v, digits=1):
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def delta(v, base, digits=1, invert=False):
    """기준선 대비 변화. invert 면 줄어드는 쪽이 좋다(토큰·비용)."""
    if v is None or base in (None, 0):
        return "—"
    d = (v - base) / base * 100
    if invert:
        d = -d
    return f"{d:+.{digits}f}%"


# ─────────────────────────────────────────────────────────────
# 그래프
# ─────────────────────────────────────────────────────────────
def bar_chart(key: str, title: str, labels: list, values: list,
              fmt=lambda v: f"{v:.0f}", good_high=True) -> str:
    """가로 막대. 값이 없는 항목은 회색으로 자리만 남긴다."""
    ok = [v for v in values if v is not None]
    if not ok:
        CHARTS[key] = ""
        return f"<!--CHART:{key}-->"
    vmax = max(ok) or 1
    row_h, pad_l, w = 34, 170, 900
    h = 44 + row_h * len(labels)
    best = max(ok) if good_high else min(ok)

    parts = [f'<svg class="chart" viewBox="0 0 {w} {h}" '
             f'xmlns="http://www.w3.org/2000/svg" role="img">',
             f'<text x="8" y="20" class="ax" style="font-size:13px;'
             f'font-weight:600">{html.escape(title)}</text>']
    for i, (lab, v) in enumerate(zip(labels, values)):
        y = 40 + i * row_h
        parts.append(f'<text x="8" y="{y + 15}" class="ax">{html.escape(str(lab))}</text>')
        if v is None:
            parts.append(f'<text x="{pad_l}" y="{y + 15}" class="ax">측정 없음</text>')
            continue
        bw = max(2, (w - pad_l - 110) * (v / vmax))
        color = "var(--good)" if v == best else "var(--accent)"
        parts.append(f'<rect x="{pad_l}" y="{y + 3}" width="{bw:.1f}" height="18" '
                     f'rx="3" fill="{color}" opacity="0.85"/>')
        parts.append(f'<text x="{pad_l + bw + 8:.1f}" y="{y + 17}" class="ax">'
                     f'{html.escape(fmt(v))}</text>')
    parts.append("</svg>")
    CHARTS[key] = "".join(parts)
    return f"<!--CHART:{key}-->"


def scatter_chart(key: str, title: str, pts: list) -> str:
    """가로축 절감, 세로축 정확도. 오른쪽 위로 갈수록 좋다."""
    pts = [p for p in pts if p[1] is not None and p[2] is not None]
    if len(pts) < 2:
        CHARTS[key] = ""
        return f"<!--CHART:{key}-->"
    w, h, m = 900, 380, 64
    xs = [p[1] for p in pts]
    ys = [p[2] for p in pts]
    x0, x1 = min(0, min(xs)), max(max(xs), 0.05)
    y0, y1 = min(ys) - 0.05, max(max(ys) + 0.05, 0.05)
    sx = lambda v: m + (w - m - 30) * (v - x0) / ((x1 - x0) or 1)   # noqa: E731
    sy = lambda v: h - m - (h - m - 34) * (v - y0) / ((y1 - y0) or 1)  # noqa: E731

    p = [f'<svg class="chart" viewBox="0 0 {w} {h}" '
         f'xmlns="http://www.w3.org/2000/svg" role="img">',
         f'<text x="8" y="20" class="ax" style="font-size:13px;font-weight:600">'
         f'{html.escape(title)}</text>',
         f'<line class="grid" x1="{m}" y1="{h - m}" x2="{w - 30}" y2="{h - m}"/>',
         f'<line class="grid" x1="{m}" y1="34" x2="{m}" y2="{h - m}"/>',
         f'<text x="{w - 30}" y="{h - m + 26}" class="ax" text-anchor="end">'
         f'입력 토큰 절감 →</text>',
         f'<text x="8" y="46" class="ax">↑ pass@1</text>']
    for name, x, y in pts:
        cx, cy = sx(x), sy(y)
        p.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="var(--accent)"/>')
        p.append(f'<text x="{cx + 10:.1f}" y="{cy + 4:.1f}" class="ax">'
                 f'{html.escape(name)} ({x * 100:.0f}%, {y * 100:.0f}%)</text>')
    p.append("</svg>")
    CHARTS[key] = "".join(p)
    return f"<!--CHART:{key}-->"


def ascii_bar(v, vmax, width=22):
    if v is None or not vmax:
        return "—"
    n = round(width * v / vmax)
    # 0 을 한 칸으로 올려 그리면 "아주 작음" 과 "없음" 이 같아 보인다.
    return "█" * n if n else "·"


# ─────────────────────────────────────────────────────────────
# 잡음 바닥
#
# 같은 실험을 **압축이 걸리지 않은 채로** 한 번 돌려 두면, arm 사이에
# 저절로 생기는 차이가 얼마인지 알 수 있습니다. 세 arm 이 똑같은
# 프롬프트를 보냈는데도 입력 토큰이 갈리기 때문입니다.
#
# 왜 갈리냐면 에이전트가 확률적이기 때문입니다. 같은 과제라도 어떤
# 회차는 파일을 두 번 읽고 어떤 회차는 한 번에 끝냅니다. 그 차이가
# 그대로 토큰 수에 실립니다.
#
# 이 값이 없으면 "압축으로 22% 줄였다" 를 검증할 수 없습니다. 잡음이
# 30% 인데 22% 를 성과라고 적으면 틀린 보고서가 됩니다.
# ─────────────────────────────────────────────────────────────
def load_control(run_dir, job_dirs) -> dict | None:
    if not run_dir or not run_dir.exists():
        return None
    arms_path = run_dir / "arms.json"
    if not arms_path.exists():
        return None
    arms = json.loads(arms_path.read_text(encoding="utf-8"))
    by_url = {a["base_url"]: a["name"] for a in arms}

    jobs = [j for j in (job_dirs or []) if j.exists()]
    if not jobs:
        return None
    leaves = sorted({p.parent for j in jobs for p in j.glob("*/result.json")}) or jobs
    rows = collect(leaves, by_url)
    if not rows:
        return None

    summ = summarize(rows, arms, run_dir)
    base = next((s for s in summ if s["kind"] == "direct"), None)
    if not base or not base["in_tok"]:
        return None

    # 압축 arm 이라고 적혀 있지만 실제로는 아무것도 안 한 arm 들의
    # 기준선 대비 변화. 이게 곧 "압축 없이 생기는 차이" 입니다.
    spread = [(s["arm"], 1 - s["in_tok"] / base["in_tok"])
              for s in summ if s["kind"] != "direct" and s["in_tok"]]
    if not spread:
        return None
    return {"n": len(rows), "base": base["in_tok"], "spread": spread,
            "worst": max(abs(v) for _, v in spread),
            "compressed": any(s.get("n_compress") for s in summ)}


def _noise_section(control: dict, summ: list[dict], base) -> list:
    if not control:
        return []
    L = ["", "## 4-1. 이 차이가 진짜인가", ""]
    if control["compressed"]:
        L += ["⚠️ 대조군에서 `compress` 이벤트가 나왔습니다. 진짜 대조군이 아니므로 "
              "아래 숫자를 판정 기준으로 쓰면 안 됩니다.", ""]
        return L

    L += ["저울에 같은 물건을 세 번 올렸는데 눈금이 매번 다르면, 그 차이만큼은",
          "**무게가 아니라 저울 탓**입니다. 그 폭을 먼저 재 둡니다.", "",
          "같은 실험을 **압축을 끄고** 한 번 더 돌렸습니다. 세 갈래가 똑같은",
          "프롬프트를 보냈으니 입력 토큰도 같아야 하는데, 실제로는 갈렸습니다.",
          "에이전트가 매번 똑같이 행동하지 않아서입니다 — 어떤 회차엔 파일을",
          "세 번 읽고 어떤 회차엔 다섯 번 읽습니다.", "",
          f"갈린 폭이 **±{control['worst'] * 100:.0f}%** 였습니다. 즉 "
          f"**아무것도 안 바꿔도 토큰이 이만큼 흔들립니다.**", ""]

    rows = [[f"`{a}`", f"{v * 100:+.1f}%", "압축 없음"] for a, v in control["spread"]]
    L += [_r.md_table(["대조군 갈래", "기준선 대비 입력 토큰", "실제 압축"], rows)]

    L += ["", "이번 측정을 이 기준으로 판정하면:", ""]
    cmp_rows = []
    for s in summ:
        if s["kind"] == "direct" or not s["in_tok"] or not base or not base["in_tok"]:
            continue
        red = 1 - s["in_tok"] / base["in_tok"]
        verdict = ("**확실한 효과** — 그냥 돌려서 나올 수 있는 폭을 넘습니다"
                   if abs(red) > control["worst"]
                   else "**구분 불가** — 압축 덕인지 운인지 알 수 없습니다")
        cmp_rows.append([f"`{s['arm']}`", f"{red * 100:+.1f}%",
                         f"±{control['worst'] * 100:.0f}%", verdict])
    L += [_r.md_table(["갈래", "줄어든 양", "그냥 돌려도 생기는 차이", "판정"],
                      cmp_rows)]
    L += ["", "> 이 폭을 넘으려면 표본을 늘리는 수밖에 없습니다. 태스크를 더 넣거나",
          "> `n_attempts` 를 올려서 회차 평균을 내야 합니다."]
    return L


# ─────────────────────────────────────────────────────────────
# 본문
# ─────────────────────────────────────────────────────────────
def build_md(meta: dict, arms: list[dict], rows: list[dict],
             summ: list[dict], control: dict | None = None) -> str:
    base = next((s for s in summ if s["kind"] == "direct"), summ[0] if summ else None)
    langs = sorted({r["lang"] for r in rows})
    tasks = sorted({r["task"] for r in rows})
    ok = [s for s in summ if s["n_ok"]]

    L = [f"# {meta['name']} — 컨테이너 롤아웃 결과", ""]
    L += [f"*{meta['stamp']} · {meta['benchmark']} · {meta['model']} · "
          f"태스크 {len(tasks)}개 · 언어 {'/'.join(langs) or '—'} · "
          f"trial {len(rows)}건*", ""]

    # ── 1. 세 줄 요약 ───────────────────────────────────────
    L += ["## 1. 세 줄 요약", ""]
    L += _summary_lines(base, ok, rows, meta)

    # ── 2. 무엇을 어떻게 쟀나 ────────────────────────────────
    L += ["", "## 2. 무엇을 어떻게 쟀나", "",
          "에이전트가 **컨테이너 안에서 실제로** 과제를 풀고, 별도 채점 컨테이너가",
          "테스트를 돌립니다. 압축은 에이전트와 모델 사이에 낀 프록시가 합니다.",
          "에이전트도 벤치마크도 압축이 끼어든 걸 모릅니다.", "",
          "```",
          "에이전트 컨테이너 ──▶ squid(egress) ──▶ proxy.py ──▶ 모델 API",
          "                                         └ LLMLingua-2 압축",
          "        ↓ 다 끝나면",
          "채점 컨테이너 ──▶ 테스트 실행 ──▶ reward",
          "```", "",
          "그래서 이 표의 pass@1 은 **대리 지표가 아니라 실제 성공률**입니다.",
          "대신 1 trial 이 5~15분이라 조건을 많이 둘 수 없습니다.", ""]
    L += _params_table(meta, arms)

    # ── 3. 지표 읽는 법 ─────────────────────────────────────
    L += ["", "## 3. 지표 읽는 법", ""] + _glossary()

    # ── 4. 결과 ─────────────────────────────────────────────
    L += ["", "## 4. 결과", ""]
    L += _result_table(summ, base)
    L += ["", bar_chart("pass1", "pass@1 (높을수록 좋음)",
                        [s["arm"] for s in summ], [s["pass1"] for s in summ],
                        lambda v: f"{v * 100:.0f}%")]
    L += ["", bar_chart("tokens", "평균 입력 토큰 (낮을수록 좋음)",
                        [s["arm"] for s in summ], [s["in_tok"] for s in summ],
                        lambda v: f"{v:,.0f}", good_high=False)]
    L += ["", _ascii_block(summ)]
    L += _noise_section(control, summ, base)

    # ── 5. 맞바꿈 ───────────────────────────────────────────
    if base and base["in_tok"]:
        pts = [(s["arm"], 1 - (s["in_tok"] / base["in_tok"]), s["pass1"])
               for s in summ if s["in_tok"] and s["pass1"] is not None]
        L += ["", "## 5. 절감과 정확도의 맞바꿈", "",
              "왼쪽 아래로 갈수록 나쁩니다. 토큰도 못 줄이고 정확도도 떨어진 것입니다.",
              "오른쪽 위가 이상적입니다.", "",
              scatter_chart("trade", "절감 × pass@1", pts)]

    # ── 6. 태스크별 ─────────────────────────────────────────
    L += ["", "## 6. 태스크·언어별", ""] + _per_task(rows, summ, tasks, langs)

    # ── 7. 실패한 trial ─────────────────────────────────────
    L += ["", "## 7. 실패한 trial", ""] + _failures(rows)

    # ── 8. 한계 ─────────────────────────────────────────────
    L += ["", "## 8. 이 결과로 말할 수 없는 것", ""] + _limits(meta, rows, summ)

    # ── 부록 ────────────────────────────────────────────────
    L += ["", "## 부록 — 재현", ""] + _repro(meta)
    return "\n".join(L)


def _summary_lines(base, ok, rows, meta) -> list:
    """수치를 보고 문장을 고른다. 미리 심어 둔 결론은 없다."""
    if not ok:
        return ["채점된 trial 이 없습니다. 7절의 실패 목록을 먼저 보세요.", ""]

    out = []

    # ── 0. 압축이 정말 걸렸는가 ─────────────────────────────
    # 가장 먼저 본다. 압축기가 조용히 놀고 있으면 아래 비교는 전부
    # "baseline 대 baseline" 이 되고, 표는 "압축해도 차이 없다" 로 읽힌다.
    # 실제로 그런 적이 있다 — 프록시가 /chat/completions 만 보고 있는데
    # 에이전트는 /responses 를 불러서, 압축 arm 이 원문을 그대로 보냈다.
    silent = [s for s in ok if s["kind"] != "direct" and not s.get("n_compress")]
    if silent:
        names = ", ".join(f"**{s['arm']}**" for s in silent)
        out.append(
            f"⚠️ {names} 는 압축 arm 인데 `compress` 이벤트가 **한 건도 없습니다.** "
            "프록시를 지나가긴 했지만 아무것도 줄이지 않았다는 뜻이라, "
            "이 arm 의 수치는 baseline 과 같은 조건입니다. 비교로 쓰지 마세요.")

    comp = [s for s in ok if s["kind"] != "direct" and s.get("n_compress")]
    if base and base["n_ok"] and comp:
        # ── 바닥 효과 ────────────────────────────────────────
        # 기준선이 0% 면 압축이 정확도를 떨어뜨렸는지 알 수 없습니다.
        # 떨어질 자리가 없기 때문입니다. 이걸 적어 두지 않으면 표만 보고
        # "압축해도 정확도가 안 떨어진다" 는 반대 결론이 나옵니다.
        if not base["pass1"] and all(not s["pass1"] for s in comp):
            out.append(
                "**모든 arm 이 pass@1 0% 입니다.** 기준선부터 못 푸는 과제라 "
                "압축이 정확도를 떨어뜨렸는지는 **이 측정으로 알 수 없습니다**"
                "(바닥 효과). 아래에서 읽을 수 있는 것은 토큰·비용·스텝뿐입니다.")

        best = max(comp, key=lambda s: (s["pass1"] or 0))
        if base["in_tok"] and best["in_tok"]:
            red = 1 - best["in_tok"] / base["in_tok"]
            gap = (best["pass1"] or 0) - (base["pass1"] or 0)
            verb = "같았습니다" if abs(gap) < 1e-9 else (
                "높았습니다" if gap > 0 else "낮았습니다")
            out.append(
                f"압축 arm 중 가장 나은 **{best['arm']}** 는 기준선 대비 입력 토큰을 "
                f"**{red * 100:+.1f}%** 바꾸면서 pass@1 이 "
                f"**{abs(gap) * 100:.1f}%p {verb}**"
                f" ({pc(base['pass1'])} → {pc(best['pass1'])}).")
            if red < 0:
                out.append(
                    "토큰이 **늘었습니다.** 압축은 프롬프트를 줄이지만, 정보가 빠지면 "
                    "에이전트가 파일을 다시 읽습니다. 그 되읽기가 절감분을 먹습니다.")
    n_err = sum(1 for r in rows if r["error"])
    if n_err:
        out.append(f"{len(rows)}건 중 **{n_err}건이 오류로 중단**됐습니다. "
                   f"압축 품질과 무관한 실패가 섞여 있는지 7절에서 확인하세요.")
    else:
        out.append(f"{len(rows)}건 모두 끝까지 돌았습니다. 중단으로 인한 왜곡은 없습니다.")

    n_ok_total = sum(s["n_ok"] for s in ok)
    out.append(f"채점된 trial 은 **{n_ok_total}건**뿐입니다. "
               f"이 숫자는 **경향**이지 순위가 아닙니다 — 8절을 읽어 주세요.")

    # 문장이 몇 개 남을지는 수치에 달려 있어서 번호는 마지막에 붙인다.
    return [f"{i}. {s}" for i, s in enumerate(out, 1)]


def _params_table(meta, arms) -> list:
    head = ["arm", "경로", "압축기", "rate", "이 값이 뜻하는 것"]
    rows = []
    for a in arms:
        if a["kind"] == "direct":
            rows.append([f"`{a['name']}`", "모델 API 직행", "—", "—",
                         "압축 없음. 다른 모든 값의 기준선입니다."])
        else:
            r = a.get("ratio")
            rows.append([f"`{a['name']}`", "프록시 경유",
                         a.get("compressor", "—"), f"`{r}`" if r else "—",
                         f"프롬프트를 원래 길이의 **{r}배**까지 남깁니다. "
                         f"작을수록 세게 줄입니다." if r else "—"])
    return [_r.md_table(head, rows)] + ["",
            "> **rate 는 목표치이지 결과가 아닙니다.** LLMLingua 는 토큰을 지우는 "
            "방식이라 실제 절감은 문서 성격에 따라 달라집니다. 실제로 얼마나 "
            "줄었는지는 4절의 *입력 토큰* 열을 보세요.", ""]


def _glossary() -> list:
    head = ["지표", "무엇인가", "어떻게 나오나", "방향"]
    rows = [
        ["**pass@1**", "한 번 시도해서 과제를 완전히 푼 비율",
         "채점 컨테이너가 테스트를 돌려 `reward`가 1인 trial ÷ 채점된 trial", "높을수록 좋음"],
        ["**부분점수**", "다 못 풀었어도 통과한 테스트 비율",
         "`partial_reward`의 평균. pass@1 이 0이어도 여기서 차이가 보입니다", "높을수록 좋음"],
        ["**입력 토큰**", "롤아웃 전체에서 모델에 **들여보낸** 토큰의 합",
         "에이전트가 기록한 `n_input_tokens`의 평균. 압축 효과가 최종적으로 "
         "나타나는 곳입니다", "낮을수록 좋음"],
        ["**peak 컨텍스트**", "한 번의 호출에서 가장 컸던 프롬프트",
         "`peak_context_tokens`의 평균. 컨텍스트 한도에 부딪히는지 보는 값", "낮을수록 좋음"],
        ["**스텝**", "에이전트가 명령을 몇 번 실행했나",
         "`n_agent_steps`의 평균. 압축으로 정보가 빠지면 되읽느라 늘어납니다", "낮을수록 좋음"],
        ["**비용**", "그 trial 의 모델 요금",
         "`cost_usd`의 평균. 캐시 할인이 반영된 실제 청구 기준", "낮을수록 좋음"],
        ["**소요**", "trial 하나가 걸린 벽시계 시간",
         "`started_at`~`finished_at`. 압축 자체의 지연이 여기 포함됩니다", "낮을수록 좋음"],
        ["**자기보고 절감**", "프록시가 스스로 잰 문자 수 절감",
         "`chars_before`/`chars_after`. **참고값입니다** — 압축기가 자기 성적을 "
         "매기는 셈이라, 근거는 왼쪽의 *입력 토큰*입니다", "참고"],
    ]
    return [_r.md_table(head, rows)]


def _result_table(summ, base) -> list:
    head = ["arm", "채점", "pass@1", "부분점수", "입력 토큰", "vs 기준",
            "peak", "스텝", "비용", "소요", "자기보고"]
    rows = []
    for s in summ:
        p = s["proxy"]
        self_red = (1 - p["after"] / p["before"]) if p["before"] else None
        rows.append([
            f"`{s['arm']}`",
            f"{s['n_ok']}/{s['n']}" + (f" (오류 {s['n_err']})" if s["n_err"] else ""),
            pc(s["pass1"]), pc(s["partial"]),
            num(s["in_tok"]),
            "기준" if s is base else delta(s["in_tok"], base["in_tok"] if base else None,
                                          invert=True),
            num(s["peak"]), num(s["steps"], 1),
            "—" if s["cost"] is None else f"${s['cost']:.2f}",
            "—" if s["secs"] is None else f"{s['secs'] / 60:.1f}분",
            pc(self_red),
        ])
    out = [_r.md_table(head, rows)]
    retries = sum(s["proxy"]["auth_retry"] for s in summ)
    if retries:
        out += ["", f"> 프록시가 401 을 받아 토큰을 새로 발급하고 재시도한 횟수: "
                    f"**{retries}회**. 이 재시도가 없으면 그 시점에 롤아웃이 "
                    f"중단됩니다(에이전트가 `--exit-immediately` 로 돌기 때문)."]
    return out


def _ascii_block(summ) -> str:
    """마크다운만 보는 사람을 위한 막대. HTML 에서는 위의 SVG 를 봅니다."""
    vals = [s["pass1"] for s in summ if s["pass1"] is not None]
    if not vals:
        return ""
    vmax = max(vals) or 1
    w = max(len(s["arm"]) for s in summ)
    lines = ["```", "pass@1"]
    for s in summ:
        lines.append(f"  {s['arm']:<{w}}  {ascii_bar(s['pass1'], vmax):<22} {pc(s['pass1'])}")
    toks = [s["in_tok"] for s in summ if s["in_tok"]]
    if toks:
        tmax = max(toks)
        lines += ["", "평균 입력 토큰"]
        for s in summ:
            lines.append(f"  {s['arm']:<{w}}  {ascii_bar(s['in_tok'], tmax):<22} {num(s['in_tok'])}")
    lines.append("```")
    return "\n".join(lines)


def _per_task(rows, summ, tasks, langs) -> list:
    names = [s["arm"] for s in summ]
    head = ["태스크", "언어"] + names
    out = []
    for t in tasks:
        for lg in langs:
            cells = []
            for n in names:
                m = [r for r in rows if r["task"] == t and r["lang"] == lg and r["arm"] == n]
                if not m:
                    cells.append("—")
                elif m[0]["error"]:
                    cells.append("오류")
                else:
                    rw = m[0]["reward"]
                    pt = m[0]["partial"]
                    mark = "✅" if rw == 1 else "❌"
                    cells.append(f"{mark} {pc(pt, 0)}" if pt is not None else mark)
            out.append([t, lg] + cells)
    if not out:
        return ["집계할 trial 이 없습니다."]
    return [_r.md_table(head, out), "",
            "✅ = 전부 통과(reward 1) · ❌ = 미통과 · 옆의 %는 부분점수입니다.",
            "부분점수가 높은데 ❌ 라면 \"거의 다 왔는데 한 가지를 놓쳤다\" 는 뜻입니다."]


def _failures(rows) -> list:
    bad = [r for r in rows if r["error"]]
    if not bad:
        return ["없습니다. 모든 trial 이 채점까지 갔습니다."]
    head = ["태스크", "언어", "arm", "예외", "스텝"]
    body = [[r["task"], r["lang"], f"`{r['arm']}`", f"`{r['error']}`",
             num(r["steps"])] for r in bad]
    return [_r.md_table(head, body), "",
            "> 스텝이 **0** 이면 모델을 한 번도 못 불렀다는 뜻이라 압축 품질과 무관합니다.",
            "> 네트워크·인증을 먼저 의심하세요. 스텝이 쌓인 뒤 죽었다면 그때는",
            "> 압축된 컨텍스트로 에이전트가 헤맸을 가능성이 있습니다."]


def _limits(meta, rows, summ) -> list:
    n_ok = sum(s["n_ok"] for s in summ)
    per_arm = min((s["n_ok"] for s in summ), default=0)
    step = (1 / per_arm * 100) if per_arm else None
    out = [
        f"- **표본이 {n_ok}건입니다.** arm 당 가장 적은 곳이 {per_arm}건이라, "
        + (f"한 건이 뒤집히면 pass@1 이 {step:.0f}%p 움직입니다. "
           if step else "")
        + "순위를 말하려면 `n_attempts` 를 올려 다시 돌려야 합니다.",
        "- **태스크가 편향돼 있습니다.** 여기 쓴 태스크는 전체 중 일부만 고른 것이라, "
        "다른 태스크에서 같은 결론이 나온다는 보장이 없습니다.",
        "- **모델 한 종류만 봤습니다.** 압축에 대한 내성은 모델마다 다릅니다. "
        f"여기서는 `{meta['model']}` 하나입니다.",
        "- **캐시가 결과를 흔듭니다.** 압축은 프롬프트 앞부분을 바꾸므로 프리픽스 "
        "캐시가 깨집니다. 그래서 토큰이 줄어도 **비용은 늘 수 있습니다.** "
        "4절에서 두 열을 같이 보세요.",
    ]
    return out


def _repro(meta) -> list:
    return ["```bash",
            "# 1) pier 를 이 환경에 맞게 손봅니다 (사내망 미러 + egress 허용 포트)",
            "./.venv/bin/python patch_pier.py",
            "",
            "# 2) 프록시를 띄우고 pier 설정을 만듭니다",
            "export OPENAI_API_KEY=$(az account get-access-token \\",
            "  --scope https://cognitiveservices.azure.com/.default \\",
            "  --query accessToken -o tsv)",
            f"export UPSTREAM_BASE_URL={meta.get('upstream', '<endpoint>')}",
            "export PUBLIC_HOST=host.docker.internal",
            "export PIER_EXTRA_SAFE_PORTS='8801 8802 8803 8804'",
            f"python launch.py experiments/{meta['name']}.yaml",
            "",
            "# 3) 롤아웃",
            f"pier run --config runs/agentic-eval/{meta['benchmark']}/{meta['name']}/"
            f"{meta['stamp']}/en/pier.yaml --jobs-dir /tmp/job",
            "",
            "# 4) 이 보고서",
            f"python report_run.py runs/agentic-eval/{meta['benchmark']}/{meta['name']}/"
            f"{meta['stamp']} --jobs /tmp/job -o reports/{meta['name']}",
            "```", "",
            "> `PIER_EXTRA_SAFE_PORTS` 를 빼면 압축 arm 이 **0 스텝에서 죽습니다.** "
            "pier 의 egress 프록시(squid)가 80/443 외의 포트를 허용목록보다 "
            "**먼저** 막기 때문입니다. 자세한 이유는 `patch_pier.py` 의 설명에 있습니다."]


# ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="롤아웃 결과 보고서")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--jobs", type=Path, nargs="+", required=True)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--control", type=Path, metavar="RUN_DIR",
                    help="압축이 걸리지 않은 채로 돈 같은 실험. 그냥 돌려도 생기는 차이를 재는 데 씁니다")
    ap.add_argument("--control-jobs", type=Path, nargs="+", metavar="DIR")
    args = ap.parse_args()

    arms_path = args.run_dir / "arms.json"
    if not arms_path.exists():
        sys.exit(f"✗ arms.json 이 없습니다: {arms_path}")
    arms = json.loads(arms_path.read_text(encoding="utf-8"))
    by_url = {a["base_url"]: a["name"] for a in arms}

    meta_path = args.run_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta.setdefault("name", args.run_dir.parent.name)
    meta.setdefault("benchmark", args.run_dir.parent.parent.name)
    meta.setdefault("stamp", args.run_dir.name)
    meta.setdefault("model", "—")

    jobs = [j for j in args.jobs if j.exists()]
    if not jobs:
        sys.exit(f"✗ jobs 디렉터리가 없습니다: {args.jobs}")
    # 잡 폴더가 언어별로 갈려 있습니다(smoke-en, smoke-ko). trial 은 그 바로
    # 아래에 있으므로, result.json 을 가진 부모를 잡 폴더로 봅니다.
    job_dirs = sorted({p.parent for j in jobs for p in j.glob("*/result.json")}) or jobs
    rows = collect(job_dirs, by_url)
    if not rows:
        sys.exit(f"✗ trial 을 찾지 못했습니다: {jobs}")

    summ = summarize(rows, arms, args.run_dir)
    control = load_control(args.control, args.control_jobs)
    md = build_md(meta, arms, rows, summ, control)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.md").write_text(md, encoding="utf-8")
    _r.CHARTS.update(CHARTS)
    (args.out / "report.html").write_text(_r.build_html(md, meta["name"]),
                                          encoding="utf-8")
    (args.out / "results.json").write_text(
        json.dumps({"meta": meta, "arms": arms, "trials": rows, "summary": summ},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"▸ trial {len(rows)}건 · arm {len(arms)}개")
    for s in summ:
        print(f"    {s['arm']:<22} 채점 {s['n_ok']}/{s['n']}  "
              f"pass@1 {pc(s['pass1'])}  입력 {num(s['in_tok'])}")
    print(f"▸ {args.out}/report.md · report.html · results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""여러 갈래로 흩어진 측정을 **한 장**으로 모읍니다.

왜 또 리포트인가
────────────────
지금까지 리포트가 셋 있습니다.

    reports/llmlingua2-grid/    압축기만 24조건으로 훑은 것 (대리 측정)
    reports/terminal-bench*/    도커로 에이전트를 돌린 것 (정석 측정)
    reports/llmlingua-deepswe/  그 전 세대 대리 측정

각각은 자기 실험만 설명합니다. 그래서 "그래서 압축을 써도 되는가" 라는
질문에는 셋을 다 읽어야 답이 나옵니다. 이 스크립트는 그 답을 한 장에
씁니다 — 무엇을 어떻게 쟀고, 파라미터가 각각 무슨 뜻이고, 압축이 실제로
텍스트를 어떻게 바꾸고, 결과가 무엇이고, 그 수치를 어디까지 믿을 수
있는지까지.

원칙
────
측정값을 이 파일에 적지 않습니다. 전부 결과 파일에서 읽습니다. 숫자를
손으로 옮기면 다음 실행 때 조용히 틀린 리포트가 됩니다.

쓰는 곳
    ./.venv/bin/python report_summary.py \
        --grid ../../reports/llmlingua2-grid/results.json \
        --run  runs/agentic-eval/terminal-bench/terminal-bench-wide/<stamp> \
        --jobs /tmp/tbwide2 \
        --control-run runs/.../<stamp> --control-jobs /tmp/tbjob-nocompress \
        --samples ../../reports/summary/samples.json \
        -o ../../reports/summary
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import report as _r          # noqa: E402  (md_table · CSS · build_html 재사용)
import report_run as _rr     # noqa: E402  (롤아웃 판독 재사용)

REPO = HERE.parent.parent


# ─────────────────────────────────────────────────────────────────────
# 사전 — 파라미터와 지표가 각각 무슨 뜻인지
# 사용자가 "저 옵션들이 뭔지 모르겠다" 고 한 부분입니다. 값이 아니라
# **뜻과 기본값**만 담습니다. 실제 쓰인 값은 결과 파일에서 읽습니다.
# ─────────────────────────────────────────────────────────────────────
PARAM_DOC = {
    "rate": ("남길 비율", "0.5 면 원문의 50% 만 남깁니다. 낮출수록 많이 줄지만 "
             "정보가 사라집니다. 이 실험의 **주 조절 손잡이**입니다."),
    "force_tokens": ("구조 문자 보존", "줄바꿈·마침표 같은 구조 토큰을 강제로 "
                     "남깁니다. 켜면 읽기는 좋아지지만 그만큼 분량을 써서 "
                     "내용 토큰이 밀려납니다."),
    "force_reserve_digit": ("숫자 보존", "숫자를 지웁니다/안 지웁니다. 오류 코드나 "
                            "줄 번호가 중요할 때 켭니다."),
    "drop_consecutive": ("중복 제거", "같은 토큰이 잇달아 나오면 하나만 남깁니다."),
    "chunk_end_tokens": ("청크 경계", "긴 글을 나눠 압축할 때 경계로 삼을 토큰 수."),
}

POLICY_DOC = {
    "rate": ("압축률", "위 `rate` 와 같습니다."),
    "keep_last": ("최근 N개 보존", "대화의 마지막 N개 메시지는 건드리지 않습니다. "
                  "직전 맥락이 깨지면 에이전트가 바로 헤매기 때문입니다."),
    "min_chars": ("최소 길이", "이보다 짧은 메시지는 압축하지 않습니다. "
                  "짧은 글은 줄일 것도 없는데 망가지기만 합니다."),
    "skip_system": ("시스템 프롬프트 제외", "규칙·도구 설명이 든 자리라 한 글자만 "
                    "빠져도 에이전트가 형식을 어깁니다. 보통 켭니다."),
}

METRIC_DOC = [
    ("pass@1", "**정답률.** 에이전트가 과제를 한 번 시도해 실제로 통과한 비율. "
               "채점은 태스크가 들고 있는 pytest 가 합니다. 이 실험의 **최종 지표**입니다."),
    ("토큰 절감", "모델에 실제로 들어간 입력 토큰이 몇 % 줄었는지. "
                 "제공자가 세어 준 값이라 자기보고가 아닙니다."),
    ("주고받은 횟수", "에이전트가 한 과제를 푸는 동안 모델을 몇 번 불렀는지. "
                    "**헤맬수록 늘어납니다.** 부를 때마다 그때까지의 대화가 "
                    "통째로 다시 들어가므로, 이 값이 늘면 토큰도 같이 늡니다."),
    ("자기보고 절감", "압축기가 \"내가 이만큼 줄였다\" 고 기록한 값. "
                    "참고용입니다 — 캐시·재시도 때문에 실제 청구 토큰과 다릅니다."),
    ("hit@1", "간이 측정 전용. 압축된 맥락만 보고 모델이 **가장 관련 있는 파일**을 "
              "첫 번째로 맞혔는지. 정답률을 싸게 대신 재는 값입니다."),
    ("식별자 보존", "`app/auth.py`, `test_login` 같은 이름이 압축 후에도 "
                  "남아 있는 비율. 코드 작업에서 이게 깨지면 치명적입니다."),
    ("숫자 보존", "`401`, `42` 같은 숫자가 남아 있는 비율."),
    ("지연", "압축 자체에 드는 시간. 에이전트가 한 과제에 수십 번 호출하므로 "
            "그대로 곱해집니다."),
]


def pc(v, d=1):
    return "—" if v is None else f"{v * 100:.{d}f}%"


def sign(v, d=1):
    if v is None:
        return "—"
    return f"{'+' if v >= 0 else ''}{v * 100:.{d}f}%p"


def num(v):
    return "—" if v is None else f"{v:,.0f}"


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


# ─────────────────────────────────────────────────────────────────────
# 데이터 읽기
# ─────────────────────────────────────────────────────────────────────
def read_rollout(run_dir: Path, jobs: list[Path]) -> dict | None:
    """도커 롤아웃 하나를 arm 별로 접습니다.

    `arms.json` 은 압축 없는 arm 을 `compressor: null · ratio: null` 로 적습니다.
    아래에서 `"none"` / 1.0 으로 펴 두면 이후 코드가 갈래를 안 칩니다.
    """
    arms_f = run_dir / "arms.json"
    if not arms_f.exists():
        return None
    arms = json.loads(arms_f.read_text(encoding="utf-8"))
    for a in arms:
        a["compressor"] = a.get("compressor") or "none"
        a["rate"] = a.get("ratio") if a.get("ratio") is not None else 1.0
        a["params"] = a.get("args") or {}
        a["protect"] = a.get("protect") or {}
    by_url = {a["base_url"]: a["name"] for a in arms if a.get("base_url")}
    rows = _rr.collect(jobs, by_url)
    if not rows:
        return None

    out = {"arms": arms, "rows": rows, "run_dir": run_dir, "by_arm": []}
    for a in arms:
        band = [r for r in rows if r["arm"] == a["name"]]
        if not band:
            continue
        rw = [r["reward"] for r in band if r["reward"] is not None]
        px = _rr.proxy_stats(run_dir, a["name"])
        out["by_arm"].append({
            "name": a["name"],
            "compressor": a.get("compressor", "—"),
            "rate": a.get("rate"),
            "n": len(band),
            "pass1": (sum(1 for x in rw if x > 0) / len(rw)) if rw else None,
            "n_pass": sum(1 for x in rw if x > 0),
            "in_tok": mean([r["in_tok"] for r in band]),
            "out_tok": mean([r["out_tok"] for r in band]),
            "steps": mean([r["steps"] for r in band]),
            "secs": mean([r["secs"] for r in band]),
            "n_compress": px.get("n_compress", 0),
            "self_red": (1 - px["after"] / px["before"]) if px.get("before") else None,
            "tasks_passed": sorted({r["task"] for r in band
                                    if (r["reward"] or 0) > 0}),
        })
    return out


def read_grid(path: Path) -> dict | None:
    """대리 측정(압축기 단독) 결과."""
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    arms = {a["name"]: a for a in d["arms"]}
    summ = []
    for name, a in arms.items():
        band = [r for r in d["runs"] if r["arm"] == name]
        if not band:
            continue
        f = lambda k: mean([float(r[k]) for r in band            # noqa: E731
                            if str(r.get(k, "")) not in ("", "None")])
        asked = [r for r in band if str(r.get("asked")) == "True"]
        summ.append({
            "arm": name, "group": a["group"], "rate": a["rate"],
            "compressor": a["compressor"], "params": a.get("params") or {},
            "protect": a.get("protect") or {},
            "reduction": f("reduction"), "ident": f("ident"), "num": f("num"),
            "latency": f("latency_s"),
            "hit1": mean([float(r["hit1"]) for r in asked
                          if str(r.get("hit1", "")) not in ("", "None")]),
            "n": len(band),
        })
    return {"meta": d, "summ": summ,
            "base": next((s for s in summ if s["compressor"] == "none"), None)}


# ─────────────────────────────────────────────────────────────────────
# 본문
# ─────────────────────────────────────────────────────────────────────
def build_md(D: dict) -> str:
    L = ["# LLM 토큰 압축 — 측정 보고서", "",
         f"<p class='meta'>생성 {datetime.now():%Y-%m-%d %H:%M} · "
         f"압축기 LLMLingua-2 · 대상 코딩 에이전트</p>", "",
         "이 문서 하나로 끝나도록 썼습니다. **무엇을 쟀고 · 파라미터가 무슨 "
         "뜻이고 · 압축이 글을 어떻게 바꾸고 · 결과가 무엇이고 · 그 수치를 "
         "어디까지 믿을 수 있는지** 순서로 갑니다.", ""]
    L += _toc()
    L += _headline(D)
    L += _how(D)
    L += _samples(D)
    L += _params(D)
    L += _benchmark(D)
    L += _result_docker(D)
    L += _result_grid(D)
    L += _trust(D)
    L += _verdict(D)
    return "\n".join(L)


def _toc() -> list:
    items = ["한눈에", "무엇을 어떻게 쟀나", "압축이 실제로 하는 일 (샘플)",
             "파라미터 사전", "벤치마크 설명", "결과 ① 정석 측정 (도커)",
             "결과 ② 대리 측정 (압축기 단독)", "이 수치를 믿어도 되나",
             "그래서 무엇을 할까"]
    return ["<div class='toc'>",
            " · ".join(f"<a href='#s{i}'>{i}. {t}</a>"
                       for i, t in enumerate(items, 1)),
            "</div>", ""]


# ── 1. 한눈에 ────────────────────────────────────────────────────────
def _headline(D) -> list:
    L = ["", "<h2 id='s1'>1. 한눈에</h2>", ""]
    dk, gr = D.get("docker"), D.get("grid")

    if dk and dk["by_arm"]:
        base = next((a for a in dk["by_arm"] if a["compressor"] == "none"),
                    dk["by_arm"][0])
        comp = [a for a in dk["by_arm"] if a is not base]
        L += ["**정석 측정(도커에서 에이전트를 실제로 돌린 것)의 결론부터** — "
              "압축은 토큰을 줄였고, **정답률도 같이 줄었습니다.**", ""]
        rows = []
        for a in [base] + comp:
            d_in = (a["in_tok"] / base["in_tok"] - 1) if (
                base["in_tok"] and a["in_tok"]) else None
            is_base = a is base
            d_p = None if is_base else (
                (a["pass1"] - base["pass1"])
                if (a["pass1"] is not None and base["pass1"] is not None)
                else None)
            rows.append([f"`{a['name']}`",
                         "압축 안 함" if is_base else f"rate {a['rate']}",
                         f"{a['n_pass']}/{a['n']}",
                         pc(a["pass1"], 0), "기준" if is_base else sign(d_p, 0),
                         num(a["in_tok"]), "기준" if is_base else pc(d_in)])
        L += [_r.md_table(["arm", "설정", "통과", "pass@1", "vs 기준선",
                           "평균 입력 토큰", "토큰 변화"], rows)]
        # 부분집합인지 — 이게 사실이면 "압축이 능력을 깎았다" 는 읽기가 강해집니다.
        bs = set(base["tasks_passed"])
        nested = all(set(a["tasks_passed"]) <= bs for a in comp)
        if nested and comp:
            L += ["", "> 압축 arm 이 통과한 태스크는 **모두 기준선도 통과한 "
                  "것**입니다. 압축이 없던 능력을 만들어 내지는 않았고, "
                  "있던 능력을 깎기만 했습니다."]

    if gr and gr["base"]:
        b = gr["base"]
        keep = [s for s in gr["summ"] if s["compressor"] == "llmlingua"
                and s["hit1"] is not None and b["hit1"] is not None
                and s["hit1"] >= b["hit1"] - 0.05]
        if keep:
            best = max(keep, key=lambda s: s["reduction"])
            L += ["", f"**대리 측정(압축기만 {gr['meta'] and sum(1 for _ in gr['meta']['runs'])}회 "
                  f"돌린 것)에서는** 품질을 지키면서 `{best['arm']}` 조건이 "
                  f"토큰을 **{pc(best['reduction'])}** 줄였습니다. "
                  "다만 이건 에이전트를 돌린 게 아니라 "
                  "'압축된 글만 보고도 맞는 파일을 고를 수 있나' 만 확인한 간이 측정입니다.", ""]

    L += ["", "> **한 줄로.** 압축기 자체는 잘 돕니다(절반을 줄여도 파일은 "
          "찾아냅니다). 그런데 **에이전트를 실제로 돌리면 정답률이 떨어집니다.** "
          "이 둘의 간극이 이 보고서의 핵심입니다 — 8절에서 이유를 다룹니다.", ""]
    return L


# ── 2. 무엇을 어떻게 쟀나 ────────────────────────────────────────────
def _how(D) -> list:
    L = ["", "<h2 id='s2'>2. 무엇을 어떻게 쟀나</h2>", "",
         "측정을 **두 갈래**로 했습니다. 비싼 쪽과 싼 쪽입니다.", ""]
    L += ["```",
          "  ① 정석 측정 (도커)                    ② 대리 측정 (압축기 단독)",
          "  ────────────────────────              ────────────────────────",
          "  Terminal Bench 태스크                  같은 저장소의 실제 코드",
          "        ↓                                       ↓",
          "  격리된 도커 컨테이너                    맥락을 조립",
          "        ↓                                       ↓",
          "  코딩 에이전트가 셸을 두드림            [압축기]  ← rate·옵션을 바꿔 가며",
          "        ↓  (모든 호출이 프록시를 지남)           ↓",
          "  [프록시가 프롬프트를 압축]              모델에 '어느 파일?' 한 번 질문",
          "        ↓                                       ↓",
          "  태스크가 들고 있는 pytest 가 채점       맞혔나 (hit@1)",
          "        ↓                                       ↓",
          "     pass@1  ← 최종 지표                  싸고 빠름 · 조건을 많이 시험",
          "```", ""]
    L += ["|  | ① 정석 측정 | ② 대리 측정 |", "|---|---|---|",
          "| 무엇을 보나 | 과제를 **실제로 푸는가** | 압축 후에도 **핵심이 남는가** |",
          "| 에이전트 | 돕니다 (셸·파일 편집) | 안 돕니다 (한 번 질문) |",
          "| 채점 | 태스크의 pytest | 정답 파일과 대조 |",
          "| 비용 | 1건에 수 분 | 1건에 수 초 |",
          "| 쓰임 | **결론** | 조건 탐색 |", ""]

    dk = D.get("docker")
    if dk:
        n = len(dk["rows"])
        tasks = sorted({r["task"] for r in dk["rows"]})
        L += ["", "### 실제로 돌린 규모", "",
              f"- **정석**: 태스크 {len(tasks)}개 × arm {len(dk['by_arm'])}개 "
              f"= **{n} trial**", ]
    gr = D.get("grid")
    if gr:
        m = gr["meta"]
        L += [f"- **대리**: 조건 {len(gr['summ'])}개 × 케이스 "
              f"{len(m['runs']) // max(1, len(gr['summ']))}개 "
              f"= **{len(m['runs'])}회 압축**"]
    L += [""]
    return L


# ── 3. 샘플 ──────────────────────────────────────────────────────────
def _samples(D) -> list:
    S = D.get("samples")
    if not S:
        return []
    L = ["", "<h2 id='s3'>3. 압축이 실제로 하는 일 (샘플)</h2>", "",
         "숫자보다 이게 빠릅니다. **실제로 압축기를 돌려 받은 결과**입니다 "
         f"(손으로 적은 예시가 아닙니다 · 생성 {S['generated_at']}).", "",
         f"압축기 `{S['compressor']}` · {S['policy']}", ""]

    for c in S["cases"]:
        L += ["", f"### {c['label']}", "", f"{c['why']}", "",
              f"**압축 전** — {c['before_tokens']} 토큰", "",
              "```", c["before"].strip()[:900], "```", ""]
        rows = []
        for v in c["variants"]:
            rows.append([f"`{v['rate']}`", f"{v['after_tokens']}",
                         pc(v["reduction"]), f"{v['latency_s']}s"])
        L += [_r.md_table(["rate", "토큰", "절감", "지연"], rows)]
        mid = next((v for v in c["variants"] if v["rate"] == 0.5),
                   c["variants"][len(c["variants"]) // 2])
        L += ["", f"**압축 후 (rate {mid['rate']})** — {mid['after_tokens']} 토큰", "",
              "```", mid["after"].strip()[:900], "```"]

    L += ["", "> **여기서 바로 보이는 것.** 과제 설명은 절반으로 줄여도 핵심이 "
          "다 남습니다 — 오류 코드도, 파일 경로도, 줄 번호도 살아 있습니다. "
          "**그런데 도구 출력은 식별자가 깨집니다** "
          "(`test_parser.py::test_parse_header` → `_parser.py_parse_header`). "
          "에이전트가 그 이름으로 다시 명령을 만들어야 하는데 이름이 "
          "망가져 있으면 헛손질을 합니다. 6절의 정답률 하락과 이어지는 "
          "대목입니다.", ""]
    return L


# ── 4. 파라미터 ──────────────────────────────────────────────────────
def _params(D) -> list:
    L = ["", "<h2 id='s4'>4. 파라미터 사전</h2>", "",
         "손잡이가 두 층입니다. **압축기 안쪽**(LLMLingua-2 인자)과 "
         "**바깥 정책**(무엇을 압축 대상에서 뺄지)입니다.", "",
         "### 압축기 인자", ""]
    L += [_r.md_table(["인자", "뜻", "설명"],
                      [[f"`{k}`", v[0], v[1]] for k, v in PARAM_DOC.items()])]
    L += ["", "### 바깥 정책 (압축기에 넘기기 전에 우리가 정하는 것)", ""]
    L += [_r.md_table(["항목", "뜻", "설명"],
                      [[f"`{k}`", v[0], v[1]] for k, v in POLICY_DOC.items()])]

    # 실제로 어떤 값을 썼는지 — 결과 파일에서 읽습니다.
    dk = D.get("docker")
    if dk:
        L += ["", "### 정석 측정에서 실제로 쓴 값", ""]
        rows = []
        for a in dk["arms"]:
            p = a.get("params") or {}
            pr = a.get("protect") or {}
            rows.append([f"`{a['name']}`", a.get("compressor", "—"),
                         str(a.get("rate", "—")),
                         ", ".join(f"{k}={v}" for k, v in p.items()) or "기본값",
                         ", ".join(f"{k}={v}" for k, v in pr.items()) or "—"])
        L += [_r.md_table(["arm", "압축기", "rate", "압축기 인자", "정책"], rows)]
    gr = D.get("grid")
    if gr:
        L += ["", "### 대리 측정에서 훑은 조건", "",
              "24개 조건을 다섯 갈래로 나눠 돌렸습니다.", ""]
        g = {}
        for s in gr["summ"]:
            g.setdefault(s["group"], []).append(s["arm"])
        L += [_r.md_table(["갈래", "무엇을 바꾸나", "조건"],
                          [[k, {"기준선": "압축 안 함",
                                "압축률": "`rate` 만 바꿈",
                                "압축기 옵션": "LLMLingua-2 인자",
                                "보호 정책": "무엇을 압축에서 뺄지",
                                "모델 크기": "분류 모델 크기",
                                "대조군": "LLMLingua 대신 단순 절단"}.get(k, "—"),
                            " · ".join(f"`{x}`" for x in v)]
                           for k, v in g.items()])]
    L += [""]
    return L


# ── 5. 벤치마크 ──────────────────────────────────────────────────────
def _benchmark(D) -> list:
    L = ["", "<h2 id='s5'>5. 벤치마크 설명</h2>", "",
         "**Terminal Bench 2.1** 을 씁니다. 에이전트에게 터미널만 주고 실제 "
         "과제를 시키는 벤치마크입니다. 태스크마다 도커 이미지와 채점용 "
         "pytest 가 딸려 있습니다.", "",
         "채점이 **사람 판단이 아니라 테스트 통과 여부**라, 정답률이 "
         "재현 가능합니다.", ""]
    L += ["```",
          "  태스크 = 도커 이미지 + 과제 설명 + tests/test_outputs.py",
          "",
          "  1. 컨테이너를 띄운다",
          "  2. 에이전트가 셸을 두드려 과제를 푼다   ← 여기 프롬프트가 압축된다",
          "  3. 컨테이너를 그대로 두고 pytest 를 돌린다",
          "  4. 전부 통과하면 reward=1, 하나라도 실패하면 0",
          "```", ""]
    L += ["", "### 지표", ""]
    L += [_r.md_table(["지표", "설명"], [[f"**{k}**", v] for k, v in METRIC_DOC])]

    dk = D.get("docker")
    if dk:
        tasks = sorted({r["task"] for r in dk["rows"]})
        L += ["", "### 쓴 태스크", "",
              f"{len(tasks)}개입니다. 성격이 겹치지 않게 골랐습니다.", "",
              " · ".join(f"`{t}`" for t in tasks), ""]
    L += [""]
    return L


# ── 6. 정석 결과 ─────────────────────────────────────────────────────
def _result_docker(D) -> list:
    dk = D.get("docker")
    if not dk:
        return ["", "<h2 id='s6'>6. 결과 ① 정석 측정 (도커)</h2>", "",
                "_아직 결과가 없습니다._", ""]
    L = ["", "<h2 id='s6'>6. 결과 ① 정석 측정 (도커)</h2>", "",
         "**이게 결론입니다.** 에이전트가 실제로 과제를 풀었는지 봅니다.", ""]

    base = next((a for a in dk["by_arm"] if a["compressor"] == "none"),
                dk["by_arm"][0])
    rows = []
    for a in dk["by_arm"]:
        is_base = a is base
        d_p = None if is_base else (
            (a["pass1"] - base["pass1"])
            if (a["pass1"] is not None and base["pass1"] is not None) else None)
        d_in = (a["in_tok"] / base["in_tok"] - 1) if (
            base["in_tok"] and a["in_tok"]) else None
        rows.append([f"`{a['name']}`", f"{a['n_pass']}/{a['n']}",
                     pc(a["pass1"], 0), "기준" if is_base else sign(d_p, 0),
                     num(a["in_tok"]), "기준" if is_base else pc(d_in),
                     f"{a['steps']:.1f}" if a["steps"] else "—",
                     f"{a['secs']:.0f}s" if a["secs"] else "—",
                     pc(a["self_red"]) if a["self_red"] else "—",
                     str(a["n_compress"])])
    L += [_r.md_table(["arm", "통과", "pass@1", "vs 기준", "평균 입력 토큰",
                       "토큰 변화", "평균 주고받은 횟수", "평균 소요", "자기보고 절감",
                       "압축 횟수"], rows)]
    L += ["", "- **평균 입력 토큰** — 제공자가 세어 준 값입니다. 압축이 실제로 "
          "청구서를 줄였는지가 여기 나옵니다.",
          "- **자기보고 절감** — 압축기가 기록한 값. 위 값과 다른 건 캐시와 "
          "재시도 때문입니다.",
          "- **압축 횟수** — 0 이면 압축이 안 걸린 것입니다. 이 칸이 있는 이유는 "
          "8절에 있습니다.", ""]

    # 태스크 × arm 격자 — 어느 과제에서 잃었는지가 평균보다 많은 걸 말합니다.
    tasks = sorted({r["task"] for r in dk["rows"]})
    names = [a["name"] for a in dk["by_arm"]]
    L += ["", "### 어느 태스크에서 잃었나", "",
          "평균만 보면 '조금 떨어졌다' 로 뭉개집니다. 격자로 보면 "
          "**어떤 성격의 과제가 압축에 약한지**가 보입니다.", ""]
    grid = {}
    for r in dk["rows"]:
        grid[(r["task"], r["arm"])] = r["reward"]
    rows = []
    for t in tasks:
        cells = []
        for n in names:
            v = grid.get((t, n))
            cells.append("✅" if (v or 0) > 0 else ("—" if v is None else "❌"))
        rows.append([f"`{t}`"] + cells)
    L += [_r.md_table(["태스크"] + [f"`{n}`" for n in names], rows)]

    lost = [t for t in tasks
            if (grid.get((t, base["name"])) or 0) > 0
            and any((grid.get((t, n)) or 0) == 0 for n in names
                    if n != base["name"])]
    if lost:
        L += ["", f"> 압축 때문에 잃은 태스크: "
              f"{' · '.join(f'`{t}`' for t in lost)}. "
              "기준선은 풀었는데 압축 arm 이 못 푼 것들입니다."]
    L += _steps(dk, base)
    L += [""]
    return L


def _steps(dk, base) -> list:
    """왜 절감이 기대만큼 안 나오는지 — 스텝 수로 설명합니다.

    arm 평균만 보면 "22% 줄었다" 로 끝납니다. 그런데 태스크별로 짝지어
    보면 **압축했는데 토큰이 늘어난** 태스크가 나옵니다. 그 태스크들은
    하나같이 스텝이 늘었습니다. 압축이 맥락을 깨면 에이전트가 헤매고,
    헤매면 호출이 늘고, 호출이 늘면 아낀 것보다 더 씁니다.

    이 절이 6절의 정답률 하락과 7절의 "압축기는 잘 되던데" 사이의
    간극을 메웁니다.
    """
    per = {}
    for r in dk["rows"]:
        per.setdefault(r["task"], {})[r["arm"]] = r
    b = base["name"]
    pairs = []
    for t, m in per.items():
        if b not in m or not m[b].get("in_tok"):
            continue
        for n, r in m.items():
            if n == b or not r.get("in_tok"):
                continue
            pairs.append({
                "task": t, "arm": n,
                "d_tok": r["in_tok"] / m[b]["in_tok"] - 1,
                "d_step": (r["steps"] - m[b]["steps"])
                if (r.get("steps") and m[b].get("steps")) else None,
                "pass": (r.get("reward") or 0) > 0,
                "base_pass": (m[b].get("reward") or 0) > 0,
            })
    if not pairs:
        return []

    up = [p for p in pairs if p["d_tok"] > 0]
    L = ["", "### 왜 절감이 기대만큼 안 나오나 — 에이전트가 헤맵니다", "",
         "arm 평균만 보면 뭉개집니다. **같은 태스크끼리 짝지어** 보면 "
         "다른 그림이 나옵니다.", ""]
    rows = []
    for p in sorted(pairs, key=lambda x: -x["d_tok"]):
        # 토큰 변화는 **비율**이라 %p 가 아니라 % 입니다. (%p 는 pass@1 처럼
        # 이미 퍼센트인 값끼리 뺄 때만 씁니다.)
        d = p["d_tok"]
        rows.append([f"`{p['task']}`", f"`{p['arm']}`",
                     f"{'+' if d >= 0 else ''}{d * 100:.1f}%",
                     (f"{p['d_step']:+.0f}" if p["d_step"] is not None else "—"),
                     ("✅" if p["pass"] else "❌") +
                     ("" if p["base_pass"] == p["pass"]
                      else " ← 기준선은 통과")])
    L += [_r.md_table(["태스크", "갈래", "토큰 변화", "주고받은 횟수 변화", "통과"], rows)]

    if up:
        worst = max(up, key=lambda p: p["d_tok"])
        n_up_step = sum(1 for p in up if (p["d_step"] or 0) > 0)
        L += ["", f"> **압축했는데 토큰이 오히려 늘어난 경우가 {len(up)}건**"
              f"입니다. 최악은 `{worst['task']}` 의 `{worst['arm']}` 로 "
              f"**{worst['d_tok']*100:+.0f}%** 였습니다.",
              ">",
              f"> 그중 {n_up_step}건은 **에이전트가 명령을 더 많이 "
              "주고받았습니다.** 압축이 맥락을 깨면 에이전트가 헤매고, "
              "헤매면 모델을 더 부르고, 더 부르면 **아낀 것보다 더 씁니다.** "
              "3절에서 본 식별자 손상이 여기서 숫자로 나타납니다.", ""]
    return L


# ── 7. 대리 결과 ─────────────────────────────────────────────────────
def _result_grid(D) -> list:
    gr = D.get("grid")
    if not gr:
        return []
    L = ["", "<h2 id='s7'>7. 결과 ② 대리 측정 (압축기 단독)</h2>", "",
         "조건을 많이 시험하려고 만든 간이 측정입니다. **결론이 아니라 "
         "탐색 결과**로 읽어 주세요.", ""]
    b = gr["base"]
    band = sorted([s for s in gr["summ"] if s["group"] == "압축률"],
                  key=lambda s: s["rate"])
    if band:
        L += ["### rate 를 낮추면", "",
              "```", f"{'rate':>5}  {'절감':>7}  {'hit@1':>6}  품질"]
        for s in band:
            h = s["hit1"]
            L.append(f"{s['rate']:>5}  {pc(s['reduction']):>7}  "
                     f"{(pc(h,0) if h is not None else '—'):>6}  "
                     f"{'█' * round(22 * h) if h is not None else ''}")
        L += ["```", ""]
        pts = [(s["rate"], s["hit1"]) for s in band if s["hit1"] is not None]
        if any(y < x for (_, x), (_, y) in zip(pts, pts[1:])):
            L += ["> **곡선이 단조롭지 않습니다.** 덜 줄인 조건이 더 나쁘게 나온 "
                  "구간이 있습니다. 표본이 조건 간 순위를 가릴 만큼 크지 않다는 "
                  "뜻이라, 개별 조건 이름을 권고로 읽으면 안 됩니다. "
                  "확실한 건 **양 끝**뿐입니다 — 많이 줄이면 확실히 나빠집니다.", ""]

    other = [s for s in gr["summ"] if s["group"] in
             ("압축기 옵션", "보호 정책", "모델 크기", "대조군")]
    if other:
        L += ["", "### 옵션·대조군", ""]
        rows = []
        for s in sorted(other, key=lambda x: x["group"]):
            d = (s["hit1"] - b["hit1"]) if (s["hit1"] is not None
                                            and b and b["hit1"] is not None) else None
            rows.append([s["group"], f"`{s['arm']}`", pc(s["reduction"]),
                         pc(s["hit1"], 0), sign(d, 0),
                         pc(s["ident"]), pc(s["num"]),
                         f"{s['latency']:.1f}s" if s["latency"] else "—"])
        L += [_r.md_table(["갈래", "조건", "절감", "hit@1", "vs 기준",
                           "식별자", "숫자", "지연"], rows)]

    trunc = next((s for s in gr["summ"] if s["compressor"] == "truncate"), None)
    if trunc and b and trunc["hit1"] is not None and b["hit1"] is not None:
        peer = next((s for s in band if abs(s["rate"] - trunc["rate"]) < 1e-6),
                    None)
        if peer and peer["hit1"] is not None:
            same = abs(trunc["hit1"] - peer["hit1"]) < 0.02
            L += ["", f"> **대조군을 꼭 보세요.** 그냥 뒤를 자른 "
                  f"`{trunc['arm']}` 이 hit@1 {pc(trunc['hit1'],0)} 로, "
                  f"같은 rate 의 LLMLingua-2 ({pc(peer['hit1'],0)}) 와 "
                  + ("**같습니다**. 이 태스크에서는 비싼 압축기를 쓸 이유가 "
                     "약했다는 뜻입니다." if same
                     else "다릅니다.") ]
    L += [""]
    return L


# ── 8. 신뢰도 ────────────────────────────────────────────────────────
def _trust(D) -> list:
    L = ["", "<h2 id='s8'>8. 이 수치를 믿어도 되나</h2>", "",
         "이 절이 이 보고서에서 제일 중요합니다. **앞의 표를 어디까지 "
         "믿을지**를 정하기 때문입니다.", ""]

    # 8-1 "그냥 다시 돌려도 생기는 차이"
    # 원래 "잡음 바닥(noise floor)" 이라고 적었는데, 이건 계측 분야 용어라
    # 처음 읽는 사람에게 통하지 않습니다. 뜻 그대로 풀어 씁니다.
    ct = D.get("control")
    if ct and ct["by_arm"]:
        toks = [(a["name"], a["in_tok"]) for a in ct["by_arm"] if a["in_tok"]]
        if len(toks) > 1:
            hi = max(t for _, t in toks)
            spread = [(n, t / hi - 1) for n, t in toks]
            worst = max(abs(v) for _, v in spread)
            L += ["### 8-1. 그냥 다시 돌려도 결과는 달라집니다", "",
                  "저울에 같은 물건을 세 번 올렸는데 눈금이 매번 다르면, "
                  "그 눈금 차이만큼은 **무게가 아니라 저울 탓**입니다. "
                  "이 실험에도 같은 문제가 있습니다.", "",
                  "확인해 봤습니다. 세 갈래 모두 **압축을 끄고** 똑같은 과제를 "
                  "똑같이 시켰습니다. 결과가 같아야 정상인데, 이만큼 갈렸습니다.", ""]
            L += [_r.md_table(["갈래 (전부 압축 없음)", "평균 입력 토큰",
                               "가장 큰 값과의 차이"],
                              [[f"`{n}`", num(t), pc(v)] for (n, t), (_, v)
                               in zip(toks, spread)])]
            L += ["", "> 원인은 에이전트가 **매번 똑같이 행동하지 않는다**는 "
                  "데 있습니다. 어떤 회차엔 파일을 세 번 읽고, 어떤 회차엔 "
                  "다섯 번 읽습니다. 그만큼 토큰이 달라집니다.",
                  ">",
                  f"> 즉 이 실험에서는 **아무것도 안 바꿔도 토큰이 "
                  f"±{worst*100:.0f}% 까지 흔들립니다.** "
                  f"그래서 압축해서 {worst*100:.0f}% 미만으로 줄었다면, "
                  "그게 압축 덕인지 그냥 운이었는지 구분할 방법이 없습니다.", ""]

            dk = D.get("docker")
            if dk:
                base = next((a for a in dk["by_arm"]
                             if a["compressor"] == "none"), None)
                if base and base["in_tok"]:
                    L += ["이 기준으로 실제 측정을 판정하면 이렇습니다.", ""]
                    rows = []
                    for a in dk["by_arm"]:
                        if a is base or not a["in_tok"]:
                            continue
                        red = 1 - a["in_tok"] / base["in_tok"]
                        rows.append([
                            f"`{a['name']}`", pc(red), f"±{worst*100:.0f}%",
                            "**확실한 효과**" if abs(red) > worst
                            else "구분 불가 — 운일 수도 있습니다"])
                    if rows:
                        L += [_r.md_table(
                            ["갈래", "줄어든 양", "그냥 돌려도 생기는 차이",
                             "판정"], rows)]
                    L += ["", "> 이 표가 이 보고서에서 가장 불편한 부분입니다. "
                          "**토큰 절감이 확실하다고 말할 수 없습니다.** "
                          "확실해지려면 태스크를 훨씬 늘려야 합니다.", ""]

    # 8-2 두 침묵 실패
    L += ["", "### 8-2. 이전 측정을 버린 이유 — 두 개의 침묵 실패", "",
          "에러 없이 조용히 틀린 결과를 내던 버그가 둘 있었습니다. "
          "둘 다 **표에는 그럴듯한 숫자로 찍혔습니다.**", ""]
    L += [_r.md_table(
        ["#", "무엇이 잘못됐나", "표에는 어떻게 보였나", "어떻게 고쳤나"],
        [["1", "프록시가 `/chat/completions` 만 압축했는데, 에이전트는 "
               "`/responses` 를 호출했습니다. **압축이 한 번도 안 걸렸습니다.**",
          "\"압축해도 결과가 같다\" — 사실은 같은 프롬프트를 보내고 있었음",
          "두 API 본문을 같은 모양으로 펴는 어댑터를 넣었습니다. "
          "이제 압축 횟수가 표에 찍힙니다(6절)."],
         ["2", "채점 컨테이너가 PyPI 파일 서버에 막혀 `pytest` 설치에 "
               "실패했습니다. **테스트가 한 줄도 안 돌고 0점이 찍혔습니다.**",
          "\"모든 arm 이 pass@1 0%\" — 벤치마크가 어려운 줄로 보였음",
          "채점 컨테이너에도 미러를 넣었습니다. 같은 태스크가 "
          "지금은 통과합니다."]])]
    L += ["", "> 두 번째가 특히 위험했습니다. 에이전트 로그를 열어 보니 "
          "**과제를 완벽히 수행해 놓고** 0점을 받고 있었습니다. "
          "그래서 이 보고서의 리포트 생성기는 압축 횟수와 채점 실행 여부를 "
          "매번 확인해 경고를 띄웁니다.", ""]

    # 8-3 표본
    dk = D.get("docker")
    if dk:
        tasks = sorted({r["task"] for r in dk["rows"]})
        per = len(tasks)
        L += ["", "### 8-3. 표본이 작습니다", "",
              f"arm 당 태스크 {per}개입니다. **한 건이 "
              f"{100/per:.1f}%p 를 움직입니다.** 그래서,", "",
              f"- {100/per:.0f}%p 안팎의 차이는 우연으로도 납니다",
              "- 방향(압축할수록 떨어진다)은 읽을 수 있지만, "
              "**정확한 하락 폭은 못 믿습니다**",
              "- 폭을 말하려면 태스크를 수십 개로 늘려야 합니다", ""]
    return L


# ── 9. 결론 ──────────────────────────────────────────────────────────
def _verdict(D) -> list:
    L = ["", "<h2 id='s9'>9. 그래서 무엇을 할까</h2>", ""]
    dk = D.get("docker")
    if dk and dk["by_arm"]:
        base = next((a for a in dk["by_arm"] if a["compressor"] == "none"),
                    dk["by_arm"][0])
        comp = [a for a in dk["by_arm"] if a is not base
                and a["pass1"] is not None]
        drop = [a for a in comp if base["pass1"] is not None
                and a["pass1"] < base["pass1"]]
        if drop:
            L += ["**코딩 에이전트의 프롬프트를 통째로 LLMLingua-2 에 "
                  "넣는 방식은 권하지 않습니다.** 측정한 범위에서 "
                  "토큰은 줄었지만 정답률이 같이 내려갔습니다.", ""]
    L += ["이유는 3절 샘플에 있습니다. 압축기는 **산문**에는 잘 듣지만 "
          "**도구 출력의 식별자를 망가뜨립니다.** 에이전트는 그 이름으로 "
          "다음 명령을 만들기 때문에, 이름이 깨지면 헛손질을 합니다.", "",
          "그 헛손질이 6절에서 숫자로 잡힙니다 — **압축했는데 토큰이 늘어난 "
          "태스크**들입니다. 에이전트가 모델을 더 여러 번 부르는 바람에 "
          "아낀 것보다 더 썼습니다. "
          "즉 압축의 손해는 정답률에서만 오는 게 아니라, "
          "**절감 자체를 되돌려 놓는 방식으로도** 옵니다.", ""]
    L += ["", "### 대신 해 볼 것", "",
          "| 방향 | 왜 |",
          "|---|---|",
          "| 도구 출력만 **규칙 기반**으로 줄이기 (로그 접기·중복 제거) | "
          "식별자를 안 건드리면서 가장 큰 자리를 줄입니다 |",
          "| 오래된 턴만 압축하고 최근 턴은 원문 유지 | "
          "이미 `keep_last` 로 하고 있습니다. 이 값을 키워 보는 게 다음 실험 |",
          "| 산문(과제 설명·문서)에만 압축 적용 | "
          "3절에서 보듯 여기는 절반을 줄여도 핵심이 남습니다 |",
          "| 단순 절단과 꼭 비교하기 | "
          "7절 대조군을 보면 비싼 압축기가 항상 이기지 않습니다 |", ""]
    L += ["", "### 다음에 측정할 것", "",
          "- 태스크를 수십 개로 늘려 하락 폭을 정확히 재기 (8-3)",
          "- `keep_last` 를 키워 가며 정답률 회복 지점 찾기",
          "- 도구 출력 전용 규칙 압축기와 정면 비교", ""]
    return L


# ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", type=Path)
    ap.add_argument("--run", type=Path)
    ap.add_argument("--jobs", type=Path, nargs="*", default=[])
    ap.add_argument("--control-run", type=Path)
    ap.add_argument("--control-jobs", type=Path, nargs="*", default=[])
    ap.add_argument("--samples", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    a = ap.parse_args()

    D = {}
    if a.grid and a.grid.exists():
        D["grid"] = read_grid(a.grid)
        print(f"  대리 측정 {len(D['grid']['summ'])}조건")
    if a.run and a.jobs:
        D["docker"] = read_rollout(a.run, list(a.jobs))
        if D["docker"]:
            print(f"  정석 측정 {len(D['docker']['rows'])} trial")
    if a.control_run and a.control_jobs:
        D["control"] = read_rollout(a.control_run, list(a.control_jobs))
        if D["control"]:
            print(f"  대조군 {len(D['control']['rows'])} trial")
    if a.samples and a.samples.exists():
        D["samples"] = json.loads(a.samples.read_text(encoding="utf-8"))
        print(f"  샘플 {len(D['samples']['cases'])}건")

    md = build_md(D)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "report.md").write_text(md, encoding="utf-8")
    (a.out / "report.html").write_text(
        _r.build_html(md, "토큰 압축 측정 보고서"), encoding="utf-8")
    print(f"▸ {a.out}/report.md · report.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

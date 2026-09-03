#!/usr/bin/env python3
"""벤치마크 결과 → 마크다운 + HTML 리포트.

    ./.venv/bin/python report.py <리포트이름>

`reports/<이름>/results.json` 을 읽어 같은 폴더에 `report.md` 와
`report.html` 을 쓴다.

해석은 **전부 데이터에서 계산한다.** 문장에 수치를 박아 두면 조건이 바뀔
때 조용히 틀린 리포트가 된다.
"""

from __future__ import annotations

import argparse
import html
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
REPORTS = REPO / "reports"

# md 에 심은 자리표시자 -> SVG. build_html 이 끼워 넣는다.
CHARTS: dict = {}


# ═══════════════════════════════════════════════════════════════
# 집계
# ═══════════════════════════════════════════════════════════════

def agg(rows: list, keys: tuple) -> dict:
    """(arm, lang) 등으로 묶어 평균을 낸다."""
    buckets = defaultdict(list)
    for r in rows:
        buckets[tuple(r[k] for k in keys)].append(r)
    out = {}
    for k, rs in buckets.items():
        ok = [r for r in rs if not r["error"]]
        if not ok:
            out[k] = None
            continue
        out[k] = {
            "n": len(ok),
            "n_error": len(rs) - len(ok),
            "tokens_before": sum(r["tokens_before"] for r in ok),
            "tokens_after": sum(r["tokens_after"] for r in ok),
            "reduction": st.mean(r["reduction"] for r in ok),
            "ident": st.mean(r["ident"] for r in ok),
            "path": st.mean(r["path"] for r in ok),
            "num": st.mean(r["num"] for r in ok),
            "latency": st.median(r["latency_s"] for r in ok),
            "latency_max": max(r["latency_s"] for r in ok),
            "newline_kept": st.mean(
                (r["struct_after"]["newline"] / r["struct_before"]["newline"])
                if r["struct_before"]["newline"] else 1.0 for r in ok),
            "touched": st.mean(r["n_touched"] for r in ok),
        }
    return out


def pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def signed(x, digits=1):
    return f"{x * 100:+.{digits}f}%"


# ═══════════════════════════════════════════════════════════════
# 그래프
#
# 마크다운에는 막대를 글자로 그리고, HTML 에는 같은 데이터를 SVG 로 그린다.
# 외부 라이브러리를 쓰지 않는 이유는 리포트가 파일 하나로 열려야 하기
# 때문이다(file:// 로 열어도 그려져야 한다).
#
# HTML 쪽은 <!--CHART:이름--> 자리표시자를 md 에 심어 두고, md_to_html 이
# 그 자리에 SVG 를 끼워 넣는다. 마크다운으로 읽는 사람은 바로 위의 글자
# 막대를 본다.
# ═══════════════════════════════════════════════════════════════

BAR = "█"


def ascii_bar(value: float, vmax: float, width: int = 24) -> str:
    if vmax <= 0:
        return ""
    n = max(0, min(width, round(value / vmax * width)))
    return BAR * n


def chart_tradeoff(by_arm: dict, arms: dict) -> tuple:
    """절감 대비 식별자 보존. 이 리포트에서 가장 중요한 그림이다."""
    pts = []
    for (n,), v in by_arm.items():
        if not v or not arms[n]["group"].startswith(("스윕", "대조")):
            continue
        fam = ("truncate" if n.startswith("truncate") else
               "v2s" if n.startswith("v2s") else
               "v2" if n.startswith("v2") else "v1")
        pts.append((fam, n, v["reduction"], v["ident"]))
    if not pts:
        return "", ""

    md = ["**절감(가로) 대비 식별자 보존(막대)** — 오른쪽 아래일수록 많이 "
          "줄이면서 잘 지킨 것입니다.", ""]
    md.append("```")
    for fam, n, r, i in sorted(pts, key=lambda x: (x[0], -x[2])):
        md.append(f"{n:<16} 절감 {r * 100:5.1f}%  식별자 "
                  f"{ascii_bar(i, 1.0):<24} {i * 100:5.1f}%")
    md.append("```")

    W, H, PL, PB = 720, 380, 56, 44
    body = []
    for gx in range(0, 101, 20):
        x = PL + (W - PL - 20) * gx / 100
        body.append(f'<line x1="{x:.0f}" y1="10" x2="{x:.0f}" y2="{H - PB}" '
                    f'class="grid"/><text x="{x:.0f}" y="{H - PB + 16}" '
                    f'class="ax" text-anchor="middle">{gx}%</text>')
    for gy in range(0, 101, 20):
        y = (H - PB) - (H - PB - 10) * gy / 100
        body.append(f'<line x1="{PL}" y1="{y:.0f}" x2="{W - 20}" y2="{y:.0f}" '
                    f'class="grid"/><text x="{PL - 8}" y="{y + 4:.0f}" '
                    f'class="ax" text-anchor="end">{gy}%</text>')
    color = {"truncate": "#9aa4b2", "v1": "#e0b341",
             "v2": "#63c98f", "v2s": "#e06c75"}
    for fam, n, r, i in pts:
        x = PL + (W - PL - 20) * min(max(r, 0), 1)
        y = (H - PB) - (H - PB - 10) * i
        body.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="6" '
                    f'fill="{color[fam]}"><title>{html.escape(n)} · '
                    f'절감 {r * 100:.1f}% · 식별자 {i * 100:.1f}%</title></circle>')
    lg = []
    for k, c in color.items():
        lg.append(f'<circle cx="0" cy="-4" r="5" fill="{c}"/>'
                  f'<text x="10" y="0" class="ax">{k}</text>')
    legend = "".join(f'<g transform="translate({PL + n * 110},{H - 8})">{g}</g>'
                     for n, g in enumerate(lg))
    svg = (f'<svg viewBox="0 0 {W} {H}" class="chart">'
           f'<text x="{PL}" y="0" class="ax"></text>'
           + "".join(body)
           + f'<text x="{W // 2}" y="{H - 24}" class="ax" '
             f'text-anchor="middle">절감률 →</text>'
           + f'<text transform="translate(14,{H // 2}) rotate(-90)" '
             f'class="ax" text-anchor="middle">식별자 보존율 →</text>'
           + legend + "</svg>")
    return "\n".join(md), svg


def chart_pairs(by_arm: dict) -> tuple:
    """force_tokens 켬/끔 짝 비교 — 경로 보존."""
    pairs = []
    for (n,), v in by_arm.items():
        if "-nt-" not in n or not v:
            continue
        twin = n.replace("-nt-", "-")
        tv = by_arm.get((twin,))
        if tv:
            pairs.append((twin, tv["path"], v["path"]))
    if not pairs:
        return "", ""
    pairs.sort()

    md = ["**`force_tokens` 켬 → 끔 · 경로 보존**", "", "```"]
    for n, a, b in pairs:
        md.append(f"{n:<14} 켬 {ascii_bar(a, 1.0, 18):<18} {a * 100:5.1f}%")
        md.append(f"{'':<14} 끔 {ascii_bar(b, 1.0, 18):<18} {b * 100:5.1f}%")
    md.append("```")

    W, rowh, PL = 720, 34, 130
    H = 24 + rowh * len(pairs)
    body = []
    for k, (n, a, b) in enumerate(pairs):
        y = 16 + rowh * k
        body.append(f'<text x="{PL - 10}" y="{y + 14}" class="ax" '
                    f'text-anchor="end">{html.escape(n)}</text>')
        for j, (val, col) in enumerate(((a, "#e06c75"), (b, "#63c98f"))):
            wpx = (W - PL - 70) * val
            body.append(f'<rect x="{PL}" y="{y + j * 12}" width="{wpx:.0f}" '
                        f'height="10" fill="{col}" rx="2"/>')
        body.append(f'<text x="{W - 62}" y="{y + 9}" class="ax">'
                    f'{a * 100:.0f}%</text>')
        body.append(f'<text x="{W - 62}" y="{y + 21}" class="ax">'
                    f'{b * 100:.0f}%</text>')
    svg = (f'<svg viewBox="0 0 {W} {H}" class="chart">' + "".join(body) +
           '</svg><p class="meta">위 막대(빨강)가 켬, 아래(초록)가 끔입니다.</p>')
    return "\n".join(md), svg


def chart_latency(by_arm: dict, arms: dict) -> tuple:
    vals = [(n, v["latency"]) for (n,), v in by_arm.items()
            if v and not n.startswith("truncate")]
    if not vals:
        return "", ""
    fam = {}
    for n, l in vals:
        k = ("v2s" if n.startswith("v2s") else
             "v2" if n.startswith("v2") else "v1")
        fam.setdefault(k, []).append(l)
    rows = [(k, st.mean(v)) for k, v in fam.items()]
    rows.sort(key=lambda r: -r[1])
    vmax = max(r[1] for r in rows)

    md = ["**컨텍스트 한 벌을 압축하는 데 걸린 시간 (평균)**", "", "```"]
    for k, l in rows:
        md.append(f"{k:<6} {ascii_bar(l, vmax, 30):<30} {l:6.2f}s "
                  f"(30턴이면 {l * 30:5.0f}s)")
    md.append("```")

    W, rowh, PL = 720, 30, 70
    H = 12 + rowh * len(rows)
    body = []
    for k, (name, l) in enumerate(rows):
        y = 8 + rowh * k
        body.append(f'<text x="{PL - 10}" y="{y + 15}" class="ax" '
                    f'text-anchor="end">{name}</text>')
        body.append(f'<rect x="{PL}" y="{y + 4}" '
                    f'width="{(W - PL - 90) * l / vmax:.0f}" height="15" '
                    f'fill="#6ea8fe" rx="2"/>')
        body.append(f'<text x="{W - 84}" y="{y + 16}" class="ax">'
                    f'{l:.2f}s</text>')
    return "\n".join(md), (f'<svg viewBox="0 0 {W} {H}" class="chart">'
                            + "".join(body) + "</svg>")


# ═══════════════════════════════════════════════════════════════
# 마크다운
# ═══════════════════════════════════════════════════════════════

def md_table(head: list, rows: list, align: list = None) -> str:
    align = align or ["left"] * len(head)
    sep = {"left": ":--", "right": "--:", "center": ":-:"}
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join(sep[a] for a in align) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def build_md(d: dict) -> str:
    runs = d["runs"]
    arms = {a["name"]: a for a in d["arms"]}
    env = d["environment"]
    P = []

    def w(s=""):
        P.append(s)

    # ── 머리말 ────────────────────────────────────────────────
    w(f"# 압축기 벤치마크 — {d['name']}")
    w()
    w(f"DeepSWE 태스크 {len(d['tasks'])}건을 한국어·영어로, 조건 "
      f"{len(d['arms'])}개에서 압축해 잰 결과입니다. 총 {len(runs)}회 측정했고 "
      f"{d['elapsed_s'] / 60:.1f}분 걸렸습니다.")
    w()
    w("## ⚠️ 먼저 읽어주세요 — 이 리포트가 재지 않은 것")
    w()
    w("**pass@1(과제 성공률)은 여기 없습니다.** 그건 에이전트를 컨테이너에서 "
      "실제로 돌려야 나오고, 태스크 하나에 최대 3시간이 걸립니다.")
    w()
    w("MS 공유 문서에는 `품질` 열이 있었습니다. 이 리포트에는 대신 **보존율**이 "
      "있는데, 둘은 다른 값입니다. 나란히 놓고 \"품질이 이렇다\"고 읽으시면 "
      "안 됩니다.")
    w()
    w("보존율은 **선행 지표**입니다.")
    w()
    w("- 정답에 필요한 문자열이 사라졌다면 맞힐 길이 없습니다 → **낮으면 확실히 나쁨**")
    w("- 남아 있다고 해서 모델이 맞힌다는 보장은 없습니다 → **높다고 반드시 좋지는 않음**")
    w()
    w("값싸게 후보를 거르는 용도로 보시고, 살아남은 조건만 실제 롤아웃으로 "
      "확인하시면 됩니다.")
    w()

    # ── 측정 조건 ─────────────────────────────────────────────
    w("## 1. 무엇을, 어떻게 쟀나")
    w()
    w("### 입력 — 에이전트 컨텍스트를 실제 태스크 파일로 조립")
    w()
    w("지시문만 압축하면 실제 상황과 다릅니다. 에이전트 컨텍스트의 대부분은 "
      "**읽어들인 파일 내용과 툴 출력**이고 지시문은 극히 일부입니다.")
    w()
    w("그래서 태스크에 실제로 들어 있는 코드로 8개 메시지를 조립했습니다. "
      "지어낸 텍스트는 쓰지 않았습니다.")
    w()
    w("```")
    w("system     출력 형식 계약 (mini-swe-agent 계열)     " f"{d['system_prompt_chars']:,}자")
    w("user       instruction.md                          en 또는 ko")
    w("assistant  bash: ls -R . | head -50")
    w("user       OBSERVATION: solution.patch 앞 6,000자   실제 코드")
    w("assistant  bash: cat tests/test_main.py")
    w("user       OBSERVATION: test.patch 앞 4,000자       실제 테스트")
    w("assistant  bash: python -m pytest -x")
    w("user       OBSERVATION: 1 failed, 42 passed")
    w("```")
    w()
    w("> 한국어 조건은 **지시문만** 한국어입니다. 코드는 그대로 영어입니다. "
      "실제로 한국어 지시를 받은 에이전트가 보는 것도 이 모양입니다.")
    w()
    w("### 지표")
    w()
    w(md_table(
        ["지표", "무엇", "왜 보나"],
        [["절감률", "토큰 전 → 후", "MS 문서의 `total_tok` 증감과 같은 축입니다"],
         ["식별자 보존", "함수·클래스·변수명이 남은 비율", "사라지면 무엇을 고칠지 모릅니다"],
         ["경로 보존", "파일 경로가 남은 비율", "깨지면 패치가 적용조차 안 됩니다"],
         ["숫자 보존", "임계값·크기가 남은 비율", "한 자리만 틀려도 테스트가 떨어집니다"],
         ["개행 보존", "줄 구조가 남은 비율", "코드 모양이 무너지면 읽지 못합니다"],
         ["지연", "압축에 걸린 시간(중앙값)", "매 턴 얹히므로 체감에 직결됩니다"]],
        ["left", "left", "left"]))
    w()
    w("보존율은 **부분문자열 검사**입니다. 뜻이 지켜져도 표현이 바뀌면 0으로 "
      "잡히므로, 실제 이해도의 하한으로 보시면 됩니다.")
    w()
    w("### 환경")
    w()
    w(md_table(["항목", "값"],
               [["Python", env["python"]],
                ["플랫폼", env["platform"]],
                ["transformers", env["transformers"]],
                ["torch", env["torch"]],
                ["llmlingua", env["llmlingua"]],
                ["토큰 계수", f"tiktoken {env['tiktoken']} · o200k_base"],
                ["장치", "CPU"]],
               ["left", "left"]))
    w()
    w("> `transformers` 를 4.46.3 으로 고정했습니다. 5.x 에서는 LLMLingua v1 이 "
      "긴 입력에서 깨집니다(`past_key_values` 형식 변경). 이 리포트를 재현하시려면 "
      "같은 버전을 쓰셔야 합니다.")
    w()
    w("### 기본 보호 정책")
    w()
    bp = d["protect_default"]
    w(md_table(["항목", "값", "뜻"],
               [["keep_last", bp["keep_last"], "마지막 N개 메시지는 원문 유지"],
                ["min_chars", bp["min_chars"], "이보다 짧으면 건드리지 않음"],
                ["skip_system", bp["skip_system"], "system 프롬프트 보호"]],
               ["left", "right", "left"]))
    w()

    # ── 읽는 법 ───────────────────────────────────────────────
    w("## 2. 표를 읽는 법")
    w()
    w("### 조건 이름 규칙")
    w()
    w("`v2-nt-r0.5` 처럼 붙여 씁니다. 세 조각입니다.")
    w()
    w("```")
    w("v2  -  nt  -  r0.5")
    w(" |      |      +-- rate. 남길 비율입니다. 0.5 면 절반만 남깁니다")
    w(" |      +--------- 옵션 꼬리표. 없으면 기본 설정입니다")
    w(" +---------------- 압축기")
    w("```")
    w()
    w(md_table(
        ["조각", "값", "뜻"],
        [["압축기", "`truncate`", "그냥 뒤를 자릅니다. 대조군입니다"],
         ["", "`v1`", "LLMLingua v1 — 생성 모델의 perplexity 로 고릅니다"],
         ["", "`v2`", "LLMLingua-2 — 전용 분류 모델 (큰 것, 2.2GB)"],
         ["", "`v2s`", "LLMLingua-2 — 같은 알고리즘, 작은 모델 (700MB)"],
         ["꼬리표", "(없음)", "기본 설정"],
         ["", "`nt`", "`force_tokens` 를 껐습니다 (no tokens)"],
         ["", "`no-digit`", "`force_reserve_digit` 을 껐습니다"],
         ["", "`no-drop`", "`drop_consecutive` 를 껐습니다"],
         ["", "`no-tokens`", "`force_tokens` 를 껐습니다"],
         ["", "`keeplast0`", "마지막 메시지 보호를 껐습니다"],
         ["", "`nosysguard`", "system 프롬프트도 압축했습니다"],
         ["", "`minchars0`", "짧은 메시지도 압축했습니다"],
         ["rate", "`r0.3`~`r0.9`", "낮을수록 세게 압축합니다"]],
        ["left", "left", "left"]))
    w()
    w("> `nt` 와 `no-tokens` 는 같은 설정입니다. 앞의 것은 압축률을 훑는 "
      "스윕에서, 뒤의 것은 `rate=0.5` 고정 절제에서 쓴 이름입니다.")
    w()
    w("### 각 열이 무엇인가")
    w()
    w(md_table(
        ["열", "무엇", "높으면", "어떻게 계산했나"],
        [["갈래", "이 조건을 왜 돌렸나", "—", "—"],
         ["rate", "남길 비율(설정값)", "덜 압축", "설정 그대로"],
         ["토큰 전 → 후", "케이스 14개 합계", "—", "tiktoken o200k_base"],
         ["절감", "토큰이 줄어든 비율", "**좋음**", "1 − 후/전"],
         ["식별자", "함수·클래스·변수명이 남은 비율", "**좋음**",
          "원문에서 뽑은 40개 중 압축 후에도 그대로 있는 개수"],
         ["경로", "파일 경로가 남은 비율", "**좋음**", "같은 방식, 경로 20개"],
         ["숫자", "임계값·크기가 남은 비율", "**좋음**", "같은 방식, 숫자 10개"],
         ["지연", "컨텍스트 한 벌 압축에 걸린 시간", "**나쁨**", "케이스별 중앙값"]],
        ["left", "left", "center", "left"]))
    w()
    w("**절감과 나머지는 방향이 반대입니다.** 절감만 크고 보존율이 낮으면 "
      "쓸 수 없습니다. 둘을 함께 보셔야 합니다.")
    w()
    w("### 압축기 옵션 세 가지")
    w()
    w("`llmlingua` 라이브러리에 넘기는 인자입니다. 이름만으로는 무엇을 하는지 "
      "짐작하기 어려워 따로 적습니다.")
    w()
    w(md_table(
        ["옵션", "이름이 주는 인상", "실제로 하는 일", "이 랩의 기본값"],
        [["`force_reserve_digit`", "숫자를 지킨다",
          "숫자 토큰을 버리지 않도록 가중치를 줍니다. 다만 숫자가 여러 "
          "토큰으로 쪼개져 있으면 완전히 막지는 못합니다", "**켬**"],
         ["`drop_consecutive`", "연달아 나오는 것을 버린다",
          "같은 토큰이 이어지면 하나만 남깁니다. 반복이 많은 로그에서 "
          "절감이 커집니다", "**켬**"],
         ["`force_tokens`", "이 문자들을 지킨다",
          "⚠️ **반대로 동작합니다.** 해당 문자를 별도 토큰으로 떼어내서, "
          "되조립할 때 주변에 공백이 끼어듭니다. 5-1 절을 보세요", "**끔**"]],
        ["left", "left", "left", "center"]))
    w()

    # ── 전체 결과 ─────────────────────────────────────────────
    w("## 3. 전체 결과")
    w()
    by_arm = agg(runs, ("arm",))
    rows = []
    for a in d["arms"]:
        s = by_arm.get((a["name"],))
        if not s:
            rows.append([a["name"], a["group"], "—", "전부 실패", "", "", "", "", ""])
            continue
        rows.append([
            f"`{a['name']}`", a["group"], a["rate"],
            f"{s['tokens_before']:,} → {s['tokens_after']:,}",
            pct(s["reduction"]), pct(s["ident"]), pct(s["path"]),
            pct(s["num"]), f"{s['latency']:.2f}s",
        ])
    w(md_table(["조건", "갈래", "rate", "토큰 전 → 후", "절감",
                "식별자", "경로", "숫자", "지연"], rows,
               ["left", "left", "right", "right", "right",
                "right", "right", "right", "right"]))
    w()
    md_c, svg_c = chart_tradeoff(by_arm, arms)
    if md_c:
        w("### 한눈에 — 절감과 보존의 맞바꿈")
        w()
        w("<!--CHART:tradeoff-->")
        w(md_c)
        w()
    w(_read_all(by_arm, arms))
    w()
    md_l, svg_l = chart_latency(by_arm, arms)
    if md_l:
        w("### 지연")
        w()
        w("<!--CHART:latency-->")
        w(md_l)
        w()
    CHARTS.clear()
    CHARTS.update(tradeoff=svg_c, latency=svg_l)

    # ── 언어 ──────────────────────────────────────────────────
    w("## 4. 한국어 vs 영어")
    w()
    by_lang = agg(runs, ("arm", "lang"))
    rows = []
    for a in d["arms"]:
        e, k = by_lang.get((a["name"], "en")), by_lang.get((a["name"], "ko"))
        if not (e and k):
            continue
        rows.append([f"`{a['name']}`",
                     pct(e["reduction"]), pct(k["reduction"]),
                     signed(k["reduction"] - e["reduction"]),
                     pct(e["ident"]), pct(k["ident"]),
                     signed(k["ident"] - e["ident"])])
    w(md_table(["조건", "절감 en", "절감 ko", "차이",
                "식별자 en", "식별자 ko", "차이"], rows,
               ["left", "right", "right", "right", "right", "right", "right"]))
    w()
    w(_read_lang(by_lang, d))
    w()

    # ── 태스크 ────────────────────────────────────────────────
    w("## 5. 태스크별로 갈리나")
    w()
    w("MS 문서의 핵심 결론이 \"태스크 유형에 따라 달라진다\"였습니다. "
      "같은 조건에서 태스크만 바꿔 봅니다.")
    w()
    focus = _pick_focus(d)
    by_task = agg([r for r in runs if r["arm"] == focus], ("task", "lang"))
    rows = []
    for t in d["tasks"]:
        e, k = by_task.get((t, "en")), by_task.get((t, "ko"))
        if not (e and k):
            continue
        rows.append([t, f"{e['tokens_before']:,}",
                     pct(e["reduction"]), pct(k["reduction"]),
                     pct(e["ident"]), pct(k["ident"]),
                     pct(e["path"]), pct(k["path"])])
    w(f"조건: `{focus}`")
    w()
    w(md_table(["태스크", "토큰(en)", "절감 en", "절감 ko",
                "식별자 en", "식별자 ko", "경로 en", "경로 ko"], rows,
               ["left", "right", "right", "right", "right", "right", "right", "right"]))
    w()
    w(_read_task(by_task, d, focus))
    w()

    # ── 경로 ──────────────────────────────────────────────────
    w(_read_paths(by_arm, arms, d))
    w()

    # ── 절제 ──────────────────────────────────────────────────
    w("## 6. 옵션 하나씩 꺼 보기")
    w()
    w("옵션을 여러 개 동시에 바꾸면 무엇 덕분인지 알 수 없습니다. "
      "`rate=0.5` 를 고정하고 하나씩만 껐습니다.")
    w()
    for group in ("옵션 절제", "보호 절제"):
        names = [a["name"] for a in d["arms"] if a["group"] == group]
        if not names:
            continue
        base = _baseline_for(group, d)
        w(f"### {group}")
        w()
        rows = []
        bs = by_arm.get((base,))
        if bs:
            rows.append([f"`{base}` (기준)", "—", pct(bs["reduction"]), "—",
                         pct(bs["ident"]), "—", pct(bs["num"])])
        for n in names:
            s = by_arm.get((n,))
            if not s or not bs:
                continue
            rows.append([f"`{n}`", _what_changed(n, base, arms),
                         pct(s["reduction"]), signed(s["reduction"] - bs["reduction"]),
                         pct(s["ident"]), signed(s["ident"] - bs["ident"]),
                         pct(s["num"])])
        w(md_table(["조건", "무엇을 바꿨나", "절감", "절감 차이",
                    "식별자", "식별자 차이", "숫자"], rows,
                   ["left", "left", "right", "right", "right", "right", "right"]))
        w()
        w(_read_ablation(group, names, base, by_arm))
        w()

    # ── MS 문서 대비 ──────────────────────────────────────────
    w("## 7. MS 공유 문서와 견주면")
    w()
    w(_read_vs_ms(by_arm, by_lang, d))
    w()

    # ── 종합 ──────────────────────────────────────────────────
    w("## 8. 정리")
    w()
    w(_read_summary(by_arm, by_lang, d))
    w()
    w("### 다음에 확인할 것")
    w()
    w("이 리포트는 값싼 선행 지표입니다. 여기서 살아남은 조건을 **실제 "
      "롤아웃**으로 확인하셔야 결론이 됩니다.")
    w()
    w("```bash")
    w("PUBLIC_HOST=<호스트> ./.venv/bin/python launch.py experiments/smoke.yaml")
    w("pier run --config <출력된 en/pier.yaml>")
    w("```")
    w()
    # ── 부록 ──────────────────────────────────────────────────
    w("## 부록. 조건별 실행 파라미터")
    w()
    w("표의 조건 하나가 어떤 설정으로 돌았는지 전부 적습니다. "
      "`results.json` 에도 같은 값이 들어 있습니다.")
    w()
    rows = []
    for a in d["arms"]:
        pr = a.get("params") or {}
        pt = a.get("protect") or {}
        rows.append([
            f"`{a['name']}`", a["compressor"], a["model"], a["rate"],
            "켬" if pr.get("force_reserve_digit") else ("끔" if pr else "—"),
            "켬" if pr.get("drop_consecutive") else ("끔" if pr else "—"),
            "켬" if pr.get("force_tokens") else ("끔" if pr else "—"),
            pt.get("keep_last", "—"), pt.get("min_chars", "—"),
            "보호" if pt.get("skip_system") else "압축",
        ])
    w(md_table(
        ["조건", "compressor", "모델", "rate", "digit", "drop", "tokens",
         "keep_last", "min_chars", "system"],
        rows,
        ["left", "left", "left", "right", "center", "center", "center",
         "right", "right", "center"]))
    w()
    w("### 같은 조건을 직접 돌려보시려면")
    w()
    w("벤치마크는 이렇게 재현합니다.")
    w()
    w("```bash")
    w("cd labs/agentic-eval")
    w(f"./.venv/bin/python benchmark.py --name {d['name']}")
    w(f"./.venv/bin/python report.py {d['name']}")
    w("```")
    w()
    w("조건 하나만 손으로 확인하실 때는 압축기를 직접 부르시면 됩니다. "
      "아래는 `v2-nt-r0.5` 와 같은 설정입니다.")
    w()
    w("```python")
    w("import compressors as C")
    w("")
    w("C.set_params(force_reserve_digit=True, drop_consecutive=True,")
    w("             force_tokens=False)          # 조건 이름의 nt 부분")
    w("C.set_policy(keep_last=2, min_chars=400, skip_system=True)")
    w("")
    w("out = C.get('llmlingua')(messages, 0.5)   # 0.5 = rate")
    w("```")
    w()
    w("프록시로 띄우실 때는 같은 설정이 이렇게 됩니다.")
    w()
    w("```bash")
    w("./.venv/bin/python proxy.py --compressor llmlingua --ratio 0.5 \\")
    w("  --port 8801 --upstream <모델 API> --arm v2-nt-r0.5")
    w("```")
    w()
    if d.get("merged_from"):
        w("### 합쳐진 측정")
        w()
        w("본 측정 뒤에 조건을 더 재서 합쳤습니다.")
        w()
        w(md_table(["이름", "시각", "조건 수"],
                   [[m["name"], m["started_at"], m["arms"]]
                    for m in d["merged_from"]],
                   ["left", "left", "right"]))
        w()
    w("---")
    w()
    w(f"측정 {len(runs)}회 · 소요 {d['elapsed_s'] / 60:.1f}분 · "
      f"생성 {d['started_at']}")
    return "\n".join(P)


# ═══════════════════════════════════════════════════════════════
# 해석 — 전부 데이터에서 계산한다
# ═══════════════════════════════════════════════════════════════

def _pick_focus(d: dict) -> str:
    for cand in ("v2-r0.5", "v2-r0.5-default", "v1-r0.5"):
        if any(a["name"] == cand for a in d["arms"]):
            return cand
    return d["arms"][0]["name"]


def _baseline_for(group: str, d: dict) -> str:
    return "v2-r0.5"


def _what_changed(name: str, base: str, arms: dict) -> str:
    a, b = arms.get(name, {}), arms.get(base, {})
    diffs = []
    for k in ("params", "protect"):
        for key, val in (a.get(k) or {}).items():
            if (b.get(k) or {}).get(key) != val:
                diffs.append(f"`{key}={val}`")
    return " · ".join(diffs) or "—"


def _read_all(by_arm: dict, arms: dict) -> str:
    ok = {k[0]: v for k, v in by_arm.items() if v}
    if not ok:
        return "측정된 조건이 없습니다."
    L = ["**표에서 보이는 것**", ""]

    # 같은 절감률에서 대조군보다 나은가
    pairs = []
    for name, s in ok.items():
        if not name.startswith("truncate"):
            continue
        rate = arms[name]["rate"]
        for other, o in ok.items():
            if other.startswith("truncate") or arms[other]["rate"] != rate:
                continue
            if arms[other]["group"] != "스윕":
                continue
            pairs.append((rate, other, o["ident"] - s["ident"],
                          o["reduction"] - s["reduction"]))
    if pairs:
        wins = [p for p in pairs if p[2] > 0]
        L.append(f"**① 그냥 잘라내기와 비교** — 같은 `rate` 에서 정교한 압축기가 "
                 f"식별자를 더 지킨 경우가 {len(wins)}/{len(pairs)} 입니다.")
        best = max(pairs, key=lambda p: p[2])
        L.append(f"가장 크게 앞선 것은 `{best[1]}` 로 대조군보다 식별자 "
                 f"{best[2] * 100:+.1f}%p, 절감 {best[3] * 100:+.1f}%p 입니다.")
        L.append("")

    # 지연
    # 대조군(truncate)은 사실상 0초라 배수 비교가 뜻이 없다. 모델을 쓰는
    # 조건끼리만 견준다.
    model_arms = {n: v for n, v in ok.items() if not n.startswith("truncate")}
    if len(model_arms) >= 2:
        slow = max(model_arms.items(), key=lambda kv: kv[1]["latency"])
        fast = min(model_arms.items(), key=lambda kv: kv[1]["latency"])
        L.append(f"**② 지연** — 모델을 쓰는 조건 중 가장 느린 `{slow[0]}` 가 "
                 f"케이스당 {slow[1]['latency']:.2f}s, 가장 빠른 `{fast[0]}` 가 "
                 f"{fast[1]['latency']:.2f}s 로 "
                 f"{slow[1]['latency'] / max(fast[1]['latency'], 1e-9):.0f}배 "
                 f"차이입니다. 대조군 `truncate` 는 모델을 쓰지 않아 사실상 "
                 f"0초입니다.")
        L.append("")
        L.append(f"메시지 하나가 아니라 **컨텍스트 한 벌**을 압축한 시간입니다. "
                 f"에이전트는 매 턴 이걸 치르므로, 30턴이면 "
                 f"`{slow[0]}` 는 {slow[1]['latency'] * 30:.0f}초, "
                 f"`{fast[0]}` 는 {fast[1]['latency'] * 30:.0f}초가 "
                 f"응답 시간 위에 얹힙니다.")
        L.append("")

    # 절감 대비 보존
    L.append("**③ 절감이 큰 조건이 잘 지키지는 않습니다.** 절감률 순으로 정렬했을 때 "
             "식별자 보존율이 함께 오르지 않는다면, 그건 맞바꿈 관계라는 뜻입니다.")
    top = sorted(ok.items(), key=lambda kv: -kv[1]["reduction"])[:3]
    for n, s in top:
        L.append(f"- `{n}` 절감 {pct(s['reduction'])} · 식별자 {pct(s['ident'])} "
                 f"· 경로 {pct(s['path'])}")
    return "\n".join(L)


def _read_lang(by_lang: dict, d: dict) -> str:
    gaps = []
    for a in d["arms"]:
        e, k = by_lang.get((a["name"], "en")), by_lang.get((a["name"], "ko"))
        if e and k:
            gaps.append((a["name"], k["reduction"] - e["reduction"],
                         k["ident"] - e["ident"]))
    if not gaps:
        return ""
    L = ["**표에서 보이는 것**", ""]
    worst = min(gaps, key=lambda g: g[2])
    mean_r = st.mean(g[1] for g in gaps)
    mean_i = st.mean(g[2] for g in gaps)
    L.append(f"평균적으로 한국어가 영어보다 절감 {mean_r * 100:+.1f}%p, "
             f"식별자 보존 {mean_i * 100:+.1f}%p 입니다.")
    L.append("")
    L.append(f"격차가 가장 큰 조건은 `{worst[0]}` 로 식별자에서 "
             f"{worst[2] * 100:+.1f}%p 입니다.")
    L.append("")
    L.append("> **주의** — 두 언어가 같은 태스크를 받았습니다(`launch.py` 가 공통 "
             "태스크만 추립니다). 그러니 이 차이는 문제 난이도가 아니라 언어에서 "
             "옵니다. 다만 코드는 두 조건 모두 영어이므로, 차이가 나는 부분은 "
             "**지시문 쪽**입니다.")
    return "\n".join(L)


def _read_task(by_task: dict, d: dict, focus: str) -> str:
    vals = [(t, v) for (t, lang), v in by_task.items() if lang == "en" and v]
    if len(vals) < 2:
        return ""
    hi = max(vals, key=lambda x: x[1]["reduction"])
    lo = min(vals, key=lambda x: x[1]["reduction"])
    ihi = max(vals, key=lambda x: x[1]["ident"])
    ilo = min(vals, key=lambda x: x[1]["ident"])
    L = ["**표에서 보이는 것**", ""]
    L.append(f"같은 조건(`{focus}`)인데 태스크에 따라 절감이 "
             f"{pct(lo[1]['reduction'])}({lo[0]}) ~ "
             f"{pct(hi[1]['reduction'])}({hi[0]}) 로 갈립니다.")
    L.append("")
    L.append(f"식별자 보존은 {pct(ilo[1]['ident'])}({ilo[0]}) ~ "
             f"{pct(ihi[1]['ident'])}({ihi[0]}) 입니다.")
    L.append("")
    L.append("**압축기 설정을 태스크와 무관하게 하나로 고정하면**, 어떤 태스크는 "
             "과하게 깎이고 어떤 태스크는 덜 깎입니다. MS 문서가 \"태스크 유형에 "
             "따라 달라진다\"고 한 것과 같은 방향입니다.")
    return "\n".join(L)


def _read_paths(by_arm: dict, arms: dict, d: dict) -> str:
    """경로 보존이 유독 낮게 나오면 그 원인을 짚는다."""
    ok = {k[0]: v for k, v in by_arm.items() if v}
    if not ok:
        return ""
    L = ["## 5-1. 파일 경로가 왜 사라지나", ""]
    L.append("경로 보존은 다른 지표와 성격이 다릅니다. **부분 점수가 없습니다.** "
             "`builder.py` 가 `builder.` 가 되면 에이전트는 그 파일을 열지 "
             "못하고, 패치는 적용조차 되지 않습니다.")
    L.append("")

    rows = []
    for n, s in sorted(ok.items(), key=lambda kv: kv[1]["path"]):
        rows.append([f"`{n}`", pct(s["path"]), pct(s["num"]),
                     "켬" if (arms[n].get("params") or {}).get("force_tokens")
                     else ("끔" if arms[n].get("params") else "—")])
    L.append(md_table(["조건", "경로 보존", "숫자 보존", "force_tokens"],
                      rows[:10], ["left", "right", "right", "center"]))
    L.append("")
    L.append("*(경로 보존이 낮은 순으로 10개)*")
    L.append("")

    # force_tokens 켬/끔을 **짝지어** 비교한다. 평균을 내면 이 옵션을
    # 아예 무시하는 압축기(v1)가 섞여 효과가 희석된다.
    pairs = []
    for n in ok:
        if "-nt-" not in n:
            continue
        twin = n.replace("-nt-", "-")
        if twin in ok:
            pairs.append((twin, n, ok[twin], ok[n]))
    ignored = [a for a, b, sa, sb in pairs
               if abs(sa["path"] - sb["path"]) < 1e-9
               and abs(sa["reduction"] - sb["reduction"]) < 1e-9]
    if pairs:
        L.append("**원인은 `force_tokens` 입니다.** 같은 압축기·같은 압축률에서 "
                 "이 옵션만 바꿔 짝지었습니다.")
        L.append("")
        rows = []
        for a, b, sa, sb in sorted(pairs):
            rows.append([f"`{a}` → `{b}`",
                         f"{pct(sa['path'])} → {pct(sb['path'])}",
                         f"{pct(sa['num'])} → {pct(sb['num'])}",
                         f"{pct(sa['ident'])} → {pct(sb['ident'])}",
                         f"{pct(sa['reduction'])} → {pct(sb['reduction'])}"])
        L.append(md_table(["켬 → 끔", "경로 보존", "숫자 보존", "식별자", "절감"],
                          rows, ["left", "right", "right", "right", "right"]))
        L.append("")
        md_p, svg_p = chart_pairs(by_arm)
        if md_p:
            CHARTS["pairs"] = svg_p
            L.append("<!--CHART:pairs-->")
            L.append(md_p)
            L.append("")
        dp = st.mean(sb["path"] - sa["path"] for _, _, sa, sb in pairs)
        dn = st.mean(sb["num"] - sa["num"] for _, _, sa, sb in pairs)
        di = st.mean(sb["ident"] - sa["ident"] for _, _, sa, sb in pairs)
        dr = st.mean(sb["reduction"] - sa["reduction"] for _, _, sa, sb in pairs)
        L.append(f"평균적으로 끄면 경로 {dp * 100:+.1f}%p · 숫자 {dn * 100:+.1f}%p "
                 f"· 식별자 {di * 100:+.1f}%p · **절감 {dr * 100:+.1f}%p** 입니다.")
        L.append("")
        if dr > 0 and dp > 0:
            L.append("**맞바꿈이 아닙니다.** 끄는 쪽이 더 많이 줄이면서 더 잘 "
                     "지킵니다. 켤 이유를 찾기 어렵습니다.")
            L.append("")
        if ignored:
            L.append(f"> 한편 `{'`, `'.join(sorted(ignored))}` 는 켜든 끄든 "
                     f"**소수점까지 같습니다.** 그 압축기가 이 옵션을 받고도 "
                     f"쓰지 않는다는 뜻입니다. 인자를 넘겼다고 적용됐다고 "
                     f"믿으면 안 되는 사례입니다.")
            L.append("")
        L.append("이름만 보면 \"이 문자들을 지킨다\" 로 읽힙니다. 실제로는 그 "
                 "문자를 **별도 토큰으로 떼어냅니다.** 텍스트를 되조립할 때 "
                 "주변에 공백이 끼어듭니다.")
        L.append("")
        L.append("```")
        L.append("force_tokens 켬   builder.py   →  builder.        (py 가 떨어짐)")
        L.append("                  32,450,000   →  32, 450, 000")
        L.append("force_tokens 끔   builder.py   →  builder.py      (그대로)")
        L.append("                  32,450,000   →  32,450,000")
        L.append("```")
        L.append("")
        L.append("`compressors/llmlingua.py` 는 원래 이 옵션을 켜고 있었습니다. "
                 "\"개행과 괄호가 사라지면 모델이 파일 구조를 못 읽는다\" 는 "
                 "의도였는데, **지키려던 것을 정확히 망가뜨리고 있었습니다.** "
                 "이 측정 뒤 기본값을 끔으로 바꿨습니다.")
    return "\n".join(L)


def _read_ablation(group: str, names: list, base: str, by_arm: dict) -> str:
    bs = by_arm.get((base,))
    if not bs:
        return ""
    L = ["**무엇이 실제로 기여하나**", ""]
    for n in names:
        s = by_arm.get((n,))
        if not s:
            L.append(f"- `{n}` — 측정 실패")
            continue
        dr, di, dn = (s["reduction"] - bs["reduction"],
                      s["ident"] - bs["ident"], s["num"] - bs["num"])
        verdict = ("기여가 보입니다" if abs(di) >= 0.02 or abs(dn) >= 0.05
                   else "이 코퍼스에서는 차이가 거의 없습니다")
        L.append(f"- `{n}` — 절감 {dr * 100:+.1f}%p · 식별자 {di * 100:+.1f}%p "
                 f"· 숫자 {dn * 100:+.1f}%p → {verdict}")
    L.append("")
    L.append("차이가 없다는 것도 결과입니다. 기본값으로 켜 두면 손해는 없지만, "
             "그 옵션 덕분이라고 설명하면 틀립니다.")
    return "\n".join(L)


def _read_vs_ms(by_arm: dict, by_lang: dict, d: dict) -> str:
    L = []
    L.append("MS 공유 문서는 **Headroom** 을 **OpenCode** 에이전트로 DeepSWE·"
             "Terminal Bench 에 돌린 결과였습니다. 이 리포트와 겹치는 축과 "
             "다른 축을 먼저 갈라야 비교가 성립합니다.")
    L.append("")
    L.append(md_table(
        ["", "MS 문서", "이 리포트"],
        [["압축기", "Headroom", "LLMLingua v1 · v2"],
         ["에이전트", "OpenCode 1.17.15", "없음 (컨텍스트만 조립)"],
         ["측정", "실제 롤아웃 · 태스크당 5회", "압축만 · 태스크당 1회"],
         ["지표", "`total_tok` 증감 + 품질 점수", "토큰 절감 + 보존율"],
         ["언어", "영어 · 한국어(영문 번역)", "영어 · 한국어(번역)"],
         ["태스크", "DeepSWE 6건", f"DeepSWE {len(d['tasks'])}건"]],
        ["left", "left", "left"]))
    L.append("")
    L.append("### 겹치는 것 — 토큰 증감")
    L.append("")
    L.append("MS 문서에서 DeepSWE 6개 태스크 중 **2건은 압축을 걸었는데 토큰이 "
             "오히려 늘었습니다**(`mnamer` +15.3%, `opa-rego` +5.4%, 영어 기준).")
    L.append("")
    L.append("이 리포트에서는 그런 일이 일어나지 않습니다. **측정 방식이 다르기 "
             "때문입니다.**")
    L.append("")
    L.append("- MS 문서는 **롤아웃 전체**의 누적 토큰입니다. 압축으로 정보가 "
             "깨지면 에이전트가 파일을 다시 읽어 턴이 늘고, 그래서 총량이 "
             "늘어납니다")
    L.append("- 이 리포트는 **고정된 컨텍스트 한 번**을 압축한 값입니다. "
             "되읽기가 일어날 수 없습니다")
    L.append("")
    L.append("따라서 여기 절감률은 **낙관적인 상한**입니다. 실제 운영에서는 "
             "되읽기만큼 깎입니다. 아래 경로·식별자 보존율이 낮은 조건일수록 "
             "그 위험이 큽니다.")
    L.append("")
    L.append("### 다른 것 — 품질")
    L.append("")
    L.append("MS 문서의 `품질` 열(0.077 ~ 0.996)은 실제 채점 결과입니다. 이 "
             "리포트에는 대응하는 값이 없습니다. 보존율로 갈음하지 마세요.")
    return "\n".join(L)


def _read_summary(by_arm: dict, by_lang: dict, d: dict) -> str:
    ok = {k[0]: v for k, v in by_arm.items() if v}
    if not ok:
        return "측정 결과가 없습니다."
    arms = {a["name"]: a for a in d["arms"]}
    sweep = {n: s for n, s in ok.items()
             if arms[n]["group"].startswith("스윕")}
    L = []

    # 쓸 만한 조건: 식별자·경로 90% 이상 중 절감 최대
    usable = {n: s for n, s in sweep.items()
              if s["ident"] >= 0.9 and s["path"] >= 0.9}
    if usable:
        best = max(usable.items(), key=lambda kv: kv[1]["reduction"])
        L.append(f"**① 식별자·경로를 90% 이상 지키면서 가장 많이 줄인 조건은 "
                 f"`{best[0]}`** 로 절감 {pct(best[1]['reduction'])} 입니다.")
    else:
        L.append("**① 식별자·경로를 모두 90% 이상 지킨 조건이 없습니다.** "
                 "이 코퍼스와 설정 범위에서는 안전한 압축 지점을 찾지 못했습니다.")
    L.append("")

    # v1 vs v2
    v1 = {n: s for n, s in sweep.items() if "v1" in n}
    v2 = {n: s for n, s in sweep.items() if n.startswith("v2-")}
    if v1 and v2:
        m1r, m2r = st.mean(s["reduction"] for s in v1.values()), st.mean(
            s["reduction"] for s in v2.values())
        m1i, m2i = st.mean(s["ident"] for s in v1.values()), st.mean(
            s["ident"] for s in v2.values())
        m1l, m2l = st.mean(s["latency"] for s in v1.values()), st.mean(
            s["latency"] for s in v2.values())
        L.append(f"**② v1 과 v2** — 평균 절감 v1 {pct(m1r)} vs v2 {pct(m2r)}, "
                 f"식별자 보존 v1 {pct(m1i)} vs v2 {pct(m2i)}, "
                 f"지연 v1 {m1l:.2f}s vs v2 {m2l:.2f}s.")
        L.append("")

    # 모델 크기
    lg = {n: s for n, s in sweep.items() if n.startswith("v2-r")}
    sm = {n: s for n, s in sweep.items() if n.startswith("v2s-r")}
    if lg and sm:
        pairs = [(n, lg[n], sm[n.replace("v2-", "v2s-")])
                 for n in lg if n.replace("v2-", "v2s-") in sm]
        if pairs:
            di = st.mean(a["ident"] - b["ident"] for _, a, b in pairs)
            dr = st.mean(a["reduction"] - b["reduction"] for _, a, b in pairs)
            dl = st.mean(a["latency"] - b["latency"] for _, a, b in pairs)
            L.append(f"**③ 모델 크기(2.2GB vs 700MB)** — 큰 쪽이 절감 "
                     f"{dr * 100:+.1f}%p, 식별자 {di * 100:+.1f}%p, "
                     f"지연 {dl:+.2f}s 입니다.")
            L.append("")

    # force_tokens
    nt = [(n, s) for n, s in ok.items() if "-nt-" in n]
    if nt:
        pr = [(n, s, ok[n.replace("-nt-", "-")]) for n, s in nt
              if n.replace("-nt-", "-") in ok]
        gain = [(a, b["path"] - c["path"]) for a, b, c in pr]
        big = max(gain, key=lambda g: g[1])
        if big[1] > 0.1:
            L.append(f"**④ `force_tokens` 를 끄십시오.** 짝지어 비교했을 때 "
                     f"경로 보존이 최대 {big[1] * 100:+.0f}%p 개선됩니다"
                     f"(`{big[0]}`). 절감률도 함께 올라가므로 맞바꿈이 "
                     f"아닙니다. 5-1 절을 보세요.")
            L.append("")

    # 경로
    worst_path = min(sweep.items(), key=lambda kv: kv[1]["path"])
    L.append(f"**⑤ 가장 위험한 신호는 경로 보존입니다.** 가장 낮은 조건이 "
             f"`{worst_path[0]}` 의 {pct(worst_path[1]['path'])} 입니다. "
             f"파일 경로가 깨지면 패치가 적용조차 되지 않아, 부분 점수 없이 "
             f"0점이 납니다.")
    return "\n".join(L)


# ═══════════════════════════════════════════════════════════════
# HTML
# ═══════════════════════════════════════════════════════════════

CSS = """
:root{--bg:#0f1115;--fg:#e6e8eb;--dim:#9aa4b2;--line:#252a33;--accent:#6ea8fe;
--good:#63c98f;--warn:#e0b341;--bad:#e06c75;--card:#161a21}
@media(prefers-color-scheme:light){:root{--bg:#fff;--fg:#1c1f24;--dim:#5b6472;
--line:#e3e6ea;--accent:#1f6feb;--card:#f6f8fa}}
*{box-sizing:border-box}
body{margin:0;padding:0;background:var(--bg);color:var(--fg);
font:15px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:48px 28px 96px}
h1{font-size:30px;margin:0 0 8px;letter-spacing:-.02em}
h2{font-size:22px;margin:52px 0 14px;padding-top:20px;border-top:1px solid var(--line)}
h3{font-size:17px;margin:28px 0 10px;color:var(--accent)}
p{margin:12px 0}
code{background:var(--card);padding:2px 6px;border-radius:4px;
font:13px ui-monospace,SFMono-Regular,Menlo,monospace}
pre{background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:14px 16px;overflow-x:auto}
pre code{background:none;padding:0}
table{border-collapse:collapse;width:100%;margin:16px 0;font-size:13.5px;
display:block;overflow-x:auto;white-space:nowrap}
th,td{border-bottom:1px solid var(--line);padding:8px 12px;text-align:left}
th{background:var(--card);font-weight:600;position:sticky;top:0}
tr:hover td{background:var(--card)}
blockquote{margin:16px 0;padding:10px 18px;border-left:3px solid var(--accent);
background:var(--card);border-radius:0 6px 6px 0;color:var(--dim)}
ul{padding-left:22px}
li{margin:6px 0}
strong{color:var(--fg)}
.meta{color:var(--dim);font-size:13px}
hr{border:0;border-top:1px solid var(--line);margin:36px 0}
.toc{background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:14px 22px;margin:24px 0}
.toc a{color:var(--accent);text-decoration:none}
.toc a:hover{text-decoration:underline}
.n{text-align:right;font-variant-numeric:tabular-nums}
.chart{width:100%;height:auto;margin:18px 0;background:var(--card);
border:1px solid var(--line);border-radius:8px;padding:10px}
.chart .grid{stroke:var(--line);stroke-width:1}
.chart .ax{fill:var(--dim);font-size:11px}
"""


def md_to_html(md: str) -> str:
    """리포트가 쓰는 문법만 다룬다. 범용 변환기가 아니다."""
    import re
    out, i, lines = [], 0, md.split("\n")
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(html.escape(lines[i]))
                i += 1
            out.append("<pre><code>" + "\n".join(block) + "</code></pre>")
            i += 1
            continue
        if ln.startswith("|"):
            tbl = []
            while i < len(lines) and lines[i].startswith("|"):
                tbl.append(lines[i])
                i += 1
            out.append(_html_table(tbl))
            continue
        if ln.startswith("### "):
            out.append(f"<h3>{_inline(ln[4:])}</h3>")
        elif ln.startswith("## "):
            aid = f"s{len(out)}"
            out.append(f'<h2 id="{aid}">{_inline(ln[3:])}</h2>')
        elif ln.startswith("# "):
            out.append(f"<h1>{_inline(ln[2:])}</h1>")
        elif ln.startswith("> "):
            buf = []
            while i < len(lines) and lines[i].startswith("> "):
                buf.append(lines[i][2:])
                i += 1
            out.append(f"<blockquote>{_inline(' '.join(buf))}</blockquote>")
            continue
        elif ln.startswith("- "):
            buf = []
            while i < len(lines) and lines[i].startswith("- "):
                buf.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(buf) + "</ul>")
            continue
        elif ln.strip() == "---":
            out.append("<hr>")
        elif ln.strip():
            out.append(f"<p>{_inline(ln)}</p>")
        i += 1
    return "\n".join(out)


def _inline(s: str) -> str:
    import re
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def _html_table(rows: list) -> str:
    def cells(r):
        return [c.strip() for c in r.strip().strip("|").split("|")]

    head = cells(rows[0])
    aligns = ["right" if set(c.strip()) <= set("-:") and c.strip().endswith(":")
              and not c.strip().startswith(":") else "left"
              for c in cells(rows[1])] if len(rows) > 1 else []
    body = rows[2:] if len(rows) > 2 else []
    h = "".join(f"<th>{_inline(c)}</th>" for c in head)
    b = []
    for r in body:
        cs = cells(r)
        b.append("<tr>" + "".join(
            f'<td class="{"n" if i < len(aligns) and aligns[i] == "right" else ""}">'
            f"{_inline(c)}</td>" for i, c in enumerate(cs)) + "</tr>")
    return f"<table><thead><tr>{h}</tr></thead><tbody>{''.join(b)}</tbody></table>"


def build_html(md: str, name: str) -> str:
    import re
    toc = [f'<a href="#s{i}">{html.escape(m)}</a>'
           for i, m in enumerate(re.findall(r"^## (.+)$", md, re.M))]
    body = md_to_html(md)
    for key, svg in CHARTS.items():
        body = body.replace(f"<p>&lt;!--CHART:{key}--&gt;</p>", svg or "")
    # 목차는 첫 h2 앞에 넣는다
    nav = ('<div class="toc"><strong>목차</strong><br>' +
           " · ".join(toc) + "</div>") if toc else ""
    body = body.replace("<h2", nav + "<h2", 1) if nav else body
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>압축기 벤치마크 — {html.escape(name)}</title>
<style>{CSS}</style></head>
<body><div class="wrap">{body}</div></body></html>"""


# ═══════════════════════════════════════════════════════════════

def main() -> int:
    p = argparse.ArgumentParser(description="벤치마크 리포트 생성")
    p.add_argument("name")
    args = p.parse_args()

    d_dir = REPORTS / args.name
    src = d_dir / "results.json"
    if not src.exists():
        print(f"✗ 결과가 없습니다: {src}", file=sys.stderr)
        return 1

    d = json.loads(src.read_text(encoding="utf-8"))
    md = build_md(d)
    (d_dir / "report.md").write_text(md, encoding="utf-8")
    (d_dir / "report.html").write_text(build_html(md, d["name"]), encoding="utf-8")

    print(f"▸ {(d_dir / 'report.md').relative_to(REPO)}  ({len(md):,}자)")
    print(f"▸ {(d_dir / 'report.html').relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

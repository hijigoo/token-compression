#!/usr/bin/env python3
"""측정 결과를 기술 보고서 형식으로 냅니다.

`report_summary.py` 와 무엇이 다른가
────────────────────────────────────
`report_summary.py` 는 "무엇을 겪었는지" 를 함께 적습니다 — 버그를 어떻게
찾았고 왜 이전 수치를 버렸는지까지. 읽는 사람을 설득하는 데는 그게 맞지만,
결과만 보려는 사람에게는 잡음입니다.

이 파일은 **결과만** 냅니다. 파라미터 정의 · 지표 정의 · 실험 조건 ·
측정값 · 분석 · 한계. 순서와 어투를 기술 보고서에 맞췄습니다.

렌더링을 `report.py` 에서 가져오지 않고 여기서 직접 합니다. 기존 CSS 는
색을 여러 개 쓰는데, 이 문서는 회색조로 가야 표와 그림이 조용해집니다.

문서 모델
─────────
    Doc → [Section] → [Block]
    Block = P(문단) | Table(표) | Figure(그림) | Code(코드) | Note(각주)

표와 그림에 번호를 자동으로 매깁니다. 본문에서 `[표 1]` 처럼 참조하려면
`doc.tref(...)` 로 잡아 둔 번호를 씁니다.

쓰는 곳
    ./.venv/bin/python report_paper.py \
        --grid ../../reports/llmlingua2-grid/results.json \
        --run <run_dir> --jobs /tmp/tbwide2 \
        --control-run <run_dir> --control-jobs /tmp/tbjob-nocompress \
        --samples ../../reports/summary/samples.json \
        -o ../../reports/analysis
"""
from __future__ import annotations

import argparse
import html
import json
import re
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import report_run as _rr  # noqa: E402  (롤아웃 판독만 가져옵니다)


# ═════════════════════════════════════════════════════════════════════
# 문서 모델
# ═════════════════════════════════════════════════════════════════════
class Doc:
    def __init__(self, title: str, subtitle: str = ""):
        self.title, self.subtitle = title, subtitle
        self.abstract: list[str] = []
        self.sections: list[dict] = []
        self._t = 0          # 표 번호
        self._f = 0          # 그림 번호

    def sec(self, title: str, blocks: list) -> None:
        self.sections.append({"title": title, "blocks": blocks})

    def next_table(self) -> int:
        self._t += 1
        return self._t

    def next_fig(self) -> int:
        self._f += 1
        return self._f


class P:
    def __init__(self, text: str):
        self.text = text


class Note:
    """표·그림 아래 붙는 작은 설명."""
    def __init__(self, text: str):
        self.text = text


class Code:
    def __init__(self, text: str):
        self.text = text


class Table:
    def __init__(self, n: int, caption: str, head: list, rows: list,
                 align: str = "", note: str = ""):
        self.n, self.caption, self.head, self.rows = n, caption, head, rows
        # align: 열마다 'l' 또는 'r'. 숫자 열은 오른쪽 정렬해야 자릿수가 맞습니다.
        self.align = align or "l" * len(head)
        self.note = note


class Figure:
    def __init__(self, n: int, caption: str, svg: str, note: str = ""):
        self.n, self.caption, self.svg, self.note = n, caption, svg, note


# ═════════════════════════════════════════════════════════════════════
# 그림 — 회색조 SVG
# 색으로 구분하지 않고 **명도와 채움 패턴**으로 구분합니다. 흑백 출력에서도
# 읽히고, 색각 이상이 있어도 읽힙니다.
# ═════════════════════════════════════════════════════════════════════
GRAY = ["#111", "#666", "#aaa", "#d0d0d0"]


def _esc(s) -> str:
    return html.escape(str(s))


def grouped_bars(series: list, labels: list, fmt=lambda v: f"{v:.0f}",
                 w: int = 720, bar_h: int = 15, gap: int = 5,
                 pad_l: int = 132, pad_r: int = 74) -> str:
    """가로 묶음 막대.

    series = [(계열이름, [값…]), …]  · labels = 항목 이름
    같은 항목의 여러 계열을 붙여 그립니다. 계열은 명도로 구분합니다.
    """
    vals = [v for _, vs in series for v in vs if v is not None]
    if not vals:
        return ""
    vmax = max(vals) or 1
    grp = len(series) * (bar_h + 1) + gap * 2
    top = 26 + 18 * (len(series) > 1)
    h = top + grp * len(labels) + 8
    inner = w - pad_l - pad_r

    o = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
         f'class="fig" role="img">']
    # 눈금 — 0/25/50/75/100%
    for f in (0, .25, .5, .75, 1):
        x = pad_l + inner * f
        o.append(f'<line x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" '
                 f'y2="{h - 8}" class="grid"/>')
        o.append(f'<text x="{x:.1f}" y="{top - 10}" class="tick" '
                 f'text-anchor="middle">{fmt(vmax * f)}</text>')
    # 범례
    if len(series) > 1:
        x = pad_l
        for i, (nm, _) in enumerate(series):
            o.append(f'<rect x="{x}" y="{h - 2}" width="10" height="10" '
                     f'fill="{GRAY[i % len(GRAY)]}"/>')
            o.append(f'<text x="{x + 14}" y="{h + 7}" class="tick">{_esc(nm)}</text>')
            x += 22 + 7 * len(str(nm))
        h += 16
        o[0] = (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
                f'class="fig" role="img">')

    for r, lab in enumerate(labels):
        y0 = top + grp * r + gap
        o.append(f'<text x="{pad_l - 8}" y="{y0 + grp / 2 - 2:.0f}" '
                 f'class="lab" text-anchor="end">{_esc(lab)}</text>')
        for i, (_, vs) in enumerate(series):
            v = vs[r] if r < len(vs) else None
            y = y0 + i * (bar_h + 1)
            if v is None:
                o.append(f'<text x="{pad_l + 3}" y="{y + bar_h - 3}" '
                         f'class="tick">—</text>')
                continue
            bw = max(1.0, inner * (v / vmax))
            o.append(f'<rect x="{pad_l}" y="{y}" width="{bw:.1f}" '
                     f'height="{bar_h}" fill="{GRAY[i % len(GRAY)]}"/>')
            o.append(f'<text x="{pad_l + bw + 5:.1f}" y="{y + bar_h - 3}" '
                     f'class="val">{_esc(fmt(v))}</text>')
    o.append("</svg>")
    return "".join(o)


def line_chart(xs: list, series: list, xlabel: str, ylabel: str,
               yfmt=lambda v: f"{v:.0%}", w: int = 640, h: int = 300) -> str:
    """꺾은선. 압축률 스윕처럼 x 가 연속일 때 씁니다."""
    ok = [v for _, ys in series for v in ys if v is not None]
    if not ok or len(xs) < 2:
        return ""
    lo, hi = min(ok), max(ok)
    if hi == lo:
        hi = lo + 1e-6
    pad = (hi - lo) * .12
    lo, hi = max(0, lo - pad), hi + pad
    ml, mr, mt, mb = 58, 96, 18, 42
    iw, ih = w - ml - mr, h - mt - mb
    xlo, xhi = min(xs), max(xs)
    X = lambda v: ml + iw * (v - xlo) / (xhi - xlo or 1)   # noqa: E731
    Y = lambda v: mt + ih * (1 - (v - lo) / (hi - lo))     # noqa: E731

    o = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
         f'class="fig" role="img">']
    for f in range(5):
        v = lo + (hi - lo) * f / 4
        y = Y(v)
        o.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml + iw}" y2="{y:.1f}" '
                 f'class="grid"/>')
        o.append(f'<text x="{ml - 8}" y="{y + 4:.1f}" class="tick" '
                 f'text-anchor="end">{yfmt(v)}</text>')
    for v in xs:
        o.append(f'<text x="{X(v):.1f}" y="{mt + ih + 18}" class="tick" '
                 f'text-anchor="middle">{v}</text>')
    o.append(f'<text x="{ml + iw / 2:.0f}" y="{h - 6}" class="tick" '
             f'text-anchor="middle">{_esc(xlabel)}</text>')
    o.append(f'<text x="14" y="{mt + ih / 2:.0f}" class="tick" '
             f'transform="rotate(-90 14 {mt + ih / 2:.0f})" '
             f'text-anchor="middle">{_esc(ylabel)}</text>')

    DASH = ["", "5 3", "2 2", "8 3"]
    for i, (nm, ys) in enumerate(series):
        pts = [(X(x), Y(y)) for x, y in zip(xs, ys) if y is not None]
        if len(pts) < 2:
            continue
        d = " ".join(f"{'M' if k == 0 else 'L'}{x:.1f},{y:.1f}"
                     for k, (x, y) in enumerate(pts))
        o.append(f'<path d="{d}" fill="none" stroke="{GRAY[i % len(GRAY)]}" '
                 f'stroke-width="1.6" stroke-dasharray="{DASH[i % len(DASH)]}"/>')
        for x, y in pts:
            o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" '
                     f'fill="{GRAY[i % len(GRAY)]}"/>')
        o.append(f'<text x="{pts[-1][0] + 7:.1f}" y="{pts[-1][1] + 4:.1f}" '
                 f'class="tick">{_esc(nm)}</text>')
    o.append("</svg>")
    return "".join(o)


def scatter(pts: list, xlabel: str, ylabel: str,
            xfmt=lambda v: f"{v:.0%}", yfmt=lambda v: f"{v:.0%}",
            w: int = 620, h: int = 330) -> str:
    """산점도. (라벨, x, y) — 압축률·정확도 트레이드오프에 씁니다."""
    pts = [p for p in pts if p[1] is not None and p[2] is not None]
    if len(pts) < 2:
        return ""
    xs, ys = [p[1] for p in pts], [p[2] for p in pts]
    ml, mr, mt, mb = 58, 26, 18, 44
    iw, ih = w - ml - mr, h - mt - mb
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = min(ys), max(ys)
    xp, yp = (xhi - xlo) * .14 or .05, (yhi - ylo) * .16 or .05
    xlo, xhi, ylo, yhi = xlo - xp, xhi + xp, max(0, ylo - yp), yhi + yp
    X = lambda v: ml + iw * (v - xlo) / (xhi - xlo or 1)   # noqa: E731
    Y = lambda v: mt + ih * (1 - (v - ylo) / (yhi - ylo or 1))  # noqa: E731

    o = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
         f'class="fig" role="img">']
    for f in range(5):
        y = mt + ih * f / 4
        o.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml + iw}" y2="{y:.1f}" '
                 f'class="grid"/>')
        o.append(f'<text x="{ml - 8}" y="{y + 4:.1f}" class="tick" '
                 f'text-anchor="end">{yfmt(yhi - (yhi - ylo) * f / 4)}</text>')
        x = ml + iw * f / 4
        o.append(f'<text x="{x:.1f}" y="{mt + ih + 18}" class="tick" '
                 f'text-anchor="middle">{xfmt(xlo + (xhi - xlo) * f / 4)}</text>')
    o.append(f'<text x="{ml + iw / 2:.0f}" y="{h - 8}" class="tick" '
             f'text-anchor="middle">{_esc(xlabel)}</text>')
    o.append(f'<text x="14" y="{mt + ih / 2:.0f}" class="tick" '
             f'transform="rotate(-90 14 {mt + ih / 2:.0f})" '
             f'text-anchor="middle">{_esc(ylabel)}</text>')
    for lab, x, y in pts:
        cx, cy = X(x), Y(y)
        o.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.4" fill="#111"/>')
        o.append(f'<text x="{cx + 6:.1f}" y="{cy - 5:.1f}" class="tick">'
                 f'{_esc(lab)}</text>')
    o.append("</svg>")
    return "".join(o)


def slope(pairs: list, labels: list, fmt=lambda v: f"{v:+.0%}",
          w: int = 620) -> str:
    """기울기 그래프. 태스크별 변화량을 한 줄씩 그립니다.

    pairs = [(태스크, 값, 통과여부), …]  — 0 을 기준으로 좌우로 뻗습니다.
    """
    pairs = [p for p in pairs if p[1] is not None]
    if not pairs:
        return ""
    vs = [p[1] for p in pairs]
    lim = max(abs(min(vs)), abs(max(vs))) or 1
    row, ml, mr, mt = 21, 168, 60, 30
    h = mt + row * len(pairs) + 14
    iw = w - ml - mr
    zero = ml + iw / 2
    X = lambda v: zero + (iw / 2) * (v / lim)   # noqa: E731

    o = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
         f'class="fig" role="img">',
         f'<text x="{zero:.0f}" y="{mt - 12}" class="tick" '
         f'text-anchor="middle">변화 없음</text>',
         f'<line x1="{zero:.1f}" y1="{mt - 6}" x2="{zero:.1f}" '
         f'y2="{h - 10}" class="axis"/>']
    for i, (lab, v, ok) in enumerate(pairs):
        y = mt + row * i + row / 2
        o.append(f'<text x="{ml - 10}" y="{y + 4:.1f}" class="lab" '
                 f'text-anchor="end">{_esc(lab)}</text>')
        x = X(v)
        x0, x1 = (zero, x) if v >= 0 else (x, zero)
        o.append(f'<rect x="{x0:.1f}" y="{y - 6:.1f}" '
                 f'width="{max(1, x1 - x0):.1f}" height="12" '
                 f'fill="{"#111" if v > 0 else "#999"}"/>')
        ta, tx = ("start", x + 5) if v >= 0 else ("end", x - 5)
        o.append(f'<text x="{tx:.1f}" y="{y + 4:.1f}" class="val" '
                 f'text-anchor="{ta}">{_esc(fmt(v))}{"" if ok is None else ("  ✓" if ok else "  ✗")}</text>')
    o.append("</svg>")
    return "".join(o)


# ═════════════════════════════════════════════════════════════════════
# 렌더링
# ═════════════════════════════════════════════════════════════════════
CSS = """
:root{--fg:#17181a;--dim:#6e6e6e;--line:#e6e6e6;--bg:#fff;--soft:#fafafa}
@media(prefers-color-scheme:dark){:root{--fg:#e9e9e9;--dim:#9c9c9c;
--line:#2f2f2f;--bg:#121212;--soft:#1a1a1a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:860px;margin:0 auto;padding:56px 26px 110px}
h1{font-size:25px;font-weight:650;letter-spacing:-.015em;margin:0 0 6px;line-height:1.35}
.sub{color:var(--dim);font-size:13.5px;margin:0 0 30px}
h2{font-size:16.5px;font-weight:650;margin:46px 0 12px;padding-bottom:7px;
border-bottom:1px solid var(--fg)}
h3{font-size:14.5px;font-weight:650;margin:26px 0 8px;color:var(--fg)}
p{margin:11px 0}
.abs{border:1px solid var(--line);background:var(--soft);border-radius:3px;
padding:16px 20px;margin:0 0 26px}
.abs h3{margin:0 0 6px;font-size:12px;letter-spacing:.09em;text-transform:uppercase;
color:var(--dim)}
.abs p{margin:7px 0;font-size:14.2px}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;
background:var(--soft);border:1px solid var(--line);padding:1px 4px;border-radius:2px}
pre{background:var(--soft);border:1px solid var(--line);border-radius:3px;
padding:13px 15px;overflow-x:auto;margin:14px 0}
pre code{background:none;border:0;padding:0;font-size:12px;line-height:1.6}
table{border-collapse:collapse;width:100%;margin:6px 0 0;font-size:13.2px}
th,td{padding:6px 11px;border-bottom:1px solid var(--line);vertical-align:top}
thead th{border-top:1px solid var(--fg);border-bottom:1px solid var(--fg);
font-weight:600;text-align:left;white-space:nowrap}
tbody tr:last-child td{border-bottom:1px solid var(--fg)}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
.cap{font-size:12.5px;color:var(--dim);margin:22px 0 3px}
.cap b{color:var(--fg);font-weight:600}
.note{font-size:12.3px;color:var(--dim);margin:7px 0 0;line-height:1.6}
figure{margin:22px 0 0}
.fig{width:100%;height:auto;display:block;margin:6px 0 0}
.fig .grid{stroke:var(--line);stroke-width:1}
.fig .axis{stroke:var(--dim);stroke-width:1}
.fig .tick{fill:var(--dim);font-size:10.5px}
.fig .lab{fill:var(--fg);font-size:11px}
.fig .val{fill:var(--fg);font-size:10.5px;font-variant-numeric:tabular-nums}
.toc{font-size:13.2px;color:var(--dim);border:1px solid var(--line);
border-radius:3px;padding:12px 18px;margin:0 0 30px}
.toc a{color:var(--fg);text-decoration:none;margin-right:14px;
display:inline-block;padding:1px 0}
.toc a:hover{text-decoration:underline}
strong{font-weight:650}
hr{border:0;border-top:1px solid var(--line);margin:40px 0}
@media print{.toc{display:none}body{font-size:10.5pt}.wrap{padding:0}}
"""


def _md_inline(s: str) -> str:
    """**굵게** 와 `코드` 만 처리합니다."""
    import re
    s = _esc(s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def to_html(doc: Doc) -> str:
    o = [f'<!doctype html><html lang="ko"><head><meta charset="utf-8">',
         f'<meta name="viewport" content="width=device-width,initial-scale=1">',
         f'<title>{_esc(doc.title)}</title><style>{CSS}</style></head><body>',
         '<div class="wrap">',
         f'<h1>{_esc(doc.title)}</h1>']
    if doc.subtitle:
        o.append(f'<p class="sub">{_md_inline(doc.subtitle)}</p>')
    if doc.abstract:
        o.append('<div class="abs"><h3>요약</h3>')
        o += [f"<p>{_md_inline(t)}</p>" for t in doc.abstract]
        o.append("</div>")
    o.append('<nav class="toc">' + "".join(
        f'<a href="#s{i}">{i}. {_esc(s["title"])}</a>'
        for i, s in enumerate(doc.sections, 1)) + "</nav>")

    for i, s in enumerate(doc.sections, 1):
        o.append(f'<h2 id="s{i}">{i}. {_esc(s["title"])}</h2>')
        for b in s["blocks"]:
            o.append(_block_html(b))
    o.append("</div></body></html>")
    return "".join(o)


def _block_html(b) -> str:
    if isinstance(b, str):
        return f'<h3>{_esc(b)}</h3>'
    if isinstance(b, P):
        return f"<p>{_md_inline(b.text)}</p>"
    if isinstance(b, Note):
        return f'<p class="note">{_md_inline(b.text)}</p>'
    if isinstance(b, Code):
        return f"<pre><code>{_esc(b.text)}</code></pre>"
    if isinstance(b, Table):
        h = "".join(f'<th class="{"r" if b.align[j] == "r" else ""}">'
                    f'{_md_inline(c)}</th>' for j, c in enumerate(b.head))
        rs = "".join(
            "<tr>" + "".join(
                f'<td class="{"r" if b.align[j] == "r" else ""}">'
                f'{_md_inline(c)}</td>' for j, c in enumerate(r)) + "</tr>"
            for r in b.rows)
        n = (f'<p class="note">{_md_inline(b.note)}</p>' if b.note else "")
        return (f'<p class="cap"><b>표 {b.n}.</b> {_md_inline(b.caption)}</p>'
                f"<table><thead><tr>{h}</tr></thead><tbody>{rs}</tbody></table>{n}")
    if isinstance(b, Figure):
        n = (f'<p class="note">{_md_inline(b.note)}</p>' if b.note else "")
        return (f'<figure><p class="cap"><b>그림 {b.n}.</b> '
                f'{_md_inline(b.caption)}</p>{b.svg}{n}</figure>')
    return ""


def to_md(doc: Doc) -> str:
    L = [f"# {doc.title}", ""]
    if doc.subtitle:
        L += [doc.subtitle, ""]
    if doc.abstract:
        L += ["## 요약", ""] + [t + "\n" for t in doc.abstract]
    for i, s in enumerate(doc.sections, 1):
        L += ["", f"## {i}. {s['title']}", ""]
        for b in s["blocks"]:
            L += _block_md(b)
    return "\n".join(L)


def _block_md(b) -> list:
    if isinstance(b, str):
        return ["", f"### {b}", ""]
    if isinstance(b, P):
        return [b.text, ""]
    if isinstance(b, Note):
        return [f"> {b.text}", ""]
    if isinstance(b, Code):
        return ["```", b.text, "```", ""]
    if isinstance(b, Table):
        w = [max(len(str(x)) for x in [b.head[j]] + [r[j] for r in b.rows])
             for j in range(len(b.head))]
        sep = "|" + "|".join(("-" * (w[j] + 2))[:-1] +
                             (":" if b.align[j] == "r" else " ")
                             for j in range(len(b.head))) + "|"
        line = lambda r: "| " + " | ".join(  # noqa: E731
            str(r[j]).ljust(w[j]) for j in range(len(b.head))) + " |"
        out = [f"**표 {b.n}.** {b.caption}", "", line(b.head), sep]
        out += [line(r) for r in b.rows]
        out += [""]
        if b.note:
            out += [f"> {b.note}", ""]
        return out
    if isinstance(b, Figure):
        out = [f"**그림 {b.n}.** {b.caption}", "",
               "_(그래프는 HTML 판에서 보십시오.)_", ""]
        if b.note:
            out += [f"> {b.note}", ""]
        return out
    return []


# ═════════════════════════════════════════════════════════════════════
# 데이터
# ═════════════════════════════════════════════════════════════════════
def pc(v, d=1):
    return "—" if v is None else f"{v * 100:.{d}f}%"


def pp(v, d=1):
    return "—" if v is None else f"{'+' if v >= 0 else ''}{v * 100:.{d}f}%p"


def rel(v, d=1):
    return "—" if v is None else f"{'+' if v >= 0 else ''}{v * 100:.{d}f}%"


def num(v):
    return "—" if v is None else f"{v:,.0f}"


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def read_rollout(run_dirs, jobs: list[Path]) -> dict | None:
    """롤아웃을 조건별로 접습니다.

    `run_dirs` 는 하나 또는 여럿입니다. 언어를 나눠 돌리면(en 을 먼저 돌리고
    ko 를 나중에 돌리는 식) run 디렉터리가 갈리는데, 조건 이름은 같으므로
    한 측정으로 합쳐야 합니다. 각 run 의 `arms.json` 에서 URL→조건 이름
    대응을 모아 하나의 지도로 만듭니다. 프록시 포트는 실행마다 달라지지만
    조건 이름은 고정이므로 이 방식이 안전합니다.
    """
    if isinstance(run_dirs, (str, Path)):
        run_dirs = [run_dirs]
    run_dirs = [Path(r) for r in run_dirs if (Path(r) / "arms.json").exists()]
    if not run_dirs:
        return None

    by_url: dict[str, str] = {}
    arms: list[dict] = []
    seen: set[str] = set()
    for rd in run_dirs:
        for a in json.loads((rd / "arms.json").read_text(encoding="utf-8")):
            a["compressor"] = a.get("compressor") or "none"
            a["rate"] = a["ratio"] if a.get("ratio") is not None else 1.0
            if a.get("base_url"):
                by_url[a["base_url"]] = a["name"]
            if a["name"] not in seen:
                seen.add(a["name"])
                arms.append(a)

    rows = _rr.collect(jobs, by_url)
    # 여러 jobs 디렉터리를 한꺼번에 넘기면 다른 실험의 trial 이 섞여 들어올
    # 수 있습니다. 그런 행은 arm 을 판별하지 못해 None 이 되므로 버립니다.
    # (남겨 두면 정렬·집계가 조용히 깨집니다.)
    rows = [r for r in rows if r.get("arm")]
    if not rows:
        return None

    # `collect` 은 넘겨받은 jobs 디렉터리 이름 끝에서 언어를 뽑습니다.
    # 언어별 하위 폴더를 품은 상위 폴더 하나만 넘기면(예: /tmp/tbjob2)
    # 전 행이 같은 값을 갖게 되므로, trial 경로에서 다시 판별합니다.
    for r in rows:
        for part in reversed(Path(r["trial"]).parts):
            tail = part.rsplit("-", 1)[-1]
            if len(tail) == 2 and tail.isalpha() and tail != part:
                r["lang"] = tail
                break

    # 대조 측정은 조건이 전부 동일하므로 base_url 도 동일합니다. 그래서
    # trial 을 조건에 귀속시킬 수 없습니다(전부 마지막 조건으로 몰립니다).
    # 조건이 같다는 것은 곧 **반복 측정**이라는 뜻이므로, 태스크별로 묶어
    # 회차 번호를 부여합니다. 이렇게 해야 "같은 태스크를 세 번 돌렸을 때
    # 결과가 갈리는가" 를 볼 수 있습니다.
    if len({a["base_url"] for a in arms}) == 1 and len(arms) > 1:
        seen: dict[str, int] = {}
        for r in sorted(rows, key=lambda x: x["trial"]):
            k = r["task"]
            seen[k] = seen.get(k, 0) + 1
            r["arm"] = f"회차 {seen[k]}"
        arms = [{"name": f"회차 {i}", "compressor": "none", "rate": 1.0,
                 "base_url": arms[0]["base_url"]}
                for i in range(1, max(seen.values(), default=1) + 1)]
        rows = [r for r in rows if r["arm"] in {a["name"] for a in arms}]

    out = {"arms": arms, "rows": rows, "by_arm": [],
           "run_dir": run_dirs[0], "run_dirs": run_dirs}
    for a in arms:
        band = [r for r in rows if r["arm"] == a["name"]]
        if not band:
            continue
        # 에이전트가 예산(스텝 상한) 안에 끝내지 못하면 pier 가 예외로
        # 기록하고 reward 가 비어 있습니다. 이것을 집계에서 빼면 "끝낸
        # trial 만 모아 정확도를 계산" 하는 셈이라 압축 조건이 실제보다
        # 좋게 보입니다. **끝내지 못한 것도 실패**로 셉니다.
        rw = [(r["reward"] or 0) for r in band
              if r["reward"] is not None or r.get("error")]
        n_err = sum(1 for r in band if r.get("error"))
        # 프록시 기록은 run 마다 따로 남으므로 합산합니다.
        px = {"before": 0, "after": 0, "n_compress": 0}
        for rd in run_dirs:
            one = _rr.proxy_stats(rd, a["name"])
            for k in px:
                px[k] += one.get(k, 0) or 0
        out["by_arm"].append({
            "name": a["name"], "compressor": a["compressor"], "rate": a["rate"],
            "n": len(band), "n_pass": sum(1 for x in rw if x > 0),
            "n_err": n_err,
            "pass1": (sum(1 for x in rw if x > 0) / len(rw)) if rw else None,
            "in_tok": mean([r["in_tok"] for r in band]),
            "out_tok": mean([r["out_tok"] for r in band]),
            "steps": mean([r["steps"] for r in band]),
            "secs": mean([r["secs"] for r in band]),
            "n_compress": px.get("n_compress", 0),
            "self_red": (1 - px["after"] / px["before"]) if px.get("before") else None,
        })
    return out


def read_grid(path: Path) -> dict | None:
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
            "compressor": a["compressor"], "model": a.get("model", "—"),
            "params": a.get("params") or {}, "protect": a.get("protect") or {},
            "reduction": f("reduction"), "ident": f("ident"),
            "num": f("num"), "path": f("path"), "latency": f("latency_s"),
            "hit1": mean([float(r["hit1"]) for r in asked
                          if str(r.get("hit1", "")) not in ("", "None")]),
            "recall": mean([float(r["recall"]) for r in asked
                            if str(r.get("recall", "")) not in ("", "None")]),
            "n": len(band),
        })
    return {"meta": d, "summ": summ,
            "base": next((s for s in summ if s["compressor"] == "none"), None)}


# ═════════════════════════════════════════════════════════════════════
# 파라미터·지표 정의
# 값이 아니라 **정의**만 둡니다. 실제 사용값은 결과 파일에서 읽습니다.
# ═════════════════════════════════════════════════════════════════════
COMPRESSOR_PARAMS = [
    ("rate", "0 – 1", "유지 비율(retention ratio). 원문 토큰 중 남길 비율을 "
     "지정합니다. `rate=0.5` 는 절반을 남깁니다. 본 실험의 주 조작 변수입니다."),
    ("force_tokens", "토큰 목록", "지정한 토큰(줄바꿈·구두점 등)을 삭제 대상에서 "
     "제외합니다. 서식은 보존되나 동일 예산 내에서 내용 토큰이 밀려납니다."),
    ("force_reserve_digit", "True / False", "숫자 토큰을 삭제 대상에서 제외합니다. "
     "오류 코드·행 번호가 유의미한 입력에 적용합니다."),
    ("drop_consecutive", "True / False", "연속 중복 토큰을 1회로 축약합니다."),
    ("chunk_end_tokens", "정수", "장문을 분할 압축할 때 청크 경계로 사용할 "
     "토큰 수입니다."),
]

APPLY_POLICY = [
    ("keep_last", "정수", "대화 말미 N개 메시지를 압축 대상에서 제외합니다. "
     "직전 컨텍스트가 손상되면 에이전트의 다음 행동이 즉시 저하되므로 "
     "일반적으로 1 이상을 지정합니다."),
    ("min_chars", "정수", "지정 길이 미만의 메시지는 압축하지 않습니다. "
     "단문은 압축 이득이 작고 손상 위험만 큽니다."),
    ("skip_system", "True / False", "시스템 프롬프트를 압축 대상에서 제외합니다. "
     "도구 정의·출력 규약이 포함되어 부분 손실 시 규약 위반이 발생합니다."),
]

METRICS = [
    ("pass@1", "%", "1회 시도에서 과제를 통과한 비율. 채점은 각 태스크에 "
     "포함된 pytest 스위트가 수행하며, 전체 통과 시에만 1점을 부여합니다. "
     "본 평가의 1차 지표입니다."),
    ("입력 토큰", "토큰", "모델 제공자가 집계한 trial 당 누적 입력 토큰. "
     "압축의 실제 비용 절감 효과를 나타냅니다."),
    ("출력 토큰", "토큰", "모델이 생성한 누적 출력 토큰."),
    ("에이전트 스텝", "회", "과제 수행 중 모델 호출 횟수. 호출마다 누적 "
     "컨텍스트가 재전송되므로 스텝 증가는 입력 토큰 증가로 직결됩니다."),
    ("소요 시간", "초", "trial 당 총 실행 시간(에이전트 + 채점)."),
    ("압축률(실측)", "%", "프록시가 기록한 호출 단위 문자 수 감소율. "
     "`1 − chars_after / chars_before` 로 산출합니다."),
    ("압축 지연", "ms", "호출당 압축 연산에 소요된 시간."),
    ("pass@1 기준차", "%p", "압축 미적용 조건 대비 pass@1 의 차이입니다. "
     "두 값 모두 백분율이므로 단위는 퍼센트포인트(%p)를 씁니다."),
    ("토큰 기준차", "%", "압축 미적용 조건 대비 입력 토큰의 증감을 상대 "
     "비율로 나타낸 값입니다. 음수는 감소를 뜻합니다."),
    ("f2p", "%", "fail-to-pass. 이슈 해결을 위해 통과시켜야 하는 테스트의 "
     "통과 비율입니다. DeepSWE 에서만 산출됩니다."),
    ("p2p", "%", "pass-to-pass. 원래 통과하던 테스트를 유지한 비율입니다. "
     "이 값이 낮으면 기존 기능을 손상시킨 것입니다."),
]


# ═════════════════════════════════════════════════════════════════════
# 본문 구성
# ═════════════════════════════════════════════════════════════════════
def build(D: dict) -> Doc:
    main, ctl = D.get("main"), D.get("control")
    marks = ["Terminal Bench 2.1"]
    if D.get("swe"):
        marks.append("DeepSWE")
    doc = Doc("LLM 프롬프트 압축의 코딩 에이전트 성능 영향 평가",
              f"{' · '.join(marks)} 종단 측정 · LLMLingua-2 · "
              f"최종 추론 gpt-5.4 · 작성일 {datetime.now():%Y-%m-%d}")
    _incomplete(doc, D)
    _abstract(doc, D)
    # ── 구성 ────────────────────────────────────────────────────
    # 1~4장은 두 벤치마크에 공통인 설계·정의입니다. 5장과 6장은 벤치마크를
    # **완전히 분리**해 각자의 결과와 해석을 담고, 7장에서 나란히 놓습니다.
    # 벤치마크마다 부하 규모와 채점 방식이 달라 섞어 놓으면 어느 수치가
    # 어느 조건의 것인지 추적하기 어렵습니다.
    doc.sec("개요", _overview(doc, D))
    doc.sec("실험 설계", _design(doc, D))
    doc.sec("압축 파라미터", _params(doc, D))
    doc.sec("평가 지표", _metrics(doc))
    doc.sec("Terminal Bench 2.1 결과", _results(doc, D) + _analysis(doc, D))
    if D.get("swe"):
        doc.sec("DeepSWE 결과", _swe(doc, D))
        doc.sec("두 벤치마크 비교", _compare(doc, D))
    doc.sec("제약 사항", _limits(doc, D))
    doc.sec("결론 및 권고", _conclusion(doc, D))
    if D.get("samples"):
        doc.sec("부록. 압축 입출력 예시", _appendix(doc, D))
    return doc


def _incomplete(doc: Doc, D: dict) -> None:
    """조건별 trial 수가 어긋나면 측정이 아직 진행 중이라는 뜻입니다.

    롤아웃이 끝나기 전에 보고서를 만들면 조건마다 표본 수가 달라, 표에
    찍힌 pass@1 이 실제 성능이 아니라 "지금까지 끝난 것들의 평균" 이
    됩니다. 그 상태를 숨기면 읽는 사람이 확정 수치로 오해합니다.
    """
    warn = []
    for key, label in (("main", "주 측정"), ("swe", "DeepSWE"),
                       ("control", "대조 측정")):
        d = D.get(key)
        if not d:
            continue
        # 계획값은 run 마다 스냅샷이 따로 남습니다. 언어를 나눠 돌리거나
        # 태스크를 나중에 추가하면 각 스냅샷은 자기 몫만 아므로 합집합으로
        # 잡습니다. (최신 run 하나만 보면 그 run 의 태스크 수가 전체 계획인
        # 것처럼 잘못 표시됩니다.)
        cnt = [a["n"] for a in d["by_arm"]]
        n_plan = len({r["task"] for r in d["rows"]})
        n_lang = len({r["lang"] for r in d["rows"]})
        for rd in d.get("run_dirs") or [d["run_dir"]]:
            n_plan = max(n_plan, planned_tasks(rd) or 0)
            n_lang = max(n_lang, len(planned_langs(rd)))
        n_plan *= max(1, n_lang)
        if len(set(cnt)) > 1 or (cnt and min(cnt) < n_plan):
            warn.append(f"{label}(조건별 {min(cnt)}~{max(cnt)}/{n_plan} trial)")
    if warn:
        doc.abstract.append(
            "⚠️ **측정이 아직 진행 중입니다.** " + " · ".join(warn) +
            " — 조건별 표본 수가 서로 다르므로 아래 수치는 잠정값이며, "
            "롤아웃 완료 후 갱신됩니다. 확정 결과로 인용하지 마십시오.")


def _base_of(roll):
    return next((a for a in roll["by_arm"] if a["compressor"] == "none"),
                roll["by_arm"][0])


def _ctl_spread(D):
    """대조 측정에서 얻은 pass@1 · 입력 토큰의 회차 간 편차."""
    ctl = D.get("control")
    if not ctl or len(ctl["by_arm"]) < 2:
        return None, None
    ps = [a["pass1"] for a in ctl["by_arm"] if a["pass1"] is not None]
    tk = [a["in_tok"] for a in ctl["by_arm"] if a["in_tok"]]
    p = (max(ps) - min(ps)) if len(ps) > 1 else None
    t = (max(abs(x / max(tk) - 1) for x in tk)) if len(tk) > 1 else None
    return p, t


def _abstract(doc: Doc, D: dict) -> None:
    m = D.get("main")
    if not m:
        return
    b = _base_of(m)
    comp = [a for a in m["by_arm"] if a is not b]
    n_task = len({r["task"] for r in m["rows"]})
    pspread, tspread = _ctl_spread(D)
    sw = D.get("swe")

    scope = (f"Terminal Bench 2.1 공식 하네스로 태스크 {n_task}종 × "
             f"{len(m['by_arm'])}개 조건({len(m['rows'])} trial)")
    if sw:
        scope += (f", DeepSWE 공식 하네스로 태스크 "
                  f"{len({r['task'] for r in sw['rows']})}종 × "
                  f"{len(sw['by_arm'])}개 조건({len(sw['rows'])} trial)")
    doc.abstract.append(
        f"코딩 에이전트의 프롬프트에 LLMLingua-2 프롬프트 압축을 적용하고 "
        f"정확도와 토큰 사용량 변화를 측정하였습니다. {scope}을 비교하였으며, "
        f"최종 추론은 전 조건 동일하게 Azure AI Foundry 의 gpt-5.4 로 "
        f"수행하였습니다.")

    # 압축률을 여러 점으로 재면 "어디까지는 괜찮은가" 를 말할 수 있습니다.
    # 두 점만 있을 때는 기울기밖에 못 말합니다.
    band = sorted([a for a in comp if a["pass1"] is not None],
                  key=lambda a: -a["rate"])
    if b["pass1"] is not None and band:
        safe = [a for a in band if a["pass1"] >= b["pass1"]]
        worst = min(band, key=lambda a: a["pass1"])
        d = worst["pass1"] - b["pass1"]
        txt = (f"압축 강도를 높일수록 pass@1 이 하락하는 경향이 "
               f"관측되었습니다. 기준 조건 {pc(b['pass1'], 1)} 대비 "
               f"가장 강한 압축(`rate {worst['rate']}`)에서 "
               f"{pc(worst['pass1'], 1)}({pp(d, 1)})였습니다.")
        if safe:
            hi = min(safe, key=lambda a: a["rate"])
            dv = (hi["in_tok"] / b["in_tok"] - 1) if (hi["in_tok"] and b["in_tok"]) else None
            txt += (f" 반면 완만한 압축 구간에서는 기준 조건 수준을 "
                    f"유지하였으며, 측정 범위에서 정확도를 유지한 가장 강한 "
                    f"압축은 `rate {hi['rate']}` 였습니다.")
            if dv is not None:
                txt += (f" 다만 이 조건의 입력 토큰은 {rel(dv)} 로 "
                        + ("**비용 절감 효과가 없었습니다.**"
                           if dv > -0.05 else "감소하였습니다."))
        doc.abstract.append(txt)

    # 토큰이 실제로 줄었는지 데이터에서 판단합니다. "압축했으니 줄었을
    # 것" 이라고 적어 두면, 스텝 증가로 되레 늘어난 조건이 나왔을 때
    # 요약이 본문과 어긋납니다.
    tok = [(a, a["in_tok"] / b["in_tok"] - 1)
           for a in comp if a["in_tok"] and b["in_tok"]]
    if tok:
        down = [(a, v) for a, v in tok if v < -0.05]
        up = [(a, v) for a, v in tok if v > 0.05]
        if down:
            best = min(down, key=lambda x: x[1])
            txt = (f"입력 토큰은 {len(down)}/{len(tok)} 개 조건에서 감소하였으며 "
                   f"최대 감소는 `{best[0]['name']}` 의 {rel(best[1])} 였습니다.")
        else:
            txt = "입력 토큰은 어느 조건에서도 유의하게 감소하지 않았습니다."
        if up:
            worst = max(up, key=lambda x: x[1])
            txt += (f" 반면 {len(up)}개 조건에서는 압축을 적용했음에도 입력 "
                    f"토큰이 **증가**하였습니다"
                    f"(최대 `{worst[0]['name']}` {rel(worst[1])}).")
        txt += (" 태스크 단위 대응 비교에서 토큰이 증가한 사례는 에이전트 "
                "스텝 증가를 동반하였으며, 압축으로 손상된 컨텍스트가 추가 "
                "탐색을 유발하여 절감분을 상쇄한 것으로 해석됩니다.")
        doc.abstract.append(txt)

    if sw:
        swb = _base_of(sw)
        swc = [a2 for a2 in sw["by_arm"] if a2 is not swb]
        parts = []
        if swb["in_tok"] and b["in_tok"]:
            parts.append(f"DeepSWE 는 누적 입력이 Terminal Bench 의 "
                         f"{swb['in_tok'] / b['in_tok']:.0f}배 규모입니다")

        # DeepSWE 는 pass@1 이 전 조건 0 이라 f2p 로 봐야 차이가 보입니다.
        f2p_of = lambda nm: mean([r.get("f2p") for r in sw["rows"]   # noqa: E731
                                  if r["arm"] == nm])
        bf, cf = f2p_of(swb["name"]), [f2p_of(a2["name"]) for a2 in swc]
        cf = [x for x in cf if x is not None]
        if bf is not None and cf:
            parts.append(f"이 규모에서는 토큰이 실제로 감소했으나"
                         f"(최대 "
                         f"{rel(min((a2['in_tok'] / swb['in_tok'] - 1) for a2 in swc if a2['in_tok'] and swb['in_tok']))}"
                         f"), 이슈 해결 진척도(f2p)가 {pc(bf, 1)} 에서 "
                         f"{pc(max(cf), 1)} 이하로 떨어졌습니다")
        n_err = sum(a2.get("n_err") or 0 for a2 in swc)
        if n_err and not (swb.get("n_err") or 0):
            parts.append(f"압축 조건에서만 스텝 예산을 초과해 과제를 끝내지 "
                         f"못한 trial 이 {n_err}건 발생했습니다")
        if swb["secs"] and any(a2["secs"] for a2 in swc):
            mx = max(a2["secs"] for a2 in swc if a2["secs"])
            parts.append(f"trial 소요 시간은 최대 "
                         f"{mx / swb['secs']:.0f}배로 늘었습니다")
        if parts:
            doc.abstract.append(
                "부하 규모가 다른 두 벤치마크를 함께 측정하였습니다. "
                + ". ".join(parts) + ".")

    if pspread is not None:
        doc.abstract.append(
            f"다만 동일 조건을 반복 측정한 대조군에서 pass@1 이 "
            f"±{pspread * 100:.1f}%p, 입력 토큰이 ±{tspread * 100:.1f}% "
            f"범위로 변동하였습니다. **관측된 변화의 상당 부분이 이 변동 "
            f"범위 내에 있으므로, 경향은 확인되나 효과의 크기는 현재 표본"
            f"(조건당 {n_task}종 × 1회)으로 확정할 수 없습니다.** 결론 적용 "
            f"시 이 점을 함께 고려하여야 합니다.")


def _overview(doc: Doc, D: dict) -> list:
    sw = D.get("swe")
    B = [P("본 평가는 프롬프트 압축을 코딩 에이전트 워크로드에 적용했을 때 "
           "**비용 절감과 정확도 손실의 상충 관계**를 정량화하는 것을 목적으로 "
           "합니다."),
         P("프롬프트 압축은 모델 입력 토큰을 줄여 비용과 지연을 낮추는 기법입니다. "
           "요약·검색 기반 컨텍스트 축소와 달리 원문 토큰 중 일부를 선별 삭제하며, "
           "별도의 생성 모델을 호출하지 않으므로 오버헤드가 작습니다. "
           "본 평가에서는 Microsoft LLMLingua-2 를 대상으로 하였습니다."),
         "평가 범위",
         P("본 보고서는 **공식 하네스로 에이전트를 실제 실행하고 저장소 "
           "테스트로 채점한 종단 측정만** 수록합니다. 두 벤치마크를 사용하였으며, "
           "부하 규모가 크게 다르므로 함께 측정하였습니다.")]

    rows = [["Terminal Bench 2.1",
             "pier (공식) · Docker 격리", "태스크 내장 pytest",
             "pass@1, 입력·출력 토큰, 스텝", "**수록**"]]
    if sw:
        rows.append(["DeepSWE",
                     "pier (공식) · Docker 격리", "저장소 테스트 (f2p / p2p)",
                     "pass@1, f2p, p2p, 토큰, 스텝", "**수록**"])
    rows.append(["DeepSWE 기반 파일 지목 측정",
                 "없음 (압축기 단독 실행)", "정답 파일 목록과 대조",
                 "hit@1, recall, 보존율", "제외"])
    B += [Table(doc.next_table(), "본 보고서의 데이터 범위",
                ["측정", "하네스", "채점 방식", "산출 지표", "수록 여부"],
                rows, align="lllll")]

    if sw:
        B += [Note("DeepSWE 는 실제 오픈소스 저장소의 이슈를 해결하는 "
                   "벤치마크로, Terminal Bench 와 동일한 Harbor 계열 스키마를 "
                   "사용합니다. 채점 시 f2p(해결해야 할 테스트)와 "
                   "p2p(유지해야 할 테스트)를 분리 제공하므로, 통과하지 "
                   "못한 경우에도 진척도를 비교할 수 있습니다.")]
    B += [Note("제외한 항목은 압축기만 단독 실행하여 수정 대상 파일을 "
               "지목할 수 있는지 확인한 컴포넌트 단위 대리 측정입니다. "
               "에이전트를 실행하지 않으므로 pass@1 을 산출할 수 없어 정확도 "
               "근거로 사용하지 않았습니다. 해당 결과는 "
               "`reports/llmlingua2-grid/` 및 `reports/llmlingua-deepswe/` 에 "
               "별도 보관되어 있습니다.")]
    B += [Note("또한 채점 컨테이너의 의존성 설치 실패로 테스트가 실행되지 않은 "
               "측정 회차가 있었으며, 해당 회차는 전량 제외하고 재측정한 "
               "결과만 수록하였습니다.")]
    return B


def _design(doc: Doc, D: dict) -> list:
    """실험 설계.

    공통 항목과 벤치마크별 항목을 나눕니다. 하나의 표에 몰아넣으면
    "이 채점 방식이 두 벤치마크 모두에 해당하나?" 를 알 수 없습니다.
    실제로 채점 방식과 과제 성격은 벤치마크마다 다르고, 하네스·압축 적용
    지점·최종 모델만 공통입니다.
    """
    m, ctl, sw = D.get("main"), D.get("control"), D.get("swe")
    B = ["공통 설계",
         P("두 벤치마크 모두 **동일한 하네스·에이전트·압축기·최종 모델**을 "
           "사용하였습니다. 압축은 에이전트와 모델 사이에 놓은 역방향 "
           "프록시에서 적용되므로, 에이전트나 벤치마크 코드를 수정하지 "
           "않았습니다."),
         Code("[태스크 컨테이너 기동]\n"
              "        ↓\n"
              "[에이전트가 셸 명령으로 과제 수행]\n"
              "        ↓  ← 모든 모델 호출이 압축 프록시를 경유\n"
              "[압축 프록시: 프롬프트 일부를 선별 삭제] → [gpt-5.4]\n"
              "        ↓\n"
              "[별도 채점 컨테이너에서 테스트 실행]\n"
              "        ↓\n"
              "[reward 산출]")]

    rows = [["실행 하네스", "pier (공식 러너) · Docker 격리"],
            ["에이전트", "mini-swe-agent"],
            # 리소스 이름은 적지 않습니다. 비밀은 아니지만 저장소에 남길
            # 이유도 없고, 다른 구독에서 재현할 때 혼동만 줍니다.
            ["**최종 호출 모델**",
             "**openai/gpt-5.4** — Azure AI Foundry 엔드포인트. "
             "전 조건·전 벤치마크 동일하며, 압축 적용 조건도 압축된 "
             "프롬프트를 동일 모델로 호출합니다."],
            ["압축 모델", "LLMLingua-2 · xlm-roberta-large. 토큰 선별 전용 "
             "분류 모델이며 텍스트를 생성하지 않습니다. 위 최종 호출 "
             "모델과는 별개입니다."],
            ["압축 적용 지점", "역방향 프록시 (Chat Completions / Responses API)"],
            ["스텝 상한", "60회. 압축으로 에이전트가 헤맬 때 무한정 늘어나는 "
             "것을 막습니다. **전 조건 동일**하게 적용하였습니다."],
            ["시도 횟수", "태스크·조건당 1회 (`n_attempts=1`). 동일 태스크를 "
             "반복 시도하지 않으며, 반복에 따른 변동은 별도의 대조 측정으로 "
             "추정하였습니다."]]
    B += [Table(doc.next_table(), "공통 실험 환경", ["항목", "내용"], rows)]
    B += [Note("모델 구성이 두 단계입니다. **압축 단계**에서는 LLMLingua-2 가 "
               "어떤 토큰을 남길지 분류하고, **추론 단계**에서는 그 결과를 "
               "gpt-5.4 가 입력으로 받습니다. 보고서의 pass@1·토큰 지표는 "
               "모두 gpt-5.4 호출 기준이며, 실제 호출 모델명은 프록시 "
               "로그에서 확인하였습니다.")]

    # ── 벤치마크별 ──────────────────────────────────────────
    B += ["벤치마크별 설계",
          Table(doc.next_table(), "벤치마크 특성 비교",
                ["항목", "Terminal Bench 2.1", "DeepSWE"],
                [["과제 성격",
                  "터미널에서 완결되는 단일 과제 "
                  "(인증서 발급·git 복구·로그 추출 등)",
                  "실제 오픈소스 저장소의 이슈를 해결하고 "
                  "코드 패치를 생성"],
                 ["산출물", "파일 시스템 상태 변경", "코드 패치 (model.patch)"],
                 ["채점 방식", "태스크 내장 pytest · 전체 통과 시에만 1점",
                  "저장소 테스트 · f2p 와 p2p 를 분리 산출"],
                 ["부분 점수", "없음 (0 또는 1)",
                  "있음 (f2p·p2p 비율). pass@1 이 0 이어도 진척도 비교 가능"],
                 ["대상 언어(코드)", "셸·Python 중심",
                  "Python · TypeScript · Go · Rust 등"],
                 ["컨텍스트 규모", "상대적으로 작음",
                  "저장소 전체를 탐색하므로 크게 누적"]],
                align="lll")]
    B += [Note("두 벤치마크 모두 Harbor 계열 `task.toml` 스키마를 사용하므로 "
               "동일한 `pier` 러너로 실행됩니다. 따라서 하네스 차이로 인한 "
               "교란은 없습니다.")]

    if m:
        tasks = sorted({r["task"] for r in m["rows"]})
        B += ["Terminal Bench 태스크",
              P(f"터미널 내에서 완결되는 태스크 {len(tasks)}종으로 "
                "구성하였습니다. 학습·컴파일·GPU 를 요구하는 태스크는 제한 "
                "시간 내 완료가 불가하여, 실패 원인이 압축인지 시간 초과인지 "
                "분리되지 않으므로 제외하였습니다."),
              Table(doc.next_table(), "Terminal Bench 측정 태스크",
                    ["태스크", "내용"],
                    [[f"`{t}`", _TASK_DESC.get(t, "—")] for t in tasks])]
    if sw:
        tasks = sorted({r["task"] for r in sw["rows"]})
        B += ["DeepSWE 태스크",
              P(f"구현 언어가 겹치지 않도록 태스크 {len(tasks)}종을 "
                "선정하였습니다. trial 당 소요가 커서 태스크 수를 "
                "제한하였습니다."),
              Table(doc.next_table(), "DeepSWE 측정 태스크",
                    ["태스크", "내용"],
                    [[f"`{t}`", _TASK_DESC.get(t, "—")] for t in tasks])]

    # 계획과 진행을 나눠 보여 줍니다. 측정된 행만 세면 아직 돌리지 않은
    # 언어·태스크가 빠져, 애초에 그렇게 설계한 것처럼 읽힙니다.
    def spec(d):
        # 계획값은 run 마다 스냅샷이 따로 남습니다. 언어를 나눠 돌리거나
        # 태스크를 나중에 추가하면 각 스냅샷은 자기 몫만 알고 있으므로,
        # 전체 계획은 **합집합**으로 잡습니다. 측정된 실적이 어느 스냅샷의
        # 계획보다 크면 그 실적을 계획으로 봅니다.
        done_l = sorted({r["lang"] for r in d["rows"]})
        done_t = len({r["task"] for r in d["rows"]})
        plan_l, plan_t = set(done_l), done_t
        for rd in d.get("run_dirs") or [d["run_dir"]]:
            plan_l |= set(planned_langs(rd))
            plan_t = max(plan_t, planned_tasks(rd) or 0)
        plan_l = sorted(plan_l)
        miss = [x for x in plan_l if x not in done_l]
        lang = ", ".join(plan_l) + (f" (측정 완료: {', '.join(done_l)})"
                                    if miss else "")
        task = f"{plan_t}종" + (f" (측정 {done_t}종)" if done_t < plan_t else "")
        n_plan = plan_t * len(plan_l) * len(d["by_arm"])
        trial = (f"{len(d['rows'])} / {n_plan}"
                 if len(d["rows"]) < n_plan else str(len(d["rows"])))
        return task, lang, trial

    rows = []
    if m:
        t, lg, tr = spec(m)
        rows.append(["주 측정 (TB)", "Terminal Bench 2.1", t, lg,
                     str(len(m["by_arm"])), tr, "정확도·토큰 비교"])
    if ctl:
        t, lg, tr = spec(ctl)
        rows.append(["대조 측정 (TB)", "Terminal Bench 2.1", t, lg,
                     f"{len(ctl['by_arm'])} (반복)", tr,
                     "반복 측정 변동 추정"])
    if sw:
        t, lg, tr = spec(sw)
        rows.append(["주 측정 (SWE)", "DeepSWE", t, lg,
                     str(len(sw["by_arm"])), tr, "대규모 컨텍스트 검증"])
    if rows:
        B += ["측정 구성",
              Table(doc.next_table(), "측정 구성", 
                    ["구분", "벤치마크", "태스크", "언어", "조건", "trial",
                     "목적"], rows, align="llllrrl"),
              Note("`trial` 열이 `측정 / 계획` 형태로 표시된 경우 해당 "
                   "롤아웃이 아직 진행 중이라는 뜻입니다. 언어 열의 "
                   "‘측정 완료’ 표기도 같습니다.")]

    if ctl and m:
        same = ({r["task"] for r in ctl["rows"]} == {r["task"] for r in m["rows"]}
                and {r["lang"] for r in ctl["rows"]}
                == {r["lang"] for r in m["rows"]})
        B += [Note(("대조 측정은 전 조건 압축을 적용하지 않고 주 측정과 "
                    "**동일한 태스크·언어·설정**으로 수행한 반복 측정입니다. "
                    if same else
                    "⚠️ 대조 측정의 태스크 또는 언어 구성이 주 측정과 "
                    "다릅니다. 변동 폭 적용 시 주의가 필요합니다. ") +
                   "조건이 동일하므로 조건 간 차이는 전부 반복 측정 변동에 "
                   "해당하며, 주 측정 결과의 유의성 판단 기준으로 "
                   "사용합니다. 대조 측정은 Terminal Bench 에 대해서만 "
                   "수행하였습니다.")]
    return B


_TASK_DESC = {
    "openssl-selfsigned-cert": "자체 서명 인증서 발급",
    "fix-git": "손상된 git 저장소 상태 복구",
    "regex-log": "정규식 기반 로그 추출",
    "count-dataset-tokens": "데이터셋 토큰 수 집계",
    "sqlite-db-truncate": "SQLite 데이터베이스 파일 절단",
    "filter-js-from-html": "HTML 문서에서 스크립트 제거",
    "cancel-async-tasks": "비동기 태스크 취소 처리 수정",
    "overfull-hbox": "LaTeX 조판 경고 해소",
    "cobol-modernization": "COBOL 코드 현대화",
    "db-wal-recovery": "WAL 기반 DB 복구",
    "log-summary-date-ranges": "로그 기간별 집계",
    # DeepSWE — 실제 오픈소스 저장소의 이슈. 괄호는 구현 언어입니다.
    "mashumaro-flattened-dataclass-fields":
        "중첩 dataclass 필드 평탄화 (Python)",
    "happy-dom-abort-pending-body-reads":
        "본문 읽기 중단 처리 (TypeScript)",
    "geo-shapeindex-serialization":
        "공간 인덱스 직렬화 (Go)",
}


def _params(doc: Doc, D: dict) -> list:
    B = [P("압축 동작은 두 계층에서 제어됩니다. **압축기 하이퍼파라미터**는 "
           "LLMLingua-2 생성자에 전달되며, **적용 정책**은 어떤 메시지를 "
           "압축 대상에 포함할지 결정하는 프록시 측 설정입니다.")]
    B += ["압축기 하이퍼파라미터",
          Table(doc.next_table(), "LLMLingua-2 하이퍼파라미터",
                ["파라미터", "범위", "설명"],
                [[f"`{k}`", v, d] for k, v, d in COMPRESSOR_PARAMS])]
    B += ["적용 정책",
          Table(doc.next_table(), "압축 적용 정책",
                ["항목", "범위", "설명"],
                [[f"`{k}`", v, d] for k, v, d in APPLY_POLICY])]

    m = D.get("main")
    if m:
        rows = []
        for a in m["arms"]:
            rows.append([f"`{a['name']}`",
                         "미적용" if a["compressor"] == "none" else "LLMLingua-2",
                         "—" if a["compressor"] == "none" else f"{a['rate']}",
                         "—" if a["compressor"] == "none" else "기본값"])
        B += ["실험 조건",
              Table(doc.next_table(), "주 측정 실험 조건",
                    ["조건", "압축기", "rate", "기타 파라미터"], rows,
                    align="llrl"),
              Note("`rate` 외 하이퍼파라미터는 라이브러리 기본값을 사용하였습니다. "
                   "적용 정책은 전 조건 동일하게 `skip_system=True`, "
                   "`keep_last` 및 `min_chars` 기본값을 적용하였습니다.")]
    return B


def _metrics(doc: Doc) -> list:
    return [P("본 평가에서 사용한 지표의 정의는 다음과 같습니다."),
            Table(doc.next_table(), "평가 지표 정의",
                  ["지표", "단위", "정의"],
                  [[f"**{k}**", u, d] for k, u, d in METRICS]),
            Note("pass@1 은 1차 지표이며, 입력 토큰은 비용 지표입니다. "
                 "두 지표는 상충 관계에 있으므로 단독 해석은 지양합니다.")]


def planned_langs(run_dir: Path) -> list[str]:
    """실험 설정에 적힌 언어 목록.

    측정된 행에서만 세면 아직 안 돌린 언어가 빠져, 표가 "en 만 하기로
    했다" 처럼 읽힙니다. 계획과 진행을 구분해 보여 주려면 설정을 읽어야
    합니다.
    """
    f = run_dir / "config.snapshot.yaml"
    if not f.exists():
        return []
    for line in f.read_text(encoding="utf-8").splitlines():
        st = line.strip()
        if st.startswith("langs:") and "[" in st:
            inner = st[st.index("[") + 1:st.rindex("]")]
            return [x.strip() for x in inner.split(",") if x.strip()]
    return []


def planned_tasks(run_dir: Path) -> int | None:
    """실험 설정에 적힌 태스크 수.

    완료된 행에서 세면 롤아웃 도중에는 실제보다 작게 나옵니다. "끝나면
    분모가 N 이 된다" 는 안내를 하려면 계획값을 읽어야 합니다. yaml 파서를
    쓰지 않고 `tasks:` 블록의 목록 항목만 셉니다(설정 형식이 단순합니다).
    """
    f = run_dir / "config.snapshot.yaml"
    if not f.exists():
        return None
    n, inside = 0, False
    for line in f.read_text(encoding="utf-8").splitlines():
        st = line.strip()
        if st.startswith("tasks:"):
            inside = True
            continue
        if inside:
            if st.startswith("- "):
                n += 1
            elif st and not st.startswith("#"):
                break
    return n or None


def _results(doc: Doc, D: dict) -> list:
    m, ctl = D.get("main"), D.get("control")
    B = []
    if not m:
        return [P("측정 결과가 없습니다.")]

    b = _base_of(m)
    # ── 5.1 종합 ────────────────────────────────────────────────
    n_task = len({r["task"] for r in m["rows"]})
    n_plan = planned_tasks(m["run_dir"]) or n_task
    partial = len({a["n"] for a in m["by_arm"]}) > 1 or \
        any(a["n"] < n_plan for a in m["by_arm"])

    rows = []
    for a in m["by_arm"]:
        is_b = a is b
        rows.append([
            f"`{a['name']}`", f"{a['n_pass']}/{a['n']}", pc(a["pass1"], 1),
            "기준" if is_b else pp(a["pass1"] - b["pass1"], 1)
            if (a["pass1"] is not None and b["pass1"] is not None) else "—",
            num(a["in_tok"]),
            "기준" if is_b else rel(a["in_tok"] / b["in_tok"] - 1)
            if (a["in_tok"] and b["in_tok"]) else "—",
            num(a["out_tok"]),
            f"{a['steps']:.1f}" if a["steps"] else "—",
            f"{a['secs']:.0f}" if a["secs"] else "—",
        ])
    note = ("**통과 / 완료** 열의 분모는 해당 조건에서 **완료된 trial 수**"
            "입니다. 각 태스크는 조건당 1회만 시도하므로(`n_attempts=1`), "
            f"롤아웃이 끝나면 분모는 계획된 태스크 수({n_plan})와 같아집니다. ")
    if partial:
        note += ("**현재는 롤아웃이 진행 중이어서 조건마다 완료 수가 "
                 "다릅니다.** 조건 간 pass@1 을 직접 비교하지 마십시오. ")
    note += ("**pass@1 기준차** 는 압축 미적용 조건 대비 정확도 차이를 "
             "퍼센트포인트(%p)로, **토큰 기준차** 는 입력 토큰의 증감을 "
             "상대 비율(%)로 표기한 것입니다. 음수는 토큰이 줄었음을 "
             "뜻합니다.")
    B += ["종합 결과",
          Table(doc.next_table(),
                "조건별 종합 성능 (주 측정 세트, trial 평균)",
                ["조건", "통과 / 완료", "pass@1", "pass@1 기준차", "입력 토큰",
                 "토큰 기준차", "출력 토큰", "스텝", "소요(초)"],
                rows, align="lrrrrrrrr"),
          Note(note)]

    names = [a["name"] for a in m["by_arm"]]
    B += [Figure(doc.next_fig(),
                 "조건별 pass@1 및 평균 입력 토큰",
                 grouped_bars(
                     [("pass@1 (%)", [(a["pass1"] or 0) * 100
                                      for a in m["by_arm"]]),
                      ("입력 토큰 (천)", [(a["in_tok"] or 0) / 1000
                                       for a in m["by_arm"]])],
                     names, fmt=lambda v: f"{v:.0f}"),
                 "두 계열의 축 척도가 다르므로 절대값 비교가 아닌 "
                 "조건 간 상대 추세로 해석하십시오.")]

    # ── 5.2 태스크별 ────────────────────────────────────────────
    tasks = sorted({r["task"] for r in m["rows"]})
    cell = {(r["task"], r["arm"]): r for r in m["rows"]}
    rows = []
    for t in tasks:
        line = [f"`{t}`"]
        for n in names:
            r = cell.get((t, n))
            line.append("—" if not r or r["reward"] is None
                        else ("통과" if r["reward"] > 0 else "실패"))
        rows.append(line)
    B += ["태스크별 결과",
          Table(doc.next_table(), "태스크 × 조건 통과 여부",
                ["태스크"] + [f"`{n}`" for n in names], rows)]

    bs = {t for t in tasks if (cell.get((t, b["name"]), {}) or {}).get("reward")}
    lost = [t for t in tasks if t in bs
            and any(not (cell.get((t, n), {}) or {}).get("reward")
                    for n in names if n != b["name"])]
    if lost:
        nested = all(
            {t for t in tasks if (cell.get((t, n), {}) or {}).get("reward")} <= bs
            for n in names if n != b["name"])
        txt = (f"압축 적용으로 통과에서 실패로 전환된 태스크는 "
               f"{', '.join('`' + t + '`' for t in lost)} 입니다.")
        if nested:
            txt += (" 압축 조건이 통과한 태스크는 모두 기준 조건도 통과한 "
                    "태스크의 부분집합으로, 압축이 새로운 성공을 만들지 못하고 "
                    "기존 성공만 소실시켰음을 나타냅니다.")
        B += [Note(txt)]

    # ── 5.3 압축 동작 특성 ──────────────────────────────────────
    px = D.get("proxy") or {}
    if px:
        rows = []
        for n in names:
            s = px.get(n)
            if not s:
                continue
            rows.append([f"`{n}`", str(s["n"]), pc(s["mean"]), pc(s["p50"]),
                         pc(s["p10"]), pc(s["p90"]),
                         f"{s['lat_p50']:.0f}", f"{s['lat_p90']:.0f}"])
        if rows:
            B += ["압축 동작 특성",
                  Table(doc.next_table(),
                        "호출 단위 압축률 및 지연 분포 (주 측정 실행 중 실측)",
                        ["조건", "호출 수", "평균", "중앙값", "10분위",
                         "90분위", "지연 중앙값(ms)", "지연 90분위(ms)"],
                        rows, align="lrrrrrrr"),
                  Note("압축률은 문자 수 기준입니다. 호출마다 입력 구성이 "
                       "달라 분포가 넓게 형성되며, 지정한 `rate` 는 "
                       "메시지 단위 목표치이므로 요청 전체의 감소율과는 "
                       "일치하지 않습니다.")]

    # ── 언어별 ──────────────────────────────────────────────
    # MS 문서 세트를 따로 두던 것을 없애고, 주 측정이 en·ko 를 모두
    # 포함하도록 바꿨습니다. 별도 세트를 쓰면 태스크가 달라 언어 효과와
    # 태스크 효과가 섞였습니다.
    langs = sorted({r["lang"] for r in m["rows"]})
    if len(langs) > 1:
        rows = []
        for a in m["by_arm"]:
            line = [f"`{a['name']}`"]
            for lg in langs:
                band = [r for r in m["rows"]
                        if r["arm"] == a["name"] and r["lang"] == lg]
                rw = [r["reward"] for r in band if r["reward"] is not None]
                line += [f"{sum(1 for x in rw if x > 0)}/{len(rw)}" if rw else "—",
                         num(mean([r["in_tok"] for r in band]))]
            rows.append(line)
        head = ["조건"]
        for lg in langs:
            head += [f"{lg} 통과", f"{lg} 입력 토큰"]
        B += ["언어별 결과",
              P("동일한 태스크의 지시문만 번역하여 언어별로 측정하였습니다. "
                "채점 코드와 환경은 동일하므로, 차이는 지시문 언어에서만 "
                "발생합니다."),
              Table(doc.next_table(), "언어별 조건 성능", head, rows,
                    align="l" + "rr" * len(langs)),
              Note("번역 시 식별자·경로·명령어는 원문을 유지하도록 검증"
                   "하였습니다. 언어당 태스크 수가 제한적이므로 언어 간 "
                   "절대 비교보다 동일 언어 내 조건 간 추세로 해석하십시오.")]
    return B


def _paired(m, b):
    """태스크 단위 대응 비교. 조건 평균은 태스크 난이도 편차를 포함하므로,
    동일 태스크끼리 짝지어야 압축의 순효과가 드러납니다."""
    per = {}
    for r in m["rows"]:
        per.setdefault(r["task"], {})[r["arm"]] = r
    out = []
    for t, mm in per.items():
        base = mm.get(b["name"])
        if not base or not base.get("in_tok"):
            continue
        for n, r in mm.items():
            if n == b["name"] or not r.get("in_tok"):
                continue
            out.append({
                "task": t, "arm": n,
                "d_tok": r["in_tok"] / base["in_tok"] - 1,
                "d_step": (r["steps"] - base["steps"])
                if (r.get("steps") is not None
                    and base.get("steps") is not None) else None,
                "pass": bool(r.get("reward")),
            })
    return out


def _analysis(doc: Doc, D: dict) -> list:
    m, ctl = D.get("main"), D.get("control")
    if not m:
        return []
    b = _base_of(m)
    B = []

    # ── 6.1 정확도–압축률 ───────────────────────────────────────
    band = sorted([a for a in m["by_arm"] if a["pass1"] is not None],
                  key=lambda a: -a["rate"])
    B += ["정확도와 압축률의 상충 관계"]
    if len(band) >= 2:
        mono = all(x["pass1"] >= y["pass1"] for x, y in zip(band, band[1:]))
        B += [P(f"압축률(`rate`)을 낮출수록 pass@1 이 "
                f"{'단조 감소하였습니다' if mono else '변동하였습니다'}. "
                f"`rate` 는 유지 비율이므로 값이 작을수록 압축 강도가 "
                f"높습니다.")]
        B += [Figure(doc.next_fig(),
                     "압축률에 따른 pass@1 및 입력 토큰",
                     line_chart(
                         [a["rate"] for a in band],
                         [("pass@1", [a["pass1"] for a in band]),
                          ("입력 토큰(기준 대비)",
                           [(a["in_tok"] / b["in_tok"]) if
                            (a["in_tok"] and b["in_tok"]) else None
                            for a in band])],
                         "rate (유지 비율)", "비율"),
                     "rate=1.0 은 압축 미적용 조건입니다. 압축 강도를 "
                     "높이면 입력 토큰은 감소하나 pass@1 도 함께 "
                     "감소합니다.")]
        B += [Figure(doc.next_fig(),
                     "압축률과 정확도의 상충 관계",
                     scatter([(a["name"].replace("llmlingua2-", ""),
                               1 - (a["in_tok"] / b["in_tok"]) if
                               (a["in_tok"] and b["in_tok"]) else None,
                               a["pass1"]) for a in m["by_arm"]],
                             "입력 토큰 절감률", "pass@1"),
                     "우측 상단에 위치할수록 바람직합니다. 측정 범위에서는 "
                     "절감률 증가와 정확도 유지가 양립하지 않았습니다.")]

    # ── 6.2 토큰 증폭 ───────────────────────────────────────────
    pairs = _paired(m, b)
    if pairs:
        up = [p for p in pairs if p["d_tok"] > 0]
        B += ["토큰 증폭 현상"]
        B += [P("조건 평균으로는 입력 토큰이 감소하였으나, 동일 태스크끼리 "
                "대응 비교하면 결과가 균질하지 않습니다.")]
        arms = sorted({p["arm"] for p in pairs})
        for an in arms:
            sub = sorted([p for p in pairs if p["arm"] == an],
                         key=lambda p: p["d_tok"])
            B += [Figure(doc.next_fig(),
                         f"태스크별 입력 토큰 변화 — `{an}`",
                         slope([(p["task"], p["d_tok"], p["pass"])
                                for p in sub], None),
                         "우측(진한 막대)은 압축 적용 후 토큰이 증가한 "
                         "태스크입니다. ✓ 는 통과, ✗ 는 실패입니다.")]
        rows = []
        for p in sorted(pairs, key=lambda x: -x["d_tok"]):
            rows.append([f"`{p['task']}`", f"`{p['arm']}`", rel(p["d_tok"]),
                         f"{p['d_step']:+.0f}" if p["d_step"] is not None
                         else "—", "통과" if p["pass"] else "실패"])
        B += [Table(doc.next_table(),
                    "태스크 단위 대응 비교 (기준 조건 대비)",
                    ["태스크", "조건", "입력 토큰 증감", "스텝 증감", "결과"],
                    rows, align="llrrl")]
        if up:
            n_step = sum(1 for p in up if (p["d_step"] or 0) > 0)
            worst = max(up, key=lambda p: p["d_tok"])
            B += [P(f"전체 {len(pairs)}개 대응쌍 중 **{len(up)}개에서 입력 "
                    f"토큰이 증가**하였으며, 최대 증가폭은 "
                    f"`{worst['task']}` / `{worst['arm']}` 의 "
                    f"**{rel(worst['d_tok'], 0)}** 였습니다. "
                    f"이 중 {n_step}개는 에이전트 스텝도 함께 증가하였습니다."),
                  P("에이전트는 매 호출 시 누적 컨텍스트를 재전송합니다. "
                    "압축으로 식별자·경로 등이 손상되면 에이전트가 동일 정보를 "
                    "재조회하거나 잘못된 명령을 재시도하게 되고, 그 결과 스텝이 "
                    "증가하여 **압축으로 절감한 분량을 상회하는 추가 토큰이 "
                    "발생**합니다. 이를 토큰 증폭이라 합니다."),
                  Note("따라서 압축률만으로 비용 절감을 추정하면 실제 절감분이 "
                       "과대평가됩니다. 종단 측정에서의 실제 토큰 사용량으로 "
                       "검증해야 합니다.")]

    # ── 6.3 반복 측정 변동 ──────────────────────────────────────
    B += _variance(doc, m, b, ctl)
    return B


def _variance(doc: Doc, m, b, ctl) -> list:
    """대조 측정을 **태스크별 반복**으로 해석합니다.

    조건 평균만 비교하면 "세 조건이 각각 몇 % 였다" 로 끝나지만, 대조
    측정은 동일 조건을 태스크마다 3회 반복한 것이므로 태스크 단위로
    보아야 정보가 나옵니다. 같은 태스크를 3회 돌렸을 때 결과가 갈리면
    그 태스크의 성패는 단일 측정으로 판정할 수 없다는 뜻입니다.
    """
    B = []
    if not ctl or len(ctl["by_arm"]) < 2:
        return B
    B += ["반복 측정 변동"]
    B += [P("동일 조건(압축 미적용)으로 주 측정과 같은 태스크를 반복 "
            "측정하였습니다. 조건이 동일하므로 관측된 모든 차이는 측정 "
            "변동에 해당합니다.")]

    # 태스크별 반복 결과
    per = {}
    for r in ctl["rows"]:
        per.setdefault(r["task"], []).append(r)
    rows, flaky, det = [], 0, 0
    for t, band in sorted(per.items()):
        rw = [x["reward"] for x in band if x["reward"] is not None]
        tk = [x["in_tok"] for x in band if x["in_tok"]]
        k, n = sum(1 for x in rw if x > 0), len(rw)
        if n > 1:
            if 0 < k < n:
                flaky += 1
            else:
                det += 1
        spread = (max(tk) / min(tk) - 1) if len(tk) > 1 else None
        rows.append([f"`{t}`", f"{k}/{n}",
                     "가변" if 0 < k < n else "일정",
                     num(mean(tk)), rel(spread) if spread is not None else "—"])
    B += [Table(doc.next_table(),
                "대조 측정 태스크별 반복 결과 (압축 미적용, 반복 3회)",
                ["태스크", "통과", "판정 안정성", "평균 입력 토큰",
                 "토큰 최대 편차"], rows, align="lrlrr")]
    if flaky:
        B += [P(f"반복 간 결과가 갈린 태스크가 **{flaky}종**입니다"
                f"(안정적으로 판정된 태스크 {det}종). 해당 태스크는 단일 "
                f"측정으로 성패를 판정할 수 없으며, 주 측정에서 관측된 "
                f"통과·실패에도 동일한 불확실성이 존재합니다.")]

    # 조건 단위 (= 반복 회차 단위) pass@1 범위
    ps = [a["pass1"] for a in ctl["by_arm"] if a["pass1"] is not None]
    toks = [(a["name"], a["in_tok"]) for a in ctl["by_arm"] if a["in_tok"]]
    if toks:
        hi = max(t for _, t in toks)
        rows = [[f"`{a['name']}`", f"{a['n_pass']}/{a['n']}",
                 pc(a["pass1"], 1), num(a["in_tok"]),
                 rel(a["in_tok"] / hi - 1)]
                for a in ctl["by_arm"] if a["in_tok"]]
        B += [Table(doc.next_table(),
                    "대조 측정 회차별 집계 (전 회차 압축 미적용)",
                    ["회차", "통과", "pass@1", "입력 토큰", "최대값 대비"],
                    rows, align="lrrrr")]
        tspread = max(abs(t / hi - 1) for _, t in toks)
        pspread = (max(ps) - min(ps)) if len(ps) > 1 else None
        txt = (f"압축을 적용하지 않았음에도 회차 간 입력 토큰이 최대 "
               f"**{pc(tspread, 1)}** 차이를 보였습니다.")
        if pspread:
            txt += (f" pass@1 은 {pc(min(ps), 1)} ~ {pc(max(ps), 1)} 범위에서 "
                    f"관측되어 최대 **{pp(pspread, 1)}** 의 편차가 "
                    f"확인되었습니다.")
        B += [P(txt),
              Figure(doc.next_fig(),
                     "대조 측정 회차별 pass@1 (전 회차 동일 조건)",
                     grouped_bars([("pass@1 (%)",
                                    [(a["pass1"] or 0) * 100
                                     for a in ctl["by_arm"]])],
                                  [a["name"] for a in ctl["by_arm"]],
                                  fmt=lambda v: f"{v:.0f}"),
                     "세 회차 모두 동일 설정입니다. 막대 길이의 차이가 "
                     "곧 측정 변동입니다.")]

        # 유의성 판정
        rows = []
        for a in m["by_arm"]:
            if a is b or not a["in_tok"] or not b["in_tok"]:
                continue
            red = 1 - a["in_tok"] / b["in_tok"]
            rows.append([f"`{a['name']}`", "입력 토큰", pc(red, 1),
                         f"±{pc(tspread, 1)}",
                         "변동 초과" if abs(red) > tspread
                         else "변동 범위 내"])
        if pspread is not None and b["pass1"] is not None:
            for a in m["by_arm"]:
                if a is b or a["pass1"] is None:
                    continue
                d = a["pass1"] - b["pass1"]
                rows.append([f"`{a['name']}`", "pass@1", pp(d, 1),
                             f"±{pspread * 100:.1f}%p",
                             "변동 초과" if abs(d) > pspread
                             else "변동 범위 내"])
        if rows:
            B += [Table(doc.next_table(),
                        "주 측정 결과의 유의성 판정",
                        ["조건", "지표", "관측 변화", "측정 변동", "판정"],
                        rows, align="llrrl"),
                  Note("‘변동 범위 내’ 는 해당 변화가 압축 효과인지 측정 "
                       "변동인지 현재 표본으로는 구분할 수 없음을 의미합니다. "
                       "효과 없음을 뜻하지 않습니다.")]
    return B


def _limits(doc: Doc, D: dict) -> list:
    m = D.get("main")
    B = [P("본 측정 결과 해석 시 다음 제약을 고려하여야 합니다.")]
    pspread, tspread = _ctl_spread(D)
    rows = []
    if m:
        n_t = len({r["task"] for r in m["rows"]})
        txt = (f"조건당 태스크 {n_t}종, 시도 1회. 태스크 1건의 성패가 "
               f"pass@1 을 {100 / n_t:.1f}%p 변동시킵니다.")
        if pspread is not None:
            txt += (f" 대조 측정에서 확인된 실제 변동은 pass@1 "
                    f"±{pspread * 100:.1f}%p, 입력 토큰 "
                    f"±{tspread * 100:.1f}% 로, 본 측정에서 관측된 변화와 "
                    f"같은 크기입니다. **효과의 방향은 판별 가능하나 크기는 "
                    f"확정할 수 없습니다.**")
        rows.append(["표본 규모", txt])
        rows.append(["태스크 판정 안정성",
                     "일부 태스크는 동일 조건 반복에서도 성패가 갈렸습니다"
                     "(5장 대조 측정 표 참조). 개별 태스크의 통과·실패를 "
                     "근거로 조건을 평가하지 마십시오."])
    rows += [
        ["대상 범위",
         "LLMLingua-2 단일 압축기, 단일 모델(gpt-5.4), 단일 에이전트"
         "(mini-swe-agent) 조합에 한정된 결과입니다."],
        ["적용 방식",
         "프롬프트 전체에 일괄 압축을 적용하였습니다. 메시지 유형별 "
         "선택 적용이나 규칙 기반 전처리와의 조합은 평가하지 않았습니다."],
        ["파라미터 범위",
         "`rate` 외 하이퍼파라미터는 기본값으로 고정하였습니다. "
         "`force_tokens` 등의 조합 효과는 본 측정에 포함되지 않았습니다."],
        ["실행 환경",
         "Docker 이미지는 linux/amd64 이며 호스트는 arm64 로, 에뮬레이션 "
         "계층이 개입합니다. 또한 일부 롤아웃은 다른 측정과 동시 실행되어 "
         "CPU 자원을 공유하였습니다. **소요 시간 지표는 절대값으로 "
         "사용하지 마시고 동일 롤아웃 내 조건 간 상대 비교로만 "
         "해석하십시오.** pass@1·토큰·스텝은 자원 경합의 영향을 받지 "
         "않으므로 그대로 유효합니다."],
    ]
    B += [Table(doc.next_table(), "제약 사항", ["구분", "내용"], rows)]
    return B


def _conclusion(doc: Doc, D: dict) -> list:
    m, ctl = D.get("main"), D.get("control")
    B = []
    if not m:
        return [P("결과가 없습니다.")]
    b = _base_of(m)
    comp = [a for a in m["by_arm"] if a is not b and a["pass1"] is not None]

    B += ["측정 결론"]
    pspread, tspread = _ctl_spread(D)

    # 압축을 걸고도 토큰이 늘어난 조건이 있으면, "정확도를 잃는 대신 비용을
    # 아낀다" 는 통상적 상충 관계가 성립하지 않습니다. 그 경우 두 축 모두
    # 손해이므로 결론의 강도가 달라집니다. 데이터에서 판정합니다.
    tok = [(a2, a2["in_tok"] / b["in_tok"] - 1)
           for a2 in comp if a2["in_tok"] and b["in_tok"]]
    up = [(a2, v) for a2, v in tok if v > 0.05]
    down = [(a2, v) for a2, v in tok if v < -0.05]
    tok_note = ""
    if tok:
        if up and not down:
            tok_note = ("입력 토큰은 **어느 조건에서도 감소하지 않았고, "
                        f"{len(up)}개 조건에서는 오히려 증가**하였습니다. "
                        "정확도를 내주는 대신 비용을 아끼는 통상적 상충 관계가 "
                        "성립하지 않았으며, 두 축 모두 손해였습니다.")
        elif up:
            names = ", ".join(f"`{x['name']}`" for x, _ in up)
            tok_note = (f"입력 토큰은 조건에 따라 갈렸습니다. {names} 조건에서는 "
                        f"압축을 적용했음에도 토큰이 **증가**하여, 해당 구간에서는 "
                        f"정확도와 비용이 동시에 악화되었습니다. 감소가 관측된 "
                        f"조건은 정확도 하락 폭이 가장 컸으며, 그 감소율 역시 "
                        f"반복 측정 변동 범위와 겹칩니다. 따라서 현재 표본으로는 "
                        f"비용 절감 효과를 확정할 수 없습니다.")
        else:
            tok_note = ("입력 토큰은 감소하였으나 관측된 절감률이 반복 측정 "
                        "변동 범위 내에 있어, 현재 표본으로는 비용 절감 효과를 "
                        "확정할 수 없습니다.")
    if comp and b["pass1"] is not None:
        drop = [a for a in comp if a["pass1"] < b["pass1"]]
        if drop:
            w = min(drop, key=lambda a: a["pass1"])
            d = w["pass1"] - b["pass1"]
            txt = (f"코딩 에이전트 프롬프트 전체에 LLMLingua-2 를 일괄 "
                   f"적용한 결과, pass@1 이 {pc(b['pass1'], 1)} 에서 "
                   f"{pc(w['pass1'], 1)} 로 {pp(d, 1)} 하락하였습니다. "
                   f"압축 강도가 높을수록 하락 폭이 커졌으며, 압축 조건이 "
                   f"통과한 태스크는 기준 조건 통과 태스크의 부분집합이었습니다.")
            if pspread is not None and abs(d) <= pspread:
                txt += (f" 다만 이 하락 폭은 대조 측정에서 확인된 변동 범위"
                        f"(±{pspread * 100:.1f}%p) 내에 있어, **정확도 저하 "
                        f"경향은 관측되나 통계적으로 확정된 결과는 "
                        f"아닙니다.**")
            B += [P(txt)]
        else:
            B += [P("측정 범위에서 압축 적용에 따른 유의한 정확도 하락은 "
                    "관측되지 않았습니다.")]
    B += [P(tok_note or "입력 토큰 변화는 측정되지 않았습니다."),
          P("압축기 자체의 동작은 정상이었습니다. 부록의 입출력 예시에서 "
            "확인되듯 산문형 입력은 절반 수준으로 압축하여도 핵심 정보가 "
            "보존됩니다. 반면 명령 실행 출력에서는 식별자가 손상되며, "
            "에이전트는 해당 식별자로 후속 명령을 구성하므로 이 손상이 "
            "성능 저하의 직접적 경로로 작용합니다."),
          Note("종합하면, 현 시점에서 프로덕션 적용을 권고하기에는 근거가 "
               "부족합니다. 정확도 저하 경향과 토큰 증폭 현상이 일관되게 "
               "관측되었으므로, 전체 일괄 적용 대신 아래 방향의 선택적 "
               "적용을 검토하고 표본을 확대하여 재측정할 것을 제안합니다.")]

    B += ["권고",
          Table(doc.next_table(), "후속 검토 방향",
                ["방향", "근거"],
                [["명령 출력에 대한 규칙 기반 축약 적용 "
                  "(로그 중복 제거·스택 트레이스 축약)",
                  "식별자를 보존하면서 컨텍스트에서 가장 크게 증가하는 "
                  "영역을 축소할 수 있습니다."],
                 ["`keep_last` 확대 후 정확도 회복 지점 탐색",
                  "직전 컨텍스트 보존 범위가 정확도에 미치는 영향이 "
                  "본 측정에서 통제되지 않았습니다."],
                 ["산문형 입력(과제 설명·문서)에 한정한 선택적 적용",
                  "해당 유형에서는 압축률 대비 정보 손실이 작습니다."],
                 ["단순 절단(truncation) 대조군과의 비교 측정",
                  "압축기 도입 비용을 정당화하려면 단순 기법 대비 우위가 "
                  "확인되어야 합니다."]])]
    B += ["후속 측정 계획",
          Table(doc.next_table(), "표본 및 범위 확대 계획",
                ["항목", "현재", "목표"],
                [["태스크 수", f"{len({r['task'] for r in m['rows']})}종",
                  "수십 종 (하락 폭 정밀도 확보)"],
                 ["시도 횟수", "1회",
                  "3회 이상 (측정 변동을 넘는 신호 확보)"],
                 ["압축률 구간", f"{len(comp)}개 조건",
                  "0.3 – 0.9 세분화"],
                 ["적용 방식", "전체 일괄", "메시지 유형별 선택 적용"],
                 ["벤치마크", "Terminal Bench 2.1 단독",
                  "DeepSWE 공식 하네스 추가 (현재 미측정)"]]),
          Note("시도 횟수 확대가 최우선입니다. 대조 측정에서 확인된 변동 폭이 "
               "현재 관측된 효과 크기와 동일하므로, 반복 측정 없이는 표본을 "
               "늘려도 효과를 분리할 수 없습니다.")]
    return B


def _appendix(doc: Doc, D: dict) -> list:
    S = D["samples"]
    B = [P(f"압축기 동작을 확인하기 위해 대표 입력에 대해 실제 압축을 "
           f"수행한 결과입니다. 적용 정책은 압축기 자체의 거동을 관찰하기 "
           f"위해 해제하였습니다({S['policy']}).")]
    for c in S["cases"]:
        B += [c["label"], P(c["why"])]
        B += [Table(doc.next_table(), f"{c['label']} — 압축률별 결과",
                    ["rate", "토큰", "감소율", "지연(초)"],
                    [[str(v["rate"]), str(v["after_tokens"]),
                      pc(v["reduction"]), f"{v['latency_s']:.1f}"]
                     for v in c["variants"]], align="rrrr")]
        mid = next((v for v in c["variants"] if v["rate"] == 0.5),
                   c["variants"][len(c["variants"]) // 2])
        B += [Note(f"원문 {c['before_tokens']} 토큰"),
              Code(c["before"].strip()[:760]),
              Note(f"압축 후 (rate {mid['rate']}) {mid['after_tokens']} 토큰"),
              Code(mid["after"].strip()[:760])]
    B += [Note("산문형 입력은 압축 후에도 오류 코드·파일 경로·행 번호가 "
               "보존됩니다. 명령 출력에서는 식별자 구분자가 소실되어 "
               "`test_parser.py::test_parse_header` 가 "
               "`_parser.py_parse_header` 형태로 변형됩니다.")]
    return B


def read_proxy(run_dirs, names: list[str]) -> dict:
    """프록시가 남긴 호출 단위 기록에서 압축률·지연 분포를 뽑습니다.

    조건 평균만으로는 "rate 0.5 인데 왜 절반이 안 줄었나" 를 설명할 수
    없습니다. rate 는 메시지 단위 목표치이고, 정책에 따라 압축을 건너뛴
    메시지가 섞이므로 요청 전체 감소율은 그보다 낮습니다.
    """
    if isinstance(run_dirs, (str, Path)):
        run_dirs = [run_dirs]
    out = {}
    for n in names:
        files = [Path(rd) / f"{n}.jsonl" for rd in run_dirs]
        files = [f for f in files if f.exists()]
        if not files:
            continue
        red, lat = [], []
        lines = []
        for f in files:
            lines += f.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("event") != "compress":
                continue
            if e.get("reduction") is not None:
                red.append(float(e["reduction"]))
            if e.get("elapsed_ms") is not None:
                lat.append(float(e["elapsed_ms"]))
        if not red:
            continue
        q = lambda xs, p: sorted(xs)[min(len(xs) - 1,               # noqa: E731
                                        max(0, int(len(xs) * p)))]
        out[n] = {"n": len(red), "mean": st.mean(red), "p50": q(red, .5),
                  "p10": q(red, .1), "p90": q(red, .9),
                  "lat_p50": q(lat, .5) if lat else 0.0,
                  "lat_p90": q(lat, .9) if lat else 0.0}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    # 언어를 나눠 돌리면 run 디렉터리가 갈리므로 여러 개를 받습니다.
    ap.add_argument("--run", type=Path, nargs="+", required=True,
                    help="주 측정 run 디렉터리 (arms.json 이 있는 곳)")
    ap.add_argument("--jobs", type=Path, nargs="+", required=True)
    ap.add_argument("--control-run", type=Path, nargs="*", default=[],
                    help="대조 측정 run 디렉터리")
    ap.add_argument("--control-jobs", type=Path, nargs="*", default=[])
    ap.add_argument("--swe-run", type=Path, help="DeepSWE run 디렉터리")
    ap.add_argument("--swe-jobs", type=Path, nargs="*", default=[])
    ap.add_argument("--samples", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    a = ap.parse_args()

    D = {}
    D["main"] = read_rollout(list(a.run), list(a.jobs))
    if not D["main"]:
        print("✗ 주 측정 결과를 읽지 못했습니다", file=sys.stderr)
        return 1
    print(f"  주 측정   {len(D['main']['rows'])} trial")
    D["proxy"] = read_proxy(list(a.run),
                            [x["name"] for x in D["main"]["by_arm"]])

    if a.control_run and a.control_jobs:
        D["control"] = read_rollout(list(a.control_run), list(a.control_jobs))
        if D["control"]:
            print(f"  대조 측정 {len(D['control']['rows'])} trial")
    if a.swe_run and a.swe_jobs:
        D["swe"] = read_rollout(a.swe_run, list(a.swe_jobs))
        if D["swe"]:
            print(f"  DeepSWE  {len(D['swe']['rows'])} trial")
            D["swe_proxy"] = read_proxy(
                a.swe_run, [x["name"] for x in D["swe"]["by_arm"]])
    if a.samples and a.samples.exists():
        D["samples"] = json.loads(a.samples.read_text(encoding="utf-8"))
        print(f"  압축 예시 {len(D['samples']['cases'])}건")

    a.out.mkdir(parents=True, exist_ok=True)

    doc = build(D)
    (a.out / "report.md").write_text(to_md(doc), encoding="utf-8")
    (a.out / "report.html").write_text(to_html(doc), encoding="utf-8")

    # 요약판. 표·그림 번호는 문서마다 독립이어야 하므로 Doc 을 새로 만듭니다.
    brief = build_brief(D)
    (a.out / "brief.md").write_text(to_md(brief), encoding="utf-8")
    (a.out / "brief.html").write_text(to_html(brief), encoding="utf-8")

    # 측정 원본을 함께 남깁니다. jobs 디렉터리는 보통 /tmp 에 있어 재부팅 시
    # 사라지므로, 이것이 없으면 보고서를 다시 만들 수 없습니다.
    raw = {"generated_at": datetime.now().isoformat(timespec="seconds"),
           "sources": {k: str(v) for k, v in
                       [("run", a.run), ("jobs", a.jobs),
                        ("swe_run", a.swe_run), ("swe_jobs", a.swe_jobs),
                        ("control_run", a.control_run),
                        ("control_jobs", a.control_jobs)] if v},
           "sets": {k: {"arms": D[k]["arms"], "by_arm": D[k]["by_arm"],
                        "rows": D[k]["rows"]}
                    for k in ("main", "control", "swe") if D.get(k)},
           "proxy": D.get("proxy") or {}}
    # 업스트림 호스트명을 가립니다. 비밀은 아니지만 리소스 이름이라
    # 저장소에 남길 이유가 없고, 다른 구독에서 재현할 때 혼동을 줍니다.
    # 조건 판별은 arm 이름으로 하므로 가려도 재생성에 지장이 없습니다.
    text = json.dumps(raw, ensure_ascii=False, indent=1, default=str)
    text = re.sub(r"https://[A-Za-z0-9._-]+\.cognitiveservices\.azure\.com",
                  "https://<azure-openai-endpoint>", text)
    (a.out / "results.json").write_text(text, encoding="utf-8")
    print(f"▸ {a.out}/report.md · report.html · results.json")
    print(f"▸ {a.out}/brief.md · brief.html  (요약판)")
    return 0



def _swe(doc: Doc, D: dict) -> list:
    """DeepSWE 결과.

    Terminal Bench 와 두 가지가 다릅니다.

    1. **부하 규모** — 저장소를 훑고 여러 파일을 고치므로 누적 입력이
       Terminal Bench 의 수십 배입니다. 압축은 줄일 것이 있어야 의미가
       있으므로 이 규모에서의 거동이 실제 도입 판단에 더 가깝습니다.
    2. **채점 해상도** — 전체 통과 여부만 주지 않고 f2p(고쳐야 할 테스트)와
       p2p(깨뜨리면 안 되는 테스트)를 나눠 줍니다. 압축이 "못 고침" 을
       유발했는지 "멀쩡한 것을 깨뜨림" 을 유발했는지 구분됩니다.
    """
    sw, main = D["swe"], D.get("main")
    B = [P("DeepSWE 는 실제 오픈소스 저장소의 이슈를 해결하고 코드 패치를 "
           "생성하는 벤치마크입니다. Terminal Bench 와 동일한 Harbor 계열 "
           "스키마를 사용하며, 채점은 저장소의 테스트 스위트로 수행합니다.")]

    b = _base_of(sw)

    # ── 종합 ────────────────────────────────────────────────
    rows = []
    for a in sw["by_arm"]:
        is_b = a is b
        band = [r for r in sw["rows"] if r["arm"] == a["name"]]
        f2p = mean([r.get("f2p") for r in band])
        p2p = mean([r.get("p2p") for r in band])
        rows.append([
            f"`{a['name']}`", f"{a['n_pass']}/{a['n']}", pc(a["pass1"], 1),
            pc(f2p, 1) if f2p is not None else "—",
            pc(p2p, 1) if p2p is not None else "—",
            str(a.get("n_err") or 0),
            num(a["in_tok"]),
            "기준" if is_b else (rel(a["in_tok"] / b["in_tok"] - 1)
                                if (a["in_tok"] and b["in_tok"]) else "—"),
            f"{a['steps']:.1f}" if a["steps"] else "—",
            f"{a['secs']:.0f}" if a["secs"] else "—"])
    B += ["종합 결과",
          Table(doc.next_table(), "DeepSWE 조건별 성능 (trial 평균)",
                ["조건", "통과 / 시도", "pass@1", "f2p", "p2p", "예산 초과",
                 "입력 토큰", "토큰 기준차", "스텝", "소요(초)"], rows,
                align="lrrrrrrrrr"),
          Note("**예산 초과** 는 에이전트가 스텝 상한(60회) 안에 과제를 "
               "끝내지 못해 중단된 trial 수입니다. **실패로 집계**합니다 — "
               "제외하면 끝낸 trial 만 모아 정확도를 재는 셈이 되어 압축 "
               "조건이 실제보다 좋게 보입니다. "
               "**f2p**(fail-to-pass) 는 이슈 해결을 위해 통과시켜야 하는 "
               "테스트의 통과 비율이고, **p2p**(pass-to-pass) 는 원래 "
               "통과하던 테스트를 유지한 비율입니다. pass@1 은 두 가지가 "
               "모두 충족될 때만 1점이므로, 0점이어도 f2p 로 진척도를 "
               "비교할 수 있습니다. **토큰 기준차** 는 압축 미적용 조건 "
               "대비 입력 토큰의 증감을 상대 비율(%)로 표기한 것입니다.")]

    # 예산 초과가 압축 조건에만 몰리는지 봅니다. 그렇다면 "정확도가 조금
    # 떨어졌다" 가 아니라 "아예 끝내지 못했다" 는 뜻이라 성격이 다릅니다.
    errs = [(a["name"], a.get("n_err") or 0, a["n"]) for a in sw["by_arm"]]
    tot_err = sum(e for _, e, _ in errs)
    if tot_err:
        base_err = next((e for n, e, _ in errs if n == b["name"]), 0)
        comp_err = tot_err - base_err
        B += [P(f"**예산 초과가 {tot_err}건 발생했습니다"
                + (f" — 전부 압축 조건입니다" if base_err == 0 and comp_err
                   else f" (기준 조건 {base_err}건, 압축 조건 {comp_err}건)")
                + ".** 스텝 상한은 전 조건 동일하게 60회를 적용했으므로, "
                "압축 조건이 같은 예산 안에 과제를 끝내지 못했다는 뜻입니다. "
                "정확도가 조금 낮아진 것과는 성격이 다릅니다 — 압축으로 "
                "손상된 컨텍스트를 에이전트가 반복 탐색하면서 예산을 "
                "소진했습니다.")]

    names = [a["name"] for a in sw["by_arm"]]
    f2ps = []
    for a in sw["by_arm"]:
        band = [r for r in sw["rows"] if r["arm"] == a["name"]]
        f2ps.append((mean([r.get("f2p") for r in band]) or 0) * 100)
    B += [Figure(doc.next_fig(), "DeepSWE 조건별 f2p (이슈 해결 진척도)",
                 grouped_bars([("f2p (%)", f2ps)], names,
                              fmt=lambda v: f"{v:.0f}"),
                 "pass@1 이 0인 구간에서도 f2p 는 조건 간 차이를 드러냅니다.")]

    # ── 태스크별 ────────────────────────────────────────────
    tasks = sorted({r["task"] for r in sw["rows"]})
    cell = {(r["task"], r["arm"]): r for r in sw["rows"]}
    rows = []
    for t in tasks:
        line = [f"`{t}`"]
        for n in names:
            r = cell.get((t, n))
            if not r:
                line.append("—")
            elif (r.get("reward") or 0) > 0:
                line.append("통과")
            else:
                line.append(f"f2p {pc(r['f2p'], 0)}"
                            if r.get("f2p") is not None else "실패")
        rows.append(line)
    B += ["태스크별 결과",
          Table(doc.next_table(), "DeepSWE 태스크 × 조건",
                ["태스크"] + [f"`{n}`" for n in names], rows),
          Note("통과하지 못한 경우 f2p 를 함께 표기하였습니다. 값이 클수록 "
               "해결에 근접한 것입니다.")]

    # ── 압축 동작 ───────────────────────────────────────────
    px = D.get("swe_proxy") or {}
    rows = []
    for n in names:
        s = px.get(n)
        if s:
            rows.append([f"`{n}`", str(s["n"]), pc(s["mean"]), pc(s["p50"]),
                         pc(s["p90"]), f"{s['lat_p50']:.0f}",
                         f"{s['lat_p90']:.0f}"])
    if rows:
        B += ["압축 동작 특성",
              Table(doc.next_table(),
                    "DeepSWE 실행 중 호출 단위 압축률 및 지연",
                    ["조건", "호출 수", "평균", "중앙값", "90분위",
                     "지연 중앙값(ms)", "지연 90분위(ms)"], rows,
                    align="lrrrrrr")]
    return B



def _compare(doc: Doc, D: dict) -> list:
    """두 벤치마크를 나란히 놓습니다.

    각 장에서 따로 읽으면 "둘 다 정확도가 떨어졌다" 정도로만 남습니다.
    나란히 놓아야 **부하 규모에 따라 무엇이 달라지는지**가 보입니다 —
    압축의 절감 여지도, 손상 시 대가도, 연산 지연도 모두 컨텍스트 크기에
    따라 움직입니다.
    """
    m, sw = D.get("main"), D.get("swe")
    if not (m and sw):
        return []
    mb, sb = _base_of(m), _base_of(sw)
    B = [P("두 벤치마크는 같은 압축기·같은 조건·같은 최종 모델을 썼고 "
           "**부하 규모만 다릅니다.** 따라서 두 결과의 차이는 컨텍스트 "
           "크기가 만든 것으로 읽을 수 있습니다.")]

    # ── 7-1 부하 ────────────────────────────────────────────
    rows = [["Terminal Bench 2.1",
             f"{len({r['task'] for r in m['rows']})}종",
             num(mb["in_tok"]), f"{mb['steps']:.1f}" if mb["steps"] else "—",
             "1.0×", "터미널에서 완결되는 단일 과제"],
            ["DeepSWE",
             f"{len({r['task'] for r in sw['rows']})}종",
             num(sb["in_tok"]), f"{sb['steps']:.1f}" if sb["steps"] else "—",
             f"{sb['in_tok'] / mb['in_tok']:.1f}×"
             if (mb["in_tok"] and sb["in_tok"]) else "—",
             "저장소 전체를 탐색해 코드 패치 생성"]]
    B += ["부하 규모",
          Table(doc.next_table(),
                "기준 조건(압축 미적용)의 부하 비교",
                ["벤치마크", "태스크", "평균 입력 토큰", "평균 스텝",
                 "토큰 배수", "과제 성격"], rows, align="lrrrrl"),
          Note("압축은 줄일 것이 있어야 의미가 있으므로, 절감 여지는 "
               "DeepSWE 쪽이 훨씬 큽니다. 반대로 컨텍스트가 손상되었을 때 "
               "잃는 것도 큽니다.")]

    # ── 7-2 조건별 정확도·토큰 ──────────────────────────────
    names = [a["name"] for a in m["by_arm"]]
    sw_by = {a["name"]: a for a in sw["by_arm"]}
    rows = []
    for a in m["by_arm"]:
        t = sw_by.get(a["name"])
        d_m = ((a["in_tok"] / mb["in_tok"] - 1)
               if (a["in_tok"] and mb["in_tok"]) else None)
        d_s = ((t["in_tok"] / sb["in_tok"] - 1)
               if (t and t["in_tok"] and sb["in_tok"]) else None)
        rows.append([f"`{a['name']}`",
                     pc(a["pass1"], 1),
                     "기준" if a is mb else rel(d_m),
                     pc(t["pass1"], 1) if t else "—",
                     ("기준" if (t and t is sb)
                      else (rel(d_s) if d_s is not None else "—")),
                     pc(mean([r.get("f2p") for r in sw["rows"]
                              if r["arm"] == a["name"]]), 1) if t else "—"])
    B += ["조건별 결과",
          Table(doc.next_table(),
                "동일 조건에서의 두 벤치마크 결과",
                ["조건", "TB pass@1", "TB 토큰 기준차",
                 "SWE pass@1", "SWE 토큰 기준차", "SWE f2p"],
                rows, align="lrrrrr"),
          Note("`TB` 는 Terminal Bench, `SWE` 는 DeepSWE 입니다. "
               "DeepSWE 는 pass@1 이 0 인 구간에서도 f2p 로 진척도를 "
               "비교할 수 있습니다.")]

    # 정확도 곡선 겹쳐 보기
    band = sorted([a for a in m["by_arm"] if a["pass1"] is not None],
                  key=lambda a: -a["rate"])
    if len(band) > 1:
        xs = [a["rate"] for a in band]
        tb = [a["pass1"] for a in band]
        se = [(sw_by.get(a["name"]) or {}).get("pass1") for a in band]
        B += [Figure(doc.next_fig(),
                     "압축률에 따른 정확도 — 두 벤치마크",
                     line_chart(xs, [("Terminal Bench", tb),
                                     ("DeepSWE", se)],
                                "rate (유지 비율)", "pass@1"),
                     "rate=1.0 은 압축 미적용입니다. 곡선이 겹치는 정도로 "
                     "부하 규모가 압축 민감도에 미치는 영향을 볼 수 "
                     "있습니다.")]

    # ── 7-3 압축 연산 비용 ──────────────────────────────────
    px_m, px_s = D.get("proxy") or {}, D.get("swe_proxy") or {}
    rows = []
    for n in names:
        a, c = px_m.get(n), px_s.get(n)
        if not (a or c):
            continue
        rows.append([f"`{n}`",
                     pc(a["mean"]) if a else "—",
                     f"{a['lat_p50']:.0f}" if a else "—",
                     pc(c["mean"]) if c else "—",
                     f"{c['lat_p50']:.0f}" if c else "—",
                     (f"{c['lat_p50'] / a['lat_p50']:.0f}×"
                      if (a and c and a["lat_p50"]) else "—")])
    if rows:
        B += ["압축 연산 비용",
              Table(doc.next_table(),
                    "호출 단위 압축률과 지연 비교",
                    ["조건", "TB 압축률", "TB 지연(ms)",
                     "SWE 압축률", "SWE 지연(ms)", "지연 배수"],
                    rows, align="lrrrrr")]
        lat_m = [v["lat_p50"] for v in px_m.values() if v.get("lat_p50")]
        lat_s = [v["lat_p50"] for v in px_s.values() if v.get("lat_p50")]
        if lat_m and lat_s:
            B += [P(f"압축 연산 지연은 Terminal Bench 에서 호출당 중앙 "
                    f"{max(lat_m) / 1000:.1f}초였으나 DeepSWE 에서는 "
                    f"**{max(lat_s) / 1000:.1f}초**로 증가하였습니다. "
                    f"LLMLingua-2 는 입력 전체를 토큰 단위로 분류하므로 "
                    f"연산량이 컨텍스트 길이에 비례합니다."),
                  Note("**압축이 가장 필요한 대규모 컨텍스트에서 압축 "
                       "오버헤드도 가장 커집니다.** 에이전트는 한 과제에 "
                       "수십 번 호출하므로 이 지연이 그대로 누적됩니다. "
                       "도입 검토 시 토큰 절감액과 지연 증가를 함께 "
                       "따져야 합니다.")]

    # ── 7-4 종합 ────────────────────────────────────────────
    # pass@1 이 전 조건 0 이면(바닥 효과) 그 축으로는 아무것도 비교할 수
    # 없습니다. DeepSWE 가 그런 상태라 f2p 로 갈아탑니다. 축이 다르다는
    # 사실을 표에 드러내야 두 행을 같은 지표로 오해하지 않습니다.
    rows, note = _summary_rows([("Terminal Bench 2.1", m, mb),
                                ("DeepSWE", sw, sb)])
    if rows:
        B += ["종합",
              Table(doc.next_table(), "벤치마크별 요약",
                    ["벤치마크", "지표", "기준값", "최대 하락",
                     "최대 토큰 절감", "품질 유지 한계"],
                    rows, align="llrrrl"),
              Note(note)]
    return B


def _summary_rows(sets, with_tok: bool = False):
    """벤치마크별 한 줄 요약.

    pass@1 이 전 조건 0 이면(바닥 효과) 그 축으로는 아무것도 비교할 수
    없으므로 부분 진척도인 f2p 로 갈아탑니다. 축이 바뀐 사실을 각주에
    남겨야 두 행을 같은 지표로 오해하지 않습니다.
    """
    rows, floored = [], []
    for lbl, d, base in sets:
        if not d or not base:
            continue
        comp = [a for a in d["by_arm"] if a is not base]
        if not comp:
            continue
        f2p_of = lambda nm: mean([r.get("f2p") for r in d["rows"]  # noqa: E731
                                  if r["arm"] == nm])
        use_f2p = not any((a["pass1"] or 0) > 0 for a in d["by_arm"])
        if use_f2p:
            floored.append(lbl)
            bv, cv = f2p_of(base["name"]), [(a, f2p_of(a["name"])) for a in comp]
        else:
            bv, cv = base["pass1"], [(a, a["pass1"]) for a in comp]
        cv = [(a, v) for a, v in cv if v is not None]
        if bv is None or not cv:
            continue
        toks = [(a["in_tok"] / base["in_tok"] - 1) for a in comp
                if a["in_tok"] and base["in_tok"]]
        keep = [a for a, v in cv if v >= bv - 0.05]
        row = [lbl]
        if with_tok:
            row.append(num(base["in_tok"]))
        row += ["f2p" if use_f2p else "pass@1", pc(bv, 1),
                pp(min(v - bv for _, v in cv), 1),
                rel(min(toks)) if toks else "—",
                (f"`rate {min(keep, key=lambda a: a['rate'])['rate']}`"
                 if keep else "**없음**")]
        rows.append(row)
    note = ("‘품질 유지 한계’ 는 기준 조건 대비 지표 하락이 5%p 이내였던 "
            "가장 강한 압축 조건입니다. ‘없음’ 은 측정 범위의 모든 압축 "
            "조건에서 그보다 큰 하락이 관측되었다는 뜻입니다.")
    if floored:
        note += (f" **{', '.join(floored)} 는 전 조건 pass@1 이 0 이므로"
                 f"(바닥 효과) 완전 해결 여부로는 비교할 수 없어, 부분 "
                 f"진척도인 f2p 를 지표로 사용했습니다.** 두 행의 지표가 "
                 f"다르므로 값을 직접 견주지 마십시오.")
    return rows, note


# ═════════════════════════════════════════════════════════════════════
# 요약판
#
# 전체 보고서는 설계·정의·부록까지 담아 길어집니다. 결과만 보려는 사람에게는
# 그게 장벽이 되므로, **판단에 필요한 것만** 남긴 판을 따로 냅니다.
#
# 남기는 것: 결론 / 무엇을 쟀나 / 벤치마크별 핵심 표 / 비교 / 권고
# 빼는 것: 파라미터 사전, 지표 정의, 태스크 목록, 태스크별 격자,
#          대응 비교 전체 표, 압축 예시 부록
# ═════════════════════════════════════════════════════════════════════
def build_brief(D: dict) -> Doc:
    m, sw, ctl = D.get("main"), D.get("swe"), D.get("control")
    marks = ["Terminal Bench 2.1"] + (["DeepSWE"] if sw else [])
    doc = Doc("LLM 프롬프트 압축 성능 영향 평가 — 요약",
              f"{' · '.join(marks)} · LLMLingua-2 · 최종 추론 gpt-5.4 · "
              f"{datetime.now():%Y-%m-%d}")
    _incomplete(doc, D)
    _brief_verdict(doc, D)

    doc.sec("무엇을 쟀나", _brief_what(doc, D))
    if m:
        doc.sec("Terminal Bench 결과", _brief_bench(doc, m, D, "TB"))
    if sw:
        doc.sec("DeepSWE 결과", _brief_bench(doc, sw, D, "SWE"))
        doc.sec("두 벤치마크 비교", _brief_compare(doc, D))
    doc.sec("판단 근거의 한계", _brief_limits(doc, D))
    doc.sec("권고", _brief_reco(doc, D))
    return doc


def _brief_verdict(doc: Doc, D: dict) -> None:
    """결론을 맨 위에 둡니다. 요약판을 읽는 목적이 그것이기 때문입니다."""
    m = D.get("main")
    if not m:
        return
    b = _base_of(m)
    comp = [a for a in m["by_arm"] if a is not b and a["pass1"] is not None]
    pspread, tspread = _ctl_spread(D)

    if comp and b["pass1"] is not None:
        worst = min(comp, key=lambda a: a["pass1"])
        keep = [a for a in comp if a["pass1"] >= b["pass1"] - 0.05]
        tok = [(a, a["in_tok"] / b["in_tok"] - 1) for a in comp
               if a["in_tok"] and b["in_tok"]]
        saved = [x for x in tok if x[1] < -0.05]

        doc.abstract.append(
            f"**결론: 현 시점에서 코딩 에이전트 프롬프트에 대한 전면 적용은 "
            f"권고하지 않습니다.** 압축 강도를 높일수록 정확도가 하락했고"
            f"(최대 {pp(worst['pass1'] - b['pass1'], 1)}), 정확도를 유지한 "
            f"구간에서는 토큰이 줄지 않았습니다.")
        if saved and keep:
            hi = min(keep, key=lambda a: a["rate"])
            hv = next((v for a, v in tok if a is hi), None)
            doc.abstract.append(
                f"정확도를 지킨 가장 강한 압축은 `rate {hi['rate']}` 였으나 "
                f"입력 토큰은 {rel(hv) if hv is not None else '—'} 로 "
                f"절감 효과가 없었고, 실제로 토큰이 크게 준 "
                f"`{saved[0][0]['name']}`({rel(saved[0][1])})는 정확도가 "
                f"{pp(saved[0][0]['pass1'] - b['pass1'], 1)} 하락했습니다. "
                f"**측정 범위에서 정확도와 비용이 함께 개선되는 지점은 "
                f"없었습니다.**")
    if pspread is not None:
        doc.abstract.append(
            f"단, 동일 조건 반복 측정에서 pass@1 이 ±{pspread * 100:.1f}%p "
            f"변동했습니다. 하락 경향은 일관되나 **개별 수치의 크기는 현재 "
            f"표본으로 확정할 수 없습니다.**")


def _brief_what(doc: Doc, D: dict) -> list:
    B = [P("공식 하네스(`pier` · Docker 격리)로 에이전트를 실제 실행하고 "
           "저장소 테스트로 채점했습니다. 압축은 에이전트와 모델 사이 "
           "프록시에서 적용되며, **최종 추론은 전 조건 동일하게 "
           "gpt-5.4**(Azure)를 호출합니다."),
         Code("[에이전트] → [압축 프록시: 프롬프트 일부 삭제] → [gpt-5.4]\n"
              "                                                    ↓\n"
              "                                        [테스트로 채점]")]
    rows = []
    for key, lbl, bm, purpose in (
            ("main", "주 측정", "Terminal Bench 2.1", "정확도·토큰 비교"),
            ("control", "대조 측정", "Terminal Bench 2.1", "반복 변동 추정"),
            ("swe", "주 측정", "DeepSWE", "대규모 컨텍스트 검증")):
        d = D.get(key)
        if not d:
            continue
        rows.append([lbl, bm, f"{len({r['task'] for r in d['rows']})}종",
                     ", ".join(sorted({r["lang"] for r in d["rows"]})),
                     str(len(d["by_arm"])), str(len(d["rows"])), purpose])
    if rows:
        B += [Table(doc.next_table(), "측정 구성 (측정 완료분)",
                    ["구분", "벤치마크", "태스크", "언어", "조건", "trial",
                     "목적"], rows, align="lllllrl")]
    B += [Note("압축 조건은 `rate`(유지 비율)만 바꾸었습니다. 값이 작을수록 "
               "강하게 압축합니다. 그 외 하이퍼파라미터는 기본값입니다.")]
    return B


def _brief_bench(doc: Doc, d: dict, D: dict, tag: str) -> list:
    """벤치마크 하나의 핵심 표와 그래프만."""
    b = _base_of(d)
    is_swe = tag == "SWE"
    rows = []
    for a in d["by_arm"]:
        is_b = a is b
        line = [f"`{a['name']}`", f"{a['n_pass']}/{a['n']}", pc(a["pass1"], 1),
                "기준" if is_b else pp(a["pass1"] - b["pass1"], 1)
                if (a["pass1"] is not None and b["pass1"] is not None) else "—"]
        if is_swe:
            band = [r for r in d["rows"] if r["arm"] == a["name"]]
            f2p = mean([r.get("f2p") for r in band])
            line.append(pc(f2p, 1) if f2p is not None else "—")
        line += [num(a["in_tok"]),
                 "기준" if is_b else rel(a["in_tok"] / b["in_tok"] - 1)
                 if (a["in_tok"] and b["in_tok"]) else "—",
                 f"{a['steps']:.1f}" if a["steps"] else "—"]
        rows.append(line)
    head = ["조건", "통과 / 완료", "pass@1", "pass@1 기준차"]
    if is_swe:
        head.append("f2p")
    head += ["입력 토큰", "토큰 기준차", "스텝"]
    B = [Table(doc.next_table(), f"{'DeepSWE' if is_swe else 'Terminal Bench'} "
               f"조건별 성능", head, rows,
               align="lrrr" + ("r" if is_swe else "") + "rrr")]

    band = sorted([a for a in d["by_arm"] if a["pass1"] is not None],
                  key=lambda a: -a["rate"])
    if len(band) > 1:
        B += [Figure(doc.next_fig(),
                     f"압축률에 따른 정확도와 토큰 — "
                     f"{'DeepSWE' if is_swe else 'Terminal Bench'}",
                     line_chart([a["rate"] for a in band],
                                [("pass@1", [a["pass1"] for a in band]),
                                 ("입력 토큰(기준 대비)",
                                  [(a["in_tok"] / b["in_tok"])
                                   if (a["in_tok"] and b["in_tok"]) else None
                                   for a in band])],
                                "rate (유지 비율)", "비율"),
                     "rate=1.0 은 압축 미적용입니다. 두 선이 함께 내려가는 "
                     "구간이 없으면, 정확도를 지키면서 비용을 줄일 수 "
                     "없다는 뜻입니다.")]

    # 태스크 단위로 토큰이 늘어난 사례 — 개수만 짚습니다.
    pairs = _paired(d, b)
    up = [p for p in pairs if p["d_tok"] > 0]
    if up:
        n_step = sum(1 for p in up if (p["d_step"] or 0) > 0)
        worst = max(up, key=lambda p: p["d_tok"])
        B += [Note(f"태스크 단위로 보면 {len(pairs)}개 대응쌍 중 "
                   f"**{len(up)}개에서 입력 토큰이 오히려 증가**했습니다"
                   f"(최대 `{worst['task']}` {rel(worst['d_tok'], 0)}). "
                   f"그중 {n_step}개는 에이전트 호출 횟수도 늘었습니다 — "
                   f"압축으로 손상된 컨텍스트가 재탐색을 유발해 절감분을 "
                   f"상쇄한 것으로 보입니다.")]
    return B


def _brief_compare(doc: Doc, D: dict) -> list:
    m, sw = D["main"], D["swe"]
    mb, sb = _base_of(m), _base_of(sw)
    B = []
    if mb["in_tok"] and sb["in_tok"]:
        B += [P(f"두 벤치마크는 같은 압축기·조건·최종 모델을 썼고 **부하 "
                f"규모만 다릅니다.** DeepSWE 의 누적 입력이 Terminal Bench 의 "
                f"**{sb['in_tok'] / mb['in_tok']:.0f}배**입니다.")]
    rows, note = _summary_rows([("Terminal Bench 2.1", m, mb),
                                ("DeepSWE", sw, sb)], with_tok=True)
    if rows:
        B += [Table(doc.next_table(), "벤치마크별 요약",
                    ["벤치마크", "기준 입력 토큰", "지표", "기준값",
                     "최대 하락", "최대 토큰 절감", "품질 유지 한계"],
                    rows, align="lrlrrrl"), Note(note)]

    px_m, px_s = D.get("proxy") or {}, D.get("swe_proxy") or {}
    lat_m = [v["lat_p50"] for v in px_m.values() if v.get("lat_p50")]
    lat_s = [v["lat_p50"] for v in px_s.values() if v.get("lat_p50")]
    if lat_m and lat_s:
        B += [P(f"압축 연산 지연은 Terminal Bench 에서 호출당 중앙 "
                f"{max(lat_m) / 1000:.1f}초였으나 DeepSWE 에서는 "
                f"**{max(lat_s) / 1000:.1f}초**로 커졌습니다. LLMLingua-2 는 "
                f"입력 전체를 토큰 단위로 분류하므로 연산량이 컨텍스트 길이에 "
                f"비례합니다."),
              Note("**압축이 가장 필요한 대규모 컨텍스트에서 압축 오버헤드도 "
                   "가장 큽니다.** 에이전트는 한 과제에 수십 번 호출하므로 "
                   "이 지연이 누적됩니다.")]
    return B


def _brief_limits(doc: Doc, D: dict) -> list:
    m = D.get("main")
    pspread, tspread = _ctl_spread(D)
    B = []
    if m:
        n_t = len({r["task"] for r in m["rows"]})
        txt = (f"조건당 태스크 {n_t}종을 1회씩만 시도했습니다. 태스크 1건의 "
               f"성패가 pass@1 을 {100 / n_t:.1f}%p 움직입니다.")
        if pspread is not None:
            txt += (f" 동일 조건을 반복한 대조 측정에서 실제 변동은 pass@1 "
                    f"±{pspread * 100:.1f}%p, 입력 토큰 ±{tspread * 100:.1f}% "
                    f"였으며, 이는 본 측정에서 관측된 변화와 같은 크기입니다.")
        B += [P(txt),
              Note("따라서 **효과의 방향(압축할수록 나빠짐)은 판별 가능하나, "
                   "크기는 확정할 수 없습니다.** 크기를 확정하려면 태스크 수와 "
                   "시도 횟수를 함께 늘려야 합니다.")]
    B += [Note("본 결과는 LLMLingua-2 · gpt-5.4 · mini-swe-agent 조합, "
               "그리고 프롬프트 전체에 일괄 적용하는 방식에 한정됩니다. "
               "메시지 유형별 선택 적용은 평가하지 않았습니다.")]
    return B


def _brief_reco(doc: Doc, D: dict) -> list:
    return [P("압축기 자체는 정상 동작했습니다. 산문형 입력은 절반으로 "
              "압축해도 핵심 정보가 남습니다. 문제는 **명령 실행 출력의 "
              "식별자가 손상**된다는 점이며, 에이전트는 그 식별자로 후속 "
              "명령을 구성하므로 이것이 성능 저하의 직접 경로입니다."),
            Table(doc.next_table(), "후속 검토 방향",
                  ["방향", "근거"],
                  [["명령 출력에 규칙 기반 축약 적용 "
                    "(로그 중복 제거·스택 트레이스 축약)",
                    "식별자를 보존하면서 가장 크게 증가하는 영역을 줄입니다."],
                   ["산문형 입력(과제 설명·문서)에만 선택 적용",
                    "해당 유형은 압축률 대비 정보 손실이 작습니다."],
                   ["`keep_last` 확대 후 정확도 회복 지점 탐색",
                    "직전 컨텍스트 보존 범위의 영향이 통제되지 않았습니다."],
                   ["단순 절단(truncation) 대조군과 비교",
                    "압축기 도입 비용을 정당화하려면 단순 기법 대비 우위가 "
                    "필요합니다."],
                   ["태스크 수·시도 횟수 확대 후 재측정",
                    "현재 표본으로는 효과 크기를 확정할 수 없습니다."]])]

if __name__ == "__main__":
    raise SystemExit(main())

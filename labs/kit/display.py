"""표 출력.

한글은 글자 폭이 ASCII 의 정확히 2배가 아니라서 공백 패딩으로는 정렬이 안 맞습니다.
노트북에서는 HTML 로 그리고, 일반 파이썬으로 실행할 때는 텍스트로 떨어뜨립니다.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence

try:
    from IPython.display import HTML, display
    from IPython import get_ipython

    _IPY = get_ipython() is not None
except Exception:
    _IPY = False


def table(headers: Sequence[str], rows: Iterable[Sequence[Any]],
          foot: Optional[Sequence[Any]] = None,
          align: Optional[Sequence[str]] = None,
          title: Optional[str] = None, note: Optional[str] = None) -> None:
    rows = [list(r) for r in rows]
    align = list(align) if align else ["left"] + ["right"] * (len(headers) - 1)

    if not _IPY:
        if title:
            print(title)
        widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) + 2 if rows
                  else len(str(h)) + 2 for i, h in enumerate(headers)]

        def fmt(vs):
            return " ".join(str(v).rjust(w) if a == "right" else str(v).ljust(w)
                            for v, w, a in zip(vs, widths, align))

        print(fmt(headers))
        print("-" * sum(widths))
        for r in rows:
            print(fmt(r))
        if foot:
            print("-" * sum(widths))
            print(fmt(foot))
        if note:
            print(note)
        print()
        return

    def td(v, a, tag="td", extra=""):
        return (f'<{tag} style="text-align:{a};padding:5px 16px 5px 0;'
                f'white-space:nowrap;{extra}">{v}</{tag}>')

    head = "".join(td(h, a, "th",
                      "border-bottom:2px solid currentColor;font-weight:600;opacity:.85;")
                   for h, a in zip(headers, align))
    body = "".join("<tr>" + "".join(td(v, a) for v, a in zip(r, align)) + "</tr>" for r in rows)
    if foot:
        body += "<tr>" + "".join(
            td(v, a, "td", "border-top:1px solid currentColor;font-weight:600;")
            for v, a in zip(foot, align)) + "</tr>"

    cap = f'<div style="font-weight:600;margin:6px 0 4px;">{title}</div>' if title else ""
    tail = (f'<div style="opacity:.75;margin-top:6px;font-size:12px;">{note}</div>'
            if note else "")
    display(HTML(
        f'<div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
        f'font-size:13px;line-height:1.5;">{cap}'
        f'<table style="border-collapse:collapse;">'
        f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{tail}</div>'))


def pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.1%}"

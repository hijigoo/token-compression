#!/usr/bin/env python3
"""benchmark_v2 결과 → 한 장짜리 보고서 (md + html).

report.py 는 압축 **자체**의 지표(절감률·식별자 보존·지연)를 그립니다.
이 스크립트가 따로 있는 이유는 benchmark_v2 가 거기에 **품질**을 붙였기
때문입니다 — 압축한 컨텍스트를 실제 모델에 넣고 답을 받아 채점합니다.

    hit@1   첫 번째로 지목한 파일이 정답인가
    recall  정답 파일 중 몇 개를 찾았나

이 둘이 없으면 "절감률 50%" 가 좋은 소식인지 나쁜 소식인지 알 수 없습니다.

렌더링(표·차트·CSS)은 report.py 것을 그대로 씁니다. 같은 코드를 두 벌
두면 한쪽만 고쳐지고 두 리포트의 생김새가 갈립니다.

    ./.venv/bin/python report_v2.py llmlingua2-grid
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
REPORTS = REPO / "reports"
sys.path.insert(0, str(HERE))

import report as _r  # noqa: E402

CHARTS: dict = {}


# ─────────────────────────────────────────────────────────────
# 서식
# ─────────────────────────────────────────────────────────────
def pc(v, d=1):
    return "—" if v is None else f"{v * 100:.{d}f}%"


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.fmean(xs) if xs else None


def sign(v, d=1):
    return "—" if v is None else f"{v * 100:+.{d}f}%p"


# ─────────────────────────────────────────────────────────────
# 집계
# ─────────────────────────────────────────────────────────────
def summarize(runs: list[dict], arms: list[dict]) -> list[dict]:
    """arm 하나당 한 줄. 품질은 `asked=True` 인 행만 셉니다.

    모든 조건에 모델을 물어보지는 않습니다. 조건 24개 × 케이스 14개를
    전부 물으면 336회 호출이라 한 시간을 넘고, 그중 대부분은 압축률만
    조금 다른 이웃 조건입니다. benchmark_v2 는 대표 조건만 `ask=True` 로
    표시해 두었고, 여기서는 그 표시를 따릅니다.
    """
    out = []
    for a in arms:
        mine = [r for r in runs if r["arm"] == a["name"] and not r["error"]]
        if not mine:
            continue
        asked = [r for r in mine if r.get("asked") and not r.get("ask_error")]
        out.append({
            "arm": a["name"], "group": a["group"], "rate": a["rate"],
            "compressor": a["compressor"], "model": a["model"],
            "params": a.get("params") or {}, "protect": a.get("protect") or {},
            "n": len(mine), "n_asked": len(asked),
            "reduction": mean([r["reduction"] for r in mine]),
            "tok_before": mean([r["tokens_before"] for r in mine]),
            "tok_after": mean([r["tokens_after"] for r in mine]),
            "ident": mean([r["ident"] for r in mine]),
            "path": mean([r["path"] for r in mine]),
            "num": mean([r["num"] for r in mine]),
            "latency": mean([r["latency_s"] for r in mine]),
            "hit1": mean([r["hit1"] for r in asked]) if asked else None,
            "recall": mean([r["recall"] for r in asked]) if asked else None,
        })
    return out


def _base(summ):
    return next((s for s in summ if s["arm"] == "none"), None)


# ─────────────────────────────────────────────────────────────
# 본문
# ─────────────────────────────────────────────────────────────
def build_md(d: dict) -> str:
    runs, arms = d["runs"], d["arms"]
    summ = summarize(runs, arms)
    base = _base(summ)
    langs = sorted({r["lang"] for r in runs})
    tasks = sorted({r["task"] for r in runs})

    L = [f"# {d['name']} — LLMLingua-2 조건별 측정", "",
         f"*{d.get('started_at','')} · 조건 {len(summ)}개 · 태스크 {len(tasks)}건 · "
         f"언어 {'/'.join(langs)} · 측정 {len(runs)}회 · "
         f"모델 {d.get('ask_model','—')}*", ""]

    L += ["## 1. 세 줄 요약", ""] + _summary(base, summ)
    L += _how(d, base)
    L += _glossary()
    L += _results(summ, base)
    L += _rate_curve(summ, base)
    L += _groups(summ, base)
    L += _limits(d, summ, base)
    L += _appendix(d, summ)
    return "\n".join(L) + "\n"


def _summary(base, summ) -> list:
    out = []
    if not base:
        return ["기준선(`none`)이 없어 비교할 수 없습니다.", ""]

    comp = [s for s in summ if s["compressor"] == "llmlingua" and s["hit1"] is not None]
    if comp and base["hit1"] is not None:
        # ── 표본이 결론을 감당하는가 ────────────────────────
        # 압축률 곡선이 단조롭지 않으면(덜 줄였는데 품질이 더 나쁘면)
        # 개별 조건의 순위는 우연입니다. 그걸 먼저 말하지 않으면 아래
        # "가장 나은 조건" 이 실제 권고처럼 읽힙니다.
        band = sorted([s for s in summ if s["group"] == "압축률"
                       and s["hit1"] is not None], key=lambda s: s["rate"])
        pts = [(s["rate"], s["hit1"]) for s in band]
        if any(b < a for (_, a), (_, b) in zip(pts, pts[1:])):
            out.append(
                "⚠️ **압축률 곡선이 단조롭지 않습니다.** 덜 줄인 조건이 더 많이 줄인 "
                "조건보다 나쁘게 나온 구간이 있습니다. 표본(태스크 7건)이 조건 간 "
                "순위를 가릴 만큼 크지 않다는 뜻이라, 아래 개별 조건 이름은 "
                "**권고가 아니라 관측**으로 읽어 주세요. 5절에 자세히 적었습니다.")

        # "절감은 큰데 품질은 안 떨어진 조건" 을 찾습니다. 순위표가 아니라
        # 맞바꿈의 무릎이 어디인지가 이 실험의 질문이기 때문입니다.
        keep = [s for s in comp if s["hit1"] >= base["hit1"] - 0.05]
        if keep:
            best = max(keep, key=lambda s: s["reduction"])
            out.append(
                f"품질을 기준선의 5%p 안에서 지키면서 가장 많이 줄인 조건은 "
                f"**{best['arm']}** 입니다 — 토큰 **{pc(best['reduction'])} 절감**, "
                f"hit@1 {pc(base['hit1'],0)} → {pc(best['hit1'],0)} "
                f"({sign(best['hit1'] - base['hit1'])}).")
        else:
            out.append(
                "기준선의 5%p 안을 지킨 압축 조건이 **없습니다.** 이 태스크에서는 "
                "LLMLingua-2 를 켜는 순간 품질이 떨어졌습니다.")

        worst = min(comp, key=lambda s: s["hit1"])
        out.append(
            f"가장 나빴던 조건은 **{worst['arm']}** 로 hit@1 이 "
            f"{pc(base['hit1'],0)} → {pc(worst['hit1'],0)} "
            f"({sign(worst['hit1'] - base['hit1'])}) 였습니다. "
            f"절감은 {pc(worst['reduction'])} 였습니다.")

    lat = [s for s in summ if s["latency"] and s["compressor"] != "none"]
    if lat:
        slow = max(lat, key=lambda s: s["latency"])
        fast = min(lat, key=lambda s: s["latency"])
        out.append(
            f"압축 자체에 드는 시간은 호출당 {fast['latency']:.1f}~{slow['latency']:.1f}초입니다. "
            f"에이전트가 한 과제에 수십 번 호출하므로 이 값이 그대로 곱해집니다.")

    return [f"{i}. {s}" for i, s in enumerate(out, 1)]


def _how(d, base) -> list:
    L = ["", "## 2. 무엇을 어떻게 쟀나", "",
         "**이건 대리 측정입니다.** 에이전트를 끝까지 돌린 게 아니라, 컨텍스트를",
         "한 번 압축해서 모델에 넣고 \"어느 파일을 고쳐야 하나\" 를 물었습니다.",
         "", "```",
         "원본 컨텍스트 ──▶ LLMLingua-2 ──▶ 압축 컨텍스트 ──▶ 모델 1회 호출",
         "                                                      ↓",
         "                                          지목한 파일 ↔ 정답 파일 대조",
         "```", "",
         "그래서 여기의 hit@1 은 **pass@1 이 아닙니다.** 에이전트가 실제로",
         "고쳐서 테스트를 통과했는지는 모릅니다. 대신 조건을 많이 둘 수 있습니다 —",
         "컨테이너 롤아웃은 1회에 5~15분이라 24개 조건을 돌릴 수 없습니다.", ""]

    env = d.get("environment") or {}
    rows = [["측정 회수", f"{len(d['runs'])}회", "조건 × 태스크 × 언어"],
            ["질문 모델", d.get("ask_model", "—"), "압축된 컨텍스트를 받아 답하는 쪽"],
            ["기본 보호 정책", f"`{d.get('protect_default')}`", "모든 조건의 출발점"],
            ["시스템 프롬프트", f"{d.get('system_prompt_chars', 0):,}자",
             "`skip_system=True` 면 이건 압축 대상이 아닙니다"]]
    for k, v in env.items():
        rows.append([f"`{k}`", f"`{v}`", "버전이 바뀌면 수치도 바뀝니다"])
    L += [_r.md_table(["항목", "값", "설명"], rows)]
    return L


def _glossary() -> list:
    rows = [
        ["**절감률**", "압축 뒤 토큰이 얼마나 줄었나",
         "`1 - tokens_after / tokens_before`", "높을수록 좋음"],
        ["**hit@1**", "모델이 첫 번째로 지목한 파일이 정답인가",
         "정답 파일 목록에 들어 있으면 1", "높을수록 좋음"],
        ["**recall**", "정답 파일 중 몇 개를 찾았나",
         "지목한 파일 ∩ 정답 ÷ 정답 개수", "높을수록 좋음"],
        ["**식별자 보존**", "함수·클래스 이름이 살아남은 비율",
         "원본의 대문자 식별자 중 압축본에도 있는 비율", "높을수록 좋음"],
        ["**경로 보존**", "파일 경로가 살아남은 비율",
         "`src/foo/bar.py` 같은 토큰 기준", "높을수록 좋음"],
        ["**숫자 보존**", "숫자가 살아남은 비율",
         "`force_reserve_digit` 의 효과를 보는 값", "높을수록 좋음"],
        ["**압축 지연**", "압축 한 번에 걸린 시간",
         "`latency_s`. 에이전트 호출 수만큼 곱해집니다", "낮을수록 좋음"],
    ]
    return ["", "## 3. 지표 읽는 법", "",
            _r.md_table(["지표", "무엇인가", "어떻게 나오나", "방향"], rows)]


def _results(summ, base) -> list:
    L = ["", "## 4. 조건별 결과", "",
         "`—` 는 그 조건에 모델을 묻지 않았다는 뜻입니다(2절 참고).", ""]
    head = ["조건", "갈래", "rate", "토큰 전→후", "절감", "hit@1", "vs 기준",
            "recall", "식별자", "경로", "숫자", "지연"]
    rows = []
    for s in summ:
        d_hit = (s["hit1"] - base["hit1"]) if (s["hit1"] is not None and base
                                               and base["hit1"] is not None) else None
        rows.append([
            f"`{s['arm']}`", s["group"],
            "—" if s["compressor"] == "none" else f"{s['rate']}",
            f"{s['tok_before']:,.0f} → {s['tok_after']:,.0f}",
            pc(s["reduction"]), pc(s["hit1"], 0),
            "기준" if s["arm"] == "none" else sign(d_hit),
            pc(s["recall"], 0), pc(s["ident"]), pc(s["path"]), pc(s["num"]),
            f"{s['latency']:.1f}s" if s["latency"] else "—",
        ])
    L += [_r.md_table(head, rows)]
    return L


def _rate_curve(summ, base) -> list:
    """rate 를 바꿔 가며 절감과 품질이 어떻게 갈리는지."""
    band = sorted([s for s in summ if s["group"] == "압축률"],
                  key=lambda s: s["rate"])
    if not band:
        return []
    L = ["", "## 5. 압축률을 낮추면 어디서 부러지나", "",
         "`rate` 는 **남길 비율**입니다. 0.3 이면 30% 만 남깁니다.",
         "`—` 는 그 조건에 모델을 묻지 않았다는 뜻입니다.", "",
         "```", f"{'rate':>5}  {'절감':>7}  {'hit@1':>6}  품질"]
    for s in band:
        h = s["hit1"]
        bar = "█" * round(22 * h) if h is not None else ""
        L.append(f"{s['rate']:>5}  {pc(s['reduction']):>7}  "
                 f"{(pc(h, 0) if h is not None else '—'):>6}  {bar}")
    L.append("```")

    # ── 단조성 검사 ──────────────────────────────────────────
    # "rate 를 낮추면 품질이 떨어진다" 가 사실이라면 hit@1 은 rate 를 따라
    # 올라가야 합니다. 실제로 그런지 먼저 봅니다. 뒤집히는 구간이 있으면
    # 무릎을 찾는 일 자체가 의미가 없습니다 — 표본이 곡선을 그릴 만큼
    # 많지 않다는 뜻이기 때문입니다.
    pts = [(s["rate"], s["hit1"]) for s in band if s["hit1"] is not None]
    if len(pts) < 2:
        return L
    inversions = [(a, b) for (ra, a), (rb, b) in zip(pts, pts[1:]) if b < a]
    if inversions:
        worst = max(pts, key=lambda p: p[1])
        L += ["", f"> **곡선이 단조롭지 않습니다.** rate 를 올렸는데 hit@1 이 "
                  f"내려간 구간이 {len(inversions)}곳 있습니다"
                  f"({' · '.join(f'{r}→{pc(h,0)}' for r, h in pts)}).",
              ">",
              "> rate 가 높을수록(덜 줄일수록) 품질이 좋아야 하는데 그렇지 "
              f"않습니다. 최고점이 rate {worst[0]} 에 있는 것도 "
              "설명되지 않습니다.",
              ">",
              "> 이건 **표본이 부족하다는 신호**입니다. 태스크 7건 × 언어 2개로는 "
              "한 건이 7%p 를 움직이기 때문에, 조건 간 10~20%p 차이는 우연으로도 "
              "납니다. 무릎이 어디인지 말하려면 태스크를 늘려야 합니다.",
              ">",
              "> 지금 이 표에서 확실한 것은 **양 끝**뿐입니다 — "
              f"rate {pts[0][0]} 의 {pc(pts[0][1],0)} 는 기준선"
              f"({pc(base['hit1'],0) if base and base['hit1'] is not None else '—'})"
              "에서 크게 떨어졌고, 이건 우연으로 설명하기 어려운 폭입니다."]
        return L

    if base and base["hit1"] is not None:
        knee = next((r for r, h in pts if h < base["hit1"] - 0.05), None)
        if knee is not None:
            L += ["", f"> hit@1 이 기준선에서 5%p 넘게 떨어지는 가장 높은 rate 는 "
                      f"**{knee}** 입니다. 그보다 위는 품질을 지키면서 "
                      f"줄일 수 있는 구간입니다."]
        else:
            L += ["", "> 측정한 범위 안에서는 품질이 5%p 넘게 떨어지는 지점이 "
                      "없었습니다. 더 낮은 rate 를 넣어야 무릎이 보입니다."]
    return L


def _groups(summ, base) -> list:
    """압축률 말고 나머지 갈래 — 옵션·보호 정책·모델 크기·대조군."""
    L = ["", "## 6. 옵션이 실제로 하는 일", ""]
    # 비교 기준은 `none` 이 아니라 **같은 rate 의 기본 압축 조건**입니다.
    # `none` 은 압축기를 안 쓰므로 params 가 비어 있고, 거기에 대면 모든
    # 인자가 "바뀐 것" 으로 찍혀서 무엇을 건드렸는지 알 수 없게 됩니다.
    ref = {s["rate"]: s for s in summ if s["group"] == "압축률"}
    order = ["모델 크기", "압축기 옵션", "보호 정책", "대조군"]
    notes = {
        "모델 크기": "작은 분류 모델로 바꾸면 지연이 줄지만 보존이 떨어질 수 있습니다.",
        "압축기 옵션": "LLMLingua-2 생성자 인자입니다. 부록에 각 인자의 뜻이 있습니다.",
        "보호 정책": "무엇을 압축 **대상에서 뺄지** 정합니다. 압축기 밖의 우리 정책입니다.",
        "대조군": "그냥 뒤를 자릅니다. LLMLingua 가 이보다 나은지 보는 기준입니다.",
    }
    for g in order:
        band = [s for s in summ if s["group"] == g]
        if not band:
            continue
        L += ["", f"### {g}", "", notes.get(g, ""), "",
              f"`vs 같은 rate` 는 같은 `rate` 의 기본 조건(`v2-r…`)과 비교한 값이고, "
              f"`vs 무압축` 은 압축을 아예 안 한 기준선과 비교한 값입니다.", ""]
        rows = []
        for s in band:
            peer = ref.get(s["rate"])
            d_peer = (s["hit1"] - peer["hit1"]) if (
                peer and s["hit1"] is not None and peer["hit1"] is not None
                and peer["arm"] != s["arm"]) else None
            d_base = (s["hit1"] - base["hit1"]) if (
                s["hit1"] is not None and base and base["hit1"] is not None) else None
            rows.append([f"`{s['arm']}`", _diff_note(s, peer), pc(s["reduction"]),
                         pc(s["hit1"], 0), sign(d_peer), sign(d_base),
                         pc(s["ident"]), pc(s["num"]),
                         f"{s['latency']:.1f}s" if s["latency"] else "—"])
        L += [_r.md_table(["조건", "무엇을 바꿨나", "절감", "hit@1",
                           "vs 같은 rate", "vs 무압축", "식별자", "숫자", "지연"], rows)]
    return L


def _diff_note(s, ref) -> str:
    """이 조건이 같은 rate 의 기본 조건에서 무엇을 바꿨는지 한 칸에 적습니다."""
    parts = []
    if ref:
        for k, v in (s["params"] or {}).items():
            if (ref["params"] or {}).get(k) != v:
                parts.append(f"`{k}={v}`")
        for k, v in (s["protect"] or {}).items():
            if (ref["protect"] or {}).get(k) != v:
                parts.append(f"`{k}={v}`")
    if s["compressor"] == "truncate":
        parts.append("LLMLingua 대신 단순 절단")
    elif s["compressor"] == "llmlingua-small":
        parts.append(f"작은 모델 `{s['model'].split('/')[-1]}`")
    return " · ".join(parts) or "기본값과 같음"


_PARAM_DOC = {
    "force_tokens": ("압축해도 반드시 남길 토큰 목록을 켭니다. 줄바꿈·따옴표처럼 "
                     "구조를 지탱하는 글자가 사라지면 모델이 코드 블록의 "
                     "경계를 잃습니다."),
    "force_reserve_digit": ("숫자를 지우지 않습니다. 줄 번호·오프셋·해시가 "
                            "섞인 컨텍스트에서 이걸 끄면 '몇 번째 줄' 이 "
                            "무너집니다."),
    "drop_consecutive": ("같은 토큰이 연달아 남을 때 뒤엣것을 버립니다. 절감은 "
                         "늘지만 반복이 의미인 자리(들여쓰기·표)가 다칩니다."),
    "use_context_level_filter": "문단 단위로 먼저 거르고 토큰 단위로 들어갑니다.",
    "chunk_end_tokens": "청크 경계로 삼을 토큰. 문장이 잘리는 자리를 정합니다.",
}

_PROTECT_DOC = {
    "keep_last": ("뒤에서 몇 개 메시지를 손대지 않을지. 에이전트의 최근 대화는 "
                  "지금 하려는 일이라 지우면 바로 헤맵니다."),
    "min_chars": "이보다 짧은 메시지는 건너뜁니다. 짧은 글은 줄일 게 없습니다.",
    "skip_system": ("system 프롬프트를 압축 대상에서 뺍니다. 여기엔 출력 형식 "
                    "계약이 들어 있어서, 깨지면 모델 성능과 무관하게 파싱이 "
                    "실패합니다."),
}


def _limits(d, summ, base) -> list:
    L = ["", "## 7. 이 표로 말할 수 없는 것", "",
         "- **hit@1 은 pass@1 이 아닙니다.** 고칠 파일을 맞혔다고 실제로 고칠 수 "
         "있는 건 아닙니다. 실제 성공률은 컨테이너 롤아웃 리포트를 보세요.",
         "- **한 번 압축한 결과입니다.** 에이전트는 같은 컨텍스트를 수십 번 "
         "압축하며, 그때마다 조금씩 다른 것이 지워집니다. 그 누적은 여기 없습니다.",
         "- **되읽기가 빠져 있습니다.** 정보가 지워지면 에이전트는 파일을 다시 "
         "읽습니다. 그 추가 토큰이 절감분을 먹는데, 1회 측정에는 잡히지 않습니다."]
    n_ask = sum(1 for r in d["runs"] if r.get("asked"))
    n_arm_ask = sum(1 for s in summ if s["n_asked"])
    L += [f"- **모델에 물은 조건은 {len(summ)}개 중 {n_arm_ask}개**뿐입니다"
          f"(호출 {n_ask}회). 나머지 조건의 hit@1 칸이 `—` 인 이유입니다."]
    if base and base["hit1"] is not None and base["hit1"] < 1.0:
        L += [f"- **기준선도 완벽하지 않습니다**(hit@1 {pc(base['hit1'],0)}, "
              f"recall {pc(base['recall'],0)}). 압축 조건의 하락분에는 "
              f"과제 자체의 난이도가 섞여 있습니다."]
    return L


def _appendix(d, summ) -> list:
    L = ["", "## 부록 A. 옵션 사전", "",
         "표에 나온 인자들이 실제로 무엇을 하는지입니다.", "",
         "### LLMLingua-2 인자", ""]
    L += [_r.md_table(["인자", "하는 일"],
                      [[f"`{k}`", v] for k, v in _PARAM_DOC.items()])]
    L += ["", "### 보호 정책 (압축기 밖, 우리 코드)", ""]
    L += [_r.md_table(["인자", "하는 일"],
                      [[f"`{k}`", v] for k, v in _PROTECT_DOC.items()])]

    L += ["", "## 부록 B. 재현", "", "```bash",
          "cd labs/agentic-eval",
          "export OPENAI_API_KEY=$(az account get-access-token \\",
          "  --scope https://cognitiveservices.azure.com/.default --query accessToken -o tsv)",
          "export UPSTREAM_BASE_URL=https://<리소스>.cognitiveservices.azure.com/openai",
          f"./.venv/bin/python benchmark_v2.py --name {d['name']}",
          f"./.venv/bin/python report_v2.py {d['name']}",
          "```", "",
          f"측정에 걸린 시간: {d.get('elapsed_s', 0) / 60:.0f}분", ""]
    return L


# ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="benchmark_v2 결과 보고서")
    ap.add_argument("name")
    args = ap.parse_args()

    d_dir = REPORTS / args.name
    src = d_dir / "results.json"
    if not src.exists():
        sys.exit(f"✗ 결과가 없습니다: {src}")

    d = json.loads(src.read_text(encoding="utf-8"))
    md = build_md(d)
    (d_dir / "report.md").write_text(md, encoding="utf-8")
    _r.CHARTS.update(CHARTS)
    (d_dir / "report.html").write_text(_r.build_html(md, d["name"]), encoding="utf-8")

    summ = summarize(d["runs"], d["arms"])
    print(f"▸ 조건 {len(summ)}개 · 측정 {len(d['runs'])}회")
    print(f"▸ {(d_dir / 'report.md').relative_to(REPO)} · report.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

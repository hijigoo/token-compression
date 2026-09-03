#!/usr/bin/env python3
"""LLMLingua-2 심화 벤치마크 — 실제 모델 호출로 품질까지 잽니다.

    ./.venv/bin/python benchmark_v2.py --name v2-deep
    ./.venv/bin/python benchmark_v2.py --quick        # 시험용

## 앞선 벤치마크와 무엇이 다른가

`benchmark.py` 는 압축 전후의 **문자열**만 봤습니다. 정답 문자열이 남았는지
세는 것이라 값싸지만, 모델이 그걸 읽고 실제로 판단할 수 있는지는 모릅니다.

여기서는 한 걸음 더 갑니다. 압축된 컨텍스트를 **실제 모델에 넣고** 물어봅니다.

    "이 과제를 풀려면 어느 파일을 고쳐야 합니까?"

정답은 `solution.patch` 가 바꾼 파일 목록입니다. 사람이 채점하지 않아도
자동으로 맞출 수 있습니다.

## 왜 하필 이 질문인가

에이전트가 컨테이너에서 가장 먼저 하는 판단이 이것입니다. 여기서 틀리면
엉뚱한 파일을 열고, 남은 시간을 거기에 씁니다. **파일을 못 찾으면 pass@1 은
거의 확실히 0 입니다.**

반대로 맞혔다고 해서 반드시 푼다는 뜻은 아닙니다. 그러니 이 지표도 여전히
상한 쪽 근사입니다. 다만 문자열 보존율보다는 훨씬 실제에 가깝습니다.

## 여전히 재지 못하는 것

**되읽기.** 실제 롤아웃에서는 정보가 깨지면 에이전트가 파일을 다시 읽어
턴이 늘고, 그래서 총 토큰이 오히려 늘기도 합니다(MS 문서에서 6건 중 2건).
여기서는 컨텍스트를 한 번만 압축하므로 그 되먹임이 없습니다.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import statistics as st
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "labs"))

import benchmark as B  # noqa: E402  (컨텍스트 조립·지표를 그대로 씁니다)

EN, KO = B.EN, B.KO


def log(msg: str) -> None:
    print(f"\033[36m▸ {msg}\033[0m", flush=True)


# ═══════════════════════════════════════════════════════════════
# 정답 — solution.patch 가 실제로 바꾼 파일
# ═══════════════════════════════════════════════════════════════

def truth_files(task: str) -> list:
    patch = (EN / task / "solution" / "solution.patch").read_text(
        encoding="utf-8", errors="replace")
    files = []
    for m in re.finditer(r"^\+\+\+ b/(\S+)", patch, re.M):
        if m.group(1) not in files:
            files.append(m.group(1))
    return files


ASK = """아래는 소프트웨어 과제의 작업 컨텍스트입니다. 일부가 압축되어 있어
문장이 끊겨 있을 수 있습니다.

이 과제를 해결하려면 **어느 파일을 수정해야 합니까?**

- 저장소 기준 상대 경로로 답하세요 (예: `pkg/foo/bar.go`)
- 확실한 것부터 최대 5개까지, 한 줄에 하나씩만 쓰세요
- 설명이나 머리말 없이 경로만 쓰세요
- 컨텍스트가 손상되어 판단할 수 없으면 UNKNOWN 이라고만 쓰세요

--- 컨텍스트 시작 ---
{ctx}
--- 컨텍스트 끝 ---"""

PATH_LINE = re.compile(r"[\w./+-]+\.(?:py|go|ts|js|rs|toml|yaml|yml|json)")


def parse_answer(text: str) -> list:
    out = []
    for m in PATH_LINE.finditer(text or ""):
        p = m.group(0).lstrip("./")
        if p not in out:
            out.append(p)
    return out[:5]


def score_answer(answer: list, truth: list) -> dict:
    """맞힌 정도를 두 가지로 잰다.

    hit@1   첫 번째로 댄 파일이 정답 안에 있나 — 에이전트는 보통 첫 것부터 연다
    recall  정답 파일 중 몇 개를 짚었나
    """
    if not answer:
        return {"hit1": 0.0, "recall": 0.0, "n_answer": 0}
    tset = set(truth)

    def match(a):
        # 경로 표기가 조금 달라도 파일 이름이 같으면 맞은 것으로 본다.
        # 압축이 앞쪽 디렉터리를 깎는 경우가 있어서다.
        return a in tset or any(t.endswith("/" + a) or a.endswith("/" + t)
                                or Path(t).name == Path(a).name for t in tset)

    hits = [a for a in answer if match(a)]
    return {
        "hit1": 1.0 if match(answer[0]) else 0.0,
        "recall": len({Path(a).name for a in hits}) / max(len(tset), 1),
        "n_answer": len(answer),
    }


# ═══════════════════════════════════════════════════════════════
# 조건 — LLMLingua-2 만, 옵션을 넓게
# ═══════════════════════════════════════════════════════════════

LARGE = "llmlingua-2-xlm-roberta-large (2.2GB)"
SMALL = "llmlingua-2-bert-base-multilingual (700MB)"
BASE_PROTECT = {"keep_last": 2, "min_chars": 400, "skip_system": True}
BEST = dict(force_reserve_digit=True, drop_consecutive=True, force_tokens=False)


def arm(name, comp, model, rate, params, protect, group, ask=False) -> dict:
    return dict(name=name, compressor=comp, model=model, rate=rate,
                params=dict(params), protect=dict(protect), group=group,
                ask=ask)


def build_arms(quick: bool) -> list:
    if quick:
        return [
            arm("none", "none", "—", 1.0, {}, BASE_PROTECT, "기준선", ask=True),
            arm("v2-r0.5", "llmlingua", LARGE, 0.5, BEST, BASE_PROTECT,
                "압축률", ask=True),
        ]

    A = []
    # ── 기준선 ────────────────────────────────────────────────
    # 압축을 하지 않은 컨텍스트로 같은 질문을 던진다. 이게 없으면 정확도
    # 숫자가 높은지 낮은지 판단할 수 없다.
    A.append(arm("none", "none", "—", 1.0, {}, BASE_PROTECT, "기준선", ask=True))

    # ── 압축률 ────────────────────────────────────────────────
    for r in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        A.append(arm(f"v2-r{r}", "llmlingua", LARGE, r, BEST, BASE_PROTECT,
                     "압축률", ask=r in (0.2, 0.3, 0.5, 0.7, 0.9)))

    # ── 모델 크기 ─────────────────────────────────────────────
    for r in (0.3, 0.5, 0.7):
        A.append(arm(f"v2s-r{r}", "llmlingua-small", SMALL, r, BEST,
                     BASE_PROTECT, "모델 크기", ask=r == 0.5))

    # ── 압축기 옵션 ───────────────────────────────────────────
    for label, over in [
        ("tokens-on", dict(force_tokens=True)),
        ("no-digit", dict(force_reserve_digit=False)),
        ("no-drop", dict(drop_consecutive=False)),
        ("plain", dict(force_reserve_digit=False, drop_consecutive=False,
                       force_tokens=False)),
    ]:
        A.append(arm(f"v2-r0.5-{label}", "llmlingua", LARGE, 0.5,
                     {**BEST, **over}, BASE_PROTECT, "압축기 옵션",
                     ask=label in ("tokens-on", "plain")))

    # ── 보호 정책 ─────────────────────────────────────────────
    for label, prot in [
        ("keep0", {**BASE_PROTECT, "keep_last": 0}),
        ("keep4", {**BASE_PROTECT, "keep_last": 4}),
        ("min0", {**BASE_PROTECT, "min_chars": 0}),
        ("min1500", {**BASE_PROTECT, "min_chars": 1500}),
        ("sys-compress", {**BASE_PROTECT, "skip_system": False}),
    ]:
        A.append(arm(f"v2-r0.5-{label}", "llmlingua", LARGE, 0.5, BEST, prot,
                     "보호 정책", ask=label in ("keep0", "sys-compress")))

    # ── 대조군 ────────────────────────────────────────────────
    for r in (0.3, 0.5, 0.7):
        A.append(arm(f"truncate-r{r}", "truncate", "—", r, {}, BASE_PROTECT,
                     "대조군", ask=r == 0.5))
    return A


# ═══════════════════════════════════════════════════════════════

@dataclass
class Run:
    arm: str
    group: str
    compressor: str
    model: str
    rate: float
    params: dict
    protect: dict
    task: str
    lang: str
    # 압축 지표
    chars_before: int = 0
    chars_after: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    reduction: float = 0.0
    ident: float = 0.0
    path: float = 0.0
    num: float = 0.0
    latency_s: float = 0.0
    # 품질 지표 (실제 모델 호출)
    asked: bool = False
    hit1: float = 0.0
    recall: float = 0.0
    n_answer: int = 0
    answer: list = field(default_factory=list)
    truth: list = field(default_factory=list)
    ask_latency_s: float = 0.0
    ask_error: str = ""
    error: str = ""


def main() -> int:
    p = argparse.ArgumentParser(description="LLMLingua-2 심화 벤치마크")
    p.add_argument("--name", default=None)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--no-ask", action="store_true", help="모델 호출 생략")
    args = p.parse_args()

    from kit import env, tokens as T
    from kit.provider import complete, ContentFiltered
    import compressors as C

    env.load()
    dep = env.get("AZURE_OPENAI_DEPLOYMENT")
    counter = T.make_counter({"mode": "local"}, "gpt-5.4")

    tasks = sorted(x.name for x in KO.iterdir() if x.is_dir())
    if args.quick:
        tasks = tasks[:2]
    cases = [B.build_case(t, lang) for t in tasks for lang in ("en", "ko")]
    truths = {t: truth_files(t) for t in tasks}
    arms = build_arms(args.quick)
    n_ask = sum(1 for a in arms if a["ask"] and not args.no_ask) * len(cases)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = args.name or f"v2-deep-{stamp}"
    out_dir = REPO / "reports" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    log(f"조건 {len(arms)} × 케이스 {len(cases)} = {len(arms) * len(cases)}회 압축")
    log(f"그중 모델 호출 {n_ask}회 · 모델 {dep}")
    log(f"태스크 {len(tasks)}건 · 정답 파일 "
        f"{st.mean(len(v) for v in truths.values()):.1f}개/태스크 평균")

    runs, t0all = [], time.perf_counter()
    for i, a in enumerate(arms, 1):
        t0 = time.perf_counter()
        for case in cases:
            C.set_policy(**a["protect"])
            if a["params"]:
                C.set_params(**a["params"])
            fn = C.get(a["compressor"])

            before = "\n".join(m["content"] for m in case.messages)
            tc = time.perf_counter()
            try:
                out_msgs = fn(case.messages, a["rate"])
                err = ""
            except Exception as e:  # noqa: BLE001
                out_msgs, err = case.messages, f"{type(e).__name__}: {e}"
            dt = time.perf_counter() - tc
            after = "\n".join(m["content"] for m in out_msgs)
            tb, ta = counter(before), counter(after)

            r = Run(arm=a["name"], group=a["group"], compressor=a["compressor"],
                    model=a["model"], rate=a["rate"], params=dict(a["params"]),
                    protect=dict(a["protect"]), task=case.task, lang=case.lang,
                    chars_before=len(before), chars_after=len(after),
                    tokens_before=tb, tokens_after=ta,
                    reduction=(1 - ta / tb) if tb else 0.0,
                    ident=B.survival(after, case.must_ident),
                    path=B.survival(after, case.must_path),
                    num=B.survival(after, case.must_num),
                    latency_s=dt, error=err,
                    truth=truths[case.task])

            if a["ask"] and not args.no_ask:
                r.asked = True
                ta0 = time.perf_counter()
                try:
                    body, _ = complete(ASK.format(ctx=after), dep,
                                       max_output_tokens=512, timeout=180)
                    r.answer = parse_answer(body)
                    r.__dict__.update(score_answer(r.answer, r.truth))
                except ContentFiltered:
                    # 압축 결과가 뜻 없는 글자열이 되면 필터에 걸린다.
                    # 그것도 결과이므로 0점이 아니라 '측정 실패' 로 남긴다.
                    r.ask_error = "ContentFiltered"
                except Exception as e:  # noqa: BLE001
                    r.ask_error = f"{type(e).__name__}: {str(e)[:120]}"
                r.ask_latency_s = time.perf_counter() - ta0
            runs.append(r)

        got = [r for r in runs[-len(cases):] if not r.error]
        asked = [r for r in got if r.asked and not r.ask_error]
        red = st.mean(r.reduction for r in got) if got else 0.0
        msg = (f"  [{i:2d}/{len(arms)}] {a['name']:20s} 절감 {red:6.1%} · "
               f"식별자 {st.mean(r.ident for r in got):6.1%}")
        if asked:
            msg += (f" · hit@1 {st.mean(r.hit1 for r in asked):5.0%}"
                    f" · recall {st.mean(r.recall for r in asked):5.0%}")
        print(msg + f" · {time.perf_counter() - t0:5.1f}s", flush=True)

    payload = {
        "name": name, "started_at": stamp,
        "elapsed_s": round(time.perf_counter() - t0all, 1),
        "suite": "llmlingua-2 심화 · 실제 모델 호출 포함",
        "ask_model": dep,
        "ask_prompt": ASK,
        "environment": {"python": platform.python_version(),
                        "platform": platform.platform(), **B._versions()},
        "protect_default": BASE_PROTECT,
        "system_prompt_chars": len(B.SYSTEM),
        "tasks": tasks, "truth_files": truths,
        "arms": arms, "runs": [asdict(r) for r in runs],
    }
    (out_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"결과 {len(runs)}행 → {(out_dir / 'results.json').relative_to(REPO)}")
    print(f"  리포트: ./.venv/bin/python report_v2.py {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

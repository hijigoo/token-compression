#!/usr/bin/env python3
"""압축기 벤치마크 — DeepSWE 태스크의 실제 텍스트로.

    ./.venv/bin/python benchmark.py                 # 전체
    ./.venv/bin/python benchmark.py --quick         # 태스크 2건만
    ./.venv/bin/python benchmark.py --name my-run   # 리포트 폴더 이름

무엇을 재나
-----------
에이전트가 모델에게 보내는 `messages` 를 실제 태스크 파일로 조립하고,
프록시와 **같은 경로**(compressors.get(...))로 압축해 전후를 잰다.

무엇을 재지 않나
----------------
**pass@1 은 재지 않는다.** 그건 에이전트를 3시간씩 실제로 돌려야 나온다
(Docker + pier). 여기서 나오는 것은 그 앞단의 값싼 지표다.

MS 공유 문서는 `품질` 열에 pass@1 계열 점수를 실었다. 이 벤치마크에는 그
열이 없다. 대신 **보존율**이 있는데, 둘은 다른 값이므로 나란히 놓고
"품질이 이렇다" 고 읽으면 안 된다. 보존율은 상한도 하한도 아닌 선행
지표다 — 정답에 필요한 문자열이 사라졌다면 맞힐 길이 없으므로 낮으면
확실히 나쁘고, 높다고 반드시 좋지는 않다.

왜 이 지표들인가
----------------
에이전트는 압축된 컨텍스트를 읽고 **파일을 찾아 고친다.** 그래서 절감률
하나로는 부족하고, 무엇이 살아남았는지를 종류별로 봐야 한다.

    식별자   함수·클래스·변수명. 사라지면 무엇을 고칠지 모른다
    경로     파일 경로. 깨지면 패치가 적용조차 안 된다
    숫자     임계값·크기. 한 자리만 틀려도 테스트가 떨어진다
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import statistics as st
import subprocess
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "labs"))

EN = HERE / "datasets" / "deep-swe" / "tasks"
KO = HERE / "datasets" / "deep-swe-ko" / "tasks"


def log(msg: str) -> None:
    print(f"\033[36m▸ {msg}\033[0m", flush=True)


def die(msg: str) -> None:
    print(f"\033[31m✗ {msg}\033[0m", file=sys.stderr)
    raise SystemExit(1)


# ═══════════════════════════════════════════════════════════════
# 컨텍스트 조립
#
# 지시문만 압축하면 실제 상황과 다르다. 에이전트 컨텍스트의 대부분은
# **읽어들인 파일 내용과 툴 출력**이고, 지시문은 극히 일부다.
#
# 그래서 태스크에 실제로 들어 있는 코드(solution.patch·test.patch)를
# 툴 출력 자리에 넣어 실제 롤아웃과 비슷한 모양을 만든다. 지어낸 텍스트를
# 쓰지 않으려는 것이다.
#
# 한국어 쪽은 **지시문만** 한국어다. 코드는 그대로 영어다. 실제로 한국어
# 지시를 받은 에이전트가 보는 것도 이 모양이다.
# ═══════════════════════════════════════════════════════════════

SYSTEM = (
    "You are a coding agent operating in a Linux shell. You have exactly one "
    "tool: bash. Respond with exactly one command inside a ```bash code block. "
    "Do not explain. Do not output anything outside the code block. "
    "After each command you will receive its output as an OBSERVATION. "
    "Work on a new branch from main and commit everything when you are done. "
    "If a command fails, read the error and try a different approach. "
    "Never run interactive commands. Never wait for user input."
)


@dataclass
class Case:
    task: str
    lang: str
    messages: list
    must_ident: list      # 살아남아야 할 식별자
    must_path: list       # 살아남아야 할 파일 경로
    must_num: list        # 살아남아야 할 숫자


IDENT_PATTERNS = [
    r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b",         # snake_case
    r"\b[a-z]+(?:[A-Z][a-z0-9]*)+\b",             # camelCase
    r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b",     # PascalCase
]
PATH_RE = r"\b[\w./-]+\.(?:py|go|ts|js|rs|toml|yaml|yml|json)\b"
NUM_RE = r"\b\d{1,3}(?:,\d{3})+\b|\b\d{4,}\b"     # 3,000 또는 1800 같은 값

STOP = {"the", "and", "not", "for", "with", "this", "that"}


def _pick(text: str, patterns, limit: int) -> list:
    """빈도 높은 순으로 고른다. 한 번만 나오는 것은 잡음일 수 있다."""
    seen: dict = {}
    pats = patterns if isinstance(patterns, list) else [patterns]
    for pat in pats:
        for m in re.findall(pat, text):
            tok = m if isinstance(m, str) else m[0]
            if len(tok) < 4 or tok.lower() in STOP:
                continue
            seen[tok] = seen.get(tok, 0) + 1
    ranked = sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _ in ranked[:limit]]


def build_case(task: str, lang: str) -> Case:
    src = (EN if lang == "en" else KO) / task
    inst = (src / "instruction.md").read_text(encoding="utf-8")

    # 실제 코드. 에이전트가 파일을 열어봤을 때 보게 될 것과 같은 내용이다.
    sol = (EN / task / "solution" / "solution.patch").read_text(
        encoding="utf-8", errors="replace")
    tst = (EN / task / "tests" / "test.patch").read_text(
        encoding="utf-8", errors="replace")

    # 통째로 넣으면 태스크마다 크기가 너무 벌어져 비교가 어렵다. 앞쪽을
    # 잘라 쓴다 — 에이전트도 파일 전체를 한 번에 보지는 않는다.
    code_a, code_b = sol[:6000], tst[:4000]

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": inst},
        {"role": "assistant", "content": "```bash\nls -R . | head -50\n```"},
        {"role": "user", "content": "OBSERVATION:\n" + code_a},
        {"role": "assistant", "content": "```bash\ncat tests/test_main.py\n```"},
        {"role": "user", "content": "OBSERVATION:\n" + code_b},
        {"role": "assistant", "content": "```bash\npython -m pytest -x\n```"},
        {"role": "user", "content": "OBSERVATION:\n1 failed, 42 passed"},
    ]

    whole = inst + code_a + code_b
    return Case(
        task=task, lang=lang, messages=messages,
        must_ident=_pick(whole, IDENT_PATTERNS, 40),
        must_path=_pick(whole, PATH_RE, 20),
        must_num=_pick(whole, NUM_RE, 10),
    )


# ═══════════════════════════════════════════════════════════════
# 지표
# ═══════════════════════════════════════════════════════════════

def survival(text: str, needles: list) -> float:
    if not needles:
        return 1.0
    return sum(1 for n in needles if n in text) / len(needles)


def structure(text: str) -> dict:
    return {
        "newline": text.count("\n"),
        "backtick": text.count("`"),
        "brace": text.count("{") + text.count("}"),
        "paren": text.count("(") + text.count(")"),
    }


# ═══════════════════════════════════════════════════════════════
# 실행
# ═══════════════════════════════════════════════════════════════

@dataclass
class Run:
    """한 조건 한 케이스의 결과. **입력 변수를 전부 함께 남긴다.**

    나중에 표만 보고 "무슨 설정이었지" 를 되짚을 수 있어야 한다.
    """
    # ── 입력 ──
    arm: str
    group: str
    compressor: str
    model: str
    rate: float
    params: dict
    protect: dict
    task: str
    lang: str
    # ── 출력 ──
    chars_before: int = 0
    chars_after: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    reduction: float = 0.0
    ident: float = 0.0
    path: float = 0.0
    num: float = 0.0
    struct_before: dict = field(default_factory=dict)
    struct_after: dict = field(default_factory=dict)
    latency_s: float = 0.0
    n_touched: int = 0
    error: str = ""


def run_one(arm: dict, case: Case, counter) -> Run:
    import compressors as C

    C.set_policy(**arm["protect"])
    if arm.get("params"):
        C.set_params(**arm["params"])
    fn = C.get(arm["compressor"])

    before = "\n".join(m["content"] for m in case.messages)
    t0 = time.perf_counter()
    try:
        out_msgs = fn(case.messages, arm["rate"])
        err = ""
    except Exception as e:  # noqa: BLE001
        out_msgs, err = case.messages, f"{type(e).__name__}: {e}"
    dt = time.perf_counter() - t0
    after = "\n".join(m["content"] for m in out_msgs)

    tb, ta = counter(before), counter(after)
    return Run(
        arm=arm["name"], group=arm.get("group", ""),
        compressor=arm["compressor"], model=arm["model"],
        rate=arm["rate"], params=dict(arm.get("params") or {}),
        protect=dict(arm["protect"]), task=case.task, lang=case.lang,
        chars_before=len(before), chars_after=len(after),
        tokens_before=tb, tokens_after=ta,
        reduction=(1 - ta / tb) if tb else 0.0,
        ident=survival(after, case.must_ident),
        path=survival(after, case.must_path),
        num=survival(after, case.must_num),
        struct_before=structure(before), struct_after=structure(after),
        latency_s=dt,
        n_touched=sum(1 for a, b in zip(case.messages, out_msgs)
                      if a["content"] != b["content"]),
        error=err,
    )


# ═══════════════════════════════════════════════════════════════
# 조건 정의
# ═══════════════════════════════════════════════════════════════

BASE_PROTECT = {"keep_last": 2, "min_chars": 400, "skip_system": True}


def build_arms(full: bool) -> list:
    """압축기 × 모델 × 압축률 × 옵션 × 보호정책.

    세 갈래로 나눈다.

      스윕   압축률을 바꿔가며 절감·보존의 맞바꿈 곡선을 본다
      절제   압축률을 고정하고 옵션을 하나씩 꺼서 그 옵션의 기여를 본다
      대조   그냥 잘라내기. 정교한 압축기가 이보다 나은지 보는 기준선

    절제(ablation)를 따로 두는 이유는, 옵션을 여러 개 동시에 바꾸면
    무엇 덕분인지 알 수 없기 때문이다.

    v1 은 케이스당 십수 초가 걸린다(1.5B 를 CPU 에서 돌린다). 그래서 v1 은
    압축률 3개만 보고 절제는 옵션 2개로 줄였다. 빠진 조건이 있다는 사실을
    리포트에서 밝힌다.
    """
    ALL = dict(force_reserve_digit=True, drop_consecutive=True, force_tokens=True)
    V2 = "llmlingua-2-xlm-roberta-large (2.2GB)"
    V2S = "llmlingua-2-bert-base-multilingual (700MB)"
    V1M = "Qwen/Qwen2.5-1.5B (3GB)"

    if full == "notokens":
        # force_tokens 를 끈 스윕. 본 측정에서 이 옵션이 경로를 망가뜨리는
        # 것이 드러나 같은 축을 다시 잽니다.
        NT = dict(force_reserve_digit=True, drop_consecutive=True,
                  force_tokens=False)
        out = []
        for r in (0.3, 0.5, 0.7, 0.9):
            out.append(dict(name=f"v2-nt-r{r}", compressor="llmlingua", model=V2,
                            rate=r, params=NT, protect=BASE_PROTECT,
                            group="스윕(force_tokens 끔)"))
            out.append(dict(name=f"v2s-nt-r{r}", compressor="llmlingua-small",
                            model=V2S, rate=r, params=NT, protect=BASE_PROTECT,
                            group="스윕(force_tokens 끔)"))
        for r in (0.3, 0.5, 0.7):
            out.append(dict(name=f"v1-nt-r{r}", compressor="llmlingua-v1",
                            model=V1M, rate=r, params=NT, protect=BASE_PROTECT,
                            group="스윕(force_tokens 끔)"))
        return out

    if not full:
        return [
            dict(name="truncate-r0.5", compressor="truncate", model="—",
                 rate=0.5, params={}, protect=BASE_PROTECT, group="대조"),
            dict(name="v1-r0.5", compressor="llmlingua-v1", model=V1M,
                 rate=0.5, params=ALL, protect=BASE_PROTECT, group="스윕"),
            dict(name="v2-r0.5", compressor="llmlingua", model=V2,
                 rate=0.5, params=ALL, protect=BASE_PROTECT, group="스윕"),
        ]

    arms = []

    # ── 압축률 스윕 ───────────────────────────────────────────
    for r in (0.3, 0.5, 0.7, 0.9):
        arms.append(dict(name=f"truncate-r{r}", compressor="truncate", model="—",
                         rate=r, params={}, protect=BASE_PROTECT, group="대조"))
        arms.append(dict(name=f"v2-r{r}", compressor="llmlingua", model=V2,
                         rate=r, params=ALL, protect=BASE_PROTECT, group="스윕"))
        arms.append(dict(name=f"v2s-r{r}", compressor="llmlingua-small", model=V2S,
                         rate=r, params=ALL, protect=BASE_PROTECT, group="스윕"))
    for r in (0.3, 0.5, 0.7):          # v1 은 느려서 3개만
        arms.append(dict(name=f"v1-r{r}", compressor="llmlingua-v1", model=V1M,
                         rate=r, params=ALL, protect=BASE_PROTECT, group="스윕"))

    # ── 압축기 옵션 절제 (rate 0.5 고정) ──────────────────────
    for label, over in [
        ("no-digit", dict(force_reserve_digit=False)),
        ("no-drop", dict(drop_consecutive=False)),
        ("no-tokens", dict(force_tokens=False)),
    ]:
        arms.append(dict(name=f"v2-r0.5-{label}", compressor="llmlingua", model=V2,
                         rate=0.5, params={**ALL, **over},
                         protect=BASE_PROTECT, group="옵션 절제"))
    for label, over in [
        ("no-digit", dict(force_reserve_digit=False)),
        ("no-tokens", dict(force_tokens=False)),
    ]:
        arms.append(dict(name=f"v1-r0.5-{label}", compressor="llmlingua-v1", model=V1M,
                         rate=0.5, params={**ALL, **over},
                         protect=BASE_PROTECT, group="옵션 절제"))

    # ── 보호 정책 절제 (rate 0.5 고정) ────────────────────────
    for label, prot in [
        ("keeplast0", {**BASE_PROTECT, "keep_last": 0}),
        ("nosysguard", {**BASE_PROTECT, "skip_system": False}),
        ("minchars0", {**BASE_PROTECT, "min_chars": 0}),
    ]:
        arms.append(dict(name=f"v2-r0.5-{label}", compressor="llmlingua", model=V2,
                         rate=0.5, params=ALL, protect=prot, group="보호 절제"))
    return arms


# ═══════════════════════════════════════════════════════════════

def main() -> int:
    p = argparse.ArgumentParser(description="압축기 벤치마크")
    p.add_argument("--name", default=None, help="리포트 폴더 이름")
    p.add_argument("--quick", action="store_true", help="태스크 2건·압축률 1개")
    p.add_argument("--matrix", default=None, choices=["notokens"],
                   help="보완 행렬만 돌립니다")
    p.add_argument("--tasks", nargs="*", default=None)
    args = p.parse_args()

    if not KO.is_dir():
        die("한국어 데이터셋이 없습니다. python translate.py stage 를 먼저 돌려주세요.")

    tasks = args.tasks or sorted(x.name for x in KO.iterdir() if x.is_dir())
    if args.quick:
        tasks = tasks[:2]

    from kit import env, tokens as T
    env.load()
    counter = T.make_counter({"mode": "local"}, "gpt-5.4")

    arms = build_arms(full=args.matrix or (not args.quick))
    cases = [build_case(t, lang) for t in tasks for lang in ("en", "ko")]
    total = len(arms) * len(cases)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = args.name or f"llmlingua-{stamp}"
    out_dir = REPO / "reports" / name
    out_dir.mkdir(parents=True, exist_ok=True)

    log(f"조건 {len(arms)} × 케이스 {len(cases)} = {total}회")
    log(f"태스크 {len(tasks)}건 · 언어 en/ko · 리포트 {out_dir.relative_to(REPO)}")

    runs, t_start = [], time.perf_counter()
    for i, arm in enumerate(arms, 1):
        t0 = time.perf_counter()
        for case in cases:
            runs.append(run_one(arm, case, counter))
        done = [r for r in runs[-len(cases):] if not r.error]
        red = st.mean([r.reduction for r in done]) if done else 0.0
        idt = st.mean([r.ident for r in done]) if done else 0.0
        bad = len(cases) - len(done)
        print(f"  [{i:2d}/{len(arms)}] {arm['name']:22s} "
              f"절감 {red:6.1%} · 식별자 {idt:6.1%} · "
              f"{time.perf_counter() - t0:5.1f}s"
              + (f" · 실패 {bad}" if bad else ""), flush=True)

    payload = {
        "name": name,
        "started_at": stamp,
        "elapsed_s": round(time.perf_counter() - t_start, 1),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            **_versions(),
        },
        "protect_default": BASE_PROTECT,
        "system_prompt_chars": len(SYSTEM),
        "tasks": tasks,
        "arms": arms,
        "runs": [asdict(r) for r in runs],
    }
    (out_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"결과 {len(runs)}행 → {(out_dir / 'results.json').relative_to(REPO)}")
    print(f"  리포트: ./.venv/bin/python report.py {name}")
    return 0


def _versions() -> dict:
    out = {}
    for mod in ("transformers", "torch", "llmlingua", "tiktoken"):
        try:
            import importlib.metadata as m
            out[mod] = m.version(mod)
        except Exception:  # noqa: BLE001
            out[mod] = "없음"
    return out


if __name__ == "__main__":
    raise SystemExit(main())

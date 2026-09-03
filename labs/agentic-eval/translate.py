#!/usr/bin/env python3
"""DeepSWE 태스크 지시문을 한국어로 만들고, 한국어 데이터셋을 세운다.

왜 필요한가
-----------
DeepSWE 의 `instruction.md` 는 전부 영어다. 한국어에서도 압축이 같은 효과를
내는지 보려면 같은 태스크의 한국어판이 있어야 한다. 채점은 테스트 코드가
하므로 **지시문만** 번역하면 된다. 나머지(Dockerfile·테스트·정답 패치)는
손대지 않는다.

무엇이 위험한가
---------------
번역기가 식별자를 건드리면 태스크가 풀 수 없게 된다. `sort_by_label` 이
`정렬_기준_라벨` 이 되면 에이전트가 찾을 함수가 사라진다. 그러면 실패의
원인이 압축인지 번역인지 알 수 없게 된다. 그래서 `verify` 를 반드시 거친다.

쓰는 법
-------
    python translate.py list                  상태 보기
    python translate.py translate <태스크>…    번역 (--all 로 전체)
    python translate.py verify                식별자가 살아남았는지 검사
    python translate.py stage                 deep-swe-ko/tasks/ 생성

번역 결과는 `i18n/ko/<태스크>.md` 에 남는다. `deep-swe/` 는 gitignore 대상이라
다시 클론하면 사라지지만, 이쪽은 커밋되므로 번역 비용을 다시 치르지 않는다.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DATASETS = HERE / "datasets"
TRANSLATIONS = HERE / "translations"

# 벤치마크마다 원본 태스크가 어디 있는지 다르다. Terminal Bench 를 붙일 때
# 여기 한 줄만 늘리면 된다.
BENCHMARKS = {
    "deep-swe": "tasks",          # datasets/deep-swe/tasks/<태스크>/
}

# 명령별로 아래 세 경로를 쓴다. main() 이 --benchmark 를 읽어 채운다.
TASKS_EN: Path
KO_DIR: Path
STAGE_KO: Path


def set_benchmark(name: str) -> None:
    global TASKS_EN, KO_DIR, STAGE_KO
    if name not in BENCHMARKS:
        die(f"모르는 벤치마크: {name!r} (가능: {', '.join(BENCHMARKS)})")
    TASKS_EN = DATASETS / name / BENCHMARKS[name]
    KO_DIR = TRANSLATIONS / name / "ko"
    STAGE_KO = DATASETS / f"{name}-ko" / BENCHMARKS[name]

sys.path.insert(0, str(REPO / "labs"))


def die(msg: str) -> None:
    print(f"\033[31m✗ {msg}\033[0m", file=sys.stderr)
    raise SystemExit(1)


def log(msg: str) -> None:
    print(f"\033[36m▸ {msg}\033[0m")


# ─────────────────────────────────────────────────────────────
# 식별자 추출 — 번역 후에도 살아 있어야 하는 것들
# ─────────────────────────────────────────────────────────────

PATTERNS = [
    r"`[^`\n]+`",                        # 백틱으로 감싼 것
    r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b",  # snake_case
    r"\b[a-z]+(?:[A-Z][a-z0-9]*)+\b",      # camelCase
    r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b",  # PascalCase
    r"\b[\w./-]+\.(?:py|go|ts|js|rs|json|toml|yaml|yml|md|sh)\b",  # 파일 이름
    r"\b[A-Z][A-Z0-9_]{2,}\b",           # 상수 · 약어
]

# 영어 산문에서 흔히 나오지만 식별자가 아닌 것들. 이걸 빼지 않으면
# "번역했으니 사라진 게 당연한" 단어까지 경고로 잡힌다.
STOPWORDS = {
    "IMPORTANT", "NOTE", "WARNING", "TODO", "AND", "OR", "NOT", "THE",
    "API", "URL", "HTTP", "HTTPS", "JSON", "YAML", "XML", "CSV", "SQL",
    "CPU", "RAM", "OS", "ID", "UTF", "ASCII", "UUID", "MUST", "SHOULD",
}


def identifiers(text: str) -> set[str]:
    """번역 후에도 그대로 남아야 할 토큰을 뽑는다."""
    found: set[str] = set()
    for pat in PATTERNS:
        for m in re.findall(pat, text):
            tok = m.strip("`").strip()
            if len(tok) < 3 or tok.upper() in STOPWORDS:
                continue
            found.add(tok)
    return found


def missing(en: str, ko: str) -> list[str]:
    """영어 쪽 식별자 중 한국어 쪽에 없는 것을 돌려준다.

    한국어 쪽은 **부분문자열로만** 확인한다. 같은 정규식을 다시 돌리면
    `NDJSON의` 처럼 조사가 붙었을 때 `\\b` 가 걸리지 않아 멀쩡한 번역을
    유실로 잡는다. 한글은 `\\w` 에 포함되므로 영문자와 한글 사이에는
    단어 경계가 생기지 않기 때문이다.
    """
    return sorted(tok for tok in identifiers(en) if tok not in ko)


# ─────────────────────────────────────────────────────────────
# 번역
# ─────────────────────────────────────────────────────────────

PROMPT = """\
아래는 소프트웨어 과제 지시문입니다. 한국어로 번역하세요.

반드시 지킬 것:

1. 코드 식별자는 **원문 그대로** 두세요. 함수명·변수명·타입명·파일 경로·
   패키지명·상수·플래그·명령어가 여기 해당합니다. 예를 들어
   `sort_by_label` 을 `라벨_기준_정렬` 로 바꾸면 안 됩니다.
2. 백틱(`) 안의 내용은 한 글자도 바꾸지 마세요.
3. 마크다운 구조(제목·목록·코드블록·강조)를 그대로 유지하세요.
4. 문장을 요약하거나 생략하지 마세요. 지시문은 명세라서 한 조건이라도
   빠지면 과제가 달라집니다.
5. 기술 용어에 한국어 정착 표현이 없으면 원어를 그대로 쓰세요.
   (예: 파싱, 오버플로, 타임스탬프)
6. 번역문만 출력하세요. 설명·머리말·코드펜스로 감싸지 마세요.

--- 원문 시작 ---
{text}
--- 원문 끝 ---"""


def translate_one(text: str, deployment: str) -> str:
    from kit.provider import complete

    # 지시문은 명세라서 길이가 줄면 조건이 빠진 것이다. 넉넉히 준다.
    budget = max(4096, len(text) // 2 + 2048)
    body, _ = complete(PROMPT.format(text=text), deployment,
                       max_output_tokens=budget, timeout=600)
    out = body.strip()

    # 모델이 코드펜스로 감싸는 경우가 있다. 벗겨 준다.
    if out.startswith("```"):
        lines = out.splitlines()
        if lines[-1].strip().startswith("```"):
            out = "\n".join(lines[1:-1]).strip()
    return out + "\n"


def cmd_translate(args) -> int:
    from kit import env as kenv

    kenv.load()
    deployment = kenv.get("AZURE_OPENAI_DEPLOYMENT")
    if not deployment:
        die("AZURE_OPENAI_DEPLOYMENT 가 없습니다. labs/.env 를 확인하세요.")

    targets = pick_tasks(args)
    KO_DIR.mkdir(parents=True, exist_ok=True)
    log(f"번역 대상 {len(targets)}건 · 모델 {deployment}")

    done = skipped = 0
    for i, task in enumerate(targets, 1):
        dst = KO_DIR / f"{task}.md"
        if dst.exists() and not args.force:
            skipped += 1
            continue

        src = TASKS_EN / task / "instruction.md"
        if not src.exists():
            print(f"  [{i}/{len(targets)}] {task} — instruction.md 없음, 건너뜁니다")
            continue

        text = src.read_text(encoding="utf-8")
        try:
            ko = translate_one(text, deployment)
        except Exception as e:
            print(f"  [{i}/{len(targets)}] {task} — 실패: {type(e).__name__}: {e}")
            continue

        dst.write_text(ko, encoding="utf-8")
        lost = missing(text, ko)
        mark = "!" if lost else "✓"
        print(f"  [{i}/{len(targets)}] {mark} {task}  "
              f"{len(text):,}B → {len(ko):,}B"
              + (f"  식별자 {len(lost)}개 유실" if lost else ""), flush=True)
        done += 1

    log(f"번역 {done}건" + (f" · 이미 있어 건너뜀 {skipped}건" if skipped else ""))
    if done:
        print("  다음: python translate.py verify")
    return 0


# ─────────────────────────────────────────────────────────────
# 검증
# ─────────────────────────────────────────────────────────────

def cmd_verify(args) -> int:
    targets = [p.stem for p in sorted(KO_DIR.glob("*.md"))] \
        if not args.tasks else pick_tasks(args)
    if not targets:
        die("번역된 파일이 없습니다. 먼저 translate 를 실행하세요.")

    bad = []
    for task in targets:
        ko_path = KO_DIR / f"{task}.md"
        en_path = TASKS_EN / task / "instruction.md"
        if not ko_path.exists() or not en_path.exists():
            continue

        en, ko = en_path.read_text(encoding="utf-8"), ko_path.read_text(encoding="utf-8")
        lost = missing(en, ko)
        # 지시문은 명세라서 크게 짧아지면 조건이 빠졌다는 뜻이다.
        # 한국어는 보통 영어보다 짧아지므로 0.5 를 하한으로 본다.
        shrink = len(ko) / len(en) if en else 1.0

        if lost or shrink < 0.5:
            bad.append((task, lost, shrink))
            print(f"  ✗ {task}")
            if lost:
                head = ", ".join(lost[:6])
                more = f" 외 {len(lost) - 6}개" if len(lost) > 6 else ""
                print(f"      사라진 식별자: {head}{more}")
            if shrink < 0.5:
                print(f"      길이가 원문의 {shrink:.0%} — 내용이 빠졌을 수 있습니다")
        else:
            print(f"  ✓ {task}  (원문 대비 {shrink:.0%})")

    print()
    if bad:
        print(f"\033[33m! {len(bad)}/{len(targets)}건에 문제가 있습니다.\033[0m")
        print("  식별자가 번역되면 에이전트가 대상을 못 찾아 태스크가 실패합니다.")
        print("  그 실패를 압축 탓으로 오해하게 되므로, 고친 뒤 사용하세요.")
        print("  다시 시도: python translate.py translate <태스크> --force")
        return 1

    print(f"\033[32m✓ {len(targets)}건 모두 통과\033[0m")
    return 0


# ─────────────────────────────────────────────────────────────
# 스테이징 — 한국어 데이터셋 트리를 만든다
# ─────────────────────────────────────────────────────────────

def cmd_stage(args) -> int:
    targets = [p.stem for p in sorted(KO_DIR.glob("*.md"))] \
        if not args.tasks else pick_tasks(args)
    if not targets:
        die("번역된 파일이 없습니다. 먼저 translate 를 실행하세요.")

    if STAGE_KO.exists():
        shutil.rmtree(STAGE_KO)
    STAGE_KO.mkdir(parents=True)

    for task in targets:
        src, dst = TASKS_EN / task, STAGE_KO / task
        if not src.is_dir():
            print(f"  ✗ {task} — 원본이 없습니다")
            continue
        dst.mkdir()

        # instruction.md 만 한국어로 바꾸고 나머지는 원본을 가리킨다.
        # 복사하면 원본이 갱신될 때 조용히 어긋나고, 디스크도 낭비된다.
        for item in src.iterdir():
            if item.name == "instruction.md":
                continue
            os.symlink(os.path.relpath(item, dst), dst / item.name)
        shutil.copy2(KO_DIR / f"{task}.md", dst / "instruction.md")
        print(f"  ✓ {task}")

    log(f"한국어 데이터셋 {len(targets)}건 → {STAGE_KO.relative_to(REPO)}")
    print("  실험 yaml 에서 이렇게 쓰세요:")
    print("    dataset:")
    print("      path: ./deep-swe-ko/tasks")
    return 0


# ─────────────────────────────────────────────────────────────

def cmd_list(args) -> int:
    if not TASKS_EN.is_dir():
        die(f"{TASKS_EN} 가 없습니다. ./setup.sh 를 먼저 실행하세요.")

    all_tasks = sorted(p.name for p in TASKS_EN.iterdir() if p.is_dir())
    ko = {p.stem for p in KO_DIR.glob("*.md")} if KO_DIR.is_dir() else set()
    staged = {p.name for p in STAGE_KO.iterdir()} if STAGE_KO.is_dir() else set()

    print(f"  영어 태스크   {len(all_tasks)}건  ({TASKS_EN.relative_to(REPO)})")
    print(f"  한국어 번역   {len(ko)}건  ({KO_DIR.relative_to(REPO)})")
    print(f"  스테이징      {len(staged)}건  ({STAGE_KO.relative_to(REPO)})")

    if args.verbose and ko:
        print()
        for t in sorted(ko):
            print(f"    {'●' if t in staged else '○'} {t}")
        print("\n    ● 스테이징까지 끝남 · ○ 번역만 됨")
    return 0


def pick_tasks(args) -> list[str]:
    if not TASKS_EN.is_dir():
        die(f"{TASKS_EN} 가 없습니다. ./setup.sh 를 먼저 실행하세요.")
    if getattr(args, "all", False):
        return sorted(p.name for p in TASKS_EN.iterdir() if p.is_dir())
    if not args.tasks:
        die("태스크를 지정하거나 --all 을 주세요. 목록은 translate.py list 로 봅니다.")

    known = {p.name for p in TASKS_EN.iterdir() if p.is_dir()}
    unknown = [t for t in args.tasks if t not in known]
    if unknown:
        die(f"없는 태스크: {', '.join(unknown)}")
    return list(args.tasks)


def main() -> int:
    p = argparse.ArgumentParser(
        description="DeepSWE 지시문 한국어판 준비",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="상태 보기")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("translate", help="영어 → 한국어")
    s.add_argument("tasks", nargs="*")
    s.add_argument("--all", action="store_true", help="전체 태스크")
    s.add_argument("--force", action="store_true", help="이미 있어도 다시")
    s.set_defaults(fn=cmd_translate)

    s = sub.add_parser("verify", help="식별자 보존 검사")
    s.add_argument("tasks", nargs="*")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("stage", help="deep-swe-ko/tasks 생성")
    s.add_argument("tasks", nargs="*")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_stage)

    for sp in sub.choices.values():
        sp.add_argument("-b", "--benchmark", default="deep-swe",
                        choices=sorted(BENCHMARKS),
                        help="대상 벤치마크 (기본 deep-swe)")

    args = p.parse_args()
    set_benchmark(args.benchmark)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

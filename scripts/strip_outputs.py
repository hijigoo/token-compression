#!/usr/bin/env python3
"""노트북 출력을 지웁니다 — 커밋 전에 돌리세요.

왜 필요한가
-----------
`.gitignore` 는 **파일 단위**로만 걸러집니다. 노트북은 커밋해야 하는데
그 안의 *출력* 만 빼고 싶은 상황을 gitignore 로는 표현할 수 없습니다.

노트북 출력에는 이런 것들이 박힐 수 있습니다.

  - 엔드포인트·리소스명 (`https://our-resource.cognitiveservices...`)
  - 응답 ID (`resp_0de8a57e...`)
  - 실제 데이터가 섞인 프롬프트·응답 본문
  - 드물게 토큰·키 (실수로 print 한 경우)

사용법
------
    python scripts/strip_outputs.py               # 전체 노트북 출력 제거
    python scripts/strip_outputs.py --check       # 제거하지 않고 검사만 (CI)
    python scripts/strip_outputs.py --scan        # 민감 패턴이 있는지만 훑기
    python scripts/strip_outputs.py --stdin       # git filter 용 (stdin -> stdout)

git filter 로 자동화하기
------------------------
    git config filter.nbstrip.clean "python scripts/strip_outputs.py --stdin"
    echo '*.ipynb filter=nbstrip' >> .gitattributes

이러면 커밋할 때 자동으로 출력이 빠지고, 작업 중인 파일은 그대로 남습니다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 출력에서 발견되면 경고할 패턴. 오탐이 있어도 알려주는 쪽이 낫습니다.
SENSITIVE = [
    (r"eyJ[A-Za-z0-9_-]{20,}", "JWT 토큰으로 보이는 문자열"),
    (r"Bearer\s+[A-Za-z0-9._-]{20,}", "Bearer 토큰"),
    (r"[?&](api[-_]?key|code|sig)=[^\s&\"']+", "URL 에 박힌 키"),
    (r"sk-[A-Za-z0-9]{20,}", "OpenAI 형식 API 키"),
    (r"AccountKey=[^;\s]+", "Storage 연결문자열"),
    (r"https://(?!.*\*)[a-z0-9][a-z0-9-]{2,}\.(?:openai|cognitiveservices)\.azure\.com",
     "마스킹되지 않은 엔드포인트"),
    (r"resp_[0-9a-f]{16,}", "응답 ID"),
]


def strip(nb: dict) -> tuple[dict, int]:
    """출력과 실행 카운터를 지웁니다. (노트북, 지운 개수)"""
    n = 0
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        n += len(cell.get("outputs") or [])
        if cell.get("execution_count") is not None:
            n += 1
        cell["outputs"] = []
        cell["execution_count"] = None
        # 실행하면 붙는 부가 메타데이터도 정리합니다
        cell.get("metadata", {}).pop("execution", None)
    nb.get("metadata", {}).pop("widgets", None)
    return nb, n


def scan(nb: dict, name: str) -> list[str]:
    """출력에 민감해 보이는 문자열이 있는지 훑습니다."""
    found = []
    for i, cell in enumerate(nb.get("cells", [])):
        for out in cell.get("outputs") or []:
            text = "".join(out.get("text") or [])
            text += json.dumps(out.get("data", {}), ensure_ascii=False)
            for pat, label in SENSITIVE:
                for m in re.findall(pat, text):
                    hit = m if isinstance(m, str) else m[0]
                    found.append(f"{name} · 셀{i} · {label}: {hit[:50]}")
    return found


def notebooks() -> list[Path]:
    return sorted(
        p for p in ROOT.rglob("*.ipynb")
        if ".venv" not in p.parts and ".ipynb_checkpoints" not in p.parts
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="노트북 출력을 지웁니다.")
    ap.add_argument("--check", action="store_true", help="지우지 않고 검사만 합니다")
    ap.add_argument("--scan", action="store_true", help="민감 패턴만 훑습니다")
    ap.add_argument("--stdin", action="store_true", help="stdin->stdout (git filter 용)")
    ap.add_argument("--check-stdin", action="store_true",
                    help="stdin 노트북에 출력이 있으면 exit 1 (pre-push 훅 용)")
    ap.add_argument("paths", nargs="*", help="대상 노트북 (없으면 저장소 전체)")
    args = ap.parse_args()

    if args.check_stdin:
        try:
            nb = json.load(sys.stdin)
        except Exception:
            return 0                      # 파싱 불가 파일은 통과시킵니다
        _, n = strip(nb)
        if n:
            print(f"  ✗ {args.paths[0] if args.paths else '(stdin)'}  출력·실행흔적 {n}개")
            return 1
        return 0

    if args.stdin:
        nb, _ = strip(json.load(sys.stdin))
        json.dump(nb, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
        return 0

    targets = [Path(p) for p in args.paths] or notebooks()
    if not targets:
        print("노트북이 없습니다.")
        return 0

    dirty, alerts = [], []
    for f in targets:
        nb = json.loads(f.read_text(encoding="utf-8"))
        alerts += scan(nb, f.relative_to(ROOT) if f.is_absolute() else f)
        _, n = strip(nb)
        rel = f.relative_to(ROOT) if f.is_absolute() else f
        if n:
            dirty.append((f, rel, n, nb))

    if alerts:
        print("⚠ 출력에서 민감해 보이는 문자열을 찾았습니다")
        for a in alerts:
            print("   ", a)
        print()

    if not dirty:
        print(f"출력 없음 — 노트북 {len(targets)}개 모두 깨끗합니다.")
        return 0

    for _, rel, n, _ in dirty:
        print(f"  {rel}  출력·실행흔적 {n}개")

    if args.check or args.scan:
        print(f"\n{len(dirty)}개 노트북에 출력이 남아 있습니다.")
        print("제거하려면: python scripts/strip_outputs.py")
        return 1

    for f, rel, n, nb in dirty:
        f.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\n{len(dirty)}개 노트북의 출력을 제거했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

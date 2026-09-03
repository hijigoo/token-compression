#!/usr/bin/env python3
"""pier 를 이 환경에서 돌아가게 손봅니다.

    ./.venv/bin/python patch_pier.py          # 적용
    ./.venv/bin/python patch_pier.py --undo   # 되돌리기
    ./.venv/bin/python patch_pier.py --check  # 상태만 보기

두 군데를 고칩니다. 둘 다 **환경 문제 우회이지 pier 의 버그 수정이 아닙니다.**
망이 열려 있고 압축 프록시를 쓰지 않는다면 필요 없습니다.

────────────────────────────────────────────────────────────
패치 1 — 사내망 PyPI 미러 (mini_swe_agent.py)
────────────────────────────────────────────────────────────

pier 는 에이전트를 컨테이너 **이미지 빌드 단계**에서 설치합니다.

    uv tool install mini-swe-agent

`uv` 는 인덱스(pypi.org)에서 메타데이터를 받고, 실제 파일은
`files.pythonhosted.org` 에서 내려받습니다. **사내망은 이 파일 서버만
막고 있습니다.** 인덱스는 열려 있어서 "왜 되다 마나" 처럼 보입니다.

    pypi.org                200
    astral.sh               301
    files.pythonhosted.org  연결 실패   ← 여기

pier 가 그 설치 단계의 환경변수를 **코드에 박아** 두었습니다.

    InstallStep(user="agent", env={"LITELLM_LOCAL_MODEL_COST_MAP": "true"}, ...)

실험 설정(`agents[].env`)은 에이전트가 **실행될 때** 쓰는 값이라 빌드에는
닿지 않습니다. 그래서 이 한 줄만 넓혀 줍니다.

────────────────────────────────────────────────────────────
패치 2 — egress 프록시의 허용 포트 (environments/agent_setup.py)
────────────────────────────────────────────────────────────

pier 는 에이전트 컨테이너를 내부망에 가두고, 나가는 요청을 전부 squid
프록시로 보냅니다. 그 squid 설정에 이런 줄이 있습니다.

    acl Safe_ports port 80 443
    http_access deny !Safe_ports          ← 허용목록을 보기 **전에** 막습니다

우리 압축 실험은 모델 호출을 가로채려고 호스트에 프록시를 띄웁니다.
그 주소가 `http://host.docker.internal:8802/v1` 입니다. 도메인은
허용목록에 제대로 들어가지만(pier 가 `OPENAI_BASE_URL` 에서 뽑아 줍니다),
**포트 8802 가 Safe_ports 가 아니라서** 그 앞줄에서 잘립니다.

증상은 압축 탓처럼 보입니다. 에이전트가 0 스텝에서 죽고, 로그에는
squid 가 돌려준 HTML 만 남습니다.

    <body id=ERR_ACCESS_DENIED> ... Access Denied.
    ... trying to retrieve the URL: http://host.docker.internal:8802/v1/responses

그래서 `EXTRA_SAFE_PORTS` 환경변수를 받아 Safe_ports 에 덧붙이도록
합니다. 값을 주지 않으면 원래대로 80/443 만 허용합니다. 즉 **기본
동작은 바뀌지 않습니다.**

    export PIER_EXTRA_SAFE_PORTS="8801 8802 8803 8804"

────────────────────────────────────────────────────────────

site-packages 를 손으로 고치면 재설치할 때 조용히 사라지고, 다음 사람은
"왜 나만 안 되지" 를 처음부터 겪습니다. 스크립트로 두면 무엇을 왜 바꿨는지
남고, `--undo` 로 되돌릴 수 있습니다.
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = HERE / ".venv"
MARK = "# [token-compression]"

# 우리 프록시가 쓰는 포트 범위. launch.py 가 8801 부터 arm 수만큼 씁니다.
DEFAULT_SAFE_PORTS = os.environ.get("PIER_EXTRA_SAFE_PORTS",
                                    "8801 8802 8803 8804 8805 8806 8807 8808")
MIRROR = os.environ.get("PYPI_INDEX", "https://mirror.kakao.com/pypi/simple")


# ─────────────────────────────────────────────────────────────
# 패치 1 — PyPI 미러
# ─────────────────────────────────────────────────────────────
PYPI_ORIG = '''                InstallStep(
                    user="agent",
                    env={"LITELLM_LOCAL_MODEL_COST_MAP": "true"},
                    run=agent_run,
                ),'''

PYPI_PATCHED = '''                InstallStep(
                    user="agent",
                    env={{
                        "LITELLM_LOCAL_MODEL_COST_MAP": "true",
                        {mark} 사내망 PyPI 미러 — patch_pier.py 가 넣었습니다.
                        # files.pythonhosted.org 가 막힌 망에서 uv 가 여기로
                        # 가도록 합니다. 되돌리려면 patch_pier.py --undo
                        "UV_DEFAULT_INDEX": "{mirror}",
                        "UV_INDEX_URL": "{mirror}",
                        "PIP_INDEX_URL": "{mirror}",
                        "UV_INDEX_STRATEGY": "unsafe-best-match",
                    }},
                    run=agent_run,
                ),'''


# ─────────────────────────────────────────────────────────────
# 패치 2 — squid 허용 포트
# ─────────────────────────────────────────────────────────────
# squid.conf 를 쓰는 heredoc 이 따옴표(<<'EOF')로 묶여 있어 안에서는 셸
# 변수가 펼쳐지지 않습니다. heredoc 을 건드리면 설정 전체가 흔들리므로,
# 다 쓰고 난 **뒤에** 한 줄만 sed 로 바꿉니다. 값이 없으면 아무것도 안 합니다.
SQUID_ORIG = """EOF

exec squid -N -f /tmp/squid.conf -d 1
"""

SQUID_PATCHED = """EOF

{mark} 허용 포트 넓히기 — patch_pier.py 가 넣었습니다.
# 압축 실험은 모델 호출을 호스트 프록시(8801~)로 돌립니다. 도메인은
# 허용목록에 있지만 포트가 Safe_ports 가 아니면 그 앞줄에서 잘립니다.
# 값을 주지 않으면 원래대로 80/443 만 허용합니다.
if [ -n "${{EXTRA_SAFE_PORTS:-}}" ]; then
  sed -i "s|^acl Safe_ports port 80 443$|acl Safe_ports port 80 443 ${{EXTRA_SAFE_PORTS}}|" /tmp/squid.conf
  echo "[token-compression] Safe_ports += ${{EXTRA_SAFE_PORTS}}" >&2
fi

exec squid -N -f /tmp/squid.conf -d 1
"""

ENV_ORIG = '''    return {
        "PROXY_TOKEN": token,
        "ALLOWLIST_DOMAINS": ",".join(allowlist.domains),
    }'''

ENV_PATCHED = '''    return {
        "PROXY_TOKEN": token,
        "ALLOWLIST_DOMAINS": ",".join(allowlist.domains),
        %MARK% start-squid.sh 로 넘길 추가 허용 포트 — patch_pier.py
        "EXTRA_SAFE_PORTS": __import__("os").environ.get(
            "PIER_EXTRA_SAFE_PORTS", ""),
    }'''.replace("%MARK%", MARK)


def _find(rel: str) -> Path:
    hits = list(VENV.rglob(rel))
    if not hits:
        sys.exit(f"✗ pier 가 설치되어 있지 않습니다({rel}). ./setup.sh 를 먼저 돌려주세요.")
    return hits[0]


def _apply(path: Path, pairs: list[tuple[str, str]], undo: bool) -> str:
    """pairs 는 (원본, 패치본). undo 면 방향을 뒤집습니다."""
    src = path.read_text(encoding="utf-8")
    for before, after in pairs:
        a, b = (after, before) if undo else (before, after)
        if b in src:            # 이미 그 상태
            continue
        if a not in src:
            return f"건너뜀 (모양이 다름): {path.name}"
        src = src.replace(a, b, 1)
    path.write_text(src, encoding="utf-8")
    ast.parse(src) if path.suffix == ".py" else None   # 깨뜨리지 않았는지
    return f"✓ {path.name}"


def main() -> int:
    ap = argparse.ArgumentParser(description="pier 를 이 환경에 맞게 손봅니다")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    agent_py = _find("pier/agents/installed/mini_swe_agent.py")
    setup_py = _find("pier/environments/agent_setup.py")

    jobs = [
        (agent_py, [(PYPI_ORIG, PYPI_PATCHED.format(mark=MARK, mirror=MIRROR))]),
        (setup_py, [(SQUID_ORIG, SQUID_PATCHED.format(mark=MARK)),
                    (ENV_ORIG, ENV_PATCHED)]),
    ]

    if args.check:
        print(f"  미러       : {MIRROR}")
        print(f"  추가 포트  : {DEFAULT_SAFE_PORTS}")
        for path, _ in jobs:
            state = "적용됨" if MARK in path.read_text(encoding="utf-8") else "적용 안 됨"
            print(f"  {state:9s} : {path}")
        return 0

    for path, pairs in jobs:
        print("  " + _apply(path, pairs, args.undo))

    if args.undo:
        print("  되돌렸습니다.")
    else:
        print(f"  적용했습니다 · 미러 {MIRROR}")
        print(f"  squid 허용 포트를 쓰려면: export PIER_EXTRA_SAFE_PORTS='{DEFAULT_SAFE_PORTS}'")
        print("  되돌리기: ./.venv/bin/python patch_pier.py --undo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

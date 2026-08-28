"""`.env` 로드.

변수명은 `scripts/explore/.env.example` 과 **같습니다.** 이미 노트북용 `.env` 를
만들어 두었다면 그대로 복사해 쓰면 됩니다.

    AZURE_OPENAI_ENDPOINT      필수 (tokenizer.mode=api 일 때)
    AZURE_OPENAI_DEPLOYMENT    배포명 기본값
    AZURE_OPENAI_API_VERSION   (선택)
    AZURE_OPENAI_API_KEY       비우면 az CLI 의 Entra ID 토큰을 씁니다
    AZ_CLI                     az 가 PATH 에 없을 때 전체 경로

찾는 순서는 아래와 같고, **먼저 찾은 것만** 씁니다.

    labs/.env  →  저장소 루트 .env  →  scripts/explore/.env

이미 설정된 환경변수는 덮어쓰지 않습니다. 셸이나 CI 가 항상 우선입니다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

LABS = Path(__file__).resolve().parents[1]
ROOT = LABS.parent

CANDIDATES: List[Path] = [
    LABS / ".env",
    ROOT / ".env",
    ROOT / "scripts" / "explore" / ".env",
]

_loaded: Optional[Path] = None


def _parse(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("\"'")
        if k and k not in os.environ:          # 셸 환경변수가 우선
            os.environ[k] = v


def load(verbose: bool = False) -> Optional[Path]:
    """첫 번째로 발견한 .env 를 읽습니다. 이미 읽었으면 다시 읽지 않습니다."""
    global _loaded
    if _loaded is not None:
        return _loaded
    for p in CANDIDATES:
        if p.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(p, override=False)
            except ImportError:
                _parse(p)
            _loaded = p
            if verbose:
                print(f".env: {p}")
            return p
    if verbose:
        print(".env 를 찾지 못했습니다. 후보:")
        for p in CANDIDATES:
            print("   ", p)
    return None


def get(name: str, default: Optional[str] = None) -> Optional[str]:
    load()
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def require(name: str) -> str:
    v = get(name)
    if not v:
        raise RuntimeError(
            f"환경변수 {name} 가 필요합니다.\n"
            f"  cd labs && cp .env.example .env   (또는 cp ../scripts/explore/.env .env)"
        )
    return v


def mask_endpoint(url: Optional[str]) -> str:
    """출력에 리소스명이 그대로 남지 않게 가립니다."""
    if not url:
        return "(없음)"
    try:
        scheme, rest = url.split("://", 1)
        host, _, _ = rest.partition("/")
        name, _, domain = host.partition(".")
        return f"{scheme}://{name[:5]}***.{domain}"
    except ValueError:
        return "***"

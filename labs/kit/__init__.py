"""labs/kit — 랩 공통 기반.

랩은 `sys.path` 에 `labs/` 를 넣고 `from kit import ...` 로 씁니다.
compress.py 상단의 부트스트랩 3줄이 그 일을 합니다.
"""

from pathlib import Path

VERSION = (Path(__file__).with_name("VERSION")).read_text(encoding="utf-8").strip()

__all__ = ["VERSION"]

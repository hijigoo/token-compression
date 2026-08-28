"""실험 설정.

설정은 코드가 아니라 yaml 에 둡니다. 그래야 "조건 1개 = 파일 1개" 가 되고,
runs/ 경로에 config 이름이 그대로 남아 나중에 무엇을 돌렸는지 알 수 있습니다.

    name: noop
    lab: 00-baseline
    params: {}
    dataset: {path: ../data/sample, limit: null}
    model: gpt-5.4          # 토큰 계산 기준
    tokenizer:
      mode: local           # local(tiktoken) | api(실측)
      deployment: gpt-5.4   # mode=api 일 때
      cache: true
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from . import VERSION


@dataclass
class Config:
    name: str
    lab: str
    path: Path
    params: Dict[str, Any] = field(default_factory=dict)
    dataset: Dict[str, Any] = field(default_factory=dict)
    model: Optional[str] = None
    tokenizer: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, Any]:
        """실행 조건을 통째로 남깁니다. kit 버전이 여기 박힙니다."""
        return {
            "config": self.raw,
            "config_file": str(self.path),
            "kit_version": VERSION,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


def load(path: str | Path) -> Config:
    try:
        import yaml
    except ImportError as e:
        raise ImportError(
            "pyyaml 이 필요합니다.\n  uv pip install -r ../kit/requirements.txt"
        ) from e

    p = Path(path).resolve()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    lab = raw.get("lab") or p.parent.parent.name
    ds = dict(raw.get("dataset") or {})
    # 데이터 경로는 config 파일 기준 상대경로로 해석합니다.
    if ds.get("path"):
        ds["path"] = str((p.parent / ds["path"]).resolve())

    return Config(
        name=raw.get("name") or p.stem,
        lab=lab,
        path=p,
        params=dict(raw.get("params") or {}),
        dataset=ds,
        model=raw.get("model"),
        tokenizer=dict(raw.get("tokenizer") or {}),
        raw=raw,
    )

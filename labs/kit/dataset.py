"""코퍼스 로더.

한 줄이 한 케이스인 jsonl 을 읽습니다.

    {"id": "doc-001",
     "text": "압축 대상 원문 …",
     "question": "이 문서에서 환불 수수료는?",     (선택)
     "must_include": ["10%", "않습니다"],          (선택)
     "meta": {"kind": "numeric"}}                  (선택)

`must_include` 가 있으면 survival 을 잴 수 있습니다. LLM 호출이 없으므로
스윕을 수백 번 돌려도 비용이 0 입니다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


@dataclass
class Case:
    id: str
    text: str
    question: Optional[str] = None
    must_include: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        """카테고리. 집계를 유형별로 쪼갤 때 씁니다."""
        return str(self.meta.get("kind", "-"))


def load(path: str | Path, limit: Optional[int] = None) -> List[Case]:
    """파일 하나 또는 폴더 안의 모든 jsonl 을 읽습니다."""
    p = Path(path)
    files = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
    if not files:
        raise FileNotFoundError(
            f"{p} 에서 jsonl 을 찾지 못했습니다.\n"
            f"  labs/data 는 커밋되지 않습니다. ./fetch.sh 로 받아주세요."
        )

    cases: List[Case] = []
    for f in files:
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{f}:{lineno} JSON 파싱 실패 — {e}") from e
            if "text" not in d:
                raise ValueError(f"{f}:{lineno} 'text' 필드가 없습니다")
            cases.append(Case(
                id=str(d.get("id", f"{f.stem}-{lineno}")),
                text=d["text"],
                question=d.get("question"),
                must_include=list(d.get("must_include") or []),
                meta=d.get("meta") or {},
            ))
            if limit and len(cases) >= limit:
                return cases
    return cases


def summarize(cases: List[Case]) -> Dict[str, Any]:
    kinds: Dict[str, int] = {}
    for c in cases:
        kinds[c.kind] = kinds.get(c.kind, 0) + 1
    return {
        "n_cases": len(cases),
        "n_chars": sum(len(c.text) for c in cases),
        "with_must_include": sum(1 for c in cases if c.must_include),
        "kinds": kinds,
    }

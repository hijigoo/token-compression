"""실행 결과 기록.

    runs/<lab>/<config>/<timestamp>/
    ├── config.snapshot.yaml   설정 + kit 버전 + 환경        (커밋)
    ├── metrics.json           집계 지표                      (커밋)
    ├── report.md              사람이 읽는 요약                (커밋)
    └── records.jsonl          케이스별 원문·압축문            (커밋 안 함)

records.jsonl 을 커밋하지 않는 이유는 용량도 있지만 원문이 그대로 들어가기
때문입니다. 대신 압축 전후를 **둘 다** 남겨서, 나중에 "왜 이 케이스가 깨졌나" 를
다시 볼 수 있게 합니다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config


class Run:
    def __init__(self, cfg: Config, out_root: str | Path):
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.cfg = cfg
        self.dir = Path(out_root).resolve() / cfg.lab / cfg.name / ts
        self.dir.mkdir(parents=True, exist_ok=True)
        self.records: List[Dict[str, Any]] = []
        self._fp = (self.dir / "records.jsonl").open("w", encoding="utf-8")

    def add(self, record: Dict[str, Any], before: str = "", after: str = "") -> None:
        self.records.append(record)
        self._fp.write(json.dumps({**record, "before": before, "after": after},
                                  ensure_ascii=False) + "\n")

    def finish(self, metrics: Dict[str, Any], notes: Optional[List[str]] = None) -> Path:
        self._fp.close()

        try:
            import yaml
            (self.dir / "config.snapshot.yaml").write_text(
                yaml.safe_dump(self.cfg.snapshot(), allow_unicode=True, sort_keys=False),
                encoding="utf-8")
        except ImportError:
            (self.dir / "config.snapshot.yaml").write_text(
                json.dumps(self.cfg.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")

        (self.dir / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.dir / "report.md").write_text(self._report(metrics, notes or []), encoding="utf-8")
        return self.dir

    def _report(self, m: Dict[str, Any], notes: List[str]) -> str:
        def pct(x): return "—" if x is None else f"{x:.1%}"

        lines = [
            f"# {self.cfg.lab} · {self.cfg.name}",
            "",
            f"- 케이스 {m.get('n', 0)}건",
            f"- 토큰 {m.get('tokens_before', 0):,} → {m.get('tokens_after', 0):,}"
            f"  (**{pct(m.get('saved'))} 절감**)",
            f"- 측정 방식 `{m.get('token_backend', '?')}`",
            "",
        ]

        if "survival_mean" in m:
            lines += [
                "## 정답 보존율",
                "",
                "> 각 케이스에서 **정답에 꼭 필요한 문자열**(`must_include`) 중",
                "> 압축 후에도 남아 있는 비율입니다. 100% 면 하나도 안 잃은 것입니다.",
                "",
                "| 지표 | 값 | 뜻 |",
                "|---|---|---|",
                f"| 평균 보존율 | {pct(m['survival_mean'])} | 전체 케이스 평균 |",
                f"| 하위 5% | {pct(m['survival_p5'])} | 나쁜 쪽 5% 지점 |",
                f"| **최저 보존율** | **{pct(m['survival_worst'])}** | **가장 많이 깨진 케이스** |",
                f"| 온전한 케이스 | {pct(m['survived_all_rate'])} | 하나도 안 잃은 케이스 비율 |",
                "",
                "> **최저 보존율부터 보세요.** 평균 90% 여도 한 케이스가 0% 면",
                "> 그 질문에는 아예 답할 수 없습니다. 평균은 그걸 가립니다.",
                "",
            ]

        if m.get("by_kind"):
            lines += ["## 유형별", "", "| 유형 | 건수 | 절감 | 평균 보존율 | 최저 보존율 |",
                      "|---|---|---|---|---|"]
            for k, v in m["by_kind"].items():
                lines.append(f"| {k} | {v['n']} | {pct(v['saved'])} | "
                             f"{pct(v['survival_mean'])} | {pct(v['survival_worst'])} |")
            lines.append("")

        if notes:
            lines += ["## 메모", ""] + [f"- {n}" for n in notes] + [""]

        lines += ["---", "", f"kit `{self.cfg.snapshot()['kit_version']}` · "
                  f"설정 `{self.cfg.path.name}`"]
        return "\n".join(lines)

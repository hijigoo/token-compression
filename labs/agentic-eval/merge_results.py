#!/usr/bin/env python3
"""보완 측정을 본 결과에 합칩니다.

    ./.venv/bin/python merge_results.py <본> <보완>

같은 조건 이름이 겹치면 거부합니다. 조용히 덮으면 어느 쪽 숫자인지
알 수 없게 됩니다.
"""
import json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
base, extra = (REPO / "reports" / a / "results.json" for a in sys.argv[1:3])
b, e = (json.loads(p.read_text(encoding="utf-8")) for p in (base, extra))

dup = {a["name"] for a in b["arms"]} & {a["name"] for a in e["arms"]}
if dup:
    sys.exit(f"✗ 조건 이름이 겹칩니다: {sorted(dup)}")

b["arms"] += e["arms"]
b["runs"] += e["runs"]
b["elapsed_s"] = round(b["elapsed_s"] + e["elapsed_s"], 1)
b["merged_from"] = b.get("merged_from", []) + [
    {"name": e["name"], "started_at": e["started_at"], "arms": len(e["arms"])}]
base.write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"▸ 조건 {len(b['arms'])}개 · 측정 {len(b['runs'])}행")

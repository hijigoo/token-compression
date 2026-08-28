"""무손실 변환 모음.

**무손실의 정의를 코드로 못 박습니다: 검증할 수 있어야 무손실입니다.**

"줄었다" 는 말은 쉽습니다. 어려운 건 "아무것도 안 잃었다" 를 증명하는 것입니다.
그래서 모든 변환은 자기를 검증하는 방법을 함께 들고 옵니다. 두 가지가 있습니다.

  restore   되돌려서 원본과 **글자 단위로** 같은지 봅니다 (log_dedup)
  canon     둘 다 정규형으로 바꿔 같은지 봅니다 (json, xml, 표, 키값)

정규형 비교가 필요한 이유는, 들여쓰기를 지우면 되돌릴 수 없지만 **잃은 정보는
없기** 때문입니다. JSON 의 공백은 내용이 아니므로 파싱한 객체가 같으면 같습니다.

둘 다 없는 변환은 `ws_collapse` 하나뿐이고, 그건 실제로 정보를 버립니다.
랩은 검증된 건수와 검증 못 한 건수를 **따로 세서** 결과에 남깁니다.
검사가 조용히 생략되면 "무손실"이라는 말이 아무 의미가 없어지기 때문입니다.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple

# 변환 결과. applied=False 면 이 변환이 쓰일 수 없는 입력이었다는 뜻입니다.
Result = Tuple[bool, str, Dict[str, Any]]


# ══════════════════════════════════════════════════════════════════
# 1. json_compact — 들여쓰기와 공백 제거
#
# `json.dumps(indent=2)` 는 사람이 읽으라고 넣은 것입니다. 모델에게는
# 들여쓰기 한 칸도 토큰입니다. 파싱해서 다시 뱉으면 의미는 그대로입니다.
# ══════════════════════════════════════════════════════════════════

def json_compact(text: str) -> Result:
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False, text, {"reason": "JSON 이 아닙니다"}
    out = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return True, out, {}


def json_canon(text: str) -> Any:
    """JSON 의 정규형은 파싱한 객체입니다.

    들여쓰기·줄바꿈·구분자 공백은 내용이 아니므로, 객체가 같으면 같습니다.
    표로 편 결과(#TSV)도 여기서 같은 객체로 되돌아옵니다.
    """
    if text.startswith(TABLE_TAG):
        return json_to_table_restore(text)
    return json.loads(text)


# ══════════════════════════════════════════════════════════════════
# 2. json_to_table — 같은 키를 반복하는 배열을 표로
#
# 레코드 N개짜리 배열은 키를 N번 반복합니다. 헤더 한 줄로 빼면 N-1번을
# 아낍니다. N이 클수록 이득이 커지므로, 로그·조회 결과처럼 행이 많은
# 데이터에서 효과가 큽니다.
#
# 조건: 배열이고, 원소가 전부 flat 한 객체이고, 키 집합이 같아야 합니다.
# 하나라도 어긋나면 되돌릴 수 없으므로 적용하지 않습니다.
# ══════════════════════════════════════════════════════════════════

SEP = "\x1f"          # 값 구분자. 데이터에 나올 리 없는 제어문자를 씁니다.
TABLE_TAG = "#TSV"


def _flat_records(obj: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(obj, list) or len(obj) < 2:
        return None
    if not all(isinstance(r, dict) for r in obj):
        return None
    keys = list(obj[0].keys())
    if not keys:
        return None
    for r in obj:
        if list(r.keys()) != keys:
            return None
        for v in r.values():
            if isinstance(v, (dict, list)):
                return None                  # 중첩은 표로 못 폅니다
    return obj


def json_to_table(text: str) -> Result:
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False, text, {"reason": "JSON 이 아닙니다"}

    recs = _flat_records(obj)
    if recs is None:
        return False, text, {"reason": "키가 같은 flat 레코드 배열이 아닙니다"}

    keys = list(recs[0].keys())
    lines = [TABLE_TAG + SEP + SEP.join(keys)]
    for r in recs:
        lines.append(SEP.join(json.dumps(r[k], ensure_ascii=False) for k in keys))
    return True, "\n".join(lines), {"rows": len(recs), "cols": len(keys)}


def json_to_table_restore(text: str) -> Any:
    lines = text.split("\n")
    keys = lines[0].split(SEP)[1:]
    return [dict(zip(keys, (json.loads(v) for v in ln.split(SEP))))
            for ln in lines[1:]]


# ══════════════════════════════════════════════════════════════════
# 3. log_dedup — 줄마다 반복되는 접두사를 한 번만
#
# 로그는 타임스탬프·서비스명·trace id 를 줄마다 반복합니다. 줄이 20개면
# 같은 문자열이 20번 들어갑니다. 공통 접두사를 뽑아 헤더로 올리면
# 나머지 줄은 차이나는 부분만 남습니다.
#
# 되돌리기: 각 줄 앞에 접두사를 다시 붙이면 원본과 글자 단위로 같습니다.
# ══════════════════════════════════════════════════════════════════

PREFIX_TAG = "#PREFIX "


def _common_prefix(lines: List[str]) -> str:
    if len(lines) < 2:
        return ""
    p = lines[0]
    for ln in lines[1:]:
        i = 0
        while i < min(len(p), len(ln)) and p[i] == ln[i]:
            i += 1
        p = p[:i]
        if not p:
            return ""
    return p


def log_dedup(text: str, min_prefix: int = 8) -> Result:
    lines = text.split("\n")
    if len(lines) < 3:
        return False, text, {"reason": "줄이 3개 미만입니다"}

    p = _common_prefix(lines)
    if len(p) < min_prefix:
        return False, text, {"reason": f"공통 접두사가 {len(p)}자뿐입니다"}
    if "\n" in p or PREFIX_TAG in text:
        return False, text, {"reason": "되돌리기가 모호합니다"}

    body = "\n".join(ln[len(p):] for ln in lines)
    saved_chars = len(p) * (len(lines) - 1)
    return True, f"{PREFIX_TAG}{p}\n{body}", {
        "prefix_len": len(p), "lines": len(lines), "chars_saved": saved_chars}


def log_dedup_restore(text: str) -> str:
    head, _, body = text.partition("\n")
    p = head[len(PREFIX_TAG):]
    return "\n".join(p + ln for ln in body.split("\n"))


# ══════════════════════════════════════════════════════════════════
# 4. ws_collapse — 정렬용 공백 접기
#
# 키값 목록이나 표를 사람이 보기 좋게 맞추려고 넣은 공백은 의미가 없습니다.
# 다만 **되돌릴 수 없습니다.** 원래 공백이 몇 칸이었는지 모르기 때문입니다.
#
# 그래서 이 변환만 `lossless=False` 입니다. 의미는 보존하지만 표현은
# 복원되지 않습니다. 기본 파이프라인에서 빼 둔 이유이고, 쓰려면
# config 에서 명시적으로 켜야 합니다.
# ══════════════════════════════════════════════════════════════════

def ws_collapse(text: str) -> Result:
    out = "\n".join(re.sub(r"[ \t]{2,}", " ", ln).rstrip() for ln in text.split("\n"))
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    if out == text:
        return False, text, {"reason": "접을 공백이 없습니다"}
    return True, out, {}


# ══════════════════════════════════════════════════════════════════
# 5. xml_compact — 태그 사이 들여쓰기 제거
#
# 텍스트 노드가 없는 XML 이면 태그 사이 공백은 장식입니다. 텍스트 노드가
# 있으면 공백이 내용의 일부일 수 있으므로 건드리지 않습니다.
# ══════════════════════════════════════════════════════════════════

def xml_compact(text: str) -> Result:
    s = text.strip()
    if not (s.startswith("<") and s.endswith(">")):
        return False, text, {"reason": "XML 형태가 아닙니다"}
    # 태그와 태그 사이에 공백 외의 글자가 있으면 텍스트 노드가 있는 것입니다.
    if re.search(r">\s*[^<\s][^<]*<", s):
        return False, text, {"reason": "텍스트 노드가 있어 공백을 지울 수 없습니다"}
    out = re.sub(r">\s+<", "><", s)
    if out == s:
        return False, text, {"reason": "지울 공백이 없습니다"}
    return True, out, {}


def xml_canon(text: str) -> Any:
    """XML 의 정규형은 (태그, 정렬된 속성, 자식) 트리입니다.

    되돌리기는 불가능합니다 — 원래 들여쓰기가 몇 칸이었는지 모릅니다.
    하지만 트리가 같으면 **잃은 정보는 없습니다.** 들여쓰기는 내용이
    아니기 때문입니다. 그래서 되돌리기 대신 정규형으로 검증합니다.
    """
    def node(e):
        return (e.tag, tuple(sorted(e.attrib.items())),
                (e.text or "").strip(), tuple(node(c) for c in e))
    return node(ET.fromstring(text.strip()))


# ══════════════════════════════════════════════════════════════════
# 6. md_table_compact — 표의 정렬 패딩 제거
#
# 마크다운 표는 세로줄을 맞추려고 셀마다 공백을 채웁니다. 사람 눈에는
# 필요하지만 모델에게는 전부 토큰입니다. 구분선(`|---|---|`)도 마찬가지로
# 렌더링용이라 내용이 아닙니다.
#
# 되돌릴 수는 없지만(패딩 칸 수를 모릅니다) **셀 내용이 같으면 같습니다.**
# ══════════════════════════════════════════════════════════════════

RULE = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")


def _md_rows(text: str) -> Optional[List[List[str]]]:
    lines = [ln for ln in text.strip().split("\n") if ln.strip()]
    if len(lines) < 3 or not all("|" in ln for ln in lines):
        return None
    rows = []
    for ln in lines:
        if RULE.match(ln) and set(ln.strip()) <= set("|-: "):
            continue                       # 구분선은 내용이 아닙니다
        rows.append([c.strip() for c in ln.strip().strip("|").split("|")])
    if len(rows) < 2 or len({len(r) for r in rows}) != 1:
        return None
    return rows


def md_table_compact(text: str) -> Result:
    rows = _md_rows(text)
    if rows is None:
        return False, text, {"reason": "열 수가 일정한 마크다운 표가 아닙니다"}
    out = "\n".join(SEP.join(r) for r in rows)
    if len(out) >= len(text):
        return False, text, {"reason": "줄어들지 않습니다"}
    return True, out, {"rows": len(rows), "cols": len(rows[0])}


def md_table_canon(text: str) -> Any:
    if SEP in text:
        return [ln.split(SEP) for ln in text.strip().split("\n")]
    return _md_rows(text)


# ══════════════════════════════════════════════════════════════════
# 7. kv_compact — 키값 목록의 정렬 공백 제거
#
# 설정 파일은 콜론 위치를 맞추려고 키 뒤에 공백을 채웁니다. 키 20개면
# 눈에 안 보이는 공백이 수백 자입니다.
#
# 정규형은 (키, 값) 목록입니다. 공백은 구분자일 뿐 내용이 아닙니다.
# ══════════════════════════════════════════════════════════════════

def _kv_pairs(text: str) -> Optional[List[tuple]]:
    lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
    if len(lines) < 3:
        return None
    pairs = []
    for ln in lines:
        k, sep, v = ln.partition(":")
        if not sep or not k.strip():
            return None
        pairs.append((k.strip(), v.strip()))
    return pairs


def kv_compact(text: str) -> Result:
    pairs = _kv_pairs(text)
    if pairs is None:
        return False, text, {"reason": "'키: 값' 목록이 아닙니다"}
    out = "\n".join(f"{k}:{v}" for k, v in pairs)
    if len(out) >= len(text):
        return False, text, {"reason": "줄어들지 않습니다"}
    return True, out, {"pairs": len(pairs)}


def kv_canon(text: str) -> Any:
    return _kv_pairs(text)


# ══════════════════════════════════════════════════════════════════
# 등록표
#
# lossless=True 인 변환만 왕복 검증을 받습니다. False 인 것은 의미는
# 지키되 표현은 못 되돌린다는 선언이고, 랩은 그 사실을 결과에 남깁니다.
# ══════════════════════════════════════════════════════════════════

class Transform:
    """변환 하나. 검증 방법을 반드시 하나는 들고 있어야 합니다.

        restore  after -> before        (되돌리기. 글자 단위 일치를 봅니다)
        canon    text  -> 정규형        (양쪽을 정규형으로 바꿔 비교합니다)

    둘 다 None 이면 `lossy=True` 로 선언해야 합니다. 그래야 랩이 "이건
    검증 못 했다" 를 결과에 남길 수 있습니다.
    """

    def __init__(self, name: str, fn: Callable[..., Result],
                 restore: Optional[Callable[[str], Any]] = None,
                 canon: Optional[Callable[[str], Any]] = None,
                 note: str = ""):
        if restore is None and canon is None:
            raise ValueError(f"{name}: restore 나 canon 중 하나는 있어야 합니다")
        self.name = name
        self.fn = fn
        self.restore = restore
        self.canon = canon
        self.note = note

    @property
    def checkable(self) -> bool:
        return self.restore is not None or self.canon is not None

    def verify(self, before: str, after: str) -> Tuple[bool, str]:
        """이 변환 하나가 정보를 지켰는지 확인합니다."""
        if self.restore is not None:
            try:
                back = self.restore(after)
            except Exception as e:
                return False, f"{self.name} 복원 실패: {type(e).__name__} {e}"
            return (True, "되돌림 일치") if str(back) == before else \
                   (False, f"{self.name} 복원 결과가 원본과 다릅니다")
        try:
            a, b = self.canon(before), self.canon(after)
        except Exception as e:
            return False, f"{self.name} 정규형 실패: {type(e).__name__} {e}"
        return (True, "정규형 일치") if a == b else \
               (False, f"{self.name} 정규형이 다릅니다")


class Lossy(Transform):
    """검증할 수 없는 변환. 정보를 실제로 버립니다."""

    def __init__(self, name: str, fn: Callable[..., Result], note: str = ""):
        self.name, self.fn, self.restore, self.canon, self.note = name, fn, None, None, note

    @property
    def checkable(self) -> bool:
        return False

    def verify(self, before: str, after: str) -> Tuple[bool, str]:
        return True, f"{self.name}: 검증 불가 (되돌릴 수 없음)"


REGISTRY: Dict[str, Transform] = {
    t.name: t for t in [
        Transform("json_to_table", json_to_table, canon=json_canon,
                  note="반복되는 키를 헤더 한 줄로"),
        Transform("json_compact", json_compact, canon=json_canon,
                  note="들여쓰기·공백 제거"),
        Transform("log_dedup", log_dedup, restore=log_dedup_restore,
                  note="줄마다 반복되는 접두사를 한 번만"),
        Transform("xml_compact", xml_compact, canon=xml_canon,
                  note="태그 사이 들여쓰기 제거"),
        Transform("md_table_compact", md_table_compact, canon=md_table_canon,
                  note="표의 정렬 패딩과 구분선 제거"),
        Transform("kv_compact", kv_compact, canon=kv_canon,
                  note="키값 목록의 정렬 공백 제거"),
        Lossy("ws_collapse", ws_collapse,
              note="정렬용 공백 접기 — 원래 칸 수를 복원할 수 없습니다"),
    ]
}

# 순서가 결과를 바꿉니다. 더 많이 줄이는 변환을 먼저 시도하고, 성공하면
# 같은 대상을 겨냥한 뒤쪽 변환은 건너뜁니다.
DEFAULT_PIPELINE = ["json_to_table", "json_compact", "log_dedup",
                    "xml_compact", "md_table_compact", "kv_compact"]

# 앞이 성공하면 뒤를 건너뜁니다. 같은 입력을 두 번 바꾸면 검증이 꼬입니다.
EXCLUSIVE = {"json_to_table": ["json_compact"]}

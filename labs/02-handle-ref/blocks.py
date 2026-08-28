"""블록 저장소와 라우터.

참조 핸들의 뼈대는 두 조각입니다.

    BlockStore   본문을 블록으로 쪼개 보관하고 핸들을 붙입니다
    라우터       질문을 보고 어떤 블록을 펼칠지 고릅니다

압축률은 저장소가 정하지만 **보존율은 라우터가 정합니다.** 저장소는 아무것도
잃지 않습니다(원문이 그대로 있습니다). 잃는 순간은 라우터가 엉뚱한 블록을
고를 때입니다. 그래서 이 랩의 실패는 전부 라우팅 실패입니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class Block:
    handle: str
    title: str
    body: str

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}" if self.title else self.body


# ══════════════════════════════════════════════════════════════════
# 쪼개기
#
# 블록 경계를 어디로 잡느냐가 라우팅 난이도를 결정합니다. 문서에 이미
# 절 표시가 있으면 그걸 씁니다 — 사람이 의미 단위로 나눠 둔 것이라
# 기계가 다시 나누는 것보다 낫습니다.
# ══════════════════════════════════════════════════════════════════

SECTION = re.compile(r"^[■#]+\s*(.+)$", re.M)


def split_sections(text: str) -> List[Tuple[str, str]]:
    """`■ 제목` 형태의 절로 나눕니다. 없으면 빈 목록을 돌려줍니다."""
    marks = list(SECTION.finditer(text))
    if len(marks) < 2:
        return []
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1).strip(), text[m.end():end].strip()))
    return out


def split_paragraphs(text: str) -> List[Tuple[str, str]]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return [("", p) for p in parts]


def split_sentences(text: str, per_block: int = 2) -> List[Tuple[str, str]]:
    """문장 몇 개씩 묶습니다. 절 표시가 없는 짧은 글의 최후 수단입니다."""
    sents = [s.strip() for s in re.split(r"(?<=[.!?다요])\s+", text) if s.strip()]
    return [("", " ".join(sents[i:i + per_block]))
            for i in range(0, len(sents), per_block)]


def make_blocks(text: str, how: str = "auto", per_block: int = 2) -> List[Block]:
    if how in ("auto", "section"):
        parts = split_sections(text)
        if not parts and how == "auto":
            parts = split_paragraphs(text)
        if not parts and how == "auto":
            parts = split_sentences(text, per_block)
    elif how == "paragraph":
        parts = split_paragraphs(text)
    elif how == "sentence":
        parts = split_sentences(text, per_block)
    else:
        raise ValueError(f"모르는 분할 방식: {how}")

    if not parts:
        parts = [("", text)]
    return [Block(f"b{i + 1}", t, b) for i, (t, b) in enumerate(parts)]


# ══════════════════════════════════════════════════════════════════
# 라우터
#
# 한국어는 띄어쓰기로 단어를 자르면 조사 때문에 잘 안 맞습니다.
# ("수수료율은" vs "수수료") 그래서 **글자 2-gram** 겹침을 씁니다.
# 임베딩을 쓰면 더 낫겠지만, 그러면 이 랩이 검색 랩이 됩니다.
# 여기서 보고 싶은 건 라우팅 품질이 보존율을 어떻게 흔드는가입니다.
# ══════════════════════════════════════════════════════════════════

def bigrams(s: str) -> set:
    s = re.sub(r"\s+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def score(question: str, block: Block) -> float:
    q = bigrams(question)
    if not q:
        return 0.0
    b = bigrams(block.text)
    if not b:
        return 0.0
    # 겹친 수를 질문 길이로 나눕니다. 긴 블록이 무조건 이기지 않게 합니다.
    return len(q & b) / len(q)


def rank(question: Optional[str], blocks: List[Block],
         how: str = "bigram") -> List[Tuple[Block, float]]:
    """블록을 펼칠 우선순위대로 정렬합니다.

        bigram   질문과 글자 2-gram 이 많이 겹치는 순
        first    문서 앞에서부터 (라우팅 없음 — 대조군)
        last     문서 뒤에서부터 (최근 대화를 남기는 전략의 문서판)

    `first` 가 중요합니다. 라우터 없이 "앞에서 k개만 남기기" 는 가장 흔한
    절단 방식인데, 정답이 뒤에 있으면 그냥 못 찾습니다. 라우팅이 값을
    하는지 보려면 이것과 비교해야 합니다.
    """
    if how == "first":
        return [(b, 0.0) for b in blocks]
    if how == "last":
        return [(b, 0.0) for b in reversed(blocks)]
    if how != "bigram":
        raise ValueError(f"모르는 라우팅: {how} (bigram | first | last)")
    if not question:
        return [(b, 0.0) for b in blocks]
    return sorted(((b, score(question, b)) for b in blocks),
                  key=lambda x: -x[1])


# ══════════════════════════════════════════════════════════════════
# 다이제스트
#
# 펼치지 않은 블록도 흔적은 남겨야 합니다. 흔적이 없으면 모델은 그런
# 내용이 있었는지조차 모르고, 도구를 호출할 판단도 못 합니다.
# 이 흔적의 길이가 곧 오버헤드입니다.
# ══════════════════════════════════════════════════════════════════

def digest_line(b: Block, chars: int) -> str:
    if b.title:
        head = b.title
        if chars > 0:
            head += ": " + re.sub(r"\s+", " ", b.body)[:chars]
    else:
        head = re.sub(r"\s+", " ", b.body)[:max(chars, 12)]
    return f"[[{b.handle}]] {head}"


def render(blocks: List[Block], expand: set, digest_chars: int,
           header: bool = True) -> str:
    """컨텍스트에 실제로 들어갈 문자열을 만듭니다.

    펼친 블록은 원문 그대로, 나머지는 다이제스트 한 줄로 들어갑니다.
    """
    lines = []
    if header:
        lines.append("# 문서 색인 — [[핸들]] 로 본문을 요청할 수 있습니다")
    for b in blocks:
        if b.handle in expand:
            lines.append(f"[[{b.handle}]] {b.title}".rstrip())
            lines.append(b.body)
        else:
            lines.append(digest_line(b, digest_chars))
    return "\n".join(lines)

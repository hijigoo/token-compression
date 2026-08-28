"""RECOMP (extractive) 압축기.

    pip install sentence-transformers

RECOMP 는 pip 패키지가 아니라 논문 기법이다. 여기서는 extractive 변형을
구현한다: 문장 단위로 쪼개고, 질의(직전 대화)와의 임베딩 유사도로 순위를
매겨 상위 `ratio` 만큼만 **원래 순서대로** 남긴다.

RECOMP 계열 접근이다. 검색 성격이 강해 `labs/` 에는 별도 랩을 두지 않았고,
에이전트 컨텍스트 압축기로만 쓴다. 여기 구현은 독립적이다. 원래 방식은 text->text
오프라인이고 여기는 프록시 안의 messages->messages 라 시그니처가 다르며,
공유되는 실체는 "어떤 모델을 어떤 파라미터로 부르나" 20줄 정도다.
그 20줄을 위해 폴더 간 import 를 만들지 않는다.
"""

from __future__ import annotations

import re
from functools import lru_cache

from . import apply_to_messages

MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


@lru_cache(maxsize=1)
def _encoder():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "sentence-transformers 가 설치되지 않았습니다.\n"
            "  cd labs/agentic-eval && uv pip install sentence-transformers"
        ) from e
    return SentenceTransformer(MODEL)


def _split(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text) if s.strip()]


def compress(messages: list[dict], ratio: float) -> list[dict]:
    import numpy as np

    enc = _encoder()

    # 질의 = 마지막 사용자/툴 메시지. 에이전트의 현재 관심사를 대변한다.
    query = ""
    for msg in reversed(messages):
        if isinstance(msg.get("content"), str) and msg.get("role") in ("user", "tool"):
            query = msg["content"][:2000]
            break

    q_vec = enc.encode([query or " "], normalize_embeddings=True)[0]

    def _fn(text: str) -> str:
        sents = _split(text)
        if len(sents) < 4:
            return text  # 쪼갤 게 없으면 원문

        keep_n = max(1, int(len(sents) * ratio))
        if keep_n >= len(sents):
            return text

        vecs = enc.encode(sents, normalize_embeddings=True)
        scores = np.asarray(vecs) @ q_vec

        # 상위 keep_n 개를 고르되 출력은 원래 순서로 — 순서가 섞이면
        # 코드나 로그의 맥락이 무너진다.
        top = sorted(np.argsort(-scores)[:keep_n])
        return "\n".join(sents[i] for i in top)

    return apply_to_messages(messages, _fn)

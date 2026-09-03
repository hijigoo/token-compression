"""LLMLingua-2 의 작은 모델 — 모델 크기 축을 보기 위한 조건.

`llmlingua.py` 와 알고리즘은 같고 **모델만 다릅니다.**

    llmlingua        xlm-roberta-large   약 2.2GB  (논문이 쓴 것)
    llmlingua-small  bert-base-multi     약 700MB

랩 04 에서 큰 모델이 **더 줄이면서 더 지켰습니다.** 오프라인 텍스트에서
나온 결과인데, 코드 컨텍스트에서도 그런지는 돌려봐야 압니다. 작은 모델로
충분하다면 메모리와 지연을 크게 아낄 수 있습니다.
"""

from __future__ import annotations

from . import apply_to_messages
from .llmlingua import _make, _compress_fn

MODEL = "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank"


def compress(messages: list[dict], ratio: float) -> list[dict]:
    return apply_to_messages(messages, _compress_fn(_make(MODEL), ratio))

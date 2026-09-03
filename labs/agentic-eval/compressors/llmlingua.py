"""LLMLingua-2 압축기.

    pip install llmlingua

`labs/04-llmlingua` 와 라이브러리는 같지만 파라미터는 다르다. 저쪽은 오프라인
텍스트의 압축률 대비 ROUGE 를 재고, 여기는 에이전트 컨텍스트의 압축률 대비
pass@1 을 잰다. 질문이 다르므로 값이 같을 이유가 없다.
"""

from __future__ import annotations

from functools import lru_cache

from . import apply_to_messages, device, lingua_kwargs

MODEL = "microsoft/llmlingua-2-xlm-roberta-large-meetingbank"


@lru_cache(maxsize=3)
def _make(model: str = MODEL):
    try:
        from llmlingua import PromptCompressor
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "llmlingua 가 설치되지 않았습니다.\n"
            "  cd labs/agentic-eval && uv pip install llmlingua"
        ) from e

    # 모델 로딩은 수 초~수십 초 걸린다. 프록시 기동 시 1회만 수행한다.
    return PromptCompressor(model_name=model, use_llmlingua2=True,
                            device_map=device())


def _compress_fn(comp, ratio: float):
    """텍스트 하나를 압축하는 함수를 만듭니다. 모델을 공유하려고 나눴습니다."""
    def _fn(text: str) -> str:
        result = comp.compress_prompt(
            [text],          # v1 은 목록을 받는다. v2 도 목록으로 통일한다
            rate=ratio,
            **lingua_kwargs(),
        )
        return result["compressed_prompt"]
    return _fn


def compress(messages: list[dict], ratio: float) -> list[dict]:
    return apply_to_messages(messages, _compress_fn(_make(MODEL), ratio))

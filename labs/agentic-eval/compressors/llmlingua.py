"""LLMLingua-2 압축기.

    pip install llmlingua

`labs/04-llmlingua` 와 라이브러리는 같지만 파라미터는 다르다. 저쪽은 오프라인
텍스트의 압축률 대비 ROUGE 를 재고, 여기는 에이전트 컨텍스트의 압축률 대비
pass@1 을 잰다. 질문이 다르므로 값이 같을 이유가 없다.
"""

from __future__ import annotations

from functools import lru_cache

from . import apply_to_messages

MODEL = "microsoft/llmlingua-2-xlm-roberta-large-meetingbank"


@lru_cache(maxsize=1)
def _compressor():
    try:
        from llmlingua import PromptCompressor
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "llmlingua 가 설치되지 않았습니다.\n"
            "  cd labs/agentic-eval && uv pip install llmlingua"
        ) from e

    # 모델 로딩은 수 초~수십 초 걸린다. 프록시 기동 시 1회만 수행한다.
    return PromptCompressor(model_name=MODEL, use_llmlingua2=True)


def compress(messages: list[dict], ratio: float) -> list[dict]:
    comp = _compressor()

    def _fn(text: str) -> str:
        # rate 는 유지 비율. force_tokens 로 코드 구조 문자를 보존한다 —
        # 에이전트 컨텍스트는 대부분 파일 내용과 셸 출력이라
        # 개행/괄호가 사라지면 모델이 파일 구조를 못 읽는다.
        result = comp.compress_prompt(
            text,
            rate=ratio,
            force_tokens=["\n", "?", ".", "!", ",", ":", "{", "}", "(", ")"],
            drop_consecutive=True,
        )
        return result["compressed_prompt"]

    return apply_to_messages(messages, _fn)

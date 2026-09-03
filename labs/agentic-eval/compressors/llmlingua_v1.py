"""LLMLingua v1 압축기 — perplexity 기반 토큰 프루닝.

    pip install llmlingua

`llmlingua.py`(v2) 와 같은 라이브러리지만 **알고리즘이 다릅니다.**

| | v1 (여기) | v2 (`llmlingua.py`) |
|---|---|---|
| 판단 근거 | 인과 LM 의 perplexity — 예측 가능한 토큰을 버림 | 분류 모델이 토큰별로 남길지 판정 |
| 모델 | 생성 모델 (Qwen2.5 등) | 전용 인코더 |
| 질문 | 안 씁니다 | 안 씁니다 |

**왜 둘 다 두나.** 판단 근거가 달라서 무엇을 버리는지가 다릅니다. 코드
컨텍스트에서 어느 쪽이 덜 망가지는지는 돌려봐야 알 수 있습니다.

## LongLLMLingua 는 왜 없나

`compressors/__init__.py` 의 주석을 봐주세요. 요약하면 우리 프록시는
메시지를 하나씩 압축하는데, LongLLMLingua 의 기여는 **문서들 사이**의
순위·재배열이라 여기서는 발동하지 않습니다.

## 주의 — 숫자가 깨집니다

랩 04 에서 확인된 것입니다. 토큰 단위로 자르다 보니 `32,450,000` 같은
값이 여러 토큰으로 쪼개져 있고, 그중 하나만 빠져도 문자열이 망가집니다.
모델을 3배 키워도 고쳐지지 않았습니다.

에이전트 컨텍스트에서는 이게 더 위험합니다. 파일 경로나 식별자가 한 글자
깨지면 패치가 적용조차 안 됩니다. `force_reserve_digit` 로 숫자는
막아두지만 식별자까지 지켜주지는 않습니다.
"""

from __future__ import annotations

from functools import lru_cache

from . import apply_to_messages, device, lingua_kwargs

MODEL = "Qwen/Qwen2.5-1.5B"
"""랩 04 의 large 티어와 같은 모델.

논문은 Llama-2-7b(약 13GB)를 썼지만, arm 하나가 그만큼을 상주시키면
여러 arm 을 동시에 띄울 수 없습니다. 작은 모델의 한계로 나온 결과를
알고리즘 한계로 읽지 않도록, small(0.5B) 대신 이쪽을 씁니다.
"""


PREFLIGHT = "The quick brown fox jumps over the lazy dog. " * 60
"""기동 시 한 번 압축해 보는 문장.

짧은 텍스트는 iterative_compress_prompt 경로를 타지 않아 아래 비호환이
드러나지 않는다. 실제 에이전트 메시지 길이에 가까운 것으로 미리 밟아 본다.
"""


@lru_cache(maxsize=1)
def _compressor():
    try:
        from llmlingua import PromptCompressor
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "llmlingua 가 설치되지 않았습니다.\n"
            "  cd labs/agentic-eval && uv pip install --python .venv llmlingua"
        ) from e

    # 모델 로딩은 수 초~수십 초 걸린다. 프록시 기동 시 1회만 수행한다.
    # use_llmlingua2 를 주지 않으면 v1 입니다.
    comp = PromptCompressor(model_name=MODEL, device_map=device())

    # ── 여기서 미리 밟아 보는 이유 ────────────────────────────
    # 실패해도 apply_to_messages 가 원문을 통과시키므로 실행은 계속된다.
    # 그러면 결과표에 "절감 0%" 로 찍히는데, 그게 압축기의 성질인지 버그인지
    # 구분할 방법이 없다. 조용히 틀린 결론을 내느니 기동 때 죽는 편이 낫다.
    try:
        comp.compress_prompt([PREFLIGHT], rate=0.5)
    except ValueError as e:
        if "too many values to unpack" not in str(e):
            raise
        import transformers
        raise RuntimeError(
            f"llmlingua v1 이 이 transformers 버전과 맞지 않습니다 "
            f"(transformers {transformers.__version__}).\n"
            f"  past_key_values 형식이 바뀌었는데 llmlingua 0.2.2 는 예전 튜플을\n"
            f"  가정합니다. 긴 입력에서만 그 경로를 타서, 짧은 글로 시험하면\n"
            f"  드러나지 않습니다. 에이전트 메시지는 항상 깁니다.\n"
            f"\n"
            f"  이 랩의 기본은 v2(compressor: llmlingua)이고 그쪽은 영향받지\n"
            f"  않습니다. v1 이 꼭 필요하시면 transformers 를 4.x 로 내리거나\n"
            f"  llmlingua 상류 수정을 기다려 주세요."
        ) from e
    return comp


def compress(messages: list[dict], ratio: float) -> list[dict]:
    comp = _compressor()

    def _fn(text: str) -> str:
        result = comp.compress_prompt(
            [text],          # v1 은 목록을 받는다. v2 도 목록으로 통일한다
            rate=ratio,
            **lingua_kwargs(),
        )
        return result["compressed_prompt"]

    return apply_to_messages(messages, _fn)

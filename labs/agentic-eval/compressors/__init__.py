"""압축기 레지스트리.

라이브러리 하나 = 파일 하나. 폴더를 만들지 않는다.

각 모듈은 아래 하나만 노출하면 된다::

    def compress(messages: list[dict], ratio: float) -> list[dict]

`ratio` 는 **유지 비율**이다. 0.8 이면 원본의 80% 를 남긴다 (낮을수록 공격적).

새 라이브러리 추가:
    1. 이 폴더에 `<이름>.py` 를 만들고 `compress()` 를 구현한다
    2. 아래 REGISTRY 에 한 줄 추가한다
    3. experiments/*.yaml 에서 `compressor: <이름>` 으로 참조한다

Headroom 은 여기 없다. 이미 독립 프록시라 감쌀 필요가 없고,
launch.py 가 별도 프로세스로 띄운다.
"""

from __future__ import annotations

import importlib
from typing import Callable, Protocol


class Compressor(Protocol):
    def __call__(self, messages: list[dict], ratio: float) -> list[dict]: ...


# 이름 -> 모듈 경로. 무거운 의존성(torch 등)을 피하려고 지연 import 한다.
REGISTRY: dict[str, str | None] = {
    "none": None,  # 대조군 — 아무것도 하지 않음
    "truncate": "compressors.truncate",  # 대조군 — 그냥 뒤를 자른다
    "llmlingua": "compressors.llmlingua",        # v2 — 기본. 분류 모델
    "llmlingua-v1": "compressors.llmlingua_v1",  # v1 — perplexity (아래 주의)
    "recomp": "compressors.recomp",
}
"""LongLLMLingua 는 일부러 넣지 않았다.

세 형제 중 v1·v2 만 있다. LongLLMLingua 가 빠진 것은 설치가 어려워서가
아니라 **여기서는 그 알고리즘이 돌지 않기 때문**이다.

LongLLMLingua 의 기여는 문서들 *사이*에 있다. 질문과의 관련도로 문서를
순위 매기고, 낮은 것을 통째로 버리고, 관련도 순으로 재배열한다. 검색된
문단 20개 중 정답이 든 하나를 고르는 상황을 위한 설계다.

에이전트 컨텍스트는 그 모양이 아니다.

  · 아래 apply_to_messages 가 메시지를 **하나씩** 넘긴다. 문서가 하나뿐이라
    순위도 재배열도 발동하지 않는다. 그냥 "질문을 곁들인 v1" 이 된다
  · 독립된 문서가 아니라 순서가 곧 의미인 시퀀스다. 재배열하면 에이전트가
    무슨 명령을 언제 실행했는지가 뒤섞인다
  · 버릴 기준이 "질문과의 관련도" 가 아니라 "이미 써먹은 정보인가" 다

넣어두면 "LongLLMLingua 를 평가했다" 고 말하게 되는데 실제로 돈 것은 다른
것이므로, 결론이 틀린다. 그래서 뺐다.

정말 보시려면 메시지 배열 전체를 문서 목록으로 넘기고 reorder_context 를
끄는 별도 압축기를 만들어야 한다. apply_to_messages 를 쓰지 않는 구조다.

## 기본은 v2 다

`llmlingua` 라는 이름은 v2 를 가리킨다. v1 은 `llmlingua-v1` 로 따로 골라야
한다. 그렇게 둔 이유는 v1 이 **현재 버전 조합에서 긴 입력에 깨지기**
때문이다.

    llmlingua 0.2.2   past_key_values 를 (k, v) 튜플로 가정
    transformers 5.x  Cache 객체로 바뀜

짧은 글은 iterative_compress_prompt 경로를 타지 않아 멀쩡히 돌지만, 대략
1KB 를 넘기면 터진다. 에이전트 메시지는 항상 그보다 길다. llmlingua_v1.py
가 기동 시에 미리 밟아 보고 명확한 메시지로 죽는다.
"""


def get(name: str) -> Compressor:
    if name not in REGISTRY:
        raise KeyError(f"알 수 없는 압축기: {name!r} (가능: {', '.join(REGISTRY)})")
    module_path = REGISTRY[name]
    if module_path is None:
        return _identity
    mod = importlib.import_module(module_path)
    if not hasattr(mod, "compress"):
        raise AttributeError(f"{module_path} 에 compress() 가 없습니다")
    return mod.compress


def device() -> str:
    """모델을 올릴 장치. 없으면 cpu 로 떨어진다.

    llmlingua 는 device_map 을 주지 않으면 cuda 를 기본으로 잡는다. GPU 가
    없는 곳에서는 모델 로딩 자체가 AssertionError 로 죽는데, 그게 프록시
    기동 시점에 나므로 원인을 찾기 어렵다.
    """
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    # Apple Silicon. llmlingua 내부에서 mps 미지원 연산이 나올 수 있어
    # 안전하게 cpu 를 쓴다. 압축은 배치가 작아 체감 차이가 크지 않다.
    return "cpu"


def _identity(messages: list[dict], ratio: float) -> list[dict]:
    return messages


# ─────────────────────────────────────────────────────────────
# 공통 헬퍼 — 어떤 메시지를 압축할지 고르는 규칙
# ─────────────────────────────────────────────────────────────

MIN_CHARS = 400
"""이보다 짧은 메시지는 건드리지 않는다.

짧은 텍스트는 압축해도 절감이 미미한 반면, 지시문이 깨질 위험은 그대로다.
"""

KEEP_LAST = 2
"""마지막 N개 메시지는 원문 유지.

에이전트의 직전 관측(툴 출력)과 현재 지시는 다음 행동을 직접 결정한다.
여기를 손상시키면 압축 품질과 무관하게 루프가 무너진다.
"""


def apply_to_messages(
    messages: list[dict],
    fn: Callable[[str], str],
    *,
    min_chars: int = MIN_CHARS,
    keep_last: int = KEEP_LAST,
    skip_system: bool = True,
) -> list[dict]:
    """압축 대상 메시지만 골라 `fn` 을 적용한다.

    system 프롬프트는 기본으로 건드리지 않는다. mini-swe-agent 는 여기에
    출력 형식 계약(어떻게 bash 를 호출할지)을 넣는데, 이게 깨지면 파싱이
    실패해 모델 성능과 무관하게 trial 이 0점이 된다.
    """
    out: list[dict] = []
    last_idx = len(messages) - keep_last

    for i, msg in enumerate(messages):
        content = msg.get("content")

        skip = (
            not isinstance(content, str)  # 멀티모달 파트는 대상 아님
            or (skip_system and msg.get("role") == "system")
            or i >= last_idx
            or len(content) < min_chars
        )
        if skip:
            out.append(msg)
            continue

        try:
            new_content = fn(content)
        except Exception as e:  # noqa: BLE001
            # 압축 실패가 API 오류로 번지면 "정확도 하락" 으로 잘못 집계된다.
            # 원문을 그대로 통과시키고 계속 간다.
            print(f"[compressors] 압축 실패 (원문 유지): {type(e).__name__}: {e}", flush=True)
            out.append(msg)
            continue

        out.append({**msg, "content": new_content})

    return out

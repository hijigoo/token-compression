"""잘라내기 — 대조군.

라이브러리 없이 앞에서부터 남기고 뒤를 버린다. 의존성이 없어서 어디서나
바로 돈다.

**왜 이런 걸 두나.** "LLMLingua 로 40% 줄였더니 pass@1 이 조금 떨어졌다" 는
그 자체로는 좋은지 나쁜지 알 수 없다. 그냥 뒤를 잘라도 같은 결과가 나온다면,
그 라이브러리는 값을 못 한 것이다. 정교한 압축기는 **이것보다 나아야**
의미가 있다.

토큰이 아니라 글자 수로 자른다. 토크나이저를 부르지 않으므로 빠르고, 어차피
"제대로 고르지 않은 압축" 의 하한을 보려는 것이라 정밀할 필요가 없다.
"""

from __future__ import annotations

from . import apply_to_messages

MARK = "\n…(잘림)\n"
"""잘렸다는 사실을 모델에게 알린다.

말없이 자르면 모델은 문장이 원래 그렇게 끝난 줄 안다. 그러면 "정보가 없어서
못 풀었다" 와 "정보가 잘린 줄 몰라서 틀렸다" 가 섞인다.
"""


def compress(messages: list[dict], ratio: float) -> list[dict]:
    def _fn(text: str) -> str:
        keep = int(len(text) * ratio)
        if keep >= len(text):
            return text
        # 표시 문자열도 예산 안에서 낸다. 안 그러면 ratio=1 에 가까울 때
        # 결과가 원문보다 길어져 "압축했는데 늘어남" 이 된다.
        keep = max(0, keep - len(MARK))
        return text[:keep] + MARK

    return apply_to_messages(messages, _fn)

# labs/data — 공유 입력 코퍼스

`labs/00~09`가 **동일한 입력**으로 비교되도록 하는 곳.
서로 다른 텍스트로 잰 압축률은 비교할 수 없으므로, 이 폴더는 실험의 전제조건이다.

## ⚠️ 불변 규칙

**한 번 추가한 파일은 수정하지 않는다.**

내용이 바뀌면 과거 `runs/` 결과와 비교가 깨지는데, 이건 **아무 에러 없이 조용히**
일어난다. 두 달 전 숫자와 오늘 숫자가 왜 다른지 영원히 알 수 없게 된다.

바꿔야 하면 수정하지 말고 새로 추가한다:

```
docs-long/      →  docs-long-v2/     (기존은 그대로 둔다)
```

## 구성

| 폴더 | 용도 | 주 소비자 |
|---|---|---|
| `conversations/` | 멀티턴 대화 로그 | `05-summarize-llm`, `08-azure-compaction` |
| `docs-long/` | 장문 문서 (RAG 컨텍스트) | `01-llmlingua`, `02-selective-context`, `06-recomp` |
| `code/` | 소스 코드 파일 | `03-lossless-structure`, `04-handle-ref` |

## 코퍼스 추가 방법

각 코퍼스 폴더에는 `manifest.json`이 **반드시** 있어야 한다. 출처와 리비전이
없으면 재현이 불가능하다.

```json
{
  "name": "docs-long",
  "source": "https://huggingface.co/datasets/...",
  "revision": "a1b2c3d",
  "license": "CC-BY-4.0",
  "n_samples": 200,
  "added_at": "2026-08-28",
  "note": "평균 12k 토큰. 8k 미만 샘플은 제외했다."
}
```

절차:

1. `fetch.sh`에 획득 로직을 추가한다 (수동 복사가 아니라 스크립트로 — 재현 가능해야 한다)
2. `manifest.json`을 작성한다
3. `./fetch.sh <코퍼스명>`으로 검증한다

## 왜 데이터 파일은 커밋하지 않나

용량 문제도 있지만, 더 큰 이유는 **고객 데이터가 섞일 수 있어서**다.
`.gitignore`가 `labs/data/**`를 제외하되 `README.md`·`fetch.sh`·`manifest.json`만
남긴다. 데이터는 항상 `fetch.sh`로 재획득한다.

## deep-swe는 여기 없다

`labs/agentic-eval/deep-swe/`에 있다. 그건 압축할 코퍼스가 아니라 Docker 실행
픽스처이고, 소비자가 `agentic-eval` 하나뿐이기 때문이다.

> 배치 규칙: **소비자가 2개 이상이면 밖으로, 1개면 소비자 안에.**

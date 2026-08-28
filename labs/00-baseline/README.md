# 00-baseline — 압축하지 않는 랩

아무것도 압축하지 않습니다. 그런데도 가장 먼저 만들었고, 다른 랩을 건드리기
전에 항상 여기부터 돌려보시길 권합니다. 이유를 설명드리겠습니다.

## 이 랩이 왜 필요한가요

두 가지 역할을 합니다.

### 1. 기준선이 되어 줍니다

"40% 절감"이라는 말은 그 자체로는 아무 뜻이 없습니다. **무엇 대비 40%인지**가
있어야 비로소 의미가 생깁니다. 같은 코퍼스를 압축 없이 통과시킨 결과가 바로
그 기준입니다.

### 2. 측정 도구가 멀쩡한지 확인해 줍니다

압축을 하지 않았으니 결과가 어떻게 나와야 하는지 미리 알 수 있습니다.

```
ratio           1.0     남은 비율
saved           0.0     절감률
survival_worst  1.0     정답에 필요한 문자열이 하나도 사라지지 않음
```

**이 값이 안 나온다면 압축기가 아니라 측정 도구가 고장 난 것입니다.**
토크나이저·로더·지표 계산 중 하나가 잘못됐다는 뜻이라, 그 상태로 다른 랩을
돌려봐야 나온 숫자를 믿을 수 없습니다.

새 랩을 추가하시거나 `kit`을 손보신 뒤에는 여기부터 한 번 돌려주세요.
1초면 끝나고, 잘못된 숫자를 며칠 들여다보는 일을 막아줍니다.

## 시작하기

노트북으로 보시는 편이 이해가 빠릅니다. 원리를 한 단계씩 따라가고, 마지막에
이 랩의 모든 설정을 자동으로 돌려서 비교해 줍니다.

```bash
jupyter lab run.ipynb
```

명령줄로 돌리셔도 됩니다.

```bash
uv pip install -r ../kit/requirements.txt      # 처음 한 번만
python compress.py configs/noop.yaml
```

결과는 `runs/00-baseline/noop/<시각>/`에 쌓입니다.

| 파일 | 내용 | 커밋하나요 |
|---|---|---|
| `config.snapshot.yaml` | 설정 + kit 버전 + 실행 환경 | 예 |
| `metrics.json` | 집계 지표 | 예 |
| `report.md` | 사람이 읽는 요약 | 예 |
| `records.jsonl` | 케이스별 원문·압축문 | 아니요 |

## 결과 읽는 법

`report.md`에서 아래 세 줄만 보시면 충분합니다.

| 항목 | 정상값 | 다르게 나온다면 |
|---|---|---|
| 절감률 | `0.0%` | 압축을 안 했는데 줄었다면 로더가 원문을 바꾸고 있습니다 |
| 최저 보존율 | `100%` | 정답 문자열을 못 찾는다면 `must_include`나 정규화 쪽을 확인해 주세요 |
| 측정 방식 | `tiktoken:o200k_base` | `heuristic`이면 tiktoken이 설치돼 있지 않다는 뜻입니다 |

마지막 항목이 은근히 중요합니다. **측정 방식이 다르면 두 실행의 숫자를 나란히
놓으시면 안 됩니다.** `heuristic`은 문자 기반 근사라서 `tiktoken` 값과
10~20% 어긋납니다.

## 설정

```yaml
name: noop
lab: 00-baseline
params: {}                      # 압축을 안 하니 조정할 것이 없습니다
dataset:
  path: ../../data/sample       # config 파일 기준 상대경로입니다
  limit: null
model: gpt-5.4                  # 토큰 인코딩을 고르는 값입니다
```

`model`은 **API를 부르는 값이 아닙니다.** `tiktoken` 인코딩을 고르는 데만
씁니다. 기본 설정에서 이 랩은 네트워크를 전혀 쓰지 않습니다.

## 토큰을 어떻게 셀지 고르실 수 있습니다

같은 텍스트라도 재는 방법에 따라 숫자가 달라집니다. `configs/*.yaml`의
`tokenizer`에서 고르시면 됩니다.

| | `local` (기본) | `api` |
|---|---|---|
| 방법 | tiktoken, 없으면 문자 근사 | 모델을 호출해 `usage.input_tokens`를 읽습니다 |
| 비용 | 0 | 텍스트마다 호출 1회 |
| 정확도 | 근사치 | **과금 기준 그대로** |
| 포함되는 것 | 텍스트만 | 텍스트 + 메시지 포맷 오버헤드 (실측 +6) |

```yaml
tokenizer:
  mode: api            # local | api
  deployment:          # 비우면 .env 의 AZURE_OPENAI_DEPLOYMENT 를 씁니다
  cache: true          # 같은 텍스트는 한 번만 호출합니다
```

`api`를 써보시려면 자격증명이 필요합니다.

```bash
cd labs && cp .env.example .env       # 또는 cp ../scripts/explore/.env .env
cd 00-baseline && python compress.py configs/noop-api.yaml
```

`.env` 변수 이름은 `scripts/explore/.env.example`과 같습니다. 찾는 순서는
`labs/.env` → 저장소 루트 `.env` → `scripts/explore/.env`이고, 셸에 이미 있는
환경변수가 항상 우선합니다.

> **두 방식의 절대 토큰 수를 나란히 놓지 말아주세요.** `api` 값에는 메시지
> 포맷 오버헤드가 포함되어 `local`보다 일관되게 큽니다. 압축 전후를 같은
> 방식으로 재기 때문에 **절감률 비교는 안전하지만**, 절대값은 다릅니다.
> 그래서 모든 결과에 `token_backend`를 기록해 둡니다.

> **`api`를 쓰실 때 캐시를 끄지 말아주세요.** 케이스 N건이면 압축 전후로
> 2N회를 부르고, 압축률 스윕 10단계면 그만큼 곱해집니다. 결과는
> `labs/kit/.cache/`에 남아 다음 실행부터 재사용됩니다(커밋 제외).

## 코퍼스

기본값은 `labs/data/sample`입니다. **하네스 점검용 합성 데이터 12건**이고
벤치마크가 아닙니다. 압축이 잘 깨지는 자리 여섯 가지를 골라 각 2건씩
넣어 두었습니다.

| 유형 | 무엇을 겨냥하나요 |
|---|---|
| `numeric` | 숫자·금액이 잘려나가는 경우 |
| `negation` | 부정어가 사라져 뜻이 뒤집히는 경우 |
| `identifier` | ID·고유명사가 파편화되는 경우 |
| `similar` | 비슷한 문서 중 엉뚱한 것이 남는 경우 |
| `structured` | 표·JSON 구조가 무너지는 경우 |
| `short` | 압축이 오히려 손해인 구간 |

다른 코퍼스로 돌려보실 때는 `--data`를 쓰시면 됩니다.

```bash
python compress.py configs/noop.yaml --data ../data/sample-long
```

## 이 랩이 다루지 않는 것

- **품질 평가** — 모델에게 물어보지 않습니다. 정답 보존율은 문자열 검사입니다
- **비용 계산** — 기본 설정에서는 API를 안 부르므로 과금 토큰이 없습니다

둘 다 API를 쓰는 랩([`03-summarize-llm`](../03-summarize-llm/) 이후)에서
다룹니다.

## 다음은

[`01-lossless-structure`](../01-lossless-structure/)로 가시면 됩니다.
`compress()` 함수 하나만 바뀌고 나머지는 여기서 보신 그대로입니다.

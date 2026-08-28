# 00-baseline — 압축 없음

**아무것도 압축하지 않는 랩입니다.** 그래서 가장 먼저 만들었습니다.

## 왜 이런 랩이 필요한가

두 가지 역할을 합니다.

### 1. 기준선 — 다른 랩의 숫자는 여기에 대한 비율입니다

"40% 절감"은 그 자체로 의미가 없습니다. **무엇 대비 40%인지**가 있어야 합니다.
같은 코퍼스를 압축 없이 통과시킨 결과가 그 기준입니다.

### 2. 하네스 검증 — 여기서 틀리면 나머지가 전부 틀립니다

압축을 안 했으니 결과가 뻔합니다.

```
ratio           1.0     (남은 비율)
saved           0.0     (절감률)
survival_worst  1.0     (정답에 필요한 문자열이 하나도 안 사라짐)
```

**이 값이 안 나오면 압축기가 아니라 하네스가 고장 난 것입니다.**
토크나이저, 로더, 지표 계산 중 하나가 잘못됐다는 뜻이라 다른 랩을 돌려봐야
소용이 없습니다. 새 랩을 추가하거나 `kit` 을 고친 뒤에는 여기부터 돌리세요.

## 실행

```bash
# 처음 한 번
uv pip install -r ../kit/requirements.txt

# 실행
python compress.py configs/noop.yaml
```

결과는 `runs/00-baseline/noop/<타임스탬프>/` 에 쌓입니다.

```
config.snapshot.yaml   설정 + kit 버전 + 환경     (커밋)
metrics.json           집계 지표                   (커밋)
report.md              사람이 읽는 요약             (커밋)
records.jsonl          케이스별 원문·압축문         (커밋 안 함)
```

## 설정

```yaml
name: noop
lab: 00-baseline
params: {}                      # 압축 없음 — 조정할 게 없습니다
dataset:
  path: ../../data/sample       # config 파일 기준 상대경로
  limit: null
model: gpt-5.4                  # 토큰 계산에 쓸 인코딩 기준 (호출하지 않습니다)
```

`model` 은 **API 를 부르는 값이 아닙니다.** `tiktoken` 인코딩을 고르는 데만 씁니다.
이 랩은 네트워크를 쓰지 않습니다.

## 읽는 법

`report.md` 의 이 세 줄만 보면 됩니다.

| 항목 | 정상값 | 아니면 |
|---|---|---|
| 절감률 | `0.0%` | 압축을 안 했는데 줄었다면 로더가 원문을 변형하고 있습니다 |
| 최저 보존율 | `100%` | 정답 문자열을 못 찾는다면 `must_include` 나 정규화가 틀렸습니다 |
| 측정 방식 | `tiktoken:o200k_base` | `heuristic` 이면 tiktoken 이 없다는 뜻입니다 |

마지막 항목이 중요합니다. **측정 방식이 다르면 두 실행의 숫자를 나란히 놓으면 안 됩니다.**
`heuristic` 은 문자 기반 근사라 `tiktoken` 값과 10~20% 어긋납니다.

## 코퍼스

기본값은 `labs/data/sample` 입니다. **하네스 점검용 합성 데이터 12건**이고
벤치마크가 아닙니다. 유형은 여섯 가지입니다.

| 유형 | 겨냥하는 실패 |
|---|---|
| `numeric` | 숫자·금액 절단 |
| `negation` | 부정어 소실 — 뜻이 뒤집힙니다 |
| `identifier` | ID·고유명사 파편화 |
| `similar` | 비슷한 문서 중 엉뚱한 것이 남음 |
| `structured` | 표·JSON 구조 파괴 |
| `short` | 압축이 손해인 구간 |

실제 실험은 `./fetch.sh` 로 받는 코퍼스(`docs-long`, `conversations`, `code`)를 씁니다.

```bash
python compress.py configs/noop.yaml --data ../data/docs-long
```

## 이 랩에 없는 것

- **품질 평가** — 모델에 물어보지 않습니다. `survival` 은 문자열 검사입니다
- **비용 계산** — API 를 안 부르므로 `billed_input` 이 없습니다

둘 다 API 를 쓰는 랩(`03-summarize-llm` 이후)에서 다룹니다.

## 토큰을 어떻게 셀 것인가

**두 가지 방식이 있고 `configs/*.yaml` 의 `tokenizer` 로 고릅니다.**

| | `local` (기본) | `api` |
|---|---|---|
| 방법 | tiktoken, 없으면 문자 근사 | 모델을 호출해 `usage.input_tokens` 를 읽음 |
| 비용 | 0 | 텍스트마다 호출 1회 |
| 정확도 | 근사 | **과금 기준 그대로** |
| 포함 | 텍스트만 | 텍스트 + 메시지 포맷 오버헤드 (실측 +6) |

```yaml
tokenizer:
  mode: api            # local | api
  deployment:          # 비우면 .env 의 AZURE_OPENAI_DEPLOYMENT
  cache: true          # 같은 텍스트는 한 번만 호출합니다
```

```bash
cd labs && cp .env.example .env       # 또는 cp ../scripts/explore/.env .env
cd 00-baseline && python compress.py configs/noop-api.yaml
```

`.env` 변수명은 `scripts/explore/.env.example` 과 **같습니다.** 찾는 순서는
`labs/.env` → 저장소 루트 `.env` → `scripts/explore/.env` 이고, 셸 환경변수가 항상 우선입니다.

> **측정 방식이 다르면 비교하지 마세요.** `api` 값에는 메시지 포맷 오버헤드가
> 포함되어 `local` 보다 일관되게 큽니다. 압축 전후를 같은 방식으로 재므로
> **절감률 비교는 안전하지만**, 절대 토큰 수를 다른 랩과 나란히 놓으면 안 됩니다.
> 그래서 모든 결과에 `token_backend` 를 기록합니다.

> **`api` 는 캐시가 필수입니다.** 케이스 N건이면 압축 전후로 2N 회를 부르고,
> 압축률 스윕 10단계면 그만큼 곱해집니다. 결과는 `labs/kit/.cache/` 에 남아
> 다음 실행에서 재사용됩니다(커밋 제외).

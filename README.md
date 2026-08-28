# token-compression

LLM 컨텍스트 압축 기법을 동일 조건에서 비교하는 실험 저장소.

## 폴더 규칙

| 경로 | 의미 |
|---|---|
| `labs/NN-*/` | 압축 알고리즘. **숫자는 읽는 순서** = 의존성이 가벼운 순서 |
| `labs/*` (무번호) | 랩이 아님. 평가자(`agentic-eval`)·공유 데이터(`data`) |
| `labs/*/configs/` | 조건 1개 = 실행 1회 |
| `labs/agentic-eval/experiments/` | 비교군 여러 개 = `pier` 실행 1회 |
| `labs/data/` | `00~09` 공유 입력. **불변** — 수정 대신 `-v2` 추가 |
| `runs/<lab>/<config-or-experiment>/<timestamp>/` | 모든 실행 결과 |
| `compare/` | `runs/` 간 비교 (원본 데이터를 직접 읽지 않음) |
| `scripts/explore/` | 탐색용 노트북. 재현이 필요하면 `labs/`로 옮길 것 |
| `docs/` | 설명 문서 (HTML) |

## 설계 원칙

1. **폴더 간 코드 import 0개.** 랩끼리 서로를 참조하지 않는다.
   `agentic-eval`은 `05-headroom`을 import하지 않고, Headroom을 별도 프로세스로
   띄워 URL로만 연결한다.
2. **폴더는 늘리지 않는다.** 라이브러리 추가 = 파일 1개, 실험 추가 = yaml 1개.
3. **비교 가능성이 최우선.** 같은 입력·같은 시드가 아니면 숫자는 의미가 없다.

## 두 가지 평가 축

| | `labs/00~09` | `labs/agentic-eval` |
|---|---|---|
| 질문 | 압축률 대비 정보 손실 | 압축된 컨텍스트로 **실제 작업을 완수**하는가 |
| 입력 | `labs/data/` 코퍼스 | DeepSWE 태스크 (컨테이너 런타임 컨텍스트) |
| 지표 | 토큰 수, ROUGE, latency | pass@1, 입력 토큰 |
| 비용 | 초~분 | 시간~일 (Docker, 유료 API) |

같은 라이브러리라도 두 축에서 파라미터가 다르다. 묻는 질문이 다르기 때문이다.

## 랩 현황

| 랩 | 무엇을 | 절감 | 최저 보존율 | 의존성 | 상태 |
|---|---|---|---|---|---|
| [`00-baseline`](labs/00-baseline/) | 압축 없음 (기준선) | 0% | 100% | 없음 | 완료 |
| [`01-lossless-structure`](labs/01-lossless-structure/) | 표현의 중복만 제거 | 28.5% | 100% | 없음 | 완료 |
| [`02-handle-ref`](labs/02-handle-ref/) | 밖에 두고 핸들만 | 50.9% | 100% | 없음 | 완료 |
| [`03-summarize-llm`](labs/03-summarize-llm/) | LLM 추상 요약 | 89.2% | 100% | **API** | 완료 |
| `04-llmlingua` | 토큰 프루닝 | — | — | torch | 예정 |
| `05-headroom` | CCR 라이브러리 | — | — | pip | 예정 |
| `06-opencode` | 에이전트 세션 압축 | — | — | bun/npm | 예정 |

숫자는 각 랩의 권장 조건 기준입니다. **절감률만 보면 안 됩니다** — 같은 랩에서
조건을 바꾸면 절감이 커지면서 보존율이 0%가 되기도 합니다. 각 랩 README의
조건 비교표를 보세요.

랩끼리는 서로를 import하지 않습니다. 공통 기반은 [`labs/kit`](labs/kit/)뿐이고,
방향은 랩 → kit 단방향입니다.

### 각 랩에는 노트북이 있습니다

```bash
cd labs/01-lossless-structure && jupyter lab run.ipynb
```

노트북은 원리를 한 단계씩 보여준 뒤, 마지막에 그 랩의 `configs/*.yaml`을
**전부 찾아 돌리고 조건을 비교**합니다. 설정을 추가해도 노트북은 고칠 필요가
없습니다. 노트북은 [`labs/build_notebooks.py`](labs/build_notebooks.py)로 찍습니다.

### 코퍼스

```bash
cd labs/data && python make_synthetic.py
```

합성 데이터입니다 — 실제 고객 데이터가 섞일 수 없습니다.

| 코퍼스 | 구성 | 주 소비자 |
|---|---|---|
| `sample` | 짧은 산문 12건 (숫자·부정·식별자 밀집) | 전 랩 |
| `sample-structured` | JSON·로그·표·XML 12건 | `01` |
| `sample-long` | 7개 절 장문 8건, 정답은 한 절에만 | `02`, `03` |

## 시작하기

```bash
cp .env.example .env
uv venv && uv pip install -r requirements.txt   # 공통 프레임워크
```

랩별 의존성은 `labs/*/.venv`로 격리한다 (torch 핀 충돌 회피).

종단 평가는 [`labs/agentic-eval/README.md`](labs/agentic-eval/README.md) 참고.

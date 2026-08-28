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

## 시작하기

```bash
cp .env.example .env
uv venv && uv pip install -r requirements.txt   # 공통 프레임워크
```

랩별 의존성은 `labs/*/.venv`로 격리한다 (torch 핀 충돌 회피).

종단 평가는 [`labs/agentic-eval/README.md`](labs/agentic-eval/README.md) 참고.

# labs/kit — 랩 공통 기반

`labs/00~06` 이 **같은 방식으로 재고 같은 모양으로 기록**하게 만드는 곳.

## 왜 복사본이 아니라 공유인가

README 원칙 1 은 **랩끼리** import 하지 말라는 뜻이다(`agentic-eval` → `05-headroom`).
kit 은 랩 사이가 아니라 **랩 → 기반** 단방향이므로 순환이 생기지 않는다.

지표 코드를 랩마다 복사하면 조금씩 갈라진다. 압축률을 문자로 재는 랩과 토큰으로
재는 랩이 섞이면 **아무 에러 없이 조용히** 비교가 깨진다. 원칙 3(비교 가능성 최우선)이
무의존보다 우선한다고 판단했다.

## 재현성은 버전으로 지킨다

지표 정의가 바뀌면 과거 숫자와 비교가 깨진다. 그래서 실행마다 kit 버전을
`config.snapshot.yaml` 에 박는다. "이 실험은 kit 0.1.0 으로 쟀다" 가 남는다.

바꿀 때는 `VERSION` 을 올린다.

## 구성

| 파일 | 역할 |
|---|---|
| `tokens.py` | 응답 `usage` 정규화 · 토큰 계산 · `billed_input` |
| `dataset.py` | 코퍼스 jsonl 로더 |
| `metrics.py` | 압축률 · `survival` · 집계 |
| `runner.py` | `runs/<lab>/<config>/<ts>/` 4종 기록 |
| `config.py` | yaml 로드 + kit 버전 스탬프 |
| `display.py` | 표 출력 (노트북 HTML · 터미널 텍스트) |

## 랩이 지켜야 할 계약

```
python compress.py configs/<이름>.yaml [--data ../data/<코퍼스>] [--out ../../runs]
```

출력은 항상 `runs/<lab>/<config>/<timestamp>/` 아래 네 개다.

| 파일 | 내용 | 커밋 |
|---|---|---|
| `config.snapshot.yaml` | 설정 + kit 버전 + 환경 | O |
| `metrics.json` | 집계 지표 | O |
| `report.md` | 사람이 읽는 요약 | O |
| `records.jsonl` | 케이스별 원문·압축문 | **X** (용량·데이터 혼입) |

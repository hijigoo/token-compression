# reports/

측정 결과를 **측정 단위 폴더**로 남깁니다.

```
reports/<측정이름>/
  results.json    측정 원본. 실험 조건과 파라미터가 모두 포함됩니다
  report.md       보고서 (Markdown)
  report.html     보고서 (브라우저용)
```

## 보고서 목록

| 폴더 | 측정 방식 | 내용 |
|---|---|---|
| **`analysis/`** | 종단 (공식 하네스) | **대표 보고서.** `brief.html`(요약판)과 `report.html`(전체판) |
| `terminal-bench-wide/` | 종단 (공식 하네스) | 초기 8태스크 × 3조건 상세 (스윕에 흡수됨) |
| `terminal-bench/` | 종단 (공식 하네스) | 초기 3태스크 × 3조건 × 2언어 상세 |
| `summary/` | 혼합 | 측정 경위를 포함한 서술형 보고서 |
| `llmlingua2-grid/` | 컴포넌트 대리 | 압축기 단독 24조건 × 14케이스 = 336회 |
| `llmlingua-deepswe/` | 컴포넌트 대리 | 이전 세대 대리 측정 476회 |

`analysis/` 안의 두 문서는 같은 데이터에서 나옵니다.

| 파일 | 언제 |
|---|---|
| `brief.html` · `brief.md` | **먼저 여기.** 결론 · 벤치마크별 핵심 표 · 비교 · 권고 |
| `report.html` · `report.md` | 설계 · 파라미터 정의 · 전체 표 · 압축 예시 부록까지 |
| `results.json` | 측정 원본 (trial 단위). jobs 디렉터리가 사라져도 재생성 가능 |

### 종단 측정과 컴포넌트 대리 측정의 차이

**종단(end-to-end) 측정**은 Terminal Bench 2.1 공식 하네스로 에이전트를
Docker 컨테이너에서 실제 실행하고, 태스크에 포함된 pytest 로 채점합니다.
pass@1 이 산출됩니다.

**컴포넌트 대리 측정**은 압축기만 단독 실행한 뒤 "압축된 컨텍스트로 관련
파일을 선택할 수 있는가" 를 확인합니다. 다수 조건을 탐색할 수 있으나
공식 벤치마크 프로토콜이 아니므로 **정확도 근거로 사용하지 않습니다.**

`analysis/` 는 종단 측정만 사용합니다.

## 다시 만드는 법

### 종단 측정 보고서

경로를 알아서 찾는 스크립트가 있습니다. 보통 이것만 쓰면 됩니다.

```bash
cd labs/agentic-eval
./refresh_report.sh
```

직접 지정하실 때는 이렇게 씁니다. `--run` 과 `--control-run` 은 여러 개를
받습니다 — 언어를 나눠 돌리면 run 디렉터리가 갈리는데, 조건 이름이 같으므로
하나의 측정으로 합쳐집니다.

```bash
./.venv/bin/python report_paper.py \
  --run <run_dir…>             --jobs <jobs_dir…> \
  --control-run <run_dir…>     --control-jobs <jobs_dir…> \
  --swe-run <DeepSWE run_dir>  --swe-jobs <jobs_dir> \
  --samples ../../reports/summary/samples.json \
  -o ../../reports/analysis

# 개별 측정 상세
./.venv/bin/python report_run.py <run_dir> --jobs <jobs_dir> \
  --control <대조 run_dir> --control-jobs <jobs_dir> \
  -o ../../reports/<이름>
```

`run_dir` 는 `runs/agentic-eval/terminal-bench/<실험이름>/<타임스탬프>/`,
`jobs_dir` 는 `run_all.sh` 에 전달한 결과 경로입니다.

### 압축 입출력 예시

보고서 부록의 예시는 직접 작성하지 않고 실제 압축기를 실행해 생성합니다.

```bash
./.venv/bin/python make_samples.py -o ../../reports/summary/samples.json
```

## 측정 후 반드시 확인할 것

과거에 결과를 무효화한 원인이 두 가지 있었습니다. 둘 다 오류를 발생시키지
않고 그럴듯한 수치를 산출하므로, 측정 후 아래 두 항목을 확인하십시오.

**1. 압축이 실제로 적용되었는가**

프록시 로그(`<run_dir>/<조건>.jsonl`)에 `compress` 이벤트가 있어야 합니다.
0건이면 압축이 적용되지 않은 것이며, 결과는 기준 조건과 동일합니다.

```bash
grep -c '"event": *"compress"' <run_dir>/<조건>.jsonl
```

`report_run.py` 는 이 값이 0이면 보고서 상단에 경고를 출력합니다.

**2. 채점기가 실제로 실행되었는가**

채점 컨테이너는 `uvx` 로 pytest 를 설치합니다. PyPI 파일 서버가 차단된
환경에서는 설치가 실패하고, 테스트가 한 줄도 실행되지 않은 채 0점이
기록됩니다.

```bash
grep -l "tls handshake eof" <jobs_dir>/*/*/verifier/test-stdout.txt
```

출력이 있으면 해당 trial 의 pass@1 은 무효입니다. `launch.py` 가
`verifier.env` 에 PyPI 미러를 주입하므로 정상 환경에서는 발생하지
않습니다.

## 커밋 정책

`runs/` 는 제외합니다. 실행마다 타임스탬프 폴더가 누적되기 때문입니다.
`reports/` 는 측정 단위로 유지되므로 커밋합니다.

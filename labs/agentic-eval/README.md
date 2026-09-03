# labs/agentic-eval — 종단 평가

**여기서 묻는 질문은 하나입니다.** 압축된 컨텍스트로도 에이전트가 *실제
소프트웨어 작업을 끝까지 해내는가?*

`labs/00~06`은 압축률 대비 정보 손실을 값싸고 빠르게 잽니다. 반면 여기서는
DeepSWE 태스크를 실제로 풀게 해서 **pass@1**을 봅니다. 느리고 비싸지만
실전에 훨씬 가까운 신호를 줍니다.

번호가 없는 이유는 압축 알고리즘이 아니라 **평가자**이기 때문입니다.

> **앞의 랩들로 먼저 걸러주세요.** 정답 보존율이 낮게 나오는 조건은 여기서도
> 좋을 리가 없습니다. 값싼 축에서 명백히 깨진 것을 먼저 떨어뜨리고, 살아남은
> 후보만 이쪽으로 가져오시면 시간과 비용을 크게 아끼실 수 있습니다.

## 폴더 구성

```
setup.sh          데이터셋 클론 + venv 생성 + 의존성 설치
requirements.txt  이 랩 전용 의존성. 루트 .venv 와 섞지 않습니다
datasets/         벤치마크 데이터 (커밋 제외). 코퍼스가 아니라 Docker 픽스처입니다
  deep-swe/         영어 원본 — setup.sh 가 클론합니다
  deep-swe-ko/      한국어판 — translate.py stage 가 만듭니다
translate.py      지시문 번역 + 검증 + 스테이징
translations/     번역 결과 (커밋). 번역 비용을 다시 치르지 않으려고 남깁니다
  deep-swe/ko/
proxy.py          OpenAI 호환 압축 프록시 (표준 라이브러리만 씁니다)
compressors/      라이브러리 하나가 파일 하나입니다
                    truncate.py 는 대조군입니다 — 그냥 뒤를 자릅니다
run.ipynb         파이프라인을 한 단계씩 보는 노트북 (build_notebooks.py 가 생성)
experiments/      질문 하나가 파일 하나이자 pier 실행 한 번입니다
launch.py         arm 기동 + 포트 배정 + pier 설정 생성
patch_pier.py     pier 패치 2종 (아래 '반드시 먼저' 참고)
run_all.sh        무인 실행 — 프록시 기동 → 언어별 pier run → 정리
analyze.py        reward 와 토큰 집계
report_run.py     롤아웃 하나 → md + html
report_paper.py   여러 롤아웃 → 기술 보고서 (전체판 + 요약판)
refresh_report.sh 최신 측정으로 보고서 재생성 (경로를 알아서 찾습니다)
make_samples.py   보고서 부록용 압축 입출력 예시 생성
```

`datasets/` 와 `translations/` 가 나뉘어 있는 이유가 있습니다. `datasets/` 는
다시 받으면 그만이지만, 번역은 API 호출 비용이 듭니다. 그래서 번역만
커밋하고, 둘을 합친 `datasets/deep-swe-ko/` 는 `stage` 로 언제든 다시
만듭니다.

## 용어 — arm

**비교군 하나**를 뜻합니다. 임상시험의 treatment arm 에서 온 말입니다.
같은 태스크를 여러 조건으로 풀게 하고 결과를 비교할 때, **조건 하나가
arm 하나**입니다.

```
같은 태스크
  ├─ arm: baseline         압축 없음     ← 기준선
  ├─ arm: llmlingua-r0.5   LLMLingua 50%
  └─ arm: recomp-r0.5      ReComp 50%
                              │
                      pass@1 을 서로 비교
```

여기서는 arm 하나가 **프록시 프로세스 하나**입니다. `launch.py` 가 arm 마다
포트를 따로 주고 띄우면, 에이전트에게는 그냥 다른 API 주소로 보입니다.
`experiments/*.yaml` 의 `arms:` 목록이 그대로 비교군 목록입니다.

## 한국어 데이터 준비

DeepSWE 의 `instruction.md` 는 전부 영어입니다. 한국어에서도 압축이 같은
효과를 내는지 보려면 한국어판이 있어야 합니다. **채점은 테스트 코드가
하므로 지시문만 번역하면 됩니다.**

다른 벤치마크를 붙이시면 `-b` 로 고르실 수 있습니다. 기본은 `deep-swe`
입니다.

```bash
python translate.py list                      # 상태 보기
python translate.py translate <태스크>…        # 영어 → 한국어 (--all 로 전체)
python translate.py verify                    # 식별자가 살아남았는지 검사
python translate.py stage                     # datasets/deep-swe-ko/ 생성
```

`stage` 는 `instruction.md` 만 한국어로 바꾸고 나머지(Dockerfile·테스트·정답
패치)는 **원본을 심볼릭 링크로 가리킵니다.** 복사하면 원본이 갱신될 때
조용히 어긋납니다.

그다음 실험 yaml 에서 언어를 추가하시면 됩니다. 경로는 쓰지 않습니다.

```yaml
benchmark: deep-swe
langs: [en, ko]
```

### verify 를 건너뛰지 마세요

번역기가 식별자를 건드리면 태스크가 **풀 수 없게** 됩니다. `sort_by_label`
이 `라벨_기준_정렬` 이 되면 에이전트가 찾을 함수가 사라집니다. 그러면 그
실패가 압축 탓인지 번역 탓인지 알 수 없게 되어 실험 전체가 무의미해집니다.

`verify` 는 두 가지를 봅니다.

| 검사 | 왜 |
|---|---|
| 식별자 보존 | 함수명·파일명·상수가 원문 그대로 남아 있는지 |
| 길이 비율 | 원문의 50% 미만이면 조건이 통째로 빠졌을 수 있습니다 |

### 한국어는 토큰을 더 씁니다

같은 지시문인데 한국어가 더 깁니다. 실측해 보시면 태스크마다 차이가 크게
납니다. **언어별 절감률을 비교하실 때는 각 언어의 기준선과 비교하세요.**
영어 기준선과 한국어 압축본을 견주면 압축 효과가 아니라 언어 차이를 보게
됩니다.

## 어떻게 동작하나요

deep-swe도 pier도 **전혀 수정하지 않습니다.** 모델 URL만 프록시로 바꿔치기합니다.

```
A(기준선)  에이전트 ─────────────────────▶ 모델 API
B(압축)    에이전트 ──▶ 프록시 ──▶ 모델 API
```

에이전트 입장에서는 평범한 OpenAI 호환 엔드포인트라서 아무것도 눈치채지
못합니다. `labs/05-headroom`을 import하지 않고 **별도 프로세스 + URL**로만
연결하는 것도 같은 이유입니다.

## 처음이시면 노트북부터

`run.ipynb` 가 파이프라인을 한 단계씩 보여줍니다. 태스크 하나만 쓰고,
**8절까지는 Docker 도 API 키도 필요 없습니다.**

```
1~6절   태스크 구조 · 채점 방식 · 번역 · 태스크 선정 · 압축 보호 규칙
7절     프록시 왕복 — 가짜 서버를 띄워 모델이 받았을 내용을 직접 확인
8절     launch.py 가 만드는 것 (--dry-run)
9~10절  실제 실행 안내와 읽는 법
```

커널은 **이 폴더의 `.venv`** 로 골라주세요. 루트 `.venv` 와 다릅니다 —
`pier` 가 Python 3.12 이상을 요구하고 git 에서 설치돼서, 루트를 오염시키면
랩 00~03 이 함께 깨집니다.

```bash
./setup.sh          # .venv 생성 + pier·ipykernel·kit 설치
```

노트북은 `build_notebooks.py` 가 만듭니다. **직접 고치지 마시고** 거기를
고쳐 다시 빌드하세요.

```bash
cd .. && ./.venv/bin/python build_notebooks.py eval
```

### 무엇을 바꿔 보시면 되나

첫 셀에 설정이 모여 있습니다. 압축기를 바꾸시려면 한 줄이면 됩니다.

```python
BENCHMARK  = "deep-swe"
TASK       = "mashumaro-flattened-dataclass-fields"
COMPRESSOR = "truncate"      # none | truncate | llmlingua | recomp
RATIO      = 0.5
EXPERIMENT = "smoke"
```

`none` 과 `truncate` 는 표준 라이브러리만 씁니다. `llmlingua`·`recomp` 는
따로 설치하셔야 합니다.

## 압축기 목록

| 이름 | 무엇 | 설치 |
|---|---|---|
| `none` | 아무것도 안 함. 대조군 | 불필요 |
| `truncate` | 그냥 뒤를 자름. **해석 기준선** | 불필요 |
| `llmlingua` | **LLMLingua-2. 이 랩의 기본** | `llmlingua` |
| `llmlingua-v1` | LLMLingua v1 (아래 주의) | `llmlingua` |
| `recomp` | ReComp | `sentence-transformers` |

`truncate` 를 꼭 함께 돌려보세요. 정교한 압축기가 **그냥 잘라내기보다
못하면** 값을 못 한 것입니다. 그 판단 없이 "40% 줄이고 정확도가 조금
떨어졌다" 만 보면 좋은지 나쁜지 알 수 없습니다.

### LongLLMLingua 는 왜 없나

3형제 중 `long` 만 빠져 있습니다. 설치가 어려워서가 아니라 **여기서는 그
알고리즘이 돌지 않기 때문**입니다.

LongLLMLingua 의 기여는 문서들 *사이*에 있습니다 — 질문 관련도로 순위를
매기고, 낮은 것을 통째로 버리고, 관련도 순으로 재배열합니다. 검색된 문단
20개 중 정답이 든 하나를 고르는 상황을 위한 설계입니다.

에이전트 컨텍스트는 그 모양이 아닙니다.

- 프록시가 메시지를 **하나씩** 압축합니다. 문서가 하나뿐이라 순위도
  재배열도 발동하지 않습니다. 그냥 "질문을 곁들인 v1" 이 됩니다
- 독립된 문서가 아니라 **순서가 곧 의미**인 시퀀스입니다. 재배열하면
  에이전트가 무슨 명령을 언제 실행했는지가 뒤섞입니다
- 버릴 기준이 "질문과의 관련도" 가 아니라 "이미 써먹은 정보인가" 입니다

넣어두면 "LongLLMLingua 를 평가했다" 고 말하게 되는데 실제로 돈 것은 다른
것이라, 결론이 틀립니다.

### ⚠️ v1 은 현재 버전 조합에서 깨집니다

```
llmlingua 0.2.2    past_key_values 를 (k, v) 튜플로 가정
transformers 5.x   Cache 객체로 바뀜 → ValueError
```

짧은 글은 멀쩡히 압축되고 **대략 1KB 를 넘기면 터집니다.** 긴 입력에서만
`iterative_compress_prompt` 경로를 타기 때문입니다. 에이전트 메시지는 항상
그보다 깁니다.

프록시는 압축 실패를 원문 통과로 넘깁니다(그 trial 을 죽이지 않으려고).
그러면 결과표에 **절감 0% 로 찍히는데, 압축기의 성질인지 버그인지 구분할
수 없습니다.** 그래서 `llmlingua-v1` 은 프록시 기동 시에 미리 밟아 보고
명확한 메시지로 죽습니다. 조용히 틀린 결론을 내는 것보다 낫습니다.

기본인 `llmlingua`(v2)는 다른 경로라 영향받지 않습니다.

## 실행 방법

### 반드시 먼저 — pier 패치와 환경변수

두 가지를 하지 않으면 **압축 arm 이 0 스텝에서 죽거나, 채점이 통째로
0점으로 기록됩니다.** 둘 다 에러 메시지가 친절하지 않아 원인을 찾기
어렵습니다.

```bash
./.venv/bin/python patch_pier.py          # ① pier 패치 2종
export PIER_EXTRA_SAFE_PORTS="8801 8802 8803 8804 8805 8806"   # ② squid 허용 포트
```

| | 무엇을 | 안 하면 |
|---|---|---|
| ① `patch_pier.py` | mini-swe-agent 에 PyPI 미러 주입 · squid `Safe_ports` 확장 | 에이전트 설치 실패 또는 프록시 접속 차단 |
| ② `PIER_EXTRA_SAFE_PORTS` | 압축 프록시 포트를 squid 가 허용 | 압축 arm 이 첫 호출부터 실패 |

`PYPI_INDEX`(`launch.py` 상수)는 에이전트 컨테이너와 **채점 컨테이너 양쪽**에
들어갑니다. 채점기만 빠뜨리면 에이전트가 과제를 완벽히 풀어도 0점이
기록됩니다.

### 무인 실행

`launch.py` 는 프록시를 띄운 뒤 `signal.pause()` 로 멈춰 서서 사람이 pier
명령을 붙여넣기를 기다립니다. 한 시간짜리 롤아웃을 자리 비우고 돌리려면
`run_all.sh` 를 쓰십시오 — 프록시 기동부터 언어별 `pier run`, 정리까지
이어서 합니다.

```bash
export OPENAI_API_KEY="$(az account get-access-token \
  --scope https://cognitiveservices.azure.com/.default --query accessToken -o tsv)"
export UPSTREAM_BASE_URL=https://<리소스>.cognitiveservices.azure.com/openai
export PUBLIC_HOST=host.docker.internal
export PIER_EXTRA_SAFE_PORTS="8801 8802 8803 8804 8805 8806"

./run_all.sh experiments/terminal-bench-sweep.yaml /tmp/tbsweep
```

토큰은 약 77분이면 만료됩니다. 그보다 긴 롤아웃을 이어 돌리실 때는 롤아웃
사이에 다시 받으십시오.

### 보고서 생성

```bash
./refresh_report.sh          # 최신 run 을 찾아 reports/analysis/ 에 생성
```

전체판(`report.html`)과 요약판(`brief.html`)이 함께 나옵니다. 롤아웃이 아직
진행 중이면 보고서 상단에 경고가 자동으로 붙고, 완료되면 사라집니다.

### 수동 실행

**처음이시면 `smoke` 부터 돌려주세요.** 태스크 1개·시도 1회짜리라 파이프라인이
끝까지 이어지는지만 봅니다. 여기서 baseline 이 실패하면 압축 실험은 볼 것도
없습니다.

```bash
./setup.sh

# arm 전부 기동 + pier 설정 생성 (프록시는 켜둔 채 대기합니다)
PUBLIC_HOST=benchmark-host ./.venv/bin/python launch.py experiments/smoke.yaml

# 다른 터미널에서 — 언어마다 한 번씩입니다
pier run --config runs/agentic-eval/deep-swe/smoke/<시각>/en/pier.yaml
pier run --config runs/agentic-eval/deep-swe/smoke/<시각>/ko/pier.yaml

# 집계
./.venv/bin/python analyze.py runs/agentic-eval/deep-swe/smoke/<시각> --jobs <pier jobs 경로>
```

설정만 확인하고 싶으실 때는 `--dry-run`을 붙여주세요. 프록시를 띄우지 않고
파일만 만듭니다. Docker 도 필요 없습니다.

### 실행 폴더 구조

```
runs/agentic-eval/<벤치마크>/<실험>/<시각>/
  meta.json              무슨 조건이었나 — 태스크 목록까지
  arms.json              arm -> base_url 매핑
  config.snapshot.yaml   실험 파일 원본
  en/  pier.yaml  tasks/
  ko/  pier.yaml  tasks/
```

`tasks/` 는 이번 실행에 쓸 태스크만 심볼릭 링크로 모은 것입니다. **왜 굳이
만드나** — 다음 절을 봐주세요.

## 실험 파일 쓰는 법

```yaml
name: my-experiment
benchmark: deep-swe
langs: [en, ko]        # 생략하면 [en]
model: openai/gpt-5.5
dataset: {n_tasks: 5, sample_seed: 0}
n_attempts: 3
arms:
  - {name: baseline, kind: direct}                            # 압축 없음
  - {name: hr, kind: headroom, args: [...], env: {}}          # 외부 프록시
  - {name: rc, kind: local, compressor: recomp, ratio: 0.5}   # compressors/*.py
```

| `kind` | 무슨 뜻인가요 |
|---|---|
| `direct` | 모델 API를 그대로 호출합니다. 기준선입니다 |
| `headroom` | Headroom 프록시를 별도 프로세스로 띄웁니다 |
| `local` | `proxy.py` + `compressors/<이름>.py` 조합입니다 |

**기준선(`direct`) arm을 꼭 넣어주세요.** 비교 대상이 없으면 pass@1 숫자
하나만으로는 좋은지 나쁜지 판단할 수 없습니다.

### 무엇을 보호할지도 조건입니다

압축기는 "어떻게 줄일까" 를 정하고, `protect` 는 **"어디를 건드리지 말까"**
를 정합니다. 같은 압축기로 보호 범위만 바꿔 비교하실 수 있습니다.

```yaml
arms:
  - {name: v2, kind: local, compressor: llmlingua, ratio: 0.5}
  - {name: v2-aggressive, kind: local, compressor: llmlingua, ratio: 0.5,
     protect: {keep_last: 0, system: true}}
```

| 키 | 기본 | 뜻 |
|---|---|---|
| `keep_last` | 2 | 마지막 N개 메시지를 원문 유지. 0 이면 보호 안 함 |
| `min_chars` | 400 | 이보다 짧은 메시지는 건드리지 않음 |
| `system` | (보호) | `true` 면 system 프롬프트도 압축합니다 |

**기본값은 추론으로 정한 것이지 측정한 값이 아닙니다.** 직전 관측과 출력
형식 계약이 깨지면 압축 품질과 무관하게 루프가 끊긴다는 판단이었습니다.

MS 공유 문서에서 Headroom 을 돌렸을 때 `PROTECT_RECENT` 2개와 0개의 결과가
갈렸습니다. 즉 **보호 범위가 결과를 가르는 변수**입니다.
`experiments/protect-compare.yaml` 이 그걸 확인하는 실험입니다.

> `protect` 는 `kind: local` 에서만 씁니다. Headroom 은 자체 옵션이 있어
> `args` 로 넘기셔야 합니다.

### 태스크를 직접 고르실 수도 있습니다

```yaml
dataset:
  tasks: [mashumaro-flattened-dataclass-fields]
```

이때는 `n_tasks`·`sample_seed` 를 쓰지 않습니다. 뽑을 것이 없기 때문입니다.
특정 태스크를 재현하거나, `smoke` 처럼 가장 가벼운 것 하나만 돌릴 때 씁니다.

### ⚠️ 경로를 직접 쓰지 않는 이유

예전에는 `dataset.path` 에 데이터셋 경로를 적었습니다. 그러면 실험 파일을
복사해 한국어판을 만들 때 **`name` 은 그대로 둔 채 `path` 만 고치는** 실수가
납니다. 에러가 나지 않고, 한국어 결과가 영어 실행 폴더에 조용히 덮입니다.
나중에 결과만 보면 어느 언어였는지 알 방법이 없습니다.

지금은 `benchmark` 와 `langs` 만 적으면 `launch.py` 가 경로를 정하고, 실행
폴더도 `<벤치마크>/<실험>/<시각>/<언어>/` 로 갈라 줍니다. 사람이 경로를 쓰지
않으므로 어긋날 자리가 없습니다.

### ⚠️ 언어별 태스크 짝이 어긋나는 문제

더 조용한 함정이 하나 더 있었습니다. 영어 풀은 113건인데 한국어는 번역해 둔
것만 있습니다. **풀 크기가 다르면 같은 시드를 줘도 다른 태스크가 뽑힙니다.**
그대로 돌리면 두 언어가 서로 다른 문제를 푼 결과를 나란히 놓게 되는데,
표에서는 전혀 드러나지 않습니다.

그래서 `launch.py` 가 이렇게 합니다.

1. 모든 언어에 **공통으로 있는 태스크**만 추립니다
2. 거기서 시드로 뽑습니다 — 언어와 무관하게 같은 목록이 나옵니다
3. 뽑힌 것만 모은 트리를 언어별로 만들어 pier 에게 줍니다

3번까지 하는 이유는 샘플링을 우리 손에서 놓지 않기 위해서입니다. pier 에게
"113건 중 5건 뽑아라" 라고 맡기면 언어별로 다시 어긋날 수 있습니다.

## 늘리는 방법

**라이브러리를 추가하실 때** — `compressors/<이름>.py`에 `compress(messages, ratio)`를
구현하시고 `REGISTRY`에 한 줄 더하시면 됩니다. 폴더는 늘어나지 않습니다.

**실험을 추가하실 때** — `experiments/<질문>.yaml` 하나면 충분합니다.
파일 1개 = 질문 1개 = `pier run` 1회입니다.

실험 파일은 알고리즘별로 나누지 마시고 **알고 싶은 것**으로 나눠주세요.
`llmlingua.yaml`보다 `ratio-sweep.yaml`이 나중에 다시 볼 때 훨씬 유용합니다.

## ⚠️ 실험이 조용히 오염되는 지점들

**아래 항목들은 결과만 봐서는 잘못됐는지 알아챌 수 없습니다.** 겪어보고
정리해 둔 것이니 한 번 읽어보시길 권합니다.

| 항목 | 어떻게 처리했나요 |
|---|---|
| `--no-cache` / `--no-ccr` | `launch.py`에 **하드코딩**했습니다. yaml에 쓰시면 거부됩니다 |
| `sample_seed` | 없으면 `launch.py`가 실행을 거부합니다 |
| 압축기 장애 | 원문을 그대로 통과시킵니다. 500을 내면 "정확도 하락"으로 잘못 집계됩니다 |
| 모델 로딩 지연 | 프록시를 띄울 때 미리 데웁니다. 첫 요청에서 로딩하면 타임아웃이 성능으로 잡힙니다 |
| system 프롬프트 | 압축하지 않습니다. 출력 형식 계약이 깨지면 파싱 실패로 0점이 됩니다 |
| 절감률 | 자기보고 대신 `trajectory.json`의 실제 입력 토큰으로 교차 검증합니다 |
| **압축 API 경로** | 에이전트가 `/chat/completions` 대신 `/responses` 를 부르면 압축이 걸리지 않습니다. `proxy.py` 가 두 API 를 모두 처리하며, 측정 후 `compress` 이벤트 수를 확인하십시오 |
| **채점 컨테이너 네트워크** | 채점기가 `uvx` 로 pytest 를 설치합니다. PyPI 가 막히면 테스트가 한 줄도 안 돌고 0점이 기록됩니다. `launch.py` 가 `verifier.env` 에 미러를 주입합니다 |
| **스텝 상한** | 압축 조건은 헤매면서 스텝이 늘어납니다. 상한이 없으면 한 trial 이 몇 시간을 잡아먹습니다. `launch.py` 가 전 조건 동일하게 60 을 겁니다 |

`--no-ccr`이 왜 필수인지 조금 더 설명드리면 이렇습니다. CCR은 원문을 로컬에
두고 모델이 `headroom_retrieve` 툴로 다시 꺼내오게 하는 방식입니다. 그런데
mini-swe-agent에는 bash밖에 없어서 그 툴을 부를 수가 없습니다. 켜둔 채로
돌리면 정보가 그냥 사라진 것과 똑같아집니다.

## ⚠️ 비용을 먼저 계산해 보세요

trial 수가 `arm × n_tasks × n_attempts`로 곱해지고, 태스크 하나가 최대
3시간까지 걸립니다. 예를 들어 `ratio-sweep`은 6 arm × 5 태스크 × 3회 =
**90 trial**입니다.

**먼저 `n_tasks: 5`로 곡선 모양만 보시고**, 성능이 무너지는 구간 근처만
촘촘하게 다시 돌리시길 권합니다. 처음부터 전 구간을 촘촘히 돌리면 대부분의
시간이 아무 일도 일어나지 않는 구간에 쓰입니다.

## 네트워크 설정

컨테이너 안에서 `localhost`는 컨테이너 자기 자신을 가리킵니다. 그래서
`PUBLIC_HOST`를 `localhost`로 두시면 **반드시 실패**합니다. 컨테이너에서
실제로 도달할 수 있는 주소를 넣어주세요.

- **권장** — 사내 서버나 VM에 전부 올리시는 방법입니다. 도메인 하나에
  포트만 다르게 쓰면 되어서 관리가 가장 간단합니다
- 터널(cloudflared·ngrok)은 포트마다 하나씩 필요해서 arm이 늘어나면
  금방 관리가 어려워집니다

URL을 env에 넣어두시면 pier의 `network_allowlist()`가 egress를 자동으로
열어줍니다.

## 함께 보시면 좋은 문서

[`docs/deepswe-guide.html`](../../docs/) — DeepSWE 동작 원리, Pier 흐름 8단계,
Headroom 옵션 해설이 들어 있습니다.

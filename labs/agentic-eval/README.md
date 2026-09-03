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
setup.sh          데이터셋 클론 + pier 설치
datasets/         벤치마크 데이터 (커밋 제외). 코퍼스가 아니라 Docker 픽스처입니다
  deep-swe/         영어 원본 — setup.sh 가 클론합니다
  deep-swe-ko/      한국어판 — translate.py stage 가 만듭니다
translate.py      지시문 번역 + 검증 + 스테이징
translations/     번역 결과 (커밋). 번역 비용을 다시 치르지 않으려고 남깁니다
  deep-swe/ko/
proxy.py          OpenAI 호환 압축 프록시 (표준 라이브러리만 씁니다)
compressors/      라이브러리 하나가 파일 하나입니다
experiments/      질문 하나가 파일 하나이자 pier 실행 한 번입니다
launch.py         arm 기동 + 포트 배정 + pier 설정 생성
analyze.py        reward 와 토큰 집계
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

그다음 실험 yaml 에서 경로만 바꾸시면 됩니다.

```yaml
dataset:
  path: ./datasets/deep-swe-ko/tasks
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

## 실행 방법

```bash
./setup.sh

# arm 전부 기동 + pier 설정 생성 (프록시는 켜둔 채 대기합니다)
PUBLIC_HOST=benchmark-host ./.venv/bin/python launch.py experiments/ratio-sweep.yaml

# 다른 터미널에서
pier run --config runs/agentic-eval/ratio-sweep/<시각>/pier.yaml

# 집계
./.venv/bin/python analyze.py runs/agentic-eval/ratio-sweep/<시각> --jobs <pier jobs 경로>
```

설정만 확인하고 싶으실 때는 `--dry-run`을 붙여주세요. 프록시를 띄우지 않고
파일만 만듭니다.

## 실험 파일 쓰는 법

```yaml
name: my-experiment
model: openai/gpt-5.5
dataset: {path: ./datasets/deep-swe/tasks, n_tasks: 5, sample_seed: 0}
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

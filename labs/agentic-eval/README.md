# labs/agentic-eval — 종단 평가

**질문:** 압축된 컨텍스트로도 에이전트가 *실제 소프트웨어 작업을 완수*할 수 있는가?

`labs/00~09`가 압축률 대비 정보 손실(ROUGE 등)을 재는 반면, 여기서는 DeepSWE
태스크를 실제로 풀게 해서 **pass@1**을 잰다. 합성 지표보다 실전에 가까운 신호를 준다.

번호가 없는 이유는 알고리즘이 아니라 **평가자**이기 때문이다.

## 구조

```
setup.sh          deep-swe 클론 + pier 설치
deep-swe/         데이터셋 (gitignore). 코퍼스가 아니라 Docker 픽스처라 여기 둔다
proxy.py          OpenAI 호환 압축 프록시 (stdlib 전용)
compressors/      라이브러리 = 파일 1개
experiments/      질문 = 파일 1개 = pier 실행 1회
launch.py         arm 기동 + 포트 배정 + pier 설정 생성
analyze.py        reward + 토큰 집계
```

## 동작 원리

deep-swe도 pier도 수정하지 않는다. **모델 URL만 프록시로 바꿔치기**한다.

```
A(기준선)  에이전트 ──────────────────▶ 모델 API
B(압축)    에이전트 ──▶ 프록시 ──▶ 모델 API
```

에이전트 입장에선 평범한 OpenAI 호환 엔드포인트라 아무것도 눈치채지 못한다.
`labs/05-headroom`을 import하지 않고 **별도 프로세스 + URL**로만 연결한다.

## 사용법

```bash
./setup.sh

# arm 전부 기동 + pier 설정 생성 (프록시는 켜둔 채 대기)
PUBLIC_HOST=benchmark-host ./.venv/bin/python launch.py experiments/ratio-sweep.yaml

# 다른 터미널에서
pier run --config runs/agentic-eval/ratio-sweep/<ts>/pier.yaml

# 집계
./.venv/bin/python analyze.py runs/agentic-eval/ratio-sweep/<ts> --jobs <pier jobs 경로>
```

`--dry-run`을 붙이면 프록시를 띄우지 않고 설정만 생성한다.

## 실험 파일 스키마

```yaml
name: my-experiment
model: openai/gpt-5.5
dataset: {path: ./deep-swe/tasks, n_tasks: 5, sample_seed: 0}
n_attempts: 3
arms:
  - {name: baseline, kind: direct}                    # 압축 없음
  - {name: hr, kind: headroom, args: [...], env: {}}  # 외부 프록시
  - {name: rc, kind: local, compressor: recomp, ratio: 0.5}  # compressors/*.py
```

| kind | 의미 |
|---|---|
| `direct` | 모델 API 직접 호출. 기준선 |
| `headroom` | Headroom 프록시를 별도 프로세스로 기동 |
| `local` | `proxy.py` + `compressors/<name>.py` |

## 늘리는 법

**라이브러리 추가** → `compressors/<이름>.py`에 `compress(messages, ratio)` 구현 +
`REGISTRY`에 한 줄. 폴더는 안 늘어난다.

**실험 추가** → `experiments/<질문>.yaml` 하나. 파일 1개 = 질문 1개 = `pier run` 1회.
알고리즘별로 나누지 않고 **알고 싶은 것**으로 나눈다.

## ⚠️ 실험이 조용히 오염되는 지점

이것들은 **결과만 봐서는 알아챌 수 없다.**

| 항목 | 처리 |
|---|---|
| `--no-cache` / `--no-ccr` | `launch.py`에 **하드코딩**. yaml에 쓰면 거부된다 |
| `sample_seed` | 없으면 `launch.py`가 실행을 거부한다 |
| 압축기 장애 | 원문을 그대로 통과시킨다. 500을 내면 "정확도 하락"으로 오집계된다 |
| 모델 로딩 지연 | 프록시 기동 시 워밍업. 첫 요청에서 로딩하면 타임아웃이 성능으로 잡힌다 |
| system 프롬프트 | 압축하지 않는다. 출력 형식 계약이 깨지면 파싱 실패로 0점이 된다 |
| 절감률 | 자기보고 대신 `trajectory.json`의 실제 입력 토큰으로 교차검증 |

`--no-ccr`가 필수인 이유: CCR은 원문을 로컬에 두고 모델이 `headroom_retrieve`
툴로 되찾게 하는데, mini-swe-agent는 bash밖에 없어 그 툴을 호출할 수 없다.
켜두면 정보가 그냥 사라진 것과 같아진다.

## ⚠️ 비용

arm × n_tasks × n_attempts로 곱해지고, 태스크 하나가 최대 3시간이다.
`ratio-sweep`은 6 arm × 5 태스크 × 3회 = **90 trial**.

먼저 `n_tasks: 5`로 곡선 모양만 보고, 무너지는 구간 근처만 촘촘히 다시 돌린다.

## 네트워크

컨테이너 안의 `localhost`는 컨테이너 자신이라 **반드시 실패**한다.
`PUBLIC_HOST`는 컨테이너에서 도달 가능한 주소여야 한다.

- **권장**: 사내 서버/VM에 전부 올린다 → 도메인 1개, 포트만 다름
- 터널(cloudflared/ngrok)은 포트당 1개씩 필요해 arm이 늘면 관리가 어렵다

URL을 env에 넣으면 pier의 `network_allowlist()`가 자동으로 egress를 허용한다.

## 참고

`docs/deepswe-guide.html` — DeepSWE 동작 원리, Pier 흐름 8단계, Headroom 옵션 해설

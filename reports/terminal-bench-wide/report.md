# terminal-bench-wide — 컨테이너 롤아웃 결과

*20260903-223925 · terminal-bench · openai/gpt-5.4 · 태스크 8개 · 언어 en · trial 24건*

## 1. 세 줄 요약

1. 압축 arm 중 가장 나은 **llmlingua2-r0.7** 는 기준선 대비 입력 토큰을 **+28.5%** 바꾸면서 pass@1 이 **12.5%p 낮았습니다** (50.0% → 37.5%).
2. 24건 모두 끝까지 돌았습니다. 중단으로 인한 왜곡은 없습니다.
3. 채점된 trial 은 **24건**뿐입니다. 이 숫자는 **경향**이지 순위가 아닙니다 — 8절을 읽어 주세요.

## 2. 무엇을 어떻게 쟀나

에이전트가 **컨테이너 안에서 실제로** 과제를 풀고, 별도 채점 컨테이너가
테스트를 돌립니다. 압축은 에이전트와 모델 사이에 낀 프록시가 합니다.
에이전트도 벤치마크도 압축이 끼어든 걸 모릅니다.

```
에이전트 컨테이너 ──▶ squid(egress) ──▶ proxy.py ──▶ 모델 API
                                         └ LLMLingua-2 압축
        ↓ 다 끝나면
채점 컨테이너 ──▶ 테스트 실행 ──▶ reward
```

그래서 이 표의 pass@1 은 **대리 지표가 아니라 실제 성공률**입니다.
대신 1 trial 이 5~15분이라 조건을 많이 둘 수 없습니다.

| arm | 경로 | 압축기 | rate | 이 값이 뜻하는 것 |
|:--|:--|:--|:--|:--|
| `baseline` | 모델 API 직행 | — | — | 압축 없음. 다른 모든 값의 기준선입니다. |
| `llmlingua2-r0.7` | 프록시 경유 | llmlingua | `0.7` | 프롬프트를 원래 길이의 **0.7배**까지 남깁니다. 작을수록 세게 줄입니다. |
| `llmlingua2-r0.5` | 프록시 경유 | llmlingua | `0.5` | 프롬프트를 원래 길이의 **0.5배**까지 남깁니다. 작을수록 세게 줄입니다. |

> **rate 는 목표치이지 결과가 아닙니다.** LLMLingua 는 토큰을 지우는 방식이라 실제 절감은 문서 성격에 따라 달라집니다. 실제로 얼마나 줄었는지는 4절의 *입력 토큰* 열을 보세요.


## 3. 지표 읽는 법

| 지표 | 무엇인가 | 어떻게 나오나 | 방향 |
|:--|:--|:--|:--|
| **pass@1** | 한 번 시도해서 과제를 완전히 푼 비율 | 채점 컨테이너가 테스트를 돌려 `reward`가 1인 trial ÷ 채점된 trial | 높을수록 좋음 |
| **부분점수** | 다 못 풀었어도 통과한 테스트 비율 | `partial_reward`의 평균. pass@1 이 0이어도 여기서 차이가 보입니다 | 높을수록 좋음 |
| **입력 토큰** | 롤아웃 전체에서 모델에 **들여보낸** 토큰의 합 | 에이전트가 기록한 `n_input_tokens`의 평균. 압축 효과가 최종적으로 나타나는 곳입니다 | 낮을수록 좋음 |
| **peak 컨텍스트** | 한 번의 호출에서 가장 컸던 프롬프트 | `peak_context_tokens`의 평균. 컨텍스트 한도에 부딪히는지 보는 값 | 낮을수록 좋음 |
| **스텝** | 에이전트가 명령을 몇 번 실행했나 | `n_agent_steps`의 평균. 압축으로 정보가 빠지면 되읽느라 늘어납니다 | 낮을수록 좋음 |
| **비용** | 그 trial 의 모델 요금 | `cost_usd`의 평균. 캐시 할인이 반영된 실제 청구 기준 | 낮을수록 좋음 |
| **소요** | trial 하나가 걸린 벽시계 시간 | `started_at`~`finished_at`. 압축 자체의 지연이 여기 포함됩니다 | 낮을수록 좋음 |
| **자기보고 절감** | 프록시가 스스로 잰 문자 수 절감 | `chars_before`/`chars_after`. **참고값입니다** — 압축기가 자기 성적을 매기는 셈이라, 근거는 왼쪽의 *입력 토큰*입니다 | 참고 |

## 4. 결과

| arm | 채점 | pass@1 | 부분점수 | 입력 토큰 | vs 기준 | peak | 스텝 | 비용 | 소요 | 자기보고 |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| `baseline` | 8/8 | 50.0% | — | 27,070 | 기준 | 6,290 | 6.0 | $0.08 | 3.2분 | — |
| `llmlingua2-r0.7` | 8/8 | 37.5% | — | 19,365 | +28.5% | 4,336 | 6.2 | $0.07 | 3.3분 | 20.9% |
| `llmlingua2-r0.5` | 8/8 | 25.0% | — | 19,819 | +26.8% | 4,118 | 6.0 | $0.07 | 3.5분 | 34.8% |

<!--CHART:pass1-->

<!--CHART:tokens-->

```
pass@1
  baseline         ██████████████████████ 50.0%
  llmlingua2-r0.7  ████████████████       37.5%
  llmlingua2-r0.5  ███████████            25.0%

평균 입력 토큰
  baseline         ██████████████████████ 27,070
  llmlingua2-r0.7  ████████████████       19,365
  llmlingua2-r0.5  ████████████████       19,819
```

## 5. 절감과 정확도의 맞바꿈

왼쪽 아래로 갈수록 나쁩니다. 토큰도 못 줄이고 정확도도 떨어진 것입니다.
오른쪽 위가 이상적입니다.

<!--CHART:trade-->

## 6. 태스크·언어별

| 태스크 | 언어 | baseline | llmlingua2-r0.7 | llmlingua2-r0.5 |
|:--|:--|:--|:--|:--|
| cancel-async-tasks | en | ❌ | ❌ | ❌ |
| count-dataset-tokens | en | ❌ | ❌ | ❌ |
| filter-js-from-html | en | ✅ | ❌ | ❌ |
| fix-git | en | ✅ | ✅ | ✅ |
| openssl-selfsigned-cert | en | ✅ | ✅ | ✅ |
| overfull-hbox | en | ❌ | ❌ | ❌ |
| regex-log | en | ❌ | ❌ | ❌ |
| sqlite-db-truncate | en | ✅ | ✅ | ❌ |

✅ = 전부 통과(reward 1) · ❌ = 미통과 · 옆의 %는 부분점수입니다.
부분점수가 높은데 ❌ 라면 "거의 다 왔는데 한 가지를 놓쳤다" 는 뜻입니다.

## 7. 실패한 trial

없습니다. 모든 trial 이 채점까지 갔습니다.

## 8. 이 결과로 말할 수 없는 것

- **표본이 24건입니다.** arm 당 가장 적은 곳이 8건이라, 한 건이 뒤집히면 pass@1 이 12%p 움직입니다. 순위를 말하려면 `n_attempts` 를 올려 다시 돌려야 합니다.
- **태스크가 편향돼 있습니다.** 여기 쓴 태스크는 전체 중 일부만 고른 것이라, 다른 태스크에서 같은 결론이 나온다는 보장이 없습니다.
- **모델 한 종류만 봤습니다.** 압축에 대한 내성은 모델마다 다릅니다. 여기서는 `openai/gpt-5.4` 하나입니다.
- **캐시가 결과를 흔듭니다.** 압축은 프롬프트 앞부분을 바꾸므로 프리픽스 캐시가 깨집니다. 그래서 토큰이 줄어도 **비용은 늘 수 있습니다.** 4절에서 두 열을 같이 보세요.

## 부록 — 재현

```bash
# 1) pier 를 이 환경에 맞게 손봅니다 (사내망 미러 + egress 허용 포트)
./.venv/bin/python patch_pier.py

# 2) 프록시를 띄우고 pier 설정을 만듭니다
export OPENAI_API_KEY=$(az account get-access-token \
  --scope https://cognitiveservices.azure.com/.default \
  --query accessToken -o tsv)
export UPSTREAM_BASE_URL=<endpoint>
export PUBLIC_HOST=host.docker.internal
export PIER_EXTRA_SAFE_PORTS='8801 8802 8803 8804'
python launch.py experiments/terminal-bench-wide.yaml

# 3) 롤아웃
pier run --config runs/agentic-eval/terminal-bench/terminal-bench-wide/20260903-223925/en/pier.yaml --jobs-dir /tmp/job

# 4) 이 보고서
python report_run.py runs/agentic-eval/terminal-bench/terminal-bench-wide/20260903-223925 --jobs /tmp/job -o reports/terminal-bench-wide
```

> `PIER_EXTRA_SAFE_PORTS` 를 빼면 압축 arm 이 **0 스텝에서 죽습니다.** pier 의 egress 프록시(squid)가 80/443 외의 포트를 허용목록보다 **먼저** 막기 때문입니다. 자세한 이유는 `patch_pier.py` 의 설명에 있습니다.
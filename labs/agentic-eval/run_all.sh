#!/usr/bin/env bash
# 한 실험을 끝까지 돌린다 — 프록시 기동 → 언어별 pier run → 프록시 정리.
#
# launch.py 는 프록시를 띄운 뒤 `signal.pause()` 로 멈춰 서서 pier 명령을
# 사람이 붙여넣기를 기다린다. 한 시간짜리 롤아웃을 자리 비우고 돌리려면
# 그 사이를 이어 줄 것이 필요해서 이 스크립트를 둔다.
#
#   ./run_all.sh experiments/terminal-bench.yaml /tmp/jobs
#
# 필요한 환경변수는 아래 require 에서 확인한다.
set -euo pipefail

EXP="${1:?사용법: run_all.sh <experiment.yaml> <jobs-dir>}"
JOBS="${2:?사용법: run_all.sh <experiment.yaml> <jobs-dir>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/.venv/bin/python"
PIER="$HERE/.venv/bin/pier"

require() { [ -n "${!1:-}" ] || { echo "✗ $1 이(가) 필요합니다: $2" >&2; exit 1; }; }
require OPENAI_API_KEY  "az account get-access-token --scope https://cognitiveservices.azure.com/.default"
require UPSTREAM_BASE_URL "모델 엔드포인트"
require PUBLIC_HOST     "컨테이너에서 호스트를 부르는 이름 (host.docker.internal)"
# 이게 없으면 압축 arm 이 0 스텝에서 죽는다. patch_pier.py 설명 참고.
require PIER_EXTRA_SAFE_PORTS "squid 가 허용할 추가 포트"

# ── 1. 설정 생성 + 프록시 기동 ────────────────────────────────
# launch.py 는 pause() 로 멈추므로 배경에 두고, 산출물이 나오면 이어 간다.
LOG="$JOBS.launch.log"
mkdir -p "$(dirname "$LOG")"
"$PY" "$HERE/launch.py" "$EXP" > "$LOG" 2>&1 &
LAUNCH_PID=$!
trap 'kill "$LAUNCH_PID" 2>/dev/null || true' EXIT

echo "▸ 프록시 기동 중 (로그: $LOG)"
for _ in $(seq 1 120); do
  grep -q "프록시 유지 중" "$LOG" && break
  kill -0 "$LAUNCH_PID" 2>/dev/null || { echo "✗ launch.py 가 죽었습니다"; cat "$LOG"; exit 1; }
  sleep 5
done
grep -q "프록시 유지 중" "$LOG" || { echo "✗ 프록시 기동 시간 초과"; cat "$LOG"; exit 1; }
sed -n '/설정 생성/,$p' "$LOG"

# ── 2. 언어별 롤아웃 ──────────────────────────────────────────
# 언어를 순차로 돈다. 동시에 돌리면 Docker 가 컨테이너 수만큼 CPU 를
# 나눠 갖고, 그러면 지연 수치가 압축 탓인지 경합 탓인지 갈리지 않는다.
rc=0
while read -r lang cfg; do
  echo
  echo "════ [$lang] 롤아웃 시작 ════"
  if ! "$PIER" run --config "$cfg" --jobs-dir "$JOBS" 2>&1 | tail -40; then
    echo "✗ [$lang] pier 가 0 이 아닌 코드로 끝났습니다 (계속 진행)"
    rc=1
  fi
done < <(grep -oE '\[[a-z]{2}\] pier run --config .*' "$LOG" \
         | sed -E 's/^\[([a-z]{2})\] pier run --config /\1 /')

echo
echo "▸ 완료. 결과: $JOBS"
exit "$rc"

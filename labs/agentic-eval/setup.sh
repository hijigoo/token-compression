#!/usr/bin/env bash
# labs/agentic-eval — 종단 평가 환경 준비
#
#   ./setup.sh
#
# 하는 일: deep-swe 클론, pier 설치, 랩 전용 venv 생성, docker 확인
set -euo pipefail
cd "$(dirname "$0")"

DEEPSWE_REPO="https://github.com/datacurve-ai/deep-swe"
PIER_REPO="https://github.com/datacurve-ai/pier"

log()  { printf '\033[36m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── 1. 사전 조건 ─────────────────────────────────────────────
command -v git >/dev/null || die "git 이 필요합니다"
command -v uv  >/dev/null || die "uv 가 필요합니다 (https://docs.astral.sh/uv/)"

if ! command -v docker >/dev/null; then
  die "docker 가 필요합니다. 태스크당 컨테이너가 2개(작업용/채점용) 뜹니다."
elif ! docker info >/dev/null 2>&1; then
  die "docker 데몬이 떠 있지 않습니다. Docker Desktop 을 실행하세요."
fi
log "docker 확인됨"

# ── 2. 데이터셋 ──────────────────────────────────────────────
# 코퍼스가 아니라 Docker 실행 픽스처라 labs/data/ 가 아니라 여기 둔다.
if [[ -d datasets/deep-swe/.git ]]; then
  log "deep-swe — 이미 있음 (skip)"
else
  log "deep-swe 클론 중…"
  mkdir -p datasets
  git clone --depth 1 "$DEEPSWE_REPO" datasets/deep-swe
fi

n_tasks=$(find datasets/deep-swe/tasks -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
[[ "$n_tasks" -gt 0 ]] || die "datasets/deep-swe/tasks 가 비어 있습니다"
log "태스크 ${n_tasks}개"

# ── 3. 랩 전용 venv ──────────────────────────────────────────
# 루트 .venv 와 분리한다. llmlingua/torch 핀이 다른 랩과 충돌하기 때문.
if [[ ! -d .venv ]]; then
  log "venv 생성 중…"
  uv venv
fi

log "pier 설치 중…"
uv pip install --python .venv "git+${PIER_REPO}" || \
  warn "pier 설치 실패 — 수동 설치가 필요할 수 있습니다: uv pip install git+${PIER_REPO}"

cat <<'EOF'

  압축기는 필요한 것만 설치하세요 (모두 무겁습니다):

    uv pip install --python .venv 'headroom-ai[code]'   # headroom arm
    uv pip install --python .venv llmlingua             # llmlingua arm
    uv pip install --python .venv sentence-transformers # recomp arm

EOF

# ── 4. 다음 단계 ─────────────────────────────────────────────
cat <<'EOF'
  다음 단계

  1) 컨테이너에서 도달 가능한 주소를 준비합니다.
     컨테이너 안의 localhost 는 컨테이너 자신이라 반드시 실패합니다.
       · 사내 서버/VM 에 띄우고 그 호스트명 사용  ← 권장 (포트만 늘리면 됨)
       · 또는 cloudflared/ngrok 터널 (arm 당 1개씩 필요)

  2) 기준선부터 파이프라인을 검증합니다 (n_tasks: 5).
       PUBLIC_HOST=<호스트> ./.venv/bin/python launch.py experiments/ratio-sweep.yaml

  3) 출력된 pier 명령을 다른 터미널에서 실행합니다.

  4) 집계합니다.
       ./.venv/bin/python analyze.py runs/... --jobs <pier jobs 경로>
EOF

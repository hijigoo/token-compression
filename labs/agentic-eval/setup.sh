#!/usr/bin/env bash
# labs/agentic-eval — 종단 평가 환경 준비
#
#   ./setup.sh
#
# 하는 일: deep-swe 클론, pier 설치, 랩 전용 venv 생성, docker 확인
set -euo pipefail
cd "$(dirname "$0")"

DEEPSWE_REPO="https://github.com/datacurve-ai/deep-swe"
TBENCH_REPO="https://github.com/harbor-framework/terminal-bench-2-1"
# pier 주소는 requirements.txt 가 갖고 있습니다. 두 곳에 적으면 어긋납니다.

log()  { printf '\033[36m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── 1. 사전 조건 ─────────────────────────────────────────────
command -v git >/dev/null || die "git 이 필요합니다"
command -v uv  >/dev/null || die "uv 가 필요합니다 (https://docs.astral.sh/uv/)"

# Docker 는 **실제 실행할 때만** 필요합니다. 준비 단계에서 막지 않습니다.
# run.ipynb 은 8절까지 Docker 없이 돌고, 그게 이 랩을 처음 보는 사람이
# 밟는 경로입니다. 여기서 죽이면 노트북을 열어보지도 못합니다.
DOCKER_OK=0
if ! command -v docker >/dev/null; then
  warn "docker 가 없습니다. run.ipynb 8절까지는 그대로 보실 수 있습니다."
  warn "  실제 실행에는 필요합니다 — 태스크당 컨테이너가 2개(작업용/채점용) 뜹니다."
elif ! docker info >/dev/null 2>&1; then
  warn "docker 데몬이 떠 있지 않습니다. 실제 실행 전에 Docker Desktop 을 켜주세요."
else
  DOCKER_OK=1
  log "docker 확인됨"
fi

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

# Terminal Bench 2.1 — DeepSWE 와 성격이 다른 두 번째 벤치마크입니다.
# DeepSWE 는 "저장소를 고쳐라"(코드 편집), Terminal Bench 는 "터미널에서
# 끝내라"(파일 복구·마이그레이션·로그 집계)라 압축이 다르게 먹힐 수 있습니다.
# MS 문서가 인용한 세 태스크가 여기 들어 있습니다.
if [[ -d datasets/terminal-bench/.git ]]; then
  log "terminal-bench — 이미 있음 (skip)"
else
  log "terminal-bench 2.1 클론 중…"
  git clone --depth 1 "$TBENCH_REPO" datasets/terminal-bench
fi

tb_tasks=$(find datasets/terminal-bench/tasks -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
log "terminal-bench 태스크 ${tb_tasks}개"

# ── 3. 랩 전용 venv ──────────────────────────────────────────
# 루트 .venv 와 분리한다. llmlingua/torch 핀이 다른 랩과 충돌하기 때문.
if [[ ! -d .venv ]]; then
  log "venv 생성 중…"
  uv venv
fi

log "의존성 설치 중… (pier·ipykernel·kit)"
uv pip install --python .venv -r requirements.txt || \
  warn "설치 실패 — 수동으로: uv pip install --python .venv -r requirements.txt"

cat <<'EOF'

  압축기는 필요한 것만 설치하세요 (모두 무겁습니다).
  none·truncate 는 표준 라이브러리만 써서 지금도 돌아갑니다.

    uv pip install --python .venv 'headroom-ai[code]'   # headroom arm
    uv pip install --python .venv llmlingua             # llmlingua arm
    uv pip install --python .venv sentence-transformers # recomp arm

EOF

# ── 4. 다음 단계 ─────────────────────────────────────────────
cat <<'EOF'
  먼저 run.ipynb 을 열어보세요. 파이프라인을 한 단계씩 보여줍니다.
  8절까지는 Docker 도 API 키도 필요 없습니다.
  커널은 이 폴더의 .venv 로 골라주세요.

  다음 단계 — 실제로 돌리실 때

  1) 컨테이너에서 도달 가능한 주소를 준비합니다.
     컨테이너 안의 localhost 는 컨테이너 자신이라 반드시 실패합니다.
       · 사내 서버/VM 에 띄우고 그 호스트명 사용  ← 권장 (포트만 늘리면 됨)
       · 또는 cloudflared/ngrok 터널 (arm 당 1개씩 필요)

  2) 기준선부터 파이프라인을 검증합니다 (태스크 1개짜리 smoke).
       PUBLIC_HOST=<호스트> ./.venv/bin/python launch.py experiments/smoke.yaml

  3) 출력된 pier 명령을 다른 터미널에서 실행합니다. (Docker 필요)

  4) 집계합니다.
       ./.venv/bin/python analyze.py runs/... --jobs <pier jobs 경로>
EOF

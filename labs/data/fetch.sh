#!/usr/bin/env bash
# labs/data — 공유 코퍼스 획득
#
#   ./fetch.sh            모든 코퍼스
#   ./fetch.sh docs-long  하나만
#
# 데이터 파일은 커밋되지 않는다. 재현은 항상 이 스크립트를 통해서 한다.
set -euo pipefail
cd "$(dirname "$0")"

CORPORA=(conversations docs-long code)
want="${1:-all}"

log()  { printf '\033[36m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# 코퍼스별 획득 로직을 여기에 추가한다.
# 규칙: 멱등해야 하고(이미 있으면 skip), manifest.json 을 함께 남겨야 한다.
fetch_one() {
  local name="$1"
  [[ -d "$name" ]] || die "알 수 없는 코퍼스: $name"

  if [[ -f "$name/manifest.json" ]] && compgen -G "$name/*" > /dev/null 2>&1 \
     && [[ $(find "$name" -type f ! -name '.gitkeep' ! -name 'manifest.json' | head -1) ]]; then
    log "$name — 이미 있음 (skip)"
    return 0
  fi

  case "$name" in
    conversations)
      warn "$name 획득 로직이 아직 없습니다."
      warn "  이 함수에 다운로드 명령을 추가하고 manifest.json 을 작성하세요."
      ;;
    docs-long)
      warn "$name 획득 로직이 아직 없습니다."
      ;;
    code)
      warn "$name 획득 로직이 아직 없습니다."
      ;;
  esac
}

verify_one() {
  local name="$1"
  local n
  n=$(find "$name" -type f ! -name '.gitkeep' ! -name 'manifest.json' 2>/dev/null | wc -l | tr -d ' ')
  if [[ -f "$name/manifest.json" ]]; then
    log "$name — 파일 ${n}개, manifest 있음"
  elif [[ "$n" -gt 0 ]]; then
    # 데이터만 있고 출처가 없으면 재현이 불가능하다. 경고로 끝내지 않는다.
    die "$name — 파일 ${n}개가 있는데 manifest.json 이 없습니다. 출처 없는 데이터는 쓸 수 없습니다."
  else
    warn "$name — 비어 있음"
  fi
}

targets=("${CORPORA[@]}")
[[ "$want" != "all" ]] && targets=("$want")

for c in "${targets[@]}"; do fetch_one "$c"; done
echo
for c in "${targets[@]}"; do verify_one "$c"; done

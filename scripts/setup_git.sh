#!/usr/bin/env bash
# 저장소를 클론한 뒤 한 번만 실행하세요.
#
#   1) 노트북 출력을 커밋 시점에 자동으로 지우는 filter 를 겁니다
#   2) 푸시 직전 안전망(pre-push 훅)을 켭니다
#
# filter 설정은 .git/config 에 저장되므로 저장소에 커밋되지 않습니다.
# 그래서 클론할 때마다 한 번씩 실행해야 합니다.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
PY="$(command -v python3 || command -v python)"

git config filter.nbstrip.clean "$PY scripts/strip_outputs.py --stdin"
git config filter.nbstrip.smudge cat
git config filter.nbstrip.required true
git config core.hooksPath .githooks

echo "설정 완료"
echo "  · 커밋 시 노트북 출력 자동 제거   (filter.nbstrip)"
echo "  · 푸시 직전 검사                  (.githooks/pre-push)"
echo
echo "이미 출력이 담긴 채로 커밋된 노트북이 있다면 한 번 정리해 주세요:"
echo "  python scripts/strip_outputs.py && git add -A && git commit -m 'chore: 노트북 출력 제거'"

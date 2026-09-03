#!/usr/bin/env bash
# 최신 측정으로 보고서를 다시 만든다.
#
# 언어를 나눠 돌리면 run 디렉터리가 갈린다(en 을 먼저, ko 를 나중에).
# 조건 이름은 같으므로 report_paper.py 가 합쳐 준다. 여기서는 존재하는
# run 을 전부 모아 넘기는 일만 한다.
#
# 측정이 아직 없는 항목은 조용히 건너뛴다.
#
#   ./refresh_report.sh
set -uo pipefail
cd "$(dirname "$0")"
PY=./.venv/bin/python
RUNS=../../runs/agentic-eval

# 같은 실험 이름의 run 디렉터리를 최신순으로 모은다(언어별로 갈려 있다).
alldirs() { ls -dt "$1"/*/ 2>/dev/null; }

# 압축률 스윕이 주 측정이다. 예전 wide(3조건) 결과는 스윕에 흡수되었으므로
# 섞지 않는다 — 섞으면 조건 구성이 어긋나 표본 수가 조건마다 달라진다.
MAIN=$(alldirs "$RUNS/terminal-bench/terminal-bench-sweep")
JOBS=""
for d in /tmp/tbsweep /tmp/tbsweep-extra /tmp/tbsweep-ko; do [ -d "$d" ] && JOBS="$JOBS $d"; done
if [ -z "$MAIN" ] || [ -z "$JOBS" ]; then
  MAIN=$(alldirs "$RUNS/terminal-bench/terminal-bench-wide")
  JOBS=""
  for d in /tmp/tbwide2; do [ -d "$d" ] && JOBS="$JOBS $d"; done
fi
[ -z "$MAIN" ] && { echo "✗ 주 측정 run 을 찾지 못했습니다"; exit 1; }
[ -z "$JOBS" ] && { echo "✗ 주 측정 jobs 디렉터리가 없습니다"; exit 1; }

ARGS=(--run $MAIN --jobs $JOBS)

CTL=$(alldirs "$RUNS/terminal-bench/terminal-bench-control")
CJOBS=""
for d in /tmp/tbctl /tmp/tbctl-extra /tmp/tbctl-ko; do [ -d "$d" ] && CJOBS="$CJOBS $d"; done
[ -n "$CTL" ] && [ -n "$CJOBS" ] && ARGS+=(--control-run $CTL --control-jobs $CJOBS)

# DeepSWE: 스윕이 있으면 스윕을, 없으면 smoke 라도 넣는다.
SWE=$(alldirs "$RUNS/deep-swe/deep-swe-sweep")
if [ -n "$SWE" ] && [ -d /tmp/dssweep ]; then
  ARGS+=(--swe-run $SWE --swe-jobs /tmp/dssweep)
elif [ -d /tmp/dssmoke ] && [ -n "$(alldirs "$RUNS/deep-swe/smoke")" ]; then
  ARGS+=(--swe-run $(alldirs "$RUNS/deep-swe/smoke") --swe-jobs /tmp/dssmoke)
fi

[ -f ../../reports/summary/samples.json ] && \
  ARGS+=(--samples ../../reports/summary/samples.json)

$PY report_paper.py "${ARGS[@]}" -o ../../reports/analysis

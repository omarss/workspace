#!/usr/bin/env bash
# Drain the current round, then plan & drain the next round, forever.
#
# Round 1 is usually pre-planned at a smoke target (10). Every later
# round is auto-planned at $TARGET (default 100 — the floor the user
# asked for). Because questions are additive across rounds, repeated
# passes compound the bank.
#
# Tail the log with:   tail -f /tmp/mcqs-gen.log
# Stop with:           pkill -f 'scripts/run-forever.sh'

set -euo pipefail

cd "$(dirname "$0")/.."

TARGET="${MCQS_PER_TYPE_TARGET:-100}"
MCQS="${PWD}/.venv/bin/mcqs"

echo "[$(date -Is)] starting run-forever loop, target=${TARGET}"

round_ctr=0
while true; do
  round_ctr=$((round_ctr + 1))
  echo "[$(date -Is)] draining pending jobs (loop iter ${round_ctr})"
  "${MCQS}" generate || {
    rc=$?
    echo "[$(date -Is)] generator exited ${rc}; sleeping 30s then retrying"
    sleep 30
    continue
  }

  # Successful drain — plan the next round. Target floor is 100; a
  # plan-round at the same (subject, round, type) triple is a no-op
  # because of the UNIQUE constraint, so re-running is safe.
  echo "[$(date -Is)] drain complete; planning next round at target=${TARGET}"
  "${MCQS}" plan-round --target "${TARGET}" --notes "auto round from run-forever" || {
    echo "[$(date -Is)] plan-round failed; sleeping 60s then retrying"
    sleep 60
  }
done

#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
# The session the README's recording shows, typed and run in a scratch folder that holds a
# copy of made_up_bench.py. record.sh records it; run on its own, it plays the same session in
# the terminal it runs in.
#
# What the recording does that the commands it shows do not:
# - it switches off the machine checks, so the footer reads "Machine state: unknown." on any
#   machine: through PAIRBENCH__ variables it sets four config keys, for no checks before the
#   run, no explain launches after it, no note on the two core types of a machine that has them,
#   and a busy-core limit for the disturbance witness that no machine reaches;
# - it leaves out the lines pairbench prints on standard error;
# - it colours the prompt and the verdict words; pairbench itself prints no colour.
set -euo pipefail

export PAIRBENCH__GATES__MODE=off
export PAIRBENCH__EXPLAIN__MODE=off
export PAIRBENCH__GATES__ALLOW_MIXED_CORE_TYPES=true
export PAIRBENCH__GATES__DISCARD__MAX_BUSY_CORES=1000000

PROMPT=$'\e[35m$\e[0m '
TYPE_DELAY=0.012

type_line() {
  printf '%s' "$PROMPT"
  local text="$1" i
  for ((i = 0; i < ${#text}; i++)); do
    printf '%s' "${text:i:1}"
    sleep "$TYPE_DELAY"
  done
  sleep 0.4
  printf '\n'
}

# Colours each verdict word where the verdict column has it: FASTER in cyan, SLOWER in red,
# TIE in magenta, UNRESOLVED in yellow and NO VERDICT in grey.
highlight() {
  sed -E \
    -e $'s/  FASTER$/  \e[1;36mFASTER\e[0m/' \
    -e $'s/  SLOWER$/  \e[1;31mSLOWER\e[0m/' \
    -e $'s/  TIE$/  \e[1;35mTIE\e[0m/' \
    -e $'s/  UNRESOLVED( |$)/  \e[1;33mUNRESOLVED\e[0m\\1/' \
    -e $'s/  NO VERDICT( |$)/  \e[1;90mNO VERDICT\e[0m\\1/'
}

PLAN='pairbench plan --side "new=cmd:./made_up_bench.py new" --side "old=cmd:./made_up_bench.py old" | head -n 8'
RUN='pairbench run --side "new=cmd:./made_up_bench.py new" --side "old=cmd:./made_up_bench.py old" --driver lines'

sleep 0.5
type_line "$PLAN"
pairbench plan --side "new=cmd:./made_up_bench.py new" --side "old=cmd:./made_up_bench.py old" 2>/dev/null | head -n 8
sleep 2.4
printf '\e[H\e[2J'
type_line "$RUN"
pairbench run --side "new=cmd:./made_up_bench.py new" --side "old=cmd:./made_up_bench.py old" \
  --driver lines 2>/dev/null | highlight
sleep 0.3

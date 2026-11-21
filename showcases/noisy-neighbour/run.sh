#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
#
# Runs this showcase: ./run.sh [more options of pairbench run]
# Each call writes into a new folder pairbench-runs/<UTC time>-<process id>:
# first a run on the quiet machine into its quiet folder, then the same run
# beside a busy neighbour into its noisy folder. PAIRBENCH_NEIGHBOUR_LOOPS sets
# how many busy loops the neighbour runs (1 by default).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
. ../publish.sh
engine=${PAIRBENCH_SHOWCASE_ENGINE:-docker}
image=$(sed -n 's/^image = "\(python:[^"]*\)"$/\1/p' pairbench.toml | head -n 1)
name=pairbench-showcase-neighbour
mounts="launch.mounts=[\"$here:/showcase:ro\"]"
runs="pairbench-runs/$(date -u +%Y%m%dT%H%M%SZ)-$$"

run_pairbench quiet --config pairbench.toml --set "$mounts" --out "$runs/quiet" "$@"

"$engine" run --detach --rm --name "$name" --memory 256m -v "$here:/showcase:ro" "$image" \
  python /showcase/neighbour.py "${PAIRBENCH_NEIGHBOUR_LOOPS:-1}" >/dev/null
trap '"$engine" rm --force "$name" >/dev/null 2>&1 || true' EXIT INT TERM
run_pairbench noisy --config pairbench.toml --set "$mounts" --out "$runs/noisy" "$@"
echo "the two runs are in $here/${PAIRBENCH_SHOWCASE_PUBLISH:-$runs}" >&2

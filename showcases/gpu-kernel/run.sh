#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
#
# Runs this showcase: ./run.sh [more options of pairbench run]
# The first run builds kernel_bench inside each image into .build/, once.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
. ../publish.sh
engine=${PAIRBENCH_SHOWCASE_ENGINE:-docker}

for side in cuda1343 cuda1350; do
  image=$(sed -n "/^\[sides\.$side\]/,/^\[/s/^image = \"\(.*\)\"$/\1/p" pairbench.toml)
  if [ ! -x ".build/$side/kernel_bench" ]; then
    "$engine" run --rm --memory 8g --memory-swap 8g --gpus device=0 -v "$here:/showcase" "$image" \
      sh /showcase/build.sh "/showcase/.build/$side"
  fi
done

run_pairbench "" --config pairbench.toml --set "launch.mounts=[\"$here:/showcase:ro\"]" "$@"

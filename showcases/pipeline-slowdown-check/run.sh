#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
#
# Runs this showcase: ./run.sh [more options of pairbench run]
# The first run installs pytest and pytest-benchmark into .deps/, once.
# The exit code is that of pairbench run: 1 when revision b is SLOWER.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
. ../publish.sh
engine=${PAIRBENCH_SHOWCASE_ENGINE:-docker}
image=$(sed -n 's/^image = "\(python:[^"]*\)"$/\1/p' pairbench.toml | head -n 1)

if [ ! -d .deps/pytest/pytest_benchmark ]; then
  "$engine" run --rm --memory 2g -v "$here:/showcase" "$image" \
    python -m pip install --no-cache-dir --target /showcase/.deps/pytest \
    pytest==9.2.0 pytest-benchmark==5.3.1
fi

run_pairbench "" --config pairbench.toml --set "launch.mounts=[\"$here:/showcase:ro\"]" "$@"

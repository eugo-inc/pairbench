#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
#
# Runs this showcase: ./run.sh [more options of pairbench run]
# The first run installs PyTorch from PyPI for the pip side into .deps/, once.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
. ../publish.sh
engine=${PAIRBENCH_SHOWCASE_ENGINE:-docker}
image=$(sed -n 's/^image = "\(python:[^"]*\)"$/\1/p' pairbench.toml)

if [ ! -d .deps/torch/torch ]; then
  "$engine" run --rm --memory 8g -v "$here:/showcase" "$image" \
    python -m pip install --no-cache-dir --target /showcase/.deps/torch torch==2.15.0
fi

run_pairbench "" --config pairbench.toml --set "launch.mounts=[\"$here:/showcase:ro\"]" "$@"

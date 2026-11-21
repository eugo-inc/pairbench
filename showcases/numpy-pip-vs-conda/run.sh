#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
#
# Runs this showcase: ./run.sh [more options of pairbench run]
# The first run installs NumPy for each side into .deps/, once.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
. ../publish.sh
engine=${PAIRBENCH_SHOWCASE_ENGINE:-docker}
pip_image=$(sed -n 's/^image = "\(python:[^"]*\)"$/\1/p' pairbench.toml)
conda_image=$(sed -n 's/^image = "\(condaforge[^"]*\)"$/\1/p' pairbench.toml)

if [ ! -d .deps/pip-numpy/numpy ]; then
  "$engine" run --rm --memory 4g --memory-swap 4g -v "$here:/showcase" "$pip_image" \
    python -m pip install --no-cache-dir --target /showcase/.deps/pip-numpy numpy==2.5.4
fi
if [ ! -x .deps/conda-numpy/bin/python ]; then
  "$engine" run --rm --memory 4g --memory-swap 4g -v "$here:/showcase" "$conda_image" \
    conda create --yes --quiet --override-channels -c conda-forge \
    -p /showcase/.deps/conda-numpy python=3.13 numpy=2.5.4
fi

run_pairbench "" --config pairbench.toml --set "launch.mounts=[\"$here:/showcase:ro\"]" "$@"

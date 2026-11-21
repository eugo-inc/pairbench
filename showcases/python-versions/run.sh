#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
#
# Runs this showcase: ./run.sh [more options of pairbench run]
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
. ../publish.sh
run_pairbench "" --config pairbench.toml --set "launch.mounts=[\"$here:/showcase:ro\"]" "$@"

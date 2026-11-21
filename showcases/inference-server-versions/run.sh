#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
#
# Runs this showcase: ./run.sh [more options of pairbench run]
# The first run downloads the model, at a pinned revision, into models/, once.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
. ../publish.sh
engine=${PAIRBENCH_SHOWCASE_ENGINE:-docker}
image=$(sed -n 's/^image = "\(vllm[^"]*v0\.33\.0[^"]*\)"$/\1/p' pairbench.toml)
model=Qwen/Qwen2.5-0.5B-Instruct
revision=7ae557604adf67be50417f59c2c2f167def9a775

if [ ! -f models/Qwen2.5-0.5B-Instruct/config.json ]; then
  mkdir -p models
  "$engine" run --rm --memory 8g -v "$here/models:/models" --entrypoint python3 "$image" -c \
    "from huggingface_hub import snapshot_download; snapshot_download('$model', revision='$revision', local_dir='/models/Qwen2.5-0.5B-Instruct')"
fi

run_pairbench "" --config pairbench.toml --set "launch.mounts=[\"$here/models:/models:ro\"]" "$@"

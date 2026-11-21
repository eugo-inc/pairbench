#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
#
# Builds kernel_bench inside a CUDA development image, with that image's own
# toolkit: build.sh OUTPUT_FOLDER. run.sh calls it once per side.
set -eu
out="$1"
cmake_version=4.4.5
nvbench_commit=0f8eb2dd715f90e963a8ab0ff9374097110cc3f9

apt-get update -qq
apt-get install -y -qq --no-install-recommends ca-certificates curl git >/dev/null

arch=$(uname -m)
case "$arch" in
  x86_64) sum=ed85135c5a5135b45e50423cb406dea04ca3338da0b8ef3c9ede963559680be0 ;;
  aarch64) sum=301d5063ab259577c1b57ce5490b1aab9ea5c56dc4c822f73499553dab94925f ;;
  *) echo "build.sh: no CMake download for $arch" >&2; exit 1 ;;
esac
tarball="cmake-$cmake_version-linux-$arch.tar.gz"
curl -fsSL -o "/tmp/$tarball" \
  "https://github.com/Kitware/CMake/releases/download/v$cmake_version/$tarball"
echo "$sum  /tmp/$tarball" | sha256sum -c -
tar -xzf "/tmp/$tarball" -C /usr/local
cmake="/usr/local/cmake-$cmake_version-linux-$arch/bin/cmake"

git clone --quiet https://github.com/NVIDIA/nvbench /tmp/nvbench
git -C /tmp/nvbench checkout --quiet "$nvbench_commit"

"$cmake" -S /showcase -B /tmp/build -DNVBENCH_SOURCE=/tmp/nvbench \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=native
"$cmake" --build /tmp/build --parallel --target kernel_bench
mkdir -p "$out"
cp /tmp/build/kernel_bench "$out/kernel_bench"

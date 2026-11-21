# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""PyTorch operations on one GPU, each printed as one ``lines`` case.

Each case is the median of seven timed calls, after three untimed calls. The
GPU is synchronised before the clock is read at the start and at the end, so
each value covers the queued work to its end. TF32 is turned off for matrix
products and convolutions on both sides. With ``PAIRBENCH_WORK_FACTOR=N``
each timed call runs the operation N times.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from collections.abc import Callable

import torch

CALLS = 7
WARMUPS = 3
FACTOR = int(os.environ.get("PAIRBENCH_WORK_FACTOR", "1"))


def report(case: str, operation: Callable[[], object]) -> None:
    for _ in range(WARMUPS):
        operation()
    times = []
    for _ in range(CALLS):
        torch.cuda.synchronize()
        start = time.perf_counter()
        for _ in range(FACTOR):
            operation()
        torch.cuda.synchronize()
        times.append(time.perf_counter() - start)
    line = {"case": case, "value": statistics.median(times), "unit": "s", "better": "lower"}
    print("::pairbench::", json.dumps(line), flush=True)


def main() -> None:
    if not torch.cuda.is_available():
        print("bench.py: no CUDA device is visible", file=sys.stderr)
        sys.exit(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.manual_seed(12345)
    gpu = torch.device("cuda")

    a = torch.randn(4096, 4096, device=gpu)
    b = torch.randn(4096, 4096, device=gpu)
    report("matmul_fp32_4096", lambda: a @ b)

    ah, bh = a.to(torch.bfloat16), b.to(torch.bfloat16)
    report("matmul_bf16_4096", lambda: ah @ bh)

    images = torch.randn(32, 64, 56, 56, device=gpu)
    conv = torch.nn.Conv2d(64, 64, kernel_size=3, padding=1, device=gpu)
    with torch.no_grad():
        report("conv2d_3x3_64ch", lambda: conv(images))

    logits = torch.randn(8192, 8192, device=gpu)
    report("softmax_8192", lambda: torch.softmax(logits, dim=-1))

    tokens = torch.randn(64, 512, 1024, device=gpu)
    norm = torch.nn.LayerNorm(1024, device=gpu)
    with torch.no_grad():
        report("layernorm_1024", lambda: norm(tokens))

    report("gelu", lambda: torch.nn.functional.gelu(tokens))


if __name__ == "__main__":
    main()

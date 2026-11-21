# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The GPU profilers ``pairbench profile`` can put a launch under.

``pairbench.profile.nsight.profiler`` gives NVIDIA Nsight Systems (``nsys``)
or NVIDIA Nsight Compute (``ncu``). Both are programs the user installed;
pairbench does not include, download or redistribute either. ``perf`` is
not served here: its stacks are recorded by ``pairbench.diagnose``.

This package file imports nothing, so that importing one module of the
package loads no other.
"""

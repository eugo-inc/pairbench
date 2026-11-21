# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Diagnostics and flame graphs: the explain step of a run.

After a run is analysed and its results are written, the explain step
launches each subject and the baseline once more under instruments: hardware
counters with ``perf stat``, sampled call stacks with ``perf record``, or the
standard-library sampler of ``pystacks`` for a Python workload where ``perf``
cannot run. From what the instruments leave it writes ``diagnostics.json``,
folded stacks, difference files and flame graphs. It describes how two sides
differ; it changes no comparison, no verdict and no exit code.

The package reaches a side only through ``pairbench.runner:open_explain``
(``pairbench.api.delegate("open_explain")``). It imports no side kind, no
driver, no machine check and no energy code.

Modules: ``explain`` (the step and ``pairbench profile --tool perf``),
``instruments`` (the three instruments and what ``pairbench doctor`` is
told), ``pysampler`` (the sampler, a self-contained file), ``folded``
(folding and the difference), ``findings`` (sentences from fixed templates),
``flame`` (the flame graphs) and ``document`` (``diagnostics.json``).
"""

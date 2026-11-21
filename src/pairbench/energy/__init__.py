# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""GPU power sampling and the energy of the windows of a launch.

``pairbench.energy.sampler.energy_meter`` makes the meter a run uses. Power
is read from the GPU management library when the ``gpu`` extra is installed,
and from one long-running ``nvidia-smi`` query process otherwise. Both
sources produce the same readings, and ``pairbench.energy.integrate`` turns
them into the energy of each window.

The values cover only what the GPU reports about itself: the case ids carry
the scope ``[gpu]``, and nothing of the CPU, memory, storage, cooling or
power supply is included. Idle power is recorded and never subtracted.

This package file imports nothing, so that importing one module of the
package loads no other.
"""

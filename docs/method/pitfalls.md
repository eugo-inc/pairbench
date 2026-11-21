---
description: "Common shapes of a misleading benchmark, such as a fixed order or a floor taken at another load: how to recognise each and what pairbench does about it."
---

# How does a benchmark fool its author?

In a few common shapes, such as a fixed run order, a noise floor taken at a different load, or
a difference claimed inside the noise. Each section says what goes wrong, how to recognise it,
and what pairbench does about it.

## A fixed run order

**Shape**: every launch of A runs before every launch of B, or A always runs first in each
round. Drift of the machine, warm caches or a heating processor then land on one side.

**Sign**: the difference shrinks or flips when the order is reversed.

**What pairbench does**: rotates and reverses the order every round, checks balance, refuses
an order that never changes (`E_ORDER_NOT_VARIED`) and downgrades a comparison whose order is
badly unbalanced. See [paired rounds](paired-rounds.md).

## A noise floor taken at a different load

**Shape**: the noise is measured once, on a quiet machine, and reused for a comparison run
later beside other work, or the other way round.

**Sign**: a floor that does not change from run to run although the machine does.

**What pairbench does**: measures the floor with twins in the same rounds as the comparison.
See [noise floor](noise-floor.md).

## A floor on one side only

**Shape**: the noise of the baseline is measured and assumed to hold for the subject too.
A subject that starts more processes or uses more cores may be noisier.

**What pairbench does**: the default rule needs a twin on both sides and adds both floors;
otherwise the comparison is `NO VERDICT (one_sided_floor)`.

## Your own product with a feature switched off, called a competitor

**Shape**: a comparison of a product against itself with one feature disabled, published as
a comparison against another product. It measures the feature, not the competitor.

**What to do**: name each side by what it is. A side built from your own product is your
product, whatever is switched off. Compare against the other product's own release, in its
own recommended configuration, and say which.

## Claiming or conceding a difference inside the noise

**Shape**: a 2 percent gain announced from a run whose noise is 3 percent, or a 2 percent
loss conceded on the same evidence.

**What pairbench does**: a gap inside the bar is never FASTER or SLOWER. A significant
direction inside the bar is `UNRESOLVED (inside_noise)`; a gap outside the bar that is not
significant is `UNRESOLVED (not_significant)`. The same evidence is required for a win, a
loss and a tie.

## An analysis tool that was never given a case with a known answer

**Shape**: a script, a statistic or a dashboard that has only ever been shown real data, so
no one knows whether it can say "different" when things differ, or "same" when they do not.

**What pairbench does**: runs a negative control (twins) and a positive control (`~twice`) in
every run, and ships its known answers as `pairbench selftest`. See
[instrument controls](instrument-controls.md).

## The same run counted twice

**Shape**: two copies of one capture, or one capture and a trimmed copy of it, pooled as if
they were independent runs. Every pair counts twice and the p-value shrinks for no reason.

**What pairbench does**: refuses to pool the same capture twice, identical rows, or a copy
torn from another capture (`E_POOL_*` codes, exit 6).

## A CPU set that mixes core types

**Shape**: a pinned set that holds both fast and efficient cores. Which side gets which core
changes from launch to launch and adds noise that has nothing to do with the sides.

**What pairbench does**: refuses such a set (`E_CPUS_MIXED_TYPES`), whether every side
shares it or one side has it as its own, unless `--allow-mixed-core-types` is given;
notes an unpinned run on a machine with more than one type; and records the core type of
every CPU in the shared set. See
[shared machines](shared-machines.md#pinning).

## First-token stopwatches that differ between tools

**Shape**: a time to first token from one load tool compared with one from another. The tools
start and stop their stopwatch at different events.

**What pairbench does**: drives every side of an experiment with the same tool, and names
the tool and version beside every first-token figure. See
[first-token definitions](first-token-definitions.md).

## Start-up cost that depends on image size inside the timing

**Shape**: the time of a container launch includes pulling or unpacking layers, or a cold
read of a large image, and the larger image looks slower at the workload.

**What pairbench does**: starts every container by image ID from an image already on the
machine, never pulls during the rounds, gives the start of an image its own secondary case
(`launch`), and measures the cost of a launch for command sides. To time the work alone,
print timings from inside the workload and read them with the
[`lines` driver](../guides/lines.md). See [launch cost](launch-cost.md).

## Others

- **A result resting on one memory layout.** The addresses a process gets depend on the
  size of its environment. `--vary-env-size` changes the size from round to round.
- **Choosing primary cases after the run.** The correction for testing several cases at once
  only holds when the family was fixed before the results were seen.
- **Running again until it comes out right.** Each new run is another test. Pool runs with
  `pairbench compare` instead of keeping the one you like.

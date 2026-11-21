---
description: "The checklist for publishing a comparison: what was compared, where, how often, with what noise and which verdicts, so a reader can judge and repeat it."
---

# What should a published benchmark comparison state?

Enough for a reader to judge it and repeat it: what was compared, on which machine, how many
rounds, the noise floor, the verdicts with their p-values, and how to run it again.

## The sides

- [ ] What each side is, by a name a reader can find: an image with its digest, a package
      with its version, a commit.
- [ ] Which side is the baseline.
- [ ] Any setting that differs between the sides besides the thing being compared. If there
      is one, say why.
- [ ] That a side built from your own product is your product, whatever is switched off.

## The workload

- [ ] The workload itself, or a link to it.
- [ ] The driver that read it, and the version of the tool it launched.
- [ ] Which cases were primary, and that they were chosen before the run.
- [ ] Whether the timing includes the start of a process or a container.

## The machine

- [ ] The class of machine: processor model, core count, memory, GPU, operating system.
      The results hold these under `provenance`.
- [ ] The machine state pairbench recorded: `quiet`, `busy` or `unknown`, and every degraded
      check.
- [ ] Whether launches were pinned, and to what kind of core.

## The method

- [ ] The rule (`strict` unless you built another) and its alpha.
- [ ] The number of paired rounds.
- [ ] The number of cases the correction covered ("corrected for testing N cases at once").
- [ ] The state of the positive control.
- [ ] Any downgrade or note in the results.

## The outcome

- [ ] For each primary case: the verdict word, the ratio, the noise bar and the corrected
      p-value.
- [ ] A TIE as "no difference larger than the noise of ±X% was found", not "the same".
- [ ] An UNRESOLVED or NO VERDICT with its reason, and without calling it a win or a loss.
- [ ] Figures filled into the text from the results by `pairbench fill`, never typed by
      hand.
- [ ] Energy figures labelled as GPU-only power.
- [ ] A time to first token named with the tool and version that measured it.

## What to publish beside it

- [ ] `results.json`: it is meant to be shared and holds no host name, user name, path
      outside the run folder or environment value, except an image reference you ask for and
      the forms that the [security policy](../../SECURITY.md#known-limits-of-the-shown-command) lists as
      known limits of the shown command.
- [ ] The command that produced it, as the results record it, with absolute paths cut and
      the secret forms of
      [what the shared files hide](../reference/config.md#what-the-shared-files-hide)
      hidden. A short plain password in any other form still shows: read the command first.
- [ ] Not the capture, the diagnostics or the profiles without reading them first: they hold
      names from your code and details of your machine.

An example sentence (made-up numbers):

> On a 16-core x86-64 workstation (machine state: quiet), `new` was faster than `old` on
> `matmul`: 1.26x, outside a noise bar of ±1.8%, in 15 of 16 paired rounds (p = 0.0010,
> corrected for testing 2 cases at once; rule strict; positive control ok).

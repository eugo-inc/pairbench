# Wording a result

## Say

- The verdict word with its ratio, its noise bar and its corrected p-value. Example, with
  made-up numbers: "new is FASTER than old on matmul: 0.80x, outside a noise bar of ±1.8%,
  corrected p = 0.0010."
- The rule and the number of paired rounds: "rule strict, 16 paired rounds" (made-up).
- How many cases were tested at once, as the results say it: "corrected for testing 2 cases
  at once".
- UNRESOLVED as UNRESOLVED, with its reason in plain words: "UNRESOLVED: the difference is
  significant but lies inside the noise."
- NO VERDICT as NO VERDICT, with its reason: "NO VERDICT: neither side has a twin, so there
  is no noise floor."
- The state of the positive control, and the machine state.
- Where the result holds: this machine, this load, these rounds.

## Do not

- Do not type a number by hand. Take every number from `figures`, or write a template and run
  `pairbench fill TEMPLATE --results results.json -o OUT`. Check a filled document later with
  `--check`.
- Do not change the rule, the cases or the baseline after seeing the results, and do not
  re-run until the verdict you want appears.
- Do not describe a TIE as "no difference": it means the gap lies inside the measured noise
  and the direction is not significant.
- Do not call an UNRESOLVED a win, a loss or a tie.
- Do not quote secondary cases as if they decided the verdict; they are graded with the
  uncorrected p-value and never change the exit code.
- Do not paste function or library names from `diagnostics.json` anywhere public unless the
  user asks for it.

## Templates

A template is any text file with tokens of the form `{{fig:KEY}}` or `{{fig:KEY|FORMAT}}`,
where `KEY` is a key of `figures`, for example `{{fig:matmul.new_vs_old.ratio}}`. With
several results files, name them with `--results NAME=PATH` and write `{{fig:NAME/KEY}}`. A
missing key stops the command with exit code 7 and lists every missing key.

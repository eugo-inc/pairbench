---
description: "What each release of pairbench added and changed, newest first."
---

# Changelog

This page lists what each release of pairbench added and changed, newest first.

## 0.3.1

The pages of earlier versions kept on the documentation site, with a version picker on every
page, and a run the tool server answers as ended always given with its exit code.

- **Earlier versions on the documentation site**: the site keeps the pages of the last release
  of each earlier minor version in the folder of its major and minor version, such as `0.2/`,
  beside the latest pages, each version with its own badges, icon, share image and search. The
  header of every page has a version picker beside the site's title that lists the latest pages
  and each version the site holds, newest first, each a link to that version's home page. A
  link in an earlier version's pages to a latest page the site lacks goes to that version's own
  copy of the page. `python3 tools/docs_site.py build --published FOLDER` builds the site of a
  release with the pages of the versions before it, as the
  [contributing guide](../CONTRIBUTING.md#the-site-of-a-release) says.
- **Run state from the tool server**: `run_status` and `run_cancel` take the state of a run and
  its exit code from one reading, so a run they answer as ended always comes with its exit
  code.
- **Unchanged**: the text codes, the results format and the command line are as in 0.3.0.

## 0.3.0

Verdicts decided in exact arithmetic, the runs of one text file pooled, a capture kept in
memory that reads back complete, a lone surrogate refused only where the results would show
it, and a matching reading mode of the text format, from Python and from
`pairbench compare --matching`.

- **Exact verdicts**: the Holm correction and the compare with alpha run on the exact
  fractions of the sign test, so rounding can never turn whether a p-value passes, at any
  number of rounds. Alpha is read as its decimal text, so 0.05 is exactly 1/20. The plan, the
  fewest rounds that can give a verdict, the positive control and the note that a side differs
  from its twin use the same exact arithmetic. The p-values written to `results.json` keep
  their values. The new `pairbench.stats.holm_exact` gives the Holm correction of exact
  fractions.
- **Checking a verdict by hand**: the
  [multiple comparisons page](method/multiple-comparisons.md#checking-a-verdict-by-hand) shows
  how to check a verdict by hand from `p_raw_fraction`, and how cases with equal p-values and
  secondary cases are checked.
- **Captures kept in memory**: a capture written from `Capture.to_records`, each record on a
  line of its own as `json.dumps(record, separators=(",", ":"))` writes it, or with the new
  `Capture.to_jsonl()`, reads back complete, as its end
  record carries the hash of the lines before it, as a run writes it. A capture without an
  end, or whose run did not complete, stays incomplete.
- **Runs of one text file**: `pairbench compare` pools the different runs of one text file,
  as the [text format page](reference/text-format.md) says. The same run given twice, or the
  same run of two files with the same bytes, is still refused with `E_POOL_SAME`. Runs of one
  file that are copies of each other are refused as copies in two files are, under the strict
  reader and under `--lenient`: with `E_POOL_IDENTICAL_ROWS` when their rows are identical,
  and with `E_POOL_TRUNCATED_COPY` when one is a cut-short copy of the other.
- **Pool refusal text**: the description of `E_POOL_SAME`, in `pairbench.errors.CODES` and on
  the [exit-codes page](reference/exit-codes.md), names the same run of a file that a reader
  splits into runs, given twice, as well as the same id, file path or file hash.
- **Matching reading mode**: `pairbench.read_text_matching(inputs, default_order=...)` reads
  files or texts of the text format by a fixed set of rules of its own, all inputs as one text,
  and returns every row it keeps, with its run, round label, side, case, value, suite, pass
  order and line. It counts the malformed rows of each run and in all, refuses no row and prints
  nothing. `MatchingRun.metadata_lines` gives the line number of each metadata line of a run.
  The strict default and the lenient mode of the text reader do not change. The
  [text format page](reference/text-format.md#matching-reading) describes the mode.
- **Two-sided view**: `MatchingRead.two_sided(first, second)` gives a view of two sides. It
  keeps the rows that a pass-order line of their run orders, labels each `"first, second"` or
  `"second, first"`, and counts the rows it leaves out. `MatchingView.capture()` gives that view
  as one capture for `pairbench.analyse`; a value that is not finite is a missing cell, with a
  `value_not_finite` note that names the run and the round label. A round takes the order of
  the rows that give its cells, and a round whose cells come from rows of both orders has no
  recorded order.
- **Pool checks of a matching read**: `pairbench.check_matching_pool(read)` returns every
  refusal of the runs of a read in the matching mode, and `pairbench.refuse_matching_pool(read)`
  raises the first. Only copies are refused: runs whose rows as written are equal, with
  `E_POOL_IDENTICAL_ROWS`, a run whose rows as written are a stretch of another's, with its
  last row whole or torn, with `E_POOL_TRUNCATED_COPY`, and runs that the copy checks of
  `pairbench.analyse` refuse over the kept rows. Those checks compare the kept rows in the order
  of the text, in the order the rows ran, as the run's pass-order and `sides=` lines in this
  mode give it, and, where that differs, in the order a text capture of each run holds them, and
  count two NaN values as equal, so a copy whose rows are written in another order, or that
  holds a NaN row, is refused as it is when its runs are read as text captures. A pass-order or
  `sides=` line with a tab at either end, which this mode reads as metadata and the text reader
  as a malformed row, orders the rows in the second order as the same line without the tab does,
  so a copy under such a line can be refused here where text captures of its runs pool. A line
  above the first banner of an input counts for nothing in the order a text capture holds, as
  the text reader drops it, and where every kept row of a run stands in one part that text
  captures read as a run of its own, that order comes from the lines of that part;
  `MatchingRead.input_lines` gives the line on which each input
  begins. They compare the kept rows again with the values that are not finite left out, as a
  strict text capture reads such a row as malformed and a lenient one orders its rows with it
  and then leaves it out, so a copy that holds a `nan` or `inf` row more, wherever it sits, or
  such a row in place of the first or last row a text capture holds, is refused too; one that
  holds such a row in place of a row in between pools, as it does when its runs are read as
  text captures. Then the parts of one run that text captures read as runs of their own are
  compared in the same orders, as a first input without a banner and the input after it, or a
  file that begins with a byte-order mark and a banner, which joins the run before it in this
  mode; such a refusal's detail gives the line on which each part begins under `lines`. A copy
  refused when its runs are read as text captures is refused here too, but for a copy that
  text captures find only with the rows whose value is zero or less, which this mode reads as
  malformed, two runs without a row a text capture keeps, which text captures find identical,
  and a text capture that a line this mode alone takes for a banner splits into two runs. Each
  refusal's detail names its check and the runs, and for a stretch where it sits; the first
  refusal names the first pair of runs, in index order, that is a copy.
- **Comparing with the matching mode**:
  `pairbench compare --matching --subject NAME --baseline NAME` reads every text capture file
  it is given as one text in the matching mode, runs the pool checks of that mode, and analyses
  the two-sided view of the two sides as one capture. A refusal of a pool check, a view
  without a round that holds both sides, refused with `E_GRID`, and a view whose two sides
  ran in one order in every paired round, refused by the analysis with `E_ORDER_NOT_VARIED`,
  end it with exit code 6.
  `--lenient`, a reader other than `text`, `file` sides, `--driver`, `--levels`,
  `--allow-incomplete`, `--allow-mixed-machines`, `--assume-interleaved` and a side name a
  capture cannot hold are refused with `E_USAGE`. Without `--matching`, `pairbench compare`
  does not change. The
  [text format page](reference/text-format.md#from-the-command-line) describes the command.
- **Unit and direction of the matching mode**: with `--matching`, the values are in the unit,
  and better is in the direction, that the `unit=` and `better=` lines of the runs that give
  the view a paired round state, and in `ns` with lower better when they state none. `--unit`
  and `--better`, which takes `lower` or `higher`, name them over lines that agree or state
  nothing. Runs that state more than one unit or more than one direction, a `better=` value
  other than `lower` or `higher`, an empty one included, a `--unit` that is not UTF-8 text,
  and `--unit` or `--better` without `--matching` are refused with `E_USAGE`.
- **Verdicts of the matching mode**: the two-sided view has no twins, so no case of
  `pairbench compare --matching` has a noise floor, and under the default rule `strict` each
  case gets its medians, its ratio and its corrected p-value with NO VERDICT. Each case gets
  the note `view_without_twins`, which says so, on standard error and in the results' `notes`.
  For a verdict, give `pairbench.analyse` the view's capture and noise floors measured
  elsewhere, as [rows produced elsewhere](reference/python-api.md#rows-produced-elsewhere)
  shows.
- **Results of the matching mode**: after `pairbench compare --matching`, `results.json` holds
  the optional object `matching`, with `runs`, `malformed_rows`, `kept_rows`, `left_out_rows`,
  `other_side_rows`, and `refusal`, the detail of a refusal of that mode with its `check`, or
  `null` when that mode did not refuse: a refusal of the analysis of the view, such as
  `E_ORDER_NOT_VARIED`, is listed under `refusals` only. The results format keeps its version
  `pairbench/results/v1`.
- **Lone surrogates in what a driver reads**: a case, a metric, a unit or a tool version that a
  launch records and that holds a lone surrogate, such as `"\ud800"` in JSON output, is refused
  by `pairbench run` and `pairbench compare` with `E_LAUNCH_FAILED`, and the results of the
  refused run are written; so is a tool name that holds one, only where the note of an untested
  version would show it. The message names the side and shows the text as the results show a
  case, its secret forms hidden and its paths cut, escaped, at most 40 characters on each side
  of the surrogate, or no text where the cut leaves the surrogate out, and names no key of the
  tool's output. A lone surrogate in a part of the output no
  driver reads, under any key, in a folder of a path the results cut away, or in a case the
  positive control does not record, one that only one of its two runs gave, which a note names
  escaped, or whose `better` is `none`, is read as it is, and the run finishes. `pairbench
  compare` and `pairbench.load_capture` read a capture that holds a lone surrogate; the
  terminal report shows it as `?`, and results that would hold it and
  `pairbench.render(results, "json")` are refused with `E_USAGE`. The JSON that `pairbench
  compare --json` prints without `--out` is printed where standard output can write the
  surrogate, as under a C, POSIX or C.UTF-8 locale and in Python's UTF-8 mode, which write one
  from U+DC80 to U+DCFF as the byte it stands for, and refused with `E_USAGE` where it cannot,
  as where standard output encodes UTF-8 with the error handler `strict`. `pairbench report`
  and `pairbench.load_results` refuse a results file that holds one with `E_USAGE`. A run of
  the Python API, `pairbench.run`, which writes no results, makes none of these early refusals:
  its capture keeps the text as an escape, and only what then writes the results refuses it.
  The tool server writes a surrogate in an answer as the escape `\uNNNN`, so the answer can
  always be sent.
- **Text that is not UTF-8**: a byte that is not UTF-8 in an argument, a variable or a name,
  which reaches pairbench as a lone surrogate, is kept in the capture as an escape where the
  results hide it or cut it away, as in a `--side` spec, a `--set` value of another setting or a
  folder of an absolute path, and the run, and `pairbench compare` and `pairbench.load_capture`
  of its capture, finish. Where the results would show it, as in an argument of the workload,
  the results folder or the setting `run.node_type`, `pairbench run` refuses it before it makes
  the run folder with `E_USAGE`, naming the argument by its number or the setting, without the
  text, and a side whose identity as the results show it holds such text with
  `E_SIDE_UNIDENTIFIED`. Results that would hold a lone surrogate are refused with `E_USAGE`
  before either results file is written.
- **Refusals read back**: `errors.unprintable` keeps a backslash it cannot read as it is, such
  as one before `\Uffffffff` or `\q`, reads the rest of the text and never raises. The tool
  server's `run_status` takes the refusal of a run it started only from the two lines a
  refusal prints, its code and message line and the line that names the code's entry, and
  only once the run has ended with an exit code the code may carry, so a report row whose
  case or side name reads like a refusal is never answered as one.
- **Notes of a failed step**: the note `explain_failed`, `charts_failed` or
  `report_page_failed` that quotes a refusal keeps its message as the refusal holds it in
  `results.json`, with no new version of the results format, and its printed line escapes it
  once, as the refusal's own line does.
- **Plug-ins**: a plug-in that fails to load because a registration or a refusal failed
  inside its loading prints that failure escaped once, and `pairbench doctor --json` keeps it
  as it is. `PluginError.text` holds the failure as it is. `PluginError` needs no message, and
  a subclass of it that does not call its constructor is read by its message.
- **Plan text**: the 0.2.1 entry says that `pairbench plan` escapes every line in the same
  way; it escapes every line of the header and every cell of the table, and writes the tab
  between two cells as it is, as the [exit-codes page](reference/exit-codes.md#text-codes)
  says.
- **Shown command**: the shown command, its hashes and the name of a hyperfine case hide a
  40-character hexadecimal value at the start of a query parameter, its value or the fragment
  of an address when a `.` joins it to a path after it, as such a value is hidden between two
  slashes. A 40-character value on its own, after a digest name, in a free text, or in a case
  id in an address whose host is empty still shows, and so does a UUID in that place. For a
  command that holds such a value, `argv_sha256` and the other hashes of the command differ
  from the ones 0.2.1 wrote, so explaining a 0.2.1 results file of it stops with
  `E_SIDE_CHANGED`, and pooling a 0.2.1 capture of it with a 0.3.0 one stops with
  `E_POOL_SIDE_DRIFT`. Two hyperfine commands that differ only in such a value get one name
  and are refused with `E_USAGE`; give each its own name with the `--command-name` option of
  hyperfine. Two sides that differ only in it are compared with the note
  `sides_differ_in_hidden_value`.
- **Known limits of the shown command**: the
  [security policy](../SECURITY.md#known-limits-of-the-shown-command) lists the forms in which
  such a value in a query stays shown, and the hosts after which a path after a blank in a query
  parameter shows, as in `postgresql://?k=x` and `postgresql://[::1]?k=x`. With a path after
  anything but a host name or a port number, as in `postgresql:///db?k=x`, which has no host,
  and in the other forms the known limits name, those paths are cut. The known limits also list
  the query of an address with a bracket in its path, as in `postgresql:///a[b]?k=x`, where a
  path that follows a relative path staying inside its folder shows its folders.
- **Documentation site**: the site is built with Astro 7.4.13, outside the published Astro
  security advisories. The built pages are the same apart from the generator tag.
- **Checks**: the checks run on every push to main as well as on pull requests, with ruff and
  mypy pinned to one release each, and the tool-server tests run in the unit job. The
  developer test of the changelog reads an ampersand that cannot start a character reference
  as prose.
- Text codes whose refusals this release changes, with no code added or removed:

  - `E_USAGE`, `E_LAUNCH_FAILED`, `E_SIDE_UNIDENTIFIED`, `E_POOL_SAME`, `E_SIDE_CHANGED`,
    `E_POOL_SIDE_DRIFT`, `E_CAPTURE_INCOMPLETE`.
  - `E_POOL_IDENTICAL_ROWS`, `E_POOL_TRUNCATED_COPY`, refusals of runs of one text file that
    are copies, and of the matching mode.
  - `E_GRID`, `E_ORDER_NOT_VARIED`, refusals of the matching mode.

  The set of text codes is that of 0.2.1.

## 0.2.1

A fix to what the terminal shows of a text read from an input.

- **Lines on standard error**: a refusal, a note, a machine check that did not pass and a line
  of the command's own write a line or paragraph separator (U+2028, U+2029), a character that
  changes the order the text around it shows in (U+061C, U+200E, U+200F, U+202A to U+202E,
  U+2066 to U+2069) and a lone surrogate as an escape such as `\uNNNN`, as they write a
  control character, so a name read from an input stays on its line, shows in its own order
  and always prints. A backslash is written as `\\`, so each printed line stands for one text
  only: the typed text `\x1b` prints as `\\x1b`, and an escape character as `\x1b`. A name
  that a message quotes keeps the escapes of its quoting, and their backslashes then show
  doubled: a side named `a\b` is quoted as `'a\\b'` and shows as `'a\\\\b'`, and an escape
  character in a quoted name shows as `\\x1b`. `results.json` keeps every message as it is,
  and the tool server gives the refusal of a run it started as the refusal holds it. The
  [exit-codes page](reference/exit-codes.md#text-codes) says how a message is escaped.
- **Plan text**: `pairbench plan`, and the text the tool server's plan tool answers, escape
  every line in the same way, the header and the table alike. The numbers of
  the plan and `plan.tsv` keep each name as it is.
- **Terminal report**: a line or paragraph separator, a character that changes the order of
  the text and a lone surrogate show as `?`, as a control character does.
- **Plug-ins and the self-test**: the line of a plug-in that failed to load and the detail of
  a failed self-test control are escaped as the lines on standard error are. The text of
  `pairbench doctor` prints the failed plug-in line escaped, and its `--json` output keeps the
  text as it is.
- **Changelog check**: the test that every change to the text codes is named in the changelog
  refuses a newest entry that holds directive syntax, a line that starts with two colons or a
  colon before a letter on a line with a code span, which the documentation site would drop
  with what it holds. The set of text codes is that of 0.2.0.

## 0.2.0

A lenient mode of the text reader, the pool checks on their own, and text codes that stay
stable.

- **Lenient text reader**: `pairbench compare --lenient`, and
  `pairbench.load_capture(path, reader="text", strict=False)` and `load_captures` from Python,
  read a value that is not a finite number as a missing cell instead of a malformed row. The
  new note `value_not_finite`, one per missing cell, names the side, the round and the case;
  the capture's records and the results carry it, the analysis goes on and the round counts
  in `n_unpaired`. A round that gives a side two positions is read with its order not
  recorded, with the new note `order_contradicted`, so the cases that use it get
  `NO VERDICT (order_not_recorded)`. The strict mode stays the default and reads as in 0.1.1.
  See
  [lenient reading](reference/text-format.md#lenient-reading).
- **Pool checks on their own**: `pairbench.check_pool(captures)` runs the checks that pooling
  captures in one analysis makes, with the same code as `analyse`, and returns every refusal
  they find instead of raising the first. See
  [checking a pool](reference/python-api.md#checking-a-pool).
- **Stable text codes**: the
  [exit-codes page](reference/exit-codes.md#stability-of-the-text-codes) gives the scope of
  every text code and says when a code may be added, renamed or removed. The set of text codes
  is that of 0.1.1.

## 0.1.1

A fix to what a results file shows of a command.

- **Shown command**: a local address (`file:` and `scheme:///` forms) and a climbing relative
  path (`../`, `./../`, `data/../../`) in the query or the fragment of an address are cut as
  they are after a host, whatever stands before them, so their folders and the hosts and
  credentials around them are hidden in the shown command, in `sh -c` texts and in `--opt=`
  values. A path that ends at a home folder after a `=` shows `<hidden>`. The
  [security policy](../SECURITY.md#known-limits-of-the-shown-command) lists what still shows.
- **Case ids** are read as in 0.1.0. The names of `hyperfine` cases come from their commands,
  so a command with such a path can name its case differently in 0.1.1: pooling a capture of
  0.1.0 with one of 0.1.1 is then refused with `E_POOL_CASES`, and a `cases.groups` pattern
  written for the 0.1.0 name may miss the 0.1.1 name.
- **Publishing**: the release is built again from its tag before the upload, which goes ahead
  only when the attached files are the files that build makes.

## 0.1.0

The first release.

- **Comparing sides**: container images, commands, Python interpreters, virtual
  environments, conda environments, inference servers and result files of other tools, each
  identified before and after the run.
- **Method**: paired rounds in a rotating and reversing order with checked balance; twins
  that measure the noise floor of each side in the same run; the exact sign test; Holm's
  correction over the primary cases; the `strict` rule; a positive control in every round;
  the measured cost of a launch.
- **Machine checks**: a quiet check that can wait, CPU pinning with one type of core, a
  census of other containers, advisory locks, witnesses during every launch, and disturbed
  rounds that can only downgrade a verdict.
- **Drivers**: `wall`, `lines`, `gbench`, `nvbench`, `pytest-benchmark`,
  `hyperfine`, `perf`, `llama-bench`, `guidellm`, `aiperf` and `vllm-bench` (experimental).
- **Energy**: GPU power sampling and energy per token, labelled as GPU-only.
- **Diagnostics**: resource figures for every launch, an explain step with counters and
  sampled stacks, and interactive flame graphs written by the package itself.
- **Outputs**: `results.json`, meant to be shared, with the known limits the
  [security policy](../SECURITY.md#known-limits-of-the-shown-command) lists; terminal,
  Markdown and HTML reports, charts with the `plot` extra, and `pairbench fill` for figures
  in documents.
- **For AI agents**: `llms.txt`, an agent skill, and a tool server with the `mcp` extra.
- **Python API** and a plug-in API with seven groups.

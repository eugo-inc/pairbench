---
description: "The text input format: rows of round, side, case and value, with host blocks, read by pairbench compare with the text reader."
---

# Give pairbench rows written by hand or by another program

Write the rows in the text input format, one value per line with its round, side and case, and
analyse them with the built-in reader `text`:

```
pairbench compare results.txt --reader text
```

## Example

Fields are separated by tab characters, shown here as `<TAB>`. The values are made-up
numbers.

```
## host
unit=ns
sides=new old
pass_order=new old
suite<TAB>new<TAB>1<TAB>matmul<TAB>1920000000
suite<TAB>old<TAB>1<TAB>matmul<TAB>2410000000
pass_order=old new
suite<TAB>old<TAB>2<TAB>matmul<TAB>2395000000
suite<TAB>new<TAB>2<TAB>matmul<TAB>1911000000
```

## Grammar

1. **Runs.** A line that is exactly `## host`, or starts with `## host` followed by a space,
   begins a new run. Each run becomes one capture; the first has index 0. Lines before the
   first such line form a run of their own only when they hold a data row; otherwise they
   form no run, their metadata belongs to no run, and a malformed line among them (a title
   or a column header, say) is counted in the first run. A file with no such line is one run.
2. **Section markers.** Any other line whose first non-blank characters are `##` is ignored
   and not counted anywhere.
3. **Comments.** Any other line whose first non-blank character is `#` is a comment. It is
   ignored and counted. A comment is never a malformed row and never metadata, whatever it
   contains.
4. **Metadata.** A line without a tab that contains `=` is `key=value`. All metadata is kept
   as written; no key is required. `unit=` names the unit of the values and defaults to
   `ns`. `better=lower` or `better=higher` says which direction is better and defaults to
   `lower`. A case is of kind `time` when the unit is `ns`, `us`, `ms` or `s`.
5. **Order.** `pass_order=` followed by side names separated by spaces gives the order in
   which the sides ran for the rows that follow, until the next `pass_order=` line. Rows
   before any `pass_order=` line in a run have no recorded order, and their comparisons get
   `NO VERDICT (order_not_recorded)`.
6. **Data rows.** Exactly five tab-separated fields: suite, side, round, case, value. The
   round is an integer, the value a number. The case id is the `case` field; the suite is
   kept on the record and changes neither the id nor the floor group. The same round, side
   and case given twice is a duplicated cell (`E_GRID`). A case id that ends, or has a part
   before a `/` that ends, like the mark a run adds to a name whose cut dropped words, a
   space, `+` and eight hex digits (`t +1a2b3c4d`), is refused with `E_USAGE`: no run gave
   it that mark.
7. **Malformed rows.** A row with a different field count, or a round or value that does not
   parse, is malformed: counted, reported and skipped. A value that is not a finite number is
   malformed too, unless the file is read in the [lenient mode](#lenient-reading). A value that parses as a number and is
   zero or less is not malformed: the row is kept and its case gets
   `NO VERDICT (nonpositive_value)`.
8. **Twins.** A twin relation is declared with a metadata line `twin=NAME:SIDE`.

## Lenient reading

The reader is strict by default. Its lenient mode reads two things the strict mode does not:

```
pairbench compare results.txt --reader text --lenient
```

From Python, `pairbench.load_capture(path, reader="text", strict=False)` reads the same way, and
so does `pairbench.capture.pool.load_captures(paths, reader="text", strict=False)`. Another
reader has no lenient mode and is refused with `E_USAGE`, also when it was the one that
recognised the file.

| Input | Strict, the default | Lenient |
|---|---|---|
| a value that is not a finite number: `nan`, `inf`, `-inf` in any case, or a number too large to hold, as `1e999` | a malformed row: counted, reported and skipped; a side left with no row in a round is refused with `E_GRID` | a missing cell, with a `value_not_finite` note |
| a round that gives a side two positions | refused with `E_USAGE` | read with its order not recorded, with an `order_contradicted` note |
| rows that no `pass_order=` line precedes | no recorded order | no recorded order, as in the strict mode |

**A missing cell** is one side in one round on one case. The side keeps its place in the
round, so the grid of rounds and sides stays whole, and the cell has no value. The capture
holds one `value_not_finite` note for each missing cell, printed on standard error when the
file is read, naming the side, the round by its label, the case and the capture; when the
capture numbers the round otherwise than its label, as it numbers rounds labelled 3 to 18
from 1, the note also gives that number, as `in round 9 (the capture's round 7)`. The notes are
part of the capture's records, so a capture written to `capture.jsonl` (`Capture.to_jsonl`) and read again keeps
them and prints them on standard error again, and the results list them in `notes[]`, one
entry per cell; `refusals[]` stays empty.
The analysis goes on: the round of a missing cell gives that case no pair, and is counted in
the comparison's `n_unpaired`. The twin of a side is compared with it over the rounds both have a value in, so
a missing cell of a side or of its twin leaves that round out of the side's noise floor. A
missing cell is never read as a value and never dropped silently.

**An order not recorded** is read as it is in the strict mode, so that no verdict claims more
than the rows show:

- A comparison whose paired rounds include one where the order of either side is not
  recorded gets `NO VERDICT (order_not_recorded)`, unless `--assume-interleaved` is given, which
  the results stamp with an `assume_interleaved` note. A comparison whose paired rounds all
  have a recorded order is graded; a round that gives the case no pair, as one with a missing
  cell, does not count against it.
- The balance check counts only the rounds whose order is recorded: `order_split` of a
  comparison, and the refusal `E_ORDER_NOT_VARIED` when a pair ran in the same order in every
  one of two or more such rounds. A round of unknown order never counts as balanced.
- Disturbed rounds are set aside by the machine checks of a run, which rows read from text do
  not have; the order changes nothing in them.
- A two-sided view (`project`, below) keeps only the rounds whose recorded order names both
  sides, so a round of unknown order is left out of it, with its missing cells.

## Matching reading

The matching mode reads files of the text format by a fixed set of rules of its own, and
returns every row it keeps with its run, its pass order and its line, instead of one capture
per run. It refuses no row and prints nothing: a line it cannot read is counted. It is
reached from Python and from `pairbench compare --matching`
([from the command line](#from-the-command-line)); the tool server does not offer it.

```python
read = pairbench.read_text_matching(inputs, default_order="new old")
```

`inputs` is a `Path`, read as a UTF-8 file, or a `str`, the text itself, or a list of them. A
file that cannot be read, or that is not UTF-8, is refused with `E_USAGE`. The strict reader
and the lenient mode do not change.

### What the mode reads

1. **One text.** The inputs are read as one text, joined in the order given with one newline
   between them. The text is split into lines as Python's `str.splitlines()` splits it, so a
   carriage return also ends a line. "The white space around" a line or a field means what
   `str.strip()` removes.
2. **Runs.** A line whose text, with the white space around it removed, starts with `## host`
   opens a run, so `   ## host`, `## hostX` and `## host<TAB>x` each open one. Runs are
   numbered from 0 across the whole text. The lines above the first banner belong to run 0,
   together with the first banner's lines, so a first input without a banner is run 0 and
   the lines of a later input above its first banner belong to the last run of the input
   before it. There are as many runs as banners, or one when the text holds no banner,
   whatever it holds; an empty text is one run with no rows. A run without rows keeps its
   index.
3. **Blank lines.** A line that is empty once stripped, one of only spaces and tabs
   included, is skipped and never counted.
4. **Banners and comments.** Any other line that starts with `#` once stripped is a banner
   (2) or a comment. It is never malformed and never metadata.
5. **Metadata.** Any other line that, once stripped, holds no tab and holds `=` is metadata,
   so `<TAB>pass_order=old new` is metadata. Each run keeps its metadata lines in order, split
   at the first `=` and otherwise as written. No metadata changes which rows are kept, their
   values or their runs: `unit=` given twice, `better=up`, `sides=` given twice or
   `sides=new new` is read like any other line, and `twin=z:new` makes no side a twin.
6. **Rows.** Any other line is split on tabs as it stands. A line that does not give exactly
   five fields is malformed. The round is Python's `int()` of its field and the value
   `float()` of its field, each as written, so ` 1`, `+1`, `1_0` and ` 110 ` parse; a field
   that does not parse makes the line malformed. Suite, side and case are kept exactly as
   written, white space included. No side name and no case is checked: `x y`, `~a`, `..`, an
   empty side and an empty case are kept like any other.
7. **Values.** A value at or below zero is malformed: `0`, `-0.0`, `-5`, `-inf` and `-1e999`.
   Any other value that parses is kept as it parsed: `nan` stays NaN, and `inf` and `1e999`
   stay positive infinity.
8. **Cells given twice.** Two rows with the same round, side and case are both kept, in the
   order of the text, so a run may hold a forward pass and a reversed pass that reuse round
   numbers. The [two-sided view](#a-two-sided-view) takes the later row of each cell, so when
   the reversed pass gives every cell, every round of the view has the reversed order, and
   `pairbench.analyse` and `compare --matching` refuse it with `E_ORDER_NOT_VARIED`.
9. **A byte-order mark** is part of the first line. A first line `﻿## host` is therefore
   neither a banner nor metadata but a malformed row, and the rows after it are lines above
   the first banner. The [pool checks](#pool-checks-of-a-matching-read) compare those rows as
   the part of their run a text capture reads as a run of its own.

### The pass order of each row

A pass-order line is a metadata line that starts exactly with `pass_order=` once stripped;
` pass_order = old new` is ordinary metadata. Each kept row carries the pass-order text in
force for it: what follows `pass_order=`, with the white space around it removed and
otherwise as written, so `new  old` and `new old` are two orders. The names are not checked
against the sides. Every banner resets the order to `default_order`, the text the caller
gives, and so does a `pass_order=` line with nothing after it; the default holds until the
next pass-order line. Each row says whether its order came from a line or from the default.

### What a read returns

`read_text_matching` returns a frozen `MatchingRead` (in `pairbench.capture.matching`):

| Name | What it holds |
|---|---|
| `rows` | the kept rows in the order of the text, each a `MatchingRow` with `run`, `round` (the integer written), `side`, `case`, `value`, `suite`, `pass_order`, `order_from_line` and `line`, the number of its line in the joined text from 1 |
| `runs` | one `MatchingRun` per run, a run without rows included: `index`, `banner_line`, `metadata`, `metadata_lines` (the line number of each metadata line), `malformed_rows`, `kept_rows`, `pool_rows`, every line of the run that splits on tabs into exactly five fields except its banner, each field stripped, and `pool_row_lines` (the line number of each) |
| `run_count`, `kept_rows`, `malformed_rows` | the number of runs, of kept rows, and of malformed rows over every run |
| `default_order`, `sha256` | the default order given, and the hash of the joined text in UTF-8 |
| `input_lines` | for each input in the order given, the number of the line of the joined text on which it begins; one past the last line for an input that adds no line |

<!-- example -->
```python
>>> import pairbench
>>> text = "\n".join([
...     "## host",
...     "pass_order=new old",
...     "s\tnew\t1\tmatmul\t110",
...     "s\told\t1\tmatmul\tabc",
...     "s\told\t1\tmatmul\t100",
...     "## host",
...     "s\tnew\t2\tmatmul\t111",
... ])
>>> read = pairbench.read_text_matching(text, default_order="new old")
>>> [(r.run, r.side, r.value, r.pass_order, r.order_from_line) for r in read.rows]
[(0, 'new', 110.0, 'new old', True), (0, 'old', 100.0, 'new old', True), (1, 'new', 111.0, 'new old', False)]
>>> read.run_count, read.kept_rows, read.malformed_rows
(2, 3, 1)
```

### A two-sided view

`read.two_sided(first, second)` returns a `MatchingView` of two sides:

- A row of either side is kept when the pass-order line in force for it names both sides,
  the names split on white space. Its order is `"first, second"` when that line names
  `first` before `second`, and `"second, first"` otherwise.
- The view never uses the default order. A row before the first pass-order line of its run,
  or after an empty one, is left out, and so is a row after a line that names one of the two
  sides or neither; `left_out_no_order` counts them. A pass-order line never counts for the
  rows of a later run.
- The rows of every other side are left out and counted in `left_out_other_sides`. A name
  that no pass-order line can name, one with white space in it or an empty one, keeps none of
  its rows.
- Naming one side twice is refused with `E_USAGE`.

`view.capture(unit="ns", better="lower")` gives the view as one capture for
`pairbench.analyse`. A round of the capture is a run and a round label together, so the same
label in two runs makes two rounds; the capture numbers them 1, 2, 3 and on by run, then
label. Within a run, rows with the same round, side and case are one cell, and the later row
gives its value, whatever pass order each carries. A round that holds rows of one side only
gives no pair and is left out. The order of a round is that of the rows that give its cells.
A round whose cells come from rows of both orders, as when a reversed pass stops inside a round
or gives only some of its cells, has no recorded order: `pairbench.analyse` then gives each
case the reason `order_not_recorded`, or refuses with `E_ORDER_NOT_VARIED` when the rounds
that have an order all ran in one. `second` is the
baseline; `unit` and `better` apply to every case, and the metadata of the runs is not
consulted. A value that is not finite is a missing cell, with one `value_not_finite` note in
the capture. The note names the side, the round by its label and the index of its run, the
capture's number of the round when it is not the label, and the case, as in
`the value of new in round 1 of run 1 (the capture's round 13) on the case 'c1' of the capture
matching-… is not a finite number; the cell is read as missing`; `capture` itself prints
nothing. A view without a round that holds both sides, and a side
name a capture cannot hold, such as `~a`, are refused with `E_USAGE`. A case id that ends like
the mark a run adds to a name whose cut dropped words (` +` and eight hex digits, as in
`t +1a2b3c4d`) is kept in the capture, and `pairbench.analyse` refuses that capture with
`E_USAGE`, though the pool checks of the read do not refuse it.

<!-- example -->
```python
>>> import pairbench
>>> view = pairbench.read_text_matching("\n".join([
...     "pass_order=new old",
...     "s\tnew\t1\tmatmul\t110",
...     "s\told\t1\tmatmul\t100",
...     "pass_order=old new",
...     "s\told\t1\tmatmul\t101",
...     "s\tnew\t1\tmatmul\t90",
... ]), default_order="new old").two_sided("new", "old")
>>> [v.order for v in view.rows]
['first, second', 'first, second', 'second, first', 'second, first']
>>> sorted((o.round, o.name, o.value, o.pos) for o in view.capture().observations)
[(1, 'new', 90.0, 2), (1, 'old', 101.0, 1)]
```

The values above are made up.

### From the command line

```
pairbench compare runs.txt more.txt --matching --subject new --baseline old
```

`--matching` makes `pairbench compare` read every file it is given in the matching mode, all
of them together as one text, and compare two sides of it:

1. The [pool checks of a matching read](#pool-checks-of-a-matching-read) run over the runs of
   that text: identical written rows, then a written stretch, then the copy checks of the kept
   rows. A refusal ends `compare` with exit code 6, and the results list its text code, with
   its detail and `check` under `matching.refusal`.
2. The two-sided view of the side `--subject` names, as its first side, and the side
   `--baseline` names, as its second, is analysed as one capture, as `view.capture()` gives
   it with the unit and the direction of item 3: a round is a run and a round label, and the
   later row of a cell wins within a run. Every other side is left out.
3. The unit and the better direction are found each on its own, from the `unit=` and
   `better=` lines of the runs that give the view's capture a paired round, a round label of
   the run that holds both sides, with key and value stripped; a `unit=` line with an empty
   value states nothing, and a run whose rows never pair states nothing. When those lines state more
   than one unit, or more than one direction, in one run or across runs, `compare` is refused
   with `E_USAGE`, and the message names each value with the runs that state it, as in
   `the runs that give the view a paired round give unit= more than one value: ms (run 0),
   s (run 1)`. A `better=` value other than `lower` and `higher`, in any spelling
   (`better=more`, `better=Higher`) and an empty one included, is refused with `E_USAGE` too,
   as the strict reader refuses it. Otherwise the values are in the one unit the lines state, or in `ns` when they
   state none, and better is the one direction they state, or lower when they state none.
   `--unit UNIT` and `--better lower|higher` name the unit and the direction over lines that
   agree or state nothing; they do not lift a refusal, and `--better` takes no other value.
   The read itself refuses none of these lines; only `compare` does.
4. A view without a round that holds both sides is refused with `E_GRID` and exit code 6:
   no pass-order line names both sides, a name matches no row, or the two sides never share
   a round label within a run. The message and `matching.refusal` give the number of rows
   the view keeps and the number it left out.
5. The analysis refuses a view whose two sides ran in the same order in every paired round
   with `E_ORDER_NOT_VARIED` and exit code 6: a file whose pass-order lines always name the
   sides in one order, or a forward pass whose reversed pass reuses every round label, as in
   item 8 of [the matching reading](#matching-reading). The results list this refusal, as
   every refusal of the analysis, under `refusals` only, and `matching.refusal` stays `null`:
   it holds a refusal of the pool checks or of a view without a paired round.

`compare --matching` gives each case its medians, its ratio and its corrected p-value, but
no verdict under the default rule `strict`. The view has no twins, so no case has a noise
floor: a comparison is `NO VERDICT`, with the reason `no_floor` from enough paired rounds, or
`too_few_rounds` or `single_measurement` below that, and `no_floor` among its `reasons`
either way. Each case gets the loud note `view_without_twins`, which says so, on standard
error and in the results' `notes`. No option of the command line supplies noise floors and no
rule gives a verdict without one, so for a verdict use Python: give `pairbench.analyse` the
view's capture and noise floors measured elsewhere, as
[rows produced elsewhere](python-api.md#rows-produced-elsewhere) shows for a capture without
twins.

The view never uses a default order, so the command line has no option for one. `--subject`
and `--baseline` are both required, must differ, and must be names a capture can hold:
`~a` or `x=y` is refused with `E_USAGE`. Rows of other names are still read as the mode reads
them, and left out of the view. `--lenient`, a reader other than `text`, `file` sides,
`--driver`, `--levels`, `--allow-incomplete`, `--allow-mixed-machines` and
`--assume-interleaved` are refused with `E_USAGE`. The pool checks accept a case id that ends
like the mark a run adds to a cut name (`t +1a2b3c4d`), but the analysis of the view refuses
it with `E_USAGE` and exit code 2, as it refuses it in any capture. `results.json` records the
mode under [`matching`](results-schema.md#fields-worth-knowing): the runs, the malformed and
kept rows, and the rows the view left out.

## Round numbers are labels

Round numbers are labels used for pairing: any integer is valid, 0 included, and they need not
start at 1. Within a run, the rounds from any start are numbered 1, 2, 3 and on in the order of
their labels, which keeps the order and the pairing. Rounds labelled 3 to 18 are analysed as
rounds 1 to 16 are. A number that no row of the run holds is no round. A refusal names a round
by the label the file gave it: when label 9 lacks a side, `E_GRID` says `missing 9 old`.

## Pooling text captures

Each run of a file is one capture. Several runs, or several files, can be pooled with
`pairbench compare`: `pairbench compare runs.txt --reader text` pools every run of `runs.txt`.
A capture is one run of one file, the file named by its path or by the hash of its bytes, so two
different runs of one file pool. The same run given twice is refused with `E_POOL_SAME`, as
`pairbench compare runs.txt runs.txt --reader text` is, and so is the same run of two files
with the same bytes. Two runs that hold identical rows are refused with
`E_POOL_IDENTICAL_ROWS`. A capture whose rows are a contiguous stretch of another's is refused with
`E_POOL_TRUNCATED_COPY`, and so is a torn copy: one whose last row has the round, side and case
of the row that follows the stretch, with another value. Rows are compared by side, case, value
and where each round begins, not by round number, so relabelling the rounds of a copy does not
hide it.

Without a `sides=` line, the last side a run's rows name first is its baseline, so two files
of one experiment can name different baselines when their first rounds started with different
sides. They still pool: sides are matched by name, kind, twin relation and fingerprint, and the
baseline is set once for the pool, by `--baseline NAME` or else as the baseline of the first
capture given, with a `pool_baseline` note when the captures disagree.

## Pool checks of a matching read

The runs of one read in the matching mode are checked from Python, and by
`pairbench compare --matching` before it compares two sides:
`pairbench.check_matching_pool(read)` returns every refusal, and
`pairbench.refuse_matching_pool(read)` raises the first. The checks compare the runs of the one
text the inputs make together, so two runs of one file, or the runs of two files with the same
bytes, are compared like any others. The lines of a later input above its first banner join the
last run of the input before, so two files without a banner make one run; the parts of such a
run that text captures read as runs of their own are compared too, as the last of the copy
checks of the kept rows says. Nothing but a copy is refused: runs that time other
cases, a `unit=` line in one run only, a side that one run names and another does not, and a
case id that ends like the mark a run adds are not refused for that reason.

Three checks run, in this order, and the first refusal is the answer:

| Check (`detail["check"]`) | Text code | What it found |
|---|---|---|
| `identical_written_rows` | `E_POOL_IDENTICAL_ROWS` | two runs whose rows as written are equal |
| `written_stretch` | `E_POOL_TRUNCATED_COPY` | a run whose rows as written are a stretch of another run's, its last row whole or torn |
| `identical_rows`, `truncated_copy` | `E_POOL_IDENTICAL_ROWS`, `E_POOL_TRUNCATED_COPY` | the copy checks of [pooling text captures](#pooling-text-captures), over the kept rows of two runs |

The first two compare a run's rows as written. Those are every line of the run, the banner
left out, that splits on tabs into exactly five fields. That covers kept rows, malformed rows,
comments and a line of four tabs alike. Each field has the white space around it removed. The
rows are compared as text, field by field (suite, side, round, case and value), and are numbered
from 0 in this list. A run with no such line is left out of these two checks, but it still has
its index, because every banner counts.

- **Identical written rows.** The runs are scanned in index order. A run whose rows repeat an
  earlier run's is paired with the earliest run that holds them. `runs` gives the two run
  indices, the earlier first, and `rows` gives their row count. In the runs `X`, a cut-short
  `X`, `X`, the answer is runs 0 and 2. In the runs (banner only), `X`, `X`, it is runs 1
  and 2.
- **Written stretch.** A run S, the copy, is a stretch of another run L, the original, with
  no more rows than L, when for some row p of L every row of S but its last equals L's rows
  from p on, and L has a row where the last row of S falls. A copy of one row must equal L's
  row p. The last row is torn when it differs from that row of L in any field, and whole when
  it equals it. A whole stretch as long as L counts as identical written rows instead. L is
  scanned in run order, then S, then p from 0 up, and each pair of runs is reported once, at
  its first match. The detail gives `copy_run` and `original_run`, `copy_rows` and
  `original_rows`, `start_row` (p), `last_row` (where the copy's last row sits in L), `torn`,
  and `rows_matched` (the rows before the last). A malformed five-field row above the stretch
  counts, so it moves every row index by one.
- **The copy checks of the kept rows** compare each pair of runs that kept rows, in index
  order, in two or three orders of their rows, each with and then without the rows whose value is not
  finite, before the next pair. Rows are compared by side, case, value and where each round begins, as for text
  captures. So runs that differ only in suite, a copy with its rounds relabelled, and a copy
  with a value written another way (`100` and `1e2`) are refused. Two NaN values compare equal
  here, however each is written (`nan`, `NaN`, `-nan`), so a copy that holds a NaN row is
  refused like any other. A pair's rows are taken first in the order of the text, then in the
  order the rows ran, as the run's pass-order and `sides=` lines in this mode give it: by round,
  then by the position a pass-order line gives the side in that round, then by the side's place
  in the run's lineup (the sides of its `sides=` line, then the other sides in the order its rows
  first name them, each twin right after its side). That second order takes every line this
  mode reads as metadata, and reads its key and the text after its `=` with the white space
  around them removed. So a line with a tab at either end counts there as the same line without
  the tab: such a `pass_order=` line gives the positions the line without the tab gives, as it
  orders the read's rows, and such a `sides=` or `twin=` line gives the places in the lineup that
  the line without the tab gives. A line with spaces around its key, ` pass_order = new old` or
  `pass_order =new old`, gives positions there too, as it does in a text capture, though it sets
  no order on the read's rows. Then, where they differ for a run of the pair, the rows are
  taken in that order as the run's lines without a tab give it, and in the order a text capture
  of each run holds them: the same order, from the lines a text capture of the run reads. Those
  are the lines below the run's banner up to the end of the input it stands in, so a line with a
  tab at either end, which the text reader takes for a malformed row, counts for nothing there,
  and neither does a line above the first banner of an input, which the text reader drops, nor
  a row there. Where every kept row of a run stands in one part of it that text captures read as
  a run of its own (below), the lines are those of that part instead, as for the rows of a
  file without a banner, or of a file that begins with a byte-order mark and a banner, after a
  file that holds a banner and metadata only, or the rows above a banner followed by metadata
  only. A copy under a line with a tab at either end can be refused here where text
  captures of its runs pool, as a copy that swaps the rows of each round under such a
  pass-order or `sides=` line is. A copy whose
  rows are written in another order is refused too, as long as a pass-order or `sides=` line,
  read in one of these ways, fixes the order of its sides: without one, a copy that swaps the
  two rows of each round names its sides in another order, so its lineup differs, and it pools,
  as such a copy does when read as text captures. The default order gives no position, and
  neither does a round whose pass-order lines give a side two positions. A pass-order line above the first banner gives
  none to the rows below that banner. Then the rows of the pair are compared again with every
  row whose value is not finite left out: in the order of the text, in the order they ran by
  this mode's lines and by its lines without a tab, and in the order a text capture holds the
  rest, once as the strict text reader holds them, which reads such a row as malformed, so that
  it names no side in the lineup and gives no position, and once as the lenient one holds them,
  which orders its rows with such a row and then leaves it out. So a copy that differs from its
  original only by a `nan` or `inf` row more, wherever it sits, or by such a row in place of the
  first or last row a text capture holds, is refused as it is when the runs are read as text
  captures. A copy that holds such a row in place of a row in between pools, as it does when
  the runs are read as text captures. An order is compared only where its rows differ, for a
  run of the pair, from those of an order compared before. A pair is listed once,
  at the first comparison that finds a copy, so the first refusal of these checks names the
  first pair, in index order, that is a copy in any of them, as pooling text captures does.
  `runs` gives the two run indices. A run that kept no row is left out, and so is a run left
  without a row when the rows that are not finite are left out, from those last comparisons.
  Then the parts of one run that text captures read as runs of their own are compared, in the
  same orders. The text reader reads each file on its own and opens a run at each banner, so
  the kept rows of a run fall into a part per input they stand in and, in the input that holds
  the run's banner, a part above the banner and one below it. That covers a first input
  without a banner and the inputs after it up to the first banner, a later input's lines above
  its first banner and the run before them, the rows above the first banner and those below
  it, and a file that begins with a byte-order mark and a banner: this mode reads that line as
  a malformed row (reading rule 9), so the file joins the run before it, and a copy saved with
  a mark is refused as a part of that run. The parts are taken in the order of the text, a run
  of one part as itself, and each pair of which one is a part of a run of several is compared,
  but for a pair of two runs that the copy checks of the runs refused before. The detail of
  such a refusal gives `runs`, the run of each part, and `lines`, the line on which each part
  begins: the first line of its input, or its run's banner. A metadata line that begins an
  input counts in the order a text capture of its part holds without a byte-order mark before
  its key, as the text reader takes the mark off a file.
  So a copy that is refused when its runs are read as text captures is refused here too, with
  three exceptions. A copy that text captures find only with the rows whose value is zero or
  less, `0` and `0.0` say, as rows or by the sides and positions they give, pools: this mode
  reads such a row as malformed, and the text reader keeps it. Two runs without a row a text
  capture keeps, such as runs that hold only a banner and metadata or only malformed rows, or,
  for a lenient text capture, only rows whose value is not finite, can pool: text captures of
  them hold no observation and are refused as identical, and this mode leaves a run without a
  kept row, or without one whose value is finite, out of those comparisons; no row is pooled
  twice. And a run of a text capture that a line this mode alone takes for a banner, such as
  `## hostX`, splits in two is not compared as one run.

`check_matching_pool` lists every refusal of the three checks, in that order, so one pair of
runs can appear under more than one check. An empty list says the runs pool.

## What the results record of the command

The results record the command that was run, for the "how to reproduce" line of the reports.
In it, side specs are hidden unless `report.include_image_refs` is on, which shows the spec of
an image or serving side. With `report.include_image_refs` on, the results show image
references as typed, local archive paths included (`new=image:oci-archive:/made/up/new.tar`
stays whole). Other absolute paths, including those that start with `~/`, `~user/` or `//`,
the path of a `file://` address with what stands before it
(`file://localhost/a/m.gguf` shows `file://m.gguf`) and the path of any other address whose
host is empty (`sqlite:////a/db.sqlite` shows `sqlite:///db.sqlite`), are cut to their last
part, also when glued to an option (`-I/a/include` shows `-Iinclude`) or written after a
redirection (`<in.txt>/a/out` shows `<in.txt>out`), while the `/` after the arguments of a name
such as `BM_made_up<A, int>/8` is kept. A relative path that climbs out of its folder with `..`
is cut the same way (`../../a/in.csv` shows `in.csv`). A `file://` address with a host and no
path loses the host (`file://made-up-host` shows `file://<hidden>`). Secrets are replaced by `<hidden>` in the forms that
[what the shared files hide](config.md#what-the-shared-files-hide) lists, from credential-like
names and headers to the password options of benchmark clients and long random-looking
values. These rules also hold inside one argument that holds several words, such as the text
after `sh -c`, and inside a quoted word of it:
`sh -c 'tool --token VALUE -I/a/include'` shows `sh -c 'tool --token <hidden> -Iinclude'`.
A short plain value that nothing on that list names, such as one given after an option of one
letter (`-k VALUE`), as a plain argument or in the path of an address
(`https://made-up.example/v1/VALUE` shows `https://<hidden>/v1/VALUE`), cannot be told apart
from an ordinary value and is shown; give a secret to a side through the environment with
`env_pass` instead.

## From Python

`pairbench.capture.text.project(capture, a, b)` returns a two-sided view of a many-sided run:
only rounds whose recorded order names both sides are kept, and the relative order of the two
is preserved. The view keeps the `value_not_finite` notes of its two sides in the rounds it
keeps, each named by the view's capture id and numbered as the view numbers the round. It reads
each cell from its note, so a capture read back from `capture.jsonl` gives the same view notes
as the text file it came from; a note of that code which does not read as a cell, such as one
written by hand, stays in the view word for word, with the capture id of the run it names.

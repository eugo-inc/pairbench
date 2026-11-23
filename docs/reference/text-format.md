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
part of the capture's records, so a capture written to `capture.jsonl` and read again keeps
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

## Round numbers are labels

Round numbers are labels used for pairing: any integer is valid, 0 included, and they need not
start at 1. Within a run, the rounds from any start are numbered 1, 2, 3 and on in the order of
their labels, which keeps the order and the pairing. Rounds labelled 3 to 18 are analysed as
rounds 1 to 16 are. A number that no row of the run holds is no round. A refusal names a round
by the label the file gave it: when label 9 lacks a side, `E_GRID` says `missing 9 old`.

## Pooling text captures

Each run of a file is one capture. Several runs, or several files, can be pooled with
`pairbench compare`. A capture whose rows are a contiguous stretch of another's is refused with
`E_POOL_TRUNCATED_COPY`, and so is a torn copy: one whose last row has the round, side and case
of the row that follows the stretch, with another value. Rows are compared by side, case, value
and where each round begins, not by round number, so relabelling the rounds of a copy does not
hide it.

Without a `sides=` line, the last side a run's rows name first is its baseline, so two files
of one experiment can name different baselines when their first rounds started with different
sides. They still pool: sides are matched by name, kind, twin relation and fingerprint, and the
baseline is set once for the pool, by `--baseline NAME` or else as the baseline of the first
capture given, with a `pool_baseline` note when the captures disagree.

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

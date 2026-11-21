# Contributing to pairbench

Thank you for helping. Pull requests are welcome from anyone. This file says how to propose
a change, what a pull request needs, and what the repository may hold.

## Before you start

A small fix can go straight to a pull request. For a larger change, open an issue first and
describe it: a short discussion saves work on both sides, above all for a new driver, a new
kind of side or anything that touches the statistics.

## Setting up

```
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[plot,mcp]" pytest jsonschema ruff mypy build hatchling
pytest tests/unit tests/mutants
ruff check .
ruff format --check .
mypy src
python3 tools/docs_site.py build # the documentation site: needs Node.js 22.23.4 or newer
pairbench fill docs/readme/README.in.md --results docs/figures/launch-cost/results.json -o README.md --check
```

These are the checks a pull request must pass. The site build needs Node.js (see
Documentation below); run it when your change touches `docs/`, `site/` or the README.

Python 3.11 is the oldest version supported. The core imports only the standard library;
an extra is imported only inside the function that needs it.

## Documentation

The pages are Markdown files under `docs/`, readable as they are. Each page opens with front
matter that holds a `description` of one line, then the title, then a direct answer of one or
two sentences. `site/navigation.json` lists every page in the order of the site's sidebar.
The site is built with Starlight; building it needs Node.js 22.23.4 or newer, the version the
pinned Astro asks for, and nothing else in the repository does:

```
python3 tools/docs_site.py build    # checks the pages, runs npm ci in site/, builds site/dist
python3 tools/docs_site.py llms     # writes llms.txt from the navigation and descriptions
python3 tools/api_reference.py      # writes docs/reference/python-names.md from the code
python3 tools/share_image.py        # draws site/public/share.png, the image of a shared page
```

The build checks in three steps:

1. Before it removes, writes or installs anything: the pages and their front matter, the
   pages generated from the code, the version, the share image in `site/public/`, that each
   link written `[text](target)` or as a reference link names a page of the site or a file of
   the repository, and that each anchor such a link names is one the text gives. That is the
   id of a heading, an id written in the page, or the anchor of a config key or flag, on a
   page of the site or in a Markdown file of the repository, and a line, `#L<n>`, or a range
   of lines, `#L<a>-L<b>`, of any other file of the repository. A link to a file of the
   repository by its address on the forge, the `Source` address of `pyproject.toml` followed
   by `/blob/main/` or `/tree/main/`, must name a file or folder the repository has, and its
   anchor is checked the same way; so must such an address written as an autolink,
   `<address>`, or bare. In a git checkout the repository has the files git tracks
   and the folders that hold them, so a link to a file a build leaves, such as one in
   `site/dist/`, is refused.
2. After `npm ci`, while Astro builds: a warning or an error in Astro's output.
3. On the built site: every link, anchor and asset, the anchors Starlight adds and a link
   written in HTML among them; the share image it publishes; and that nothing is fetched from
   another host. A link to another host is not followed.

The first step reads, and turns into an address of the site, a link in each of these forms:

- `[text](target)`, `[text](target "title")`, `[text](target 'title')`,
  `[text](target (title))` and `[text](<target>)`;
- a reference link, `[text][label]`, `[label][]` or `[label]`, through its definition
  `[label]: target`, which starts its own line (after at most three spaces) and holds the
  target on that line; a title may follow the target.

It leaves three forms as they are: a definition whose target is on the next line, a bare
target that holds a space or a parenthesis, and a link written in HTML. Step 3 checks them on the
built site, where such a link to a page of `docs/` is a link to nothing; write them in a
form above.

A share image, in `site/public/` or in the built site, that differs from what
`tools/share_image.py` draws fails the build; the message names how it differs, such as an
extra chunk or another row filter.

## What the repository may hold

Everything here is public. A change is accepted only if it keeps it that way.

1. Fixtures are synthetic, or come from a real run of a public tool on a public image. Every
   fixture has a `*.provenance.json` sidecar written by a generator under
   `tests/fixtures/_gen/`. Machine values in fixtures are visibly made up, such as `host-a`.
2. No credentials, host names, account ids, internal addresses, or results that identify a
   machine. A results document holds no host name, user name or value of the environment,
   except an image reference you ask for and the forms that
   [SECURITY.md](SECURITY.md#known-limits-of-the-shown-command) lists as known limits of the shown command,
   and tests check that.
3. Every new source file starts with the licence header:

   ```
   # SPDX-License-Identifier: Apache-2.0
   # Copyright (c) 2026, Eugo, Inc.
   ```

4. A showcase uses public images only, each pinned by digest in its `sides.lock`.
5. A new driver needs a link to the public documentation of the tool it reads, with the
   version read, a fixture with its sidecar, and a test that reads the fixture.
6. No bundled proprietary tools. A third-party program is invoked as an external program and
   listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
7. No diagnostics document, flame graph or report page of a real run. They hold names from
   the code that was measured. The one exception is a showcase whose sides are all public
   images and whose result has been approved by the maintainers.
8. A results file is kept only with a `hash_inputs.json` that passed the check beside it,
   except the launch-cost results in `docs/figures/launch-cost/`.
   `tools/hash_inputs.py RUN_FOLDER --publish FOLDER` copies `results.json`, `results.md` and
   `report.html` into the folder, and the sidecar with them only when the shared files show
   every value the sidecar holds; otherwise the sidecar stays owner-only in the run folder and
   is not published. `tools/launch_cost.py` and a showcase's `run.sh` under
   `PAIRBENCH_SHOWCASE_PUBLISH` run from neutral places (the checkout reached at `/work`,
   `HOME=/home/user`, an interpreter named by a public path) into a private folder under
   `pairbench-runs/`, then publish this way. A run whose sides' commands the results hide, as
   each `--side` spec is, keeps its sidecar private, so its published files are not kept in
   this repository, with that one exception: the launch-cost results are kept without their
   sidecar because the results hide the two side commands; the commands are the constants of
   `tools/launch_cost.py`, so a reader runs that script to repeat the run rather than
   recomputing the hashes. That folder keeps only `results.json` and `machine-class.txt`, and
   a test holds its `results.json` to showing each side as `KIND:<hidden>`. A test recomputes
   the five published hashes of every other kept results file from its sidecar, and holds
   each `machine-class.txt` to the public forms `tools/launch_cost.py`
   accepts.
9. No measured performance number in prose. A number in a document is a mathematical
   known answer, a made-up example that says so, a share from the simulated experiments
   that `tools/error_rates.py` writes, or a figure filled in from a results file by
   `pairbench fill`.

## Changing the statistics

The defaults of the verdict rule are part of what a result means. A change to them, to the
schedule or to the sign test needs an issue, a reason grounded in the method pages, and
tests whose expected values are written as constants. A fix lands with a test that fails
without it.

## Changing a file format

The capture, results, config and diagnostics documents each have a JSON Schema
(`pairbench schema NAME`). Within a schema version you may add an optional field, or a value
to a field whose schema lists its values, such as a new `reason`; renaming or removing a field
or a value, or changing its meaning, needs a new schema version. Each schema refuses a field
it does not list, so a document written by a later release fails the schema of an earlier one
that lacks the field.

## Commits and pull requests

A pull request needs:

1. Tests. A fix lands with a test that fails without it. Tests assert the exact exit code and
   text code, the stream a message goes to, and expected values written as constants. A test
   that needs an external program, a container engine or a GPU skips visibly and says what it
   needs.
2. The checks under Setting up, passing.
3. The style the checks enforce: `ruff` for lint and format, `mypy` for types, Python 3.11
   syntax, the licence header on new source files.
4. Public documentation updated in the same pull request when the change alters what a user
   sees. `README.md` and `llms.txt` are generated: edit their sources and regenerate them.

Use conventional commit subjects, such as `fix(stats): ...` or `docs(guides): ...`. Keep a
pull request to one change, and say in it how you tested it. There is no rule either way on
crediting the tools that helped write a change, AI assistants included: add a credit line or
leave it out.

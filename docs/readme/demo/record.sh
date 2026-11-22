#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
# Record the README's terminal recording and draw its chart, from made-up values.
#
#   bash docs/readme/demo/record.sh
#
# Needs pairbench with the plot extra on PATH, asciinema 2 (pip install asciinema) and agg
# (https://github.com/asciinema/agg). It plays tape.sh in a scratch folder under asciinema,
# renders the recording with agg into docs/readme/demo.gif, and draws the verdict chart of that
# run into docs/readme/chart-light.svg and chart-dark.svg with chart_pair.py. The values are
# made up by made_up_bench.py, and tape.sh switches off the machine checks, so nothing in the
# recording depends on the machine that records it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readme="$(dirname "$here")"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cp "$here/made_up_bench.py" "$work/"
chmod +x "$work/made_up_bench.py"
cd "$work"

# A dark terminal of 112 columns and 24 rows, in the palette of the documentation site.
COLUMNS=112 LINES=24 asciinema rec --quiet --overwrite --idle-time-limit 2.5 \
  --cols 112 --rows 24 --command "bash $here/tape.sh" "$work/demo.cast"
agg --font-size 15 --line-height 1.3 --fps-cap 20 --idle-time-limit 2.5 --last-frame-duration 4 \
  --theme 080d17,f2f3f8,1b2233,ff6b81,22c7e0,f5c451,7c9cff,a142ff,22c7e0,f2f3f8,5b6478,ff8da1,5ee0f0,ffd479,9db4ff,c07bff,5ee0f0,ffffff \
  "$work/demo.cast" "$readme/demo.gif"

python3 "$here/chart_pair.py" "$work"/pairbench-runs/*/charts/verdict.svg "$readme"

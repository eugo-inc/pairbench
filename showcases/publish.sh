# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
#
# Read by each showcase's run.sh, from the showcase's folder, before it runs anything.
#
# It gives run_pairbench PART [options of pairbench run]. A normal run is
# "pairbench run" with the options. With PAIRBENCH_SHOWCASE_PUBLISH set to a
# folder inside the showcase, the run is one whose results may be kept: the
# checkout must be reached at /work, the run sees HOME=/home/user, and it writes
# into a new folder under pairbench-runs/, which the repository ignores, so that
# its capture and the rest of its folder stay private. tools/hash_inputs.py then
# writes hash_inputs.json there and copies results.json, results.md and
# report.html into the published folder (into PART under it, when the showcase
# runs more than once), and hash_inputs.json with them only when the shared
# files show each value the sidecar holds; otherwise the sidecar stays
# owner-only in the private folder and one line on standard error says so. The
# exit code is that of tools/hash_inputs.py when it refuses, and otherwise that
# of the run.
# A run is normal only when the variable is unset: an empty value, or one that
# names the showcase folder itself, such as "." or "./.", is refused.

publish=
if [ -n "${PAIRBENCH_SHOWCASE_PUBLISH+set}" ]; then
  publish=$PAIRBENCH_SHOWCASE_PUBLISH
  case "$here" in
    /work/showcases/*) ;;
    *)
      echo "PAIRBENCH_SHOWCASE_PUBLISH: reach this checkout at /work, so that the hashes of" \
        "the run name no folder of this machine" >&2
      exit 2
      ;;
  esac
  # What is left once each leading "." part is read: nothing when the value names the
  # showcase folder itself.
  publish_inside=$publish
  while :; do
    case "$publish_inside" in
      ./*) publish_inside=${publish_inside#./} ;;
      /*) publish_inside=${publish_inside#/} ;;
      .) publish_inside= ;;
      *) break ;;
    esac
  done
  case "/$publish/" in
    //* | */../*) publish_inside= ;;
  esac
  if [ -z "$publish_inside" ]; then
    echo "PAIRBENCH_SHOWCASE_PUBLISH: name a folder inside the showcase by a relative path," \
      "not an absolute one, and without '..'" >&2
    exit 2
  fi
  publish_runs=pairbench-runs/publish-$(date -u +%Y%m%dT%H%M%SZ)-$$
fi

run_pairbench() {
  publish_part=$1
  shift
  if [ -z "$publish" ]; then
    pairbench run "$@"
    return
  fi
  publish_out=$publish${publish_part:+/$publish_part}
  publish_run=$publish_runs/$publish_out
  publish_code=0
  HOME=/home/user pairbench run "$@" --out "$publish_run" || publish_code=$?
  if [ -f "$publish_run/results.json" ]; then
    PYTHONPATH=../../src python3 ../../tools/hash_inputs.py "$publish_run" \
      --publish "$publish_out" || return
  fi
  return "$publish_code"
}

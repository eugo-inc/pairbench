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
# A run is normal only when the variable is unset. Each of these values is
# refused with exit 2 and its own line on standard error, before anything runs:
# an empty value; one that names the showcase folder itself, such as "." or
# "./."; an absolute path or one with ".."; one with a part made only of blanks
# or only of dots, or a part that starts with "-"; and pairbench-runs or a
# folder under it, which holds the private run folders. A value that reaches,
# through a link, the showcase folder, a folder that holds it, or pairbench-runs
# or a folder under it is refused the same way, as is one with a part that is a
# link leading to no folder: the published folder would then hold the private
# run folders, or, once the run makes pairbench-runs, could.

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
  if [ -z "$publish" ]; then
    echo "PAIRBENCH_SHOWCASE_PUBLISH: the value is empty; unset it for a normal run, or name" \
      "a folder inside the showcase to publish into" >&2
    exit 2
  fi
  case "/$publish/" in
    //* | */../*)
      echo "PAIRBENCH_SHOWCASE_PUBLISH: name a folder inside the showcase by a relative path," \
        "not an absolute one, and without '..'" >&2
      exit 2
      ;;
  esac
  # Read the value part by part: an empty part and a "." part name no folder, and each
  # other part is the name of one.
  publish_rest=$publish/
  publish_named=
  while [ -n "$publish_rest" ]; do
    publish_word=${publish_rest%%/*}
    publish_rest=${publish_rest#*/}
    case "$publish_word" in
      "" | .) continue ;;
    esac
    publish_refused=
    case "$publish_word" in
      *[![:space:]]*) ;;
      *) publish_refused="a part of the folder is made only of blanks; give each part a name" ;;
    esac
    case "$publish_word" in
      *[!.]*) ;;
      *) publish_refused="a part of the folder is made only of dots; give each part a name" ;;
    esac
    case "$publish_word" in
      -*)
        publish_refused="a part of the folder starts with '-', which a command reads as an"
        publish_refused="$publish_refused option; give it another name"
        ;;
    esac
    if [ -z "$publish_named" ] && [ "$publish_word" = pairbench-runs ]; then
      publish_refused="pairbench-runs holds the private run folders; name a folder outside it"
    fi
    if [ -n "$publish_refused" ]; then
      echo "PAIRBENCH_SHOWCASE_PUBLISH: $publish_refused" >&2
      exit 2
    fi
    publish_named=$publish_word
  done
  if [ -z "$publish_named" ]; then
    echo "PAIRBENCH_SHOWCASE_PUBLISH: the value names the showcase folder itself; name a" \
      "folder inside it to publish into" >&2
    exit 2
  fi
  # Follow the links of the parts that exist, from the showcase as the system finds it; the
  # parts from the first one that does not exist on are taken as they are written.
  publish_showcase=$(pwd -P)
  publish_at=$publish_showcase
  publish_rest=$publish/
  publish_refused=
  while [ -n "$publish_rest" ]; do
    publish_word=${publish_rest%%/*}
    publish_rest=${publish_rest#*/}
    case "$publish_word" in
      "" | .) continue ;;
    esac
    if [ -d "$publish_at/$publish_word" ]; then
      publish_at=$(cd -P "$publish_at/$publish_word" && pwd -P) ||
        publish_at=$publish_at/$publish_word
    elif [ -h "$publish_at/$publish_word" ]; then
      publish_refused="a part of the folder is a link that leads to no folder; name a folder,"
      publish_refused="$publish_refused or a link to one"
      break
    else
      publish_at=$publish_at/$publish_word/$publish_rest
      publish_at=${publish_at%/}
      break
    fi
  done
  if [ -z "$publish_refused" ] && [ "$publish_at" = "$publish_showcase" ]; then
    publish_refused="the value names the showcase folder itself through a link; name a folder"
    publish_refused="$publish_refused inside it to publish into"
  fi
  if [ -z "$publish_refused" ]; then
    case "$publish_showcase/" in
      "${publish_at%/}"/*)
        publish_refused="the value names, through a link, a folder that holds the showcase and"
        publish_refused="$publish_refused so its private run folders; name a folder inside the"
        publish_refused="$publish_refused showcase to publish into"
        ;;
    esac
    case "$publish_at/" in
      "$publish_showcase/pairbench-runs/"*)
        publish_refused="the value names pairbench-runs or a folder under it through a link,"
        publish_refused="$publish_refused and pairbench-runs holds the private run folders;"
        publish_refused="$publish_refused name a folder outside it"
        ;;
    esac
  fi
  if [ -n "$publish_refused" ]; then
    echo "PAIRBENCH_SHOWCASE_PUBLISH: $publish_refused" >&2
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

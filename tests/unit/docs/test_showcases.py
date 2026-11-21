# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Each showcase is complete, pinned by digest, and publishes no result yet.

Nothing here runs a showcase: the tests read its files and load its config.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from pairbench.config import load_experiment

SHOWCASES = (
    "numpy-pip-vs-conda",
    "noisy-neighbour",
    "pipeline-slowdown-check",
    "python-versions",
    "inference-server-versions",
    "gpu-kernel",
    "vendor-container-vs-pip",
)
REQUIRED = ("README.md", "pairbench.toml", "run.sh", "sides.lock")
# The workload files of each showcase, which honour the work factor.
WORKLOADS = {
    "numpy-pip-vs-conda": ("bench.py",),
    "noisy-neighbour": ("spin.py",),
    "pipeline-slowdown-check": ("tests/test_examplelib.py",),
    "python-versions": ("bench.py",),
    "gpu-kernel": ("kernel_bench.cu",),
    "vendor-container-vs-pip": ("bench.py",),
}
WORK_FACTOR = "PAIRBENCH_WORK_FACTOR"
NO_RESULT = "No approved result exists yet."
LICENCE_HEADER = (
    "# SPDX-License-Identifier: Apache-2.0",
    "# Copyright (c) 2026, Eugo, Inc.",
)
# The helper every run.sh reads, the variable that asks it to publish, and its refusals.
PUBLISH_HELPER = ". ../publish.sh"
PUBLISH_VARIABLE = "PAIRBENCH_SHOWCASE_PUBLISH"
NEUTRAL_SHOWCASES = "/work/showcases/"
EXIT_USAGE = 2
OUTSIDE_WORK = (
    "PAIRBENCH_SHOWCASE_PUBLISH: reach this checkout at /work, so that the hashes of the run "
    "name no folder of this machine\n"
)
OUTSIDE_SHOWCASE = (
    "PAIRBENCH_SHOWCASE_PUBLISH: name a folder inside the showcase by a relative path, not an "
    "absolute one, and without '..'\n"
)
ENVIRONMENT = "docs/reference/environment.md"
PUBLISH_REFUSED_WHOLE = (
    "A normal run when unset; an empty value, or one that names the showcase folder itself such "
    "as `.` or `./.`, is refused like a folder outside the showcase."
)
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
PINNED_IMAGE = re.compile(r"^(?P<ref>[^@\s]+:[^@\s]+)@(?P<digest>sha256:[0-9a-f]{64})$")
# The operations of showcase 1, as recorded from the public page, and its address, which the
# README names once: in the sentence that says where the names of the operations come from.
# Each row of the table holds the case and the operation, between three bars.
NUMPY_PAGE = "https://eugo.io/benchmarks"
NUMPY_CREDIT = "The operations are the kinds named on the NumPy board of the public page"
NUMPY_TABLE_BARS = 3
NUMPY_OPERATIONS = (
    "Real FFT, 2M points",
    "Cholesky factorization, 1024 x 1024",
    "arcsinh, elementwise",
    "axpy, a memory-bound vector update",
    "2D FFT, 1024 x 1024",
    "sqrt, multiply, add: a chained elementwise expression",
    "exp, elementwise",
    "Matrix multiplication, 512 x 512",
)


def folder(repo_root: Path, name: str) -> Path:
    return repo_root / "showcases" / name


def images_of(config: dict[str, object]) -> dict[str, str]:
    """The image reference of each side of a config, a server's image included."""
    found: dict[str, str] = {}
    sides = config.get("sides")
    assert isinstance(sides, dict)
    for name, side in sides.items():
        assert isinstance(side, dict)
        serve = side.get("serve")
        image = serve.get("image") if isinstance(serve, dict) else side.get("image")
        if isinstance(image, str):
            found[name] = image
    return found


def short(reference: str) -> str:
    """A reference without the default registry and library prefix."""
    for prefix in ("docker.io/library/", "docker.io/"):
        if reference.startswith(prefix):
            return reference[len(prefix) :]
    return reference


def test_there_are_seven_showcases_and_an_index(repo_root: Path) -> None:
    base = repo_root / "showcases"
    found = sorted(path.name for path in base.iterdir() if path.is_dir())

    assert found == sorted(SHOWCASES)
    index = (base / "README.md").read_text(encoding="utf-8")
    assert [name for name in SHOWCASES if f"({name}/README.md)" not in index] == []


@pytest.mark.parametrize("name", SHOWCASES)
def test_a_showcase_has_every_file(repo_root: Path, name: str) -> None:
    base = folder(repo_root, name)

    assert [item for item in REQUIRED if not (base / item).is_file()] == []
    assert (base / "expected").is_dir()


@pytest.mark.parametrize("name", SHOWCASES)
def test_expected_holds_one_line_saying_no_result_is_approved(repo_root: Path, name: str) -> None:
    files = sorted((folder(repo_root, name) / "expected").iterdir())

    assert [path.name for path in files] == ["README.md"]
    assert files[0].read_text(encoding="utf-8") == NO_RESULT + "\n"


@pytest.mark.parametrize("name", SHOWCASES)
def test_run_sh_is_one_executable_script_with_the_licence_header(
    repo_root: Path, name: str
) -> None:
    script = folder(repo_root, name) / "run.sh"
    lines = script.read_text(encoding="utf-8").splitlines()

    assert lines[0] == "#!/bin/sh"
    assert tuple(lines[1:3]) == LICENCE_HEADER
    assert os.access(script, os.X_OK)
    assert "run_pairbench " in "\n".join(lines)
    assert "--config pairbench.toml" in "\n".join(lines)


@pytest.mark.parametrize("name", SHOWCASES)
def test_run_sh_reads_the_publish_helper_before_it_runs_anything(
    repo_root: Path, name: str
) -> None:
    lines = [
        line.strip()
        for line in (folder(repo_root, name) / "run.sh").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    helper = lines.index(PUBLISH_HELPER)
    runs = [i for i, line in enumerate(lines) if "$engine" in line or "run_pairbench" in line]

    assert lines[helper - 1] == 'cd "$here"'
    assert runs
    assert min(runs) > helper
    assert [line for line in lines if re.search(r"(?<![\w-])pairbench run\b", line)] == []


def stubs(base: Path, names: tuple[str, ...]) -> tuple[Path, Path]:
    """Programs that write their arguments to a log, and the log."""
    folder = base / "bin"
    folder.mkdir()
    log = base / "calls.log"
    for name in names:
        stub = folder / name
        stub.write_text(f'#!/bin/sh\necho "{name} $*" >>"{log}"\n', encoding="utf-8")
        stub.chmod(0o755)
    return folder, log


@pytest.mark.parametrize("name", SHOWCASES)
def test_publishing_from_a_folder_outside_work_is_refused_before_anything_runs(
    repo_root: Path, tmp_path: Path, name: str
) -> None:
    copy = tmp_path / "showcases"
    shutil.copytree(folder(repo_root, name), copy / name)
    shutil.copy(repo_root / "showcases" / "publish.sh", copy / "publish.sh")
    script = copy / name / "run.sh"
    if str(script.parent).startswith(NEUTRAL_SHOWCASES):
        pytest.skip("needs a temporary folder that is not under /work")
    bin_folder, log = stubs(tmp_path, ("pairbench", "docker", "python3"))
    env = {**os.environ, "PATH": f"{bin_folder}:{os.environ.get('PATH', '')}"}
    env[PUBLISH_VARIABLE] = "published"

    done = subprocess.run(
        ["sh", str(script)], capture_output=True, text=True, env=env, check=False, timeout=60
    )

    assert done.returncode == EXIT_USAGE
    assert done.stdout == ""
    assert done.stderr == OUTSIDE_WORK
    assert not log.exists()
    assert not (script.parent / "published").exists()


HELPER_STUB = """#!/bin/sh
echo "pairbench HOME=$HOME $*" >>"{log}"
while [ "$#" -gt 1 ]; do
  if [ "$1" = --out ]; then out=$2; fi
  shift
done
if [ -n "${{out:-}}" ]; then mkdir -p "$out" && echo "{{}}" >"$out/results.json"; fi
exit {code}
"""
PYTHON_STUB = """#!/bin/sh
echo "python3 PYTHONPATH=$PYTHONPATH $*" >>"{log}"
exit {code}
"""
# The private folder a publish runs into: a new one under pairbench-runs/ for each call.
PRIVATE_RUNS = r"pairbench-runs/publish-[0-9]{8}T[0-9]{6}Z-[0-9]+"
# The codes tools/hash_inputs.py refuses a publish with: a hash its rebuilt value does not give,
# and a missing or unreadable file.
WRITER_REFUSALS = (1, 2)


def publish(
    repo_root: Path,
    tmp_path: Path,
    folder_name: str | None,
    part: str,
    code: int = 0,
    writer_code: int = 0,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the publish helper as run.sh reads it, with the showcase reached under /work.

    ``code`` is the exit code of the run, and ``writer_code`` that of tools/hash_inputs.py.
    """
    showcase = tmp_path / "checkout" / "showcases" / "made-up"
    showcase.mkdir(parents=True)
    bin_folder = tmp_path / "bin"
    bin_folder.mkdir()
    log = tmp_path / "calls.log"
    (bin_folder / "pairbench").write_text(HELPER_STUB.format(log=log, code=code), encoding="utf-8")
    (bin_folder / "python3").write_text(
        PYTHON_STUB.format(log=log, code=writer_code), encoding="utf-8"
    )
    for stub in bin_folder.iterdir():
        stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_folder}:{os.environ.get('PATH', '')}", "HOME": "/x"}
    env.pop(PUBLISH_VARIABLE, None)
    if folder_name is not None:
        env[PUBLISH_VARIABLE] = folder_name
    script = (
        'set -eu; here=/work/showcases/made-up; cd "$1"; . "$2"; '
        'run_pairbench "$3" --config pairbench.toml --made-up'
    )
    done = subprocess.run(
        [
            "sh",
            "-c",
            script,
            "sh",
            str(showcase),
            str(repo_root / "showcases" / "publish.sh"),
            part,
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return done, calls


def published_calls(calls: list[str], folder_name: str) -> str:
    """The private folder both calls of a publish name, after checking the two calls."""
    run, writer = calls
    found = re.fullmatch(
        "pairbench HOME=/home/user run --config pairbench.toml --made-up "
        f"--out ({PRIVATE_RUNS})/{re.escape(folder_name)}",
        run,
    )
    assert found, run
    private = found[1]
    assert writer == (
        f"python3 PYTHONPATH=../../src ../../tools/hash_inputs.py {private}/{folder_name} "
        f"--publish {folder_name}"
    )
    return private


def test_publishing_runs_privately_with_the_neutral_home_and_publishes_through_the_check(
    repo_root: Path, tmp_path: Path
) -> None:
    done, calls = publish(repo_root, tmp_path, "published", "")

    assert (done.returncode, done.stderr) == (0, "")
    private = published_calls(calls, "published")
    showcase = tmp_path / "checkout" / "showcases" / "made-up"
    assert (showcase / private / "published" / "results.json").is_file()
    assert not (showcase / "published").exists()


def test_a_normal_run_is_pairbench_run_with_the_home_as_it_is(
    repo_root: Path, tmp_path: Path
) -> None:
    done, calls = publish(repo_root, tmp_path, None, "quiet")

    assert (done.returncode, done.stderr) == (0, "")
    assert calls == ["pairbench HOME=/x run --config pairbench.toml --made-up"]


def test_a_failed_normal_run_keeps_its_exit_code(repo_root: Path, tmp_path: Path) -> None:
    done, calls = publish(repo_root, tmp_path, None, "", code=1)

    assert done.returncode == 1
    assert calls == ["pairbench HOME=/x run --config pairbench.toml --made-up"]


def test_publishing_a_run_of_several_parts_keeps_each_under_the_folder(
    repo_root: Path, tmp_path: Path
) -> None:
    done, calls = publish(repo_root, tmp_path, "published", "quiet")

    assert (done.returncode, done.stderr) == (0, "")
    published_calls(calls, "published/quiet")


def test_publishing_keeps_the_exit_code_of_a_run_that_wrote_its_results(
    repo_root: Path, tmp_path: Path
) -> None:
    done, calls = publish(repo_root, tmp_path, "published", "", code=1)

    assert done.returncode == 1
    published_calls(calls, "published")


@pytest.mark.parametrize("writer_code", WRITER_REFUSALS)
@pytest.mark.parametrize("code", [0, 1])
def test_a_publish_the_sidecar_writer_refuses_exits_with_the_writer_s_code(
    repo_root: Path, tmp_path: Path, code: int, writer_code: int
) -> None:
    done, calls = publish(repo_root, tmp_path, "published", "", code=code, writer_code=writer_code)

    assert done.returncode == writer_code
    published_calls(calls, "published")


# A value outside the showcase, and one that names the showcase folder itself or nothing.
@pytest.mark.parametrize(
    "given", ["/work/kept", "../kept", "kept/../../x", ".", "./", "./.", "", ".//./"]
)
@pytest.mark.parametrize("part", ["", "quiet"])
def test_publishing_into_a_folder_outside_the_showcase_is_refused(
    repo_root: Path, tmp_path: Path, given: str, part: str
) -> None:
    done, calls = publish(repo_root, tmp_path, given, part)

    assert done.returncode == EXIT_USAGE
    assert done.stdout == ""
    assert done.stderr == OUTSIDE_SHOWCASE
    assert calls == []
    assert (
        sorted(path.name for path in (tmp_path / "checkout" / "showcases" / "made-up").iterdir())
        == []
    )


# A folder whose name starts with a dot is a folder inside the showcase.
@pytest.mark.parametrize("given", ["./kept", ".kept", "./.kept", "kept/."])
def test_publishing_into_a_folder_named_with_dots_inside_the_showcase_runs(
    repo_root: Path, tmp_path: Path, given: str
) -> None:
    done, calls = publish(repo_root, tmp_path, given, "")

    assert (done.returncode, done.stderr) == (0, "")
    published_calls(calls, given)


def test_the_reference_says_an_empty_value_or_the_showcase_folder_is_refused(
    repo_root: Path,
) -> None:
    text = " ".join((repo_root / ENVIRONMENT).read_text(encoding="utf-8").split())

    assert PUBLISH_REFUSED_WHOLE in text


@pytest.mark.parametrize("name", SHOWCASES)
def test_every_image_is_pinned_by_the_digest_of_the_lock(repo_root: Path, name: str) -> None:
    base = folder(repo_root, name)
    config = tomllib.loads((base / "pairbench.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((base / "sides.lock").read_text(encoding="utf-8"))["sides"]
    images = images_of(config)

    assert sorted(images) == sorted(lock)
    for side, reference in images.items():
        pinned = PINNED_IMAGE.match(reference)
        assert pinned, reference
        assert DIGEST.match(lock[side]["digest"])
        assert pinned["digest"] == lock[side]["digest"], side
        assert pinned["ref"] == short(lock[side]["image"]), side


@pytest.mark.parametrize("name", SHOWCASES)
def test_the_config_loads(repo_root: Path, name: str) -> None:
    path = folder(repo_root, name) / "pairbench.toml"
    mounts = 'launch.mounts=["/x:/showcase:ro"]'

    experiment = load_experiment(path, environ={}, sets=[mounts])

    assert len(experiment.sides) == 2
    assert experiment.baseline in {side.name for side in experiment.sides}


@pytest.mark.parametrize("name", sorted(WORKLOADS))
def test_the_workload_honours_the_work_factor(repo_root: Path, name: str) -> None:
    for workload in WORKLOADS[name]:
        text = (folder(repo_root, name) / workload).read_text(encoding="utf-8")
        assert WORK_FACTOR in text, workload


def test_the_serving_workload_is_the_load_tool(repo_root: Path) -> None:
    path = folder(repo_root, "inference-server-versions") / "pairbench.toml"

    experiment = load_experiment(path, environ={})

    assert experiment.driver == "guidellm"
    assert experiment.energy.enabled


def test_the_serving_showcase_says_when_a_budget_fixes_the_round_count(repo_root: Path) -> None:
    import pairbench
    from pairbench.config import flag_config

    showcase = folder(repo_root, "inference-server-versions")
    path = showcase / "pairbench.toml"
    plain = pairbench.plan(load_experiment(path, environ={}))
    budgeted = pairbench.plan(
        load_experiment(path, environ={}, flags=flag_config({"--budget": "2h"}))
    )

    # No launch is timed before the run, so the plan cannot fit a count to the budget.
    assert budgeted.estimate_s is None
    assert budgeted.rounds_planned == plain.rounds_planned
    readme = (showcase / "README.md").read_text(encoding="utf-8")
    (bullet,) = [item for item in readme.split("\n- ") if "`--budget`" in item]
    assert "smallest count" in bullet
    assert "after warm-up" in bullet


def test_the_numpy_showcase_names_each_operation_and_the_page_once(repo_root: Path) -> None:
    text = (folder(repo_root, "numpy-pip-vs-conda") / "README.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| `")]
    paragraphs = [" ".join(part.split()) for part in text.split("\n\n")]

    for operation in NUMPY_OPERATIONS:
        (row,) = [line for line in rows if f"| {operation} |" in line]
        assert row.count("|") == NUMPY_TABLE_BARS
    assert text.count(NUMPY_PAGE) == 1
    (credit,) = [part for part in paragraphs if NUMPY_PAGE in part]
    assert credit.startswith(NUMPY_CREDIT)


def test_the_pipeline_showcase_has_two_revisions_and_a_workflow(repo_root: Path) -> None:
    base = folder(repo_root, "pipeline-slowdown-check")
    config = tomllib.loads((base / "pairbench.toml").read_text(encoding="utf-8"))

    assert (base / "revisions/a/examplelib/__init__.py").is_file()
    assert (base / "revisions/b/examplelib/__init__.py").is_file()
    assert "--fail-on worse" in (base / "example-workflow.yml").read_text(encoding="utf-8")
    assert config["rule"]["fail_on"] == ["worse"]


def test_the_vendor_showcase_says_to_read_the_image_licence_before_publishing(
    repo_root: Path,
) -> None:
    text = (folder(repo_root, "vendor-container-vs-pip") / "README.md").read_text(encoding="utf-8")

    assert (
        "Read the licence of the vendor container before you publish a result made with it."
        in " ".join(text.split())
    )


@pytest.mark.parametrize("name", SHOWCASES)
def test_the_relative_links_of_a_showcase_resolve(repo_root: Path, kit: object, name: str) -> None:
    base = folder(repo_root, name)
    text = (base / "README.md").read_text(encoding="utf-8")
    broken = [
        target
        for target in kit.links(text)  # type: ignore[attr-defined]
        if not re.match(r"^[a-z]+:", target)
        and not target.startswith("#")
        and not (base / target.split("#", 1)[0]).exists()
    ]

    assert broken == []


def test_the_source_files_of_the_showcases_carry_the_licence_header(repo_root: Path) -> None:
    missing: list[str] = []
    for path in sorted((repo_root / "showcases").rglob("*")):
        if path.suffix not in {".py", ".sh"} or "__pycache__" in path.parts:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        start = 1 if lines and lines[0].startswith("#!") else 0
        if tuple(lines[start : start + 2]) != LICENCE_HEADER:
            missing.append(path.relative_to(repo_root).as_posix())
    assert missing == []

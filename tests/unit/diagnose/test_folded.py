# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""Folding ``perf script`` text, the difference file, the largest functions and objects."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pairbench.diagnose import folded
from pairbench.model import ObjectDiff, TopFunction, TopObject

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "diagnose"

# A fixed perf script text: a symbol with an offset, a symbol with spaces and
# parentheses in an object whose path holds spaces and parentheses, a frame
# without a symbol, a ';' in a Python frame, a sample with an empty call chain,
# a kernel frame the profiler could not name, and a header line that is
# indented as perf script prints it without call graphs.
PERF_SCRIPT = (
    "python3  101/101  1000.000001: cycles:P: \n"
    "\t    aa10 spin_loop (/usr/bin/made-up-app)\n"
    "\t    aa20 main (/usr/bin/made-up-app)\n"
    "\t    aa30 __libc_start_main (/usr/lib/libc.so.6)\n"
    "\n"
    "python3  101/101  1000.000002: cycles:P: \n"
    "\t    aa14 spin_loop+0x1c (/usr/bin/made-up-app)\n"
    "\t    aa20 main (/usr/bin/made-up-app)\n"
    "\t    aa30 __libc_start_main (/usr/lib/libc.so.6)\n"
    "\n"
    "python3  101/101  1000.000003: cycles:P: \n"
    "\t    aa40 made_up::Box<int>::put(int const&) (/srv/made up/lib thing (x2).so)\n"
    "\t    aa50 [unknown] (/srv/made up/lib thing (x2).so)\n"
    "\t    aa20 main (/usr/bin/made-up-app)\n"
    "\t    aa30 __libc_start_main (/usr/lib/libc.so.6)\n"
    "\n"
    "python3  101/101  1000.000004: cycles:P: \n"
    "\t    aa60 py::work;inner:/tmp/made_up.py (/tmp/perf-101.map)\n"
    "\t    aa20 main (/usr/bin/made-up-app)\n"
    "\n"
    "python3  101/101  1000.000005: cycles:P: \n"
    "\n"
    "         python3  101/101  1000.000006: cycles:P: \n"
    "\tffff0010 [unknown] ([unknown])\n"
    "\t    aa20 main (/usr/bin/made-up-app)\n"
)

HOLDS = (
    "# pairbench: this file holds names from the user's code: functions, shared objects and stacks"
)
FOLDED = (
    HOLDS + "\n"
    "[unknown] 1\n"
    "__libc_start_main;main;[lib thing (x2).so];made_up::Box<int>::put(int const&) 1\n"
    "__libc_start_main;main;spin_loop 2\n"
    "main;[unknown] 1\n"
    "main;py::work:inner:/tmp/made_up.py 1\n"
)

SUBJECT = "a;b 3\na;c 1\n"
BASELINE = "# a comment line\na;b 1\na;d 1\n"
DIFF = (
    HOLDS + "\n"
    "stack\tsubject_samples\tbaseline_samples\tsubject_share\tbaseline_share\tshare_change\n"
    "a;b\t3\t1\t0.750000\t0.500000\t0.250000\n"
    "a;c\t1\t0\t0.250000\t0.000000\t0.250000\n"
    "a;d\t0\t1\t0.000000\t0.500000\t-0.500000\n"
)


def test_a_fixed_perf_script_text_gives_a_fixed_folded_file() -> None:
    profile = folded.parse_perf_script(PERF_SCRIPT)
    assert folded.folded_text(profile.stacks) == FOLDED
    assert profile.samples == 6
    assert profile.instrument == "stacks"


# perf script prints a function the compiler inlined as its own frame, with
# " (inlined)" where the shared object goes, followed by the frame it was
# inlined into at the same address. Written from the format the source that
# prints a call chain gives (linked in pairbench.diagnose.folded); the real
# fixture below holds no inlined frame.
INLINED = (
    "made-up-app  7/7  1.000001: cycles:P: \n"
    "\t    bb10 made_up_leaf (inlined)\n"
    "\t    bb10 made_up_middle (inlined)\n"
    "\t    bb10 made_up_caller+0x10 (/usr/bin/made-up-app)\n"
    "\t    bb80 main (/usr/bin/made-up-app)\n"
    "\n"
    "made-up-app  7/7  1.000002: cycles:P: \n"
    "\t    bb20 made_up_leaf (inlined)\n"
    "\t    bb20 made_up_caller+0x20 (/usr/bin/made-up-app)\n"
    "\t    bb80 main (/usr/bin/made-up-app)\n"
)


def test_an_inlined_frame_takes_the_object_of_the_frame_it_was_inlined_into() -> None:
    profile = folded.parse_perf_script(INLINED)
    assert folded.top_objects(profile, 20) == (TopObject(name="made-up-app", share=1.0),)
    assert profile.leaves == {("made_up_leaf", "made-up-app"): 2}
    assert folded.folded_text(profile.stacks) == (
        HOLDS + "\n"
        "main;made_up_caller;made_up_leaf 1\n"
        "main;made_up_caller;made_up_middle;made_up_leaf 1\n"
    )


@pytest.mark.parametrize(
    "chain",
    [
        "\t    cc10 made_up_leaf (inlined)\n",
        "\t    cc10 made_up_leaf (inlined)\n\t    cc90 made_up_caller (/usr/bin/made-up-app)\n",
    ],
)
def test_an_inlined_frame_without_its_frame_at_the_same_address_has_no_object(
    chain: str,
) -> None:
    profile = folded.parse_perf_script("made-up-app  7/7  1.000001: cycles:P: \n" + chain)
    assert profile.leaves == {("made_up_leaf", "[unknown]"): 1}


def test_the_innermost_frame_of_each_sample_with_its_object() -> None:
    profile = folded.parse_perf_script(PERF_SCRIPT)
    assert profile.leaves == {
        ("spin_loop", "made-up-app"): 2,
        ("made_up::Box<int>::put(int const&)", "lib thing (x2).so"): 1,
        ("py::work:inner:/tmp/made_up.py", "[perf map]"): 1,
        ("[unknown]", "[unknown]"): 2,
    }


def test_the_largest_functions_and_objects_by_share_of_samples() -> None:
    profile = folded.parse_perf_script(PERF_SCRIPT)
    assert folded.top_functions(profile, 3) == (
        TopFunction(name="[unknown]", object="[unknown]", share=0.333333),
        TopFunction(name="spin_loop", object="made-up-app", share=0.333333),
        TopFunction(
            name="made_up::Box<int>::put(int const&)", object="lib thing (x2).so", share=0.166667
        ),
    )
    assert folded.top_objects(profile, 20) == (
        TopObject(name="[unknown]", share=0.333333),
        TopObject(name="made-up-app", share=0.333333),
        TopObject(name="[perf map]", share=0.166667),
        TopObject(name="lib thing (x2).so", share=0.166667),
    )


def test_the_difference_file_of_two_fixed_folded_files() -> None:
    rows = folded.diff_rows(folded.parse_folded(SUBJECT), folded.parse_folded(BASELINE))
    assert folded.diff_text(rows) == DIFF


def test_a_side_without_samples_has_shares_of_zero() -> None:
    rows = folded.diff_rows({("a",): 2}, {})
    assert folded.diff_text(rows).splitlines()[2] == "a\t2\t0\t1.000000\t0.000000\t1.000000"


def test_a_change_that_rounds_to_zero_has_no_sign() -> None:
    assert folded.fixed(-0.0000001) == "0.000000"
    assert folded.fixed(-0.25) == "-0.250000"


def test_a_folded_file_is_read_back_as_it_was_written() -> None:
    assert folded.folded_text(folded.parse_folded(FOLDED)) == FOLDED


def test_two_lines_of_one_stack_add_up() -> None:
    assert folded.parse_folded("a;b 2\na;b 3\n") == {("a", "b"): 5}


@pytest.mark.parametrize("line", ["a;b", "a;b x", "a;b -1", " 3"])
def test_a_line_without_a_count_is_refused(line: str) -> None:
    with pytest.raises(ValueError, match="line 1 of a folded file has no count of samples"):
        folded.parse_folded(line + "\n")


def test_a_profile_from_a_folded_file_has_no_shared_objects() -> None:
    profile = folded.profile_from_folded("main;spin 3\nmain;nap 1\n")
    assert profile.instrument == "pystacks"
    assert profile.leaves == {("spin", None): 3, ("nap", None): 1}
    assert folded.top_objects(profile, 20) == ()
    assert folded.top_functions(profile, 1) == (TopFunction(name="spin", object=None, share=0.75),)


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("a;b", "a:b"),
        ("tab\there", "tab here"),
        ("line\r\nend", "line  end"),
        ("   ", "[unknown]"),
    ],
)
def test_a_name_as_a_folded_line_holds_it(raw: str, clean: str) -> None:
    assert folded.clean_name(raw) == clean


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("/usr/lib/aarch64-linux-gnu/libc.so.6", "libc.so.6"),
        ("[kernel.kallsyms]", "[kernel.kallsyms]"),
        ("/tmp/perf-874.map", "[perf map]"),
        ("/tmp/perf-874.map.old", "perf-874.map.old"),
        ("", "[unknown]"),
    ],
)
def test_the_name_a_shared_object_is_listed_under(path: str, name: str) -> None:
    assert folded.object_name(path) == name


def test_the_build_ids_of_the_loaded_objects() -> None:
    text = "AB12 /usr/lib/libc.so.6\ncd34 [vdso]\nnot-a-build-id /x\n\nab12 /other/libc.so.6\n"
    assert folded.parse_buildids(text) == {"[vdso]": ("cd34",), "libc.so.6": ("ab12",)}


def test_objects_on_one_side_and_objects_whose_build_id_differs() -> None:
    profiles = {
        "new": folded.Profile("stacks", objects={"libc.so.6": ("aa",), "libnew.so": ("11",)}),
        "old": folded.Profile("stacks", objects={"libc.so.6": ("bb",), "libold.so": ("22",)}),
        "py": folded.Profile("pystacks"),
    }
    assert folded.compare_objects(profiles) == ObjectDiff(
        only_in={"new": ("libnew.so",), "old": ("libold.so",)},
        differ=({"name": "libc.so.6", "new": "aa", "old": "bb"},),
    )


def test_objects_are_compared_only_between_two_sides_or_more() -> None:
    profiles = {
        "new": folded.Profile("stacks", objects={"libc.so.6": ("aa",)}),
        "old": folded.Profile("pystacks"),
    }
    assert folded.compare_objects(profiles) == ObjectDiff()


# ---------------------------------------------------------------------------
# The fixture from a real run of perf in a public image
# ---------------------------------------------------------------------------


def _fixture_profile() -> folded.Profile:
    return folded.parse_perf_script(
        (FIXTURES / "perf-script.txt").read_text(encoding="utf-8"),
        (FIXTURES / "perf-buildids.txt").read_text(encoding="utf-8"),
    )


def test_the_real_perf_script_fixture_folds() -> None:
    profile = _fixture_profile()
    assert profile.samples == 27
    assert folded.top_functions(profile, 3) == (
        TopFunction(name="[unknown]", object="[unknown]", share=0.333333),
        TopFunction(name="[python3.13]", object="python3.13", share=0.296296),
        TopFunction(name="[libcrypto.so.3]", object="libcrypto.so.3", share=0.222222),
    )
    assert folded.top_objects(profile, 1) == (TopObject(name="python3.13", share=0.407407),)


def test_the_real_fixture_holds_the_python_frames_of_the_workload() -> None:
    profile = _fixture_profile()
    inclusive: dict[str, int] = {}
    for stack, count in profile.stacks.items():
        for name in set(stack):
            inclusive[name] = inclusive.get(name, 0) + count
    assert inclusive["py::main:/tmp/workload.py"] == 22
    assert inclusive["py::hash_rounds:/tmp/workload.py"] == 13
    assert inclusive["py::encode_records:/tmp/workload.py"] == 5
    assert inclusive["py::spin_numbers:/tmp/workload.py"] == 4


def test_the_real_fixture_lists_the_loaded_objects() -> None:
    assert list(_fixture_profile().objects) == [
        "[kernel.kallsyms]",
        "[vdso]",
        "_hashlib.cpython-313-aarch64-linux-gnu.so",
        "ld-linux-aarch64.so.1",
        "libc.so.6",
        "libcrypto.so.3",
        "libexpat.so.1.13.0",
        "libm.so.6",
        "libz.so.1.3.1",
        "libzstd.so.1.5.7",
        "python3.13",
    ]


def test_every_fixture_of_this_area_has_a_provenance_sidecar() -> None:
    fixtures = [p for p in FIXTURES.iterdir() if not p.name.endswith(".provenance.json")]
    assert sorted(p.name for p in fixtures) == [
        "perf-buildids.txt",
        "perf-script.txt",
        "perf-stat.txt",
    ]
    for path in fixtures:
        assert path.with_name(path.name + ".provenance.json").is_file()


def test_the_perf_stat_sidecar_says_what_the_run_kept() -> None:
    sidecar = json.loads((FIXTURES / "perf-stat.txt.provenance.json").read_text(encoding="utf-8"))
    assert sidecar["replaced"] == (
        "the start line replaced by a made-up date; every other line kept as perf printed it in "
        "the run: the counter values, how long each counter ran and for what share of the run, "
        "the figures perf derives from them (such as instructions per cycle, GHz, CPUs utilized "
        "and rates per second) and the PMU names"
    )

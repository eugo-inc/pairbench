# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The reference pages say which texts are read word by word and that ``--set`` values are hidden.

The config page names every program whose operands are command texts, every
option whose value is one, every shell and every keyword before ``:`` that
gives a name no value, as the code holds them, and each of its examples is
what the code shows; each example of a shell text is also what the code
hashes. The results page says the value of every ``--set`` is
shown hidden, and that the workload is read after each side's words.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from pairbench import model

CONFIG_PAGE = "docs/reference/config.md"
# The options of a program of ``TEXT_OPTIONS`` that hands its text to a shell.
SHELL_TEXT = ("-c", "--command")
# The options whose value is a command text, as the page names them.
TEXT_OPTIONS = {
    "gcloud": ("--command",),
    "env": ("-S", "--split-string"),
    "hyperfine": (
        "-s",
        "--setup",
        "-p",
        "--prepare",
        "-C",
        "--conclude",
        "-c",
        "--cleanup",
        "--reference",
    ),
    **dict.fromkeys(("su", "runuser", "flock", "script", "fish"), SHELL_TEXT),
}
RESULTS_PAGE = "docs/reference/results-schema.md"
HEADING = "What the shared files hide"


def section(repo_root: Path) -> str:
    """The text of the config page's section on the shared files, joined on one line."""
    text = (repo_root / CONFIG_PAGE).read_text(encoding="utf-8")
    start = text.index(f"\n## {HEADING}\n")
    end = text.index("\n## ", start + 1)
    return " ".join(text[start:end].split())


def results_page(repo_root: Path) -> str:
    return " ".join((repo_root / RESULTS_PAGE).read_text(encoding="utf-8").split())


def workload_shown(shown: str) -> str:
    """The workload of a shown ``pairbench run`` command: ``--`` and the words after it."""
    return shown[shown.index(" -- ") + 1 :]


def test_the_section_names_every_program_whose_operands_are_command_texts(
    repo_root: Path,
) -> None:
    text = section(repo_root)

    assert [name for name in model.COMMAND_TEXT_RUNNERS if f"`{name}`" not in text] == []
    assert "(`COMMAND_TEXT_RUNNERS`)" in text
    ends = model.COMMAND_TEXT_RUNNERS["parallel"].ends
    commands = model.COMMAND_TEXT_RUNNERS["tmux"].commands
    listed = ", ".join(f"`{word}`" for word in commands[:-1])
    assert f"of `parallel` up to {', '.join(f'`{e}`' for e in ends[:-1])} or `{ends[-1]}`" in text
    assert f"of `tmux` after {listed} or `{commands[-1]}` (`COMMAND_TEXT_RUNNERS`)" in text
    assert commands == (
        "new",
        "new-session",
        "new-window",
        "neww",
        "split-window",
        "splitw",
        "respawn-window",
        "respawnw",
        "respawn-pane",
        "respawnp",
    )


def test_the_section_names_every_option_whose_value_is_a_command_text(repo_root: Path) -> None:
    text = section(repo_root)

    shells = [name for name, options in model.TEXT_OPTIONS.items() if options == SHELL_TEXT]
    named = ", ".join(f"`{name}`" for name in shells[:-1])
    hyperfine = model.TEXT_OPTIONS["hyperfine"]
    runs = ", ".join(f"`{option}`" for option in hyperfine[:-1])

    assert (
        "the value of `gcloud ... --command`, of `env -S` or `--split-string`, of "
        f"{runs} or `{hyperfine[-1]}` of `hyperfine`, also in a group after its `-N`, `-i` or "
        "`-S` (`-NpTEXT`) and wherever `hyperfine` starts a command in the words of `ssh`, "
        "`watch` or `parallel`, which a shell runs once they are joined: first, or after a "
        "separator, after the assignments that lead it, after `env`, `sshpass`, `taskset`, "
        "`numactl`, `chrt`, `stdbuf`, `ionice`, `time`, `nice`, `nohup`, `timeout` or `sudo` "
        "read as below, or after the host of a "
        "nested `ssh` (`ssh made-up-host taskset -c 0 hyperfine --setup=TEXT ./bench-old`), and "
        f"of `-c` or `--command` of {named} and `{shells[-1]}` "
        "(`TEXT_OPTIONS`), given as the next argument or glued to the option"
    ) in text
    assert model.TEXT_OPTION_FLAGS == {"hyperfine": "NiVhS"}
    assert model.TEXT_OPTIONS == TEXT_OPTIONS


# Where the section says hyperfine starts a command in a runner's words, each with a client's
# command glued to ``--setup``, as typed and as shown.
JOINED_STARTS = {
    "first": ("ssh", "made-up-host"),
    "after a separator": ("ssh", "made-up-host", "cd", "made-up-dir", "&&"),
    "after an assignment": ("watch", "LC_ALL=C"),
    "after env": ("parallel", "env"),
    "after taskset": ("ssh", "made-up-host", "taskset", "-c", "0"),
    "after nice": ("ssh", "made-up-host", "nice", "-n", "5"),
    "after nohup": ("watch", "nohup"),
    "after timeout": ("parallel", "timeout", "-s", "KILL", "30"),
    "after sudo": ("ssh", "made-up-host", "sudo", "-u", "made-up-user", "LC_ALL=C"),
    "after the host of a nested ssh": ("ssh", "made-up-host", "ssh", "made-up-inner"),
}


@pytest.mark.parametrize("start", sorted(JOINED_STARTS))
def test_each_start_of_hyperfine_the_section_names_hides_its_glued_text(start: str) -> None:
    lead = JOINED_STARTS[start]
    typed = [*lead, "hyperfine", "--setup='redis-cli -a VALUE FLUSHALL'", "./bench-old"]
    hidden = [*lead, "hyperfine", "--setup='redis-cli -a <hidden> FLUSHALL'", "./bench-old"]

    assert model.public_command(typed) == shlex.join(hidden)
    assert model.hashed_argv(typed) == hidden


# What the section says of ``-S`` of hyperfine from 2.0.0 on, and a word that holds it.
SHELL_FLAG = (
    "From [hyperfine 2.0.0](https://github.com/sharkdp/hyperfine/blob/v2.0.0/src/cli.rs) on, "
    "`-S` takes no value, so `-SsTEXT` is `-S` and `-s TEXT`."
)
SHELL_FLAG_EXAMPLE = (
    ("hyperfine", "-Ssredis-cli -a VALUE PING", "./bench-old"),
    "hyperfine '-Ssredis-cli -a <hidden> PING' ./bench-old",
)


def test_the_section_says_the_s_of_hyperfine_2_takes_no_value(repo_root: Path) -> None:
    typed, shown = SHELL_FLAG_EXAMPLE

    assert SHELL_FLAG in section(repo_root)
    assert "S" in model.TEXT_OPTION_FLAGS["hyperfine"]
    assert model.public_command(list(typed)) == shown
    assert model.hashed_argv(list(typed)) == [
        "hyperfine",
        "-Ssredis-cli -a <hidden> PING",
        "./bench-old",
    ]


# What the section says of a short option of hyperfine glued with an ``=``, and its example.
SHORT_EQUALS = (
    "The parser of `hyperfine` also takes an `=` between a short option and its glued text off "
    "the text ([clap 4.5.20](https://github.com/clap-rs/clap/blob/v4.5.20/clap_builder/src/"
    "parser/parser.rs), which hyperfine 1.19.0 is built with), so "
    "`hyperfine '-s=redis-cli -a VALUE FLUSHALL' ./bench-old` shows "
    "`hyperfine '-s=redis-cli -a <hidden> FLUSHALL' ./bench-old`."
)
SHORT_EQUALS_EXAMPLE = (
    "hyperfine '-s=redis-cli -a VALUE FLUSHALL' ./bench-old",
    "hyperfine '-s=redis-cli -a <hidden> FLUSHALL' ./bench-old",
)


def test_the_section_says_a_short_option_of_hyperfine_may_hold_an_equals_sign(
    repo_root: Path,
) -> None:
    typed, shown = SHORT_EQUALS_EXAMPLE

    assert SHORT_EQUALS in section(repo_root)
    assert model.public_command(shlex.split(typed)) == shown
    assert model.hashed_argv(shlex.split(typed)) == shlex.split(shown)


def test_the_section_names_every_shell(repo_root: Path) -> None:
    text = section(repo_root)
    shells = ", ".join(f"`{shell}`" for shell in model.SHELLS[:-1])

    assert f"{shells} or `{model.SHELLS[-1]}`: `SHELLS`" in text


def test_the_section_names_every_keyword_before_a_colon(repo_root: Path) -> None:
    text = section(repo_root)
    keywords = ", ".join(f"`{word}`" for word in model.CODE_KEYWORDS[:-1])

    assert (
        f"A name with `:` right after {keywords} or `{model.CODE_KEYWORDS[-1]}` "
        "(`CODE_KEYWORDS`) is given no value"
    ) in text
    assert "After a bare name, the value of `=` or `:` starts on the same line" in text


def test_the_section_says_where_a_query_value_and_an_address_value_end(repo_root: Path) -> None:
    text = section(repo_root)

    assert "whose name looks like a credential ends at the next `&` or `#`" in text
    assert "A value there that is an address with a user part loses only that part" in text


# The credential names the page gives with a dash, a dot or small letters.
WHOLE_VALUE_NAMES = ("password", "Api-Key", "db.password")


def test_the_section_says_which_names_hide_their_whole_value(repo_root: Path) -> None:
    text = section(repo_root)
    names = ", ".join(f"`{name}=`" for name in WHOLE_VALUE_NAMES[:-1])

    assert "The test of the name ignores case, and a name with a `-` or a `.` gets it too" in text
    assert f"{names} and `{WHOLE_VALUE_NAMES[-1]}=` hide their whole value" in text
    assert "a random-looking word in it is hidden by its shape" in text
    for name in WHOLE_VALUE_NAMES:
        shown = model.public_command(("pairbench", "run", "--", "env", f"{name}=zqm made up", "x"))
        assert shown == f"pairbench run -- env '{name}=<hidden>' x"


# Examples on the page, as the code shows them after ``pairbench run --``; every value is made up.
SHOWN_EXAMPLES = (
    (
        ("ssh", "made-up-host", "API_KEY=zqm-made-up ./bench-old"),
        "ssh made-up-host 'API_KEY=<hidden> ./bench-old'",
    ),
    (
        ("env", "MADE_UP_FLAGS=--api-key=zqm-made-up --threads 8", "mytool"),
        "env 'MADE_UP_FLAGS=--api-key=<hidden> --threads 8' mytool",
    ),
    (("python3", "-c", "if token: run_old()"), "python3 -c 'if token: run_old()'"),
    (
        ("curl", "http://localhost:8000/v1?token=zqm-made-up&threads=8"),
        "http://localhost:8000/v1?token=<hidden>&threads=8",
    ),
    (
        ("redis-cli", "-u", "redis://:zqm-made-up@localhost:6379/0"),
        "redis-cli -u redis://<hidden>@localhost:6379/0",
    ),
    (
        ("ssh", "-o", "SetEnv=DB_PASSWORD=zqm made up", "made-up-host", "true"),
        "SetEnv=DB_PASSWORD=<hidden>",
    ),
    (
        ("sh", "-c", "tool API_KEY= && ./bench-old"),
        "sh -c 'tool API_KEY=<hidden> && ./bench-old'",
    ),
    (
        ("env", "-S", "tool --api-key=zqm-made-up&&./bench-old"),
        "env -S 'tool --api-key=<hidden>'",
    ),
    (
        ("ssh", "made-up-host", "tool --api-key=zqm-made-up&&./bench-old"),
        "ssh made-up-host 'tool --api-key=<hidden>&&./bench-old'",
    ),
    (
        ("watch", "-x", "tool", "DB_PASSWORD=zqm made up"),
        "watch -x tool 'DB_PASSWORD=<hidden>'",
    ),
    (
        ("gcloud", "compute", "ssh", "made-up-vm", "--command=mysql -pzqm-made-up"),
        "gcloud compute ssh made-up-vm '--command=mysql -p<hidden>'",
    ),
    (
        ("hyperfine", "--setup=redis-cli -a zqm-made-up FLUSHALL", "./bench-old"),
        "hyperfine '--setup=redis-cli -a <hidden> FLUSHALL' ./bench-old",
    ),
    (("env", "-Sredis-cli", "-a", "zqm-made-up"), "env -Sredis-cli -a '<hidden>'"),
    (
        ("tmux", "new", "-d", "API_KEY=zqm-made-up&&./bench-old"),
        "tmux new -d 'API_KEY=<hidden>&&./bench-old'",
    ),
    (
        ("su", "bench", "-c", "API_KEY=zqm-made-up&&./bench-old"),
        "su bench -c 'API_KEY=<hidden>&&./bench-old'",
    ),
    (
        ("watch", "-c", "API_KEY=zqm-made-up&&./bench-old"),
        "watch -c 'API_KEY=<hidden>&&./bench-old'",
    ),
    (
        ("taskset", "-c", "0-3", "ssh", "made-up-host", "API_KEY=zqm-made-up ./bench-old"),
        "taskset -c 0-3 ssh made-up-host 'API_KEY=<hidden> ./bench-old'",
    ),
    (
        ("timeout", "-s", "KILL", "30", "ssh", "made-up-host", "API_KEY=zqm-made-up ./bench-old"),
        "timeout -s KILL 30 ssh made-up-host 'API_KEY=<hidden> ./bench-old'",
    ),
    (
        ("setsid", "ssh", "made-up-host", "API_KEY=zqm-made-up ./bench-old"),
        "setsid ssh made-up-host 'API_KEY=<hidden>'",
    ),
)


def test_the_section_names_every_program_that_runs_the_command_after_its_operands(
    repo_root: Path,
) -> None:
    text = section(repo_root)

    assert [name for name in model._COMMAND_STARTERS if f"`{name}`" not in text] == []
    assert "the duration of `timeout`" in text
    assert "the assignments of `sudo`" in text


def test_the_section_says_a_shell_text_ends_a_value_with_its_word(repo_root: Path) -> None:
    text = section(repo_root)

    assert "In each of these texts but the one after `-c` of a program that is no shell" in text
    assert "the words end where a shell's words end" in text
    assert "a value given with `=` ends where its shell word ends" in text
    assert "so `=` or `==` followed by a blank gives the empty value" in text
    assert "A value that ends in `=` is still hidden whole" in text
    assert "The lines of a here-document there (`<<EOF` up to `EOF`)" in text
    assert (
        "A quoted word that is the text of a shell in turn is a shell text of its own, where an "
        "operator outside its own quotes ends a value too"
    ) in text


def test_the_section_names_the_command_texts_a_shell_runs(repo_root: Path) -> None:
    text = section(repo_root)
    runners = model.COMMAND_TEXT_RUNNERS
    no_shell = {name: runner.no_shell for name, runner in runners.items() if runner.no_shell}

    assert (
        "It is also a command text that the program before it hands to a shell: the remote "
        "command of `ssh`, the commands of `hyperfine`, `watch` and `parallel`, the command of "
        "`tmux` given as one argument, with blanks or none, the value of `gcloud ... --command`, "
        "and the text of `-c` or `--command` of `su`, `runuser`, `flock` and `script`"
    ) in text
    assert model.COMMAND_TEXT_RUNNERS["watch"].flags == ("-c",)
    assert (
        "The `-c` of `watch` is its colour option, also last in a group of short options "
        "(`watch -tc`), so the word after it is the command"
    ) in text
    assert [name for name, runner in runners.items() if runner.spaced] == ["tmux"]
    assert model._SPLIT_TEXTS == ("env",)
    assert "The text of `env -S` is no shell text, as `env` splits it into words" in text
    assert no_shell == {
        "hyperfine": ("-N", "--shell=none", "-Snone"),
        "watch": ("-x", "--exec"),
        "parallel": ("-q", "--quote"),
    }
    assert (
        "nor is the command of `watch -x` or `--exec`, `hyperfine -N` or `--shell none`, or "
        "`parallel -q` or `--quote`, which they run with no shell"
    ) in text


def test_the_section_says_how_the_words_of_a_command_run_with_no_shell_are_read(
    repo_root: Path,
) -> None:
    text = section(repo_root)
    runners = model.COMMAND_TEXT_RUNNERS

    assert [name for name, runner in runners.items() if runner.options_after] == ["hyperfine"]
    assert [name for name, runner in runners.items() if runner.splits] == ["hyperfine"]
    assert "Such an option counts in a group of short options too (`watch -tx`)" in text
    assert (
        "`hyperfine` takes its options after its commands as well, so `-N` or `--shell none` "
        "anywhere on its command line runs none of them in a shell"
    ) in text
    assert (
        "Only a word of its own command line counts: the `-N` inside one of its commands "
        "(`hyperfine 'ssh -N made-up-host true' TEXT`) is an option of that command, and both "
        "commands run in a shell"
    ) in text
    assert (
        "Each word of the command of `watch -x` or `parallel -q`, and of a `tmux` command given "
        "as several arguments, is one argument of the program, read as any other argument is"
    ) in text
    assert (
        "A word that a runner passes to its program as one argument, as each word of the command "
        "of `watch -x` is, is none of these texts and is read as any argument is"
    ) in " ".join((repo_root / CONFIG_PAGE).read_text(encoding="utf-8").split())


@pytest.mark.parametrize(("args", "words"), SHOWN_EXAMPLES)
def test_each_example_of_the_section_is_what_the_code_shows(
    repo_root: Path, args: tuple[str, ...], words: str
) -> None:
    shown = model.public_command(("pairbench", "run", "--", *args))

    assert shown is not None
    assert words.replace("'", "") in shown.replace("'", "")
    assert f"`{words}" in section(repo_root)


# The examples of a shell text on the page, as it writes them, and the argument list each
# comes from; every value is made up. The shown command and the hash give the same words.
SHELL_TEXT_EXAMPLES = (
    (
        ("sh", "-c", "tool --api-key=zqm-made-up&& ls -l"),
        "sh -c 'tool --api-key=<hidden>&& ls -l'",
    ),
    (
        ("sh", "-c", "curl -H 'Authorization: Bearer zqm-made-up'; ls -l"),
        "sh -c \"curl -H 'Authorization: <hidden>'; ls -l\"",
    ),
    (
        ("sh", "-c", 'sh -c "API_KEY=zqm-made-up&&./bench"'),
        "sh -c 'sh -c \"API_KEY=<hidden>&&./bench\"'",
    ),
    (
        ("sh", "-c", 'env MADE_UP_FLAGS="--api-key zqm-made-up --threads 8" mytool'),
        "sh -c 'env MADE_UP_FLAGS=\"--api-key <hidden> --threads 8\" mytool'",
    ),
    (
        ("sh", "-c", 'mytool --token" zqm-made-up" --threads 8'),
        "sh -c \"mytool '--token <hidden>' --threads 8\"",
    ),
    (
        ("sh", "-c", 'ssh made-up-host ./bench --token" zqm-made-up"'),
        "sh -c \"ssh made-up-host ./bench '--token <hidden>'\"",
    ),
    (
        ("sh", "-c", "ssh made-up-host './bench --token\\ zqm-made-up'"),
        'sh -c "ssh made-up-host \'./bench \\"--token <hidden>\\"\'"',
    ),
    (
        ("script", "-qc", "API_KEY=zqm-made-up&&./bench-old"),
        "script -qc 'API_KEY=<hidden>&&./bench-old'",
    ),
    (
        ("env", "-S", 'sh -c "API_KEY=zqm-made-up&&./bench-old"'),
        "env -S 'sh -c \"API_KEY=<hidden>&&./bench-old\"'",
    ),
    (
        ("hyperfine", "-N", 'sh -c "API_KEY=zqm-made-up&&./bench-old"'),
        "hyperfine -N 'sh -c \"API_KEY=<hidden>&&./bench-old\"'",
    ),
)


def test_the_section_says_a_shell_text_inside_a_text_with_no_shell_ends_a_value(
    repo_root: Path,
) -> None:
    text = section(repo_root)

    assert (
        "The `-c` of `su`, `runuser`, `flock`, `script` and `fish` counts last in a group of "
        "short options too"
    ) in text
    assert (
        "A quoted word of a text run with no shell that is the text of a shell is a shell text "
        "of its own, so a value there ends at its operators, glued or not"
    ) in text


def test_the_section_says_a_quoted_value_of_an_ordinary_name_is_read_by_words(
    repo_root: Path,
) -> None:
    text = section(repo_root)

    assert (
        "A value in quotes is read the same way, and so is a word quoted whole that gives a name "
        "its value, as a shell text writes them"
    ) in text


def test_the_section_says_a_word_in_quoted_parts_is_read_as_its_argument(
    repo_root: Path,
) -> None:
    text = section(repo_root)

    assert (
        "gives its program one argument with the quotes taken off, `--token VALUE`, and is read "
        "as the text of that argument. A text that a second shell runs, as the remote command of "
        "`ssh` or the text after `-c` of a shell in a shell text, splits that argument into "
        "words, so it is read as a shell text."
    ) in text
    assert (
        "Inside a word in single quotes such a word is shown in double quotes, and the other "
        "way round, so the quotes around it still hold"
    ) in text
    assert "Inside both kinds of quotes its blanks are escaped instead (`--token\\ <hidden>`)." in (
        text
    )


@pytest.mark.parametrize(("args", "words"), SHELL_TEXT_EXAMPLES)
def test_each_shell_text_example_of_the_section_is_what_the_code_shows_and_hashes(
    repo_root: Path, args: tuple[str, ...], words: str
) -> None:
    shown = model.public_command(args)

    assert f"`{words}`" in section(repo_root)
    assert shown is not None
    assert shlex.split(shown) == shlex.split(words)
    assert model.hashed_argv(args) == shlex.split(words)


def test_the_section_example_of_a_client_named_in_a_side_spec_is_what_the_code_shows(
    repo_root: Path,
) -> None:
    side = "old=cmd:./build-old/redis-benchmark {workload}"
    shown = model.public_command(
        ("pairbench", "run", "--side", side, "--", "-a", "zqm-made-up", "-n", "1000")
    )
    text = section(repo_root)

    assert shown == "pairbench run --side 'old=cmd:<hidden>' -- -a '<hidden>' -n 1000"
    assert f"`--side '{side}'`" in text
    assert f"the workload `-- -a VALUE -n 1000` shows `{workload_shown(shown)}`" in text
    assert "`config_sha256` reads the workload of the config file the same way" in text


def test_the_results_page_says_every_set_value_is_hidden(repo_root: Path) -> None:
    text = results_page(repo_root)
    shown = model.public_command(("pairbench", "run", "--set", "launch.cpus=0-3", "--", "true"))

    assert "The value of every `--set` is hidden whatever its key, and its key is kept" in text
    assert "`--set launch.cpus=0-3` shows `--set 'launch.cpus=<hidden>'`" in text
    assert shown == "pairbench run --set 'launch.cpus=<hidden>' -- true"


def test_the_results_page_says_the_workload_is_read_after_each_side(repo_root: Path) -> None:
    text = results_page(repo_root)
    side = "old=cmd:./build-old/redis-benchmark {workload}"
    shown = model.public_command(
        ("pairbench", "run", "--side", side, "--", "-a", "zqm-made-up", "-n", "1000")
    )

    assert shown == "pairbench run --side 'old=cmd:<hidden>' -- -a '<hidden>' -n 1000"
    assert (
        "The workload after `--` is read after the words each command side runs before "
        "`{workload}` too, so a client named only in a side's spec hides its password there "
        f"(`{workload_shown(shown)}`)"
    ) in text


def test_the_section_example_of_a_shell_text_that_hands_its_arguments_on_is_what_the_code_shows(
    repo_root: Path,
) -> None:
    cmd = ["sh", "-c", 'redis-benchmark "$@"', "_", model.WORKLOAD_PLACEHOLDER]
    workloads = (["-a", password, "-n", "1000"] for password in ("zqm-made-up", "pqx-made-up"))
    configs = [{"sides": {"a": {"cmd": cmd}}, "workload": {"argv": argv}} for argv in workloads]
    shown = model.public_command(
        ("pairbench", "run", "--", *configs[0]["workload"]["argv"]), config=configs[0]
    )
    text = " ".join(section(repo_root).split())

    assert shown == "pairbench run -- -a '<hidden>' -n 1000"
    assert model.config_sha256(configs[0]) == model.config_sha256(configs[1])
    assert '`cmd = ["sh", "-c", "redis-benchmark \\"$@\\"", "_", "{workload}"]`' in text
    assert f"shows the same workload as `{workload_shown(shown)}`" in text
    assert f"{model._PARAMETER_READ_SPARE} more" in text


def _image_side(recorded: dict[str, object]) -> model.Side:
    side = model.Side.image("a", "registry.example/tool:1")
    identity = {"image_id": "sha256:" + "0" * 64, "digests": (), **recorded}
    return model.Side(
        name=side.name, kind=side.kind, spec=side.spec, identity=identity, fingerprint="0" * 64
    )


@pytest.mark.parametrize(
    "recorded",
    [
        {model.IMAGE_ENTRYPOINT_KEY: ("memtier_benchmark",)},
        {
            model.IMAGE_ENTRYPOINT_KEY: ("docker-entrypoint.sh",),
            model.IMAGE_COMMAND_PROGRAM_KEY: "memtier_benchmark",
        },
    ],
    ids=["client-entrypoint", "wrapper-script-then-command"],
)
def test_the_section_example_of_an_image_entrypoint_is_what_the_code_shows(
    repo_root: Path, recorded: dict[str, object]
) -> None:
    sides = [_image_side(recorded)]
    workloads = (
        ["-s", "HOST", "-a", word, "-n", "1000"] for word in ("zqm-made-up", "pqx-made-up")
    )
    configs = [
        {"sides": {"a": {"image": "registry.example/tool:1"}}, "workload": {"argv": argv}}
        for argv in workloads
    ]
    shown = model.public_command(
        ("pairbench", "run", "--", *configs[0]["workload"]["argv"]), sides=sides
    )
    text = section(repo_root)

    assert shown == "pairbench run -- -s HOST -a '<hidden>' -n 1000"
    assert model.config_sha256(configs[0], sides) == model.config_sha256(configs[1], sides)
    assert (
        "with an image whose entrypoint is `memtier_benchmark`, the workload "
        f"`-- -s HOST -a VALUE -n 1000` shows `{workload_shown(shown)}`"
    ) in text
    assert (
        "a wrapper script such as `docker-entrypoint.sh` with the command `memtier_benchmark` "
        "hides `-a VALUE` the same way"
    ) in text
    assert (
        "When the engine's details of the image do not say what its entrypoint is, the run is "
        "refused with [`E_ENTRYPOINT_UNREADABLE`]"
    ) in text


# The client examples of the section, as it writes them typed, and as the code prints them
# after ``pairbench run --``: a word that holds ``<hidden>`` stands in quotes there.
CLIENT_EXAMPLES = (
    (
        ("sshpass", "-p", "zqm-made-up", "ssh", "-p", "2222", "HOST"),
        "sshpass -p VALUE ssh -p 2222 HOST",
        "sshpass -p '<hidden>' ssh -p 2222 HOST",
    ),
    (
        ("redis-benchmark", "-a", "zqm-made-up"),
        "redis-benchmark -a VALUE",
        "redis-benchmark -a '<hidden>'",
    ),
    (
        ("redis-benchmark", "-azqm-made-up"),
        "redis-benchmark -aVALUE",
        "redis-benchmark '-a<hidden>'",
    ),
    (
        ("mysql", "-e", "select 1; select 2", "-pzqm-made-up"),
        "mysql -e 'select 1; select 2' -pVALUE",
        "mysql -e 'select 1; select 2' '-p<hidden>'",
    ),
    (
        ("redis-cli", "-d", ";", "-a", "zqm-made-up"),
        "redis-cli -d ';' -a VALUE",
        "redis-cli -d ';' -a '<hidden>'",
    ),
    (
        ("redis-cli", "-n", "1", ">", "out", "AUTH", "zqm-made-up"),
        "redis-cli -n 1 '>' out AUTH VALUE",
        "redis-cli -n 1 '>' out AUTH '<hidden>'",
    ),
    (
        ("redis-cli", "-a", ">zqm-made-up", "PING"),
        "redis-cli -a '>VALUE' PING",
        "redis-cli -a '<hidden>' PING",
    ),
)
# The examples of a command substitution in the section, as it writes them typed and as the
# code shows and hashes them.
SUBSTITUTION_EXAMPLES = (
    (
        "sh -c './bench --label $(redis-cli -a VALUE get k) -n 5'",
        "sh -c './bench --label $(redis-cli -a <hidden> get k) -n 5'",
    ),
    (
        "sh -c 'redis-benchmark -n $(nproc) -a VALUE'",
        "sh -c 'redis-benchmark -n $(nproc) -a <hidden>'",
    ),
)


# The example of an ``eval`` in the section, as it writes it typed and as the code shows and
# hashes it.
EVAL_EXAMPLES = (
    (
        "sh -c \"eval memtier_benchmark --command \\'AUTH VALUE\\'\"",
        "sh -c 'eval \"memtier_benchmark --command '\"'\"'AUTH <hidden>'\"'\"'\"'",
    ),
    (
        "sh -c 'eval \"PGPASSWORD=VALUE psql -h db.example\"'",
        "sh -c 'eval \"PGPASSWORD=<hidden> psql -h db.example\"'",
    ),
    (
        "sh -c 'x=$(eval \"PGPASSWORD=VALUE psql -h db.example\")'",
        "sh -c 'x=$(eval \"PGPASSWORD=<hidden> psql -h db.example\")'",
    ),
    (
        'sh -c \'x="$(eval "PGPASSWORD=\\"VALUE\\" psql -h db.example")"\'',
        "sh -c 'x=\"$(eval '\"'\"'PGPASSWORD=<hidden> psql -h db.example'\"'\"')\"'",
    ),
    (
        'sh -c "eval python3 -c \\\\\\"token = \\\\\'VALUE\\\\\'\\\\\\""',
        "sh -c 'eval \"python3 -c \\\"token = '\"'\"'<hidden>'\"'\"'\\\"\"'",
    ),
)
# The example of an ``eval`` in backquotes in the section, as it writes it typed and as the code
# shows and hashes it; the page writes each in two backquotes, as it holds one.
BACKQUOTE_EXAMPLE = (
    'sh -c \'x="`eval "PGPASSWORD=\\\\"VALUE\\\\" psql -h db.example"`"\'',
    "sh -c 'x=\"`eval '\"'\"'PGPASSWORD=<hidden> psql -h db.example'\"'\"'`\"'",
)
BACKQUOTE_SENTENCE = (
    "A text in backquotes is read as the shell runs it, with the backslash taken off before a "
    'backslash, a backquote or a `$`, and in backquotes inside double quotes before a `"` too:'
)
# The sentences of the section on an ``eval`` after a line continuation or in a substitution.
EVAL_PLACES = (
    "after a line continuation, or in a command substitution, a process substitution or a "
    "subshell, is read the same way:",
    "A command substitution inside double quotes is read as the shell text it is too, so a value "
    "in escaped double quotes there is hidden and the program after it stays:",
)
LINE_CONTINUATION = (
    "A backslash right before a line break, outside quotes, joins the two lines as a shell does: "
    "that line break ends no command, and the next line goes on with the word or the command "
    "before it."
)
EVAL_SENTENCE = (
    "The words of an `eval` are read as the one shell text it runs, with their quotes taken off "
    "and their escapes read, when one of them is quoted or escaped:"
)


# The examples of a redirection in a shell text in the section, as it writes them typed and as
# the code shows and hashes them.
REDIRECTION_EXAMPLES = (
    (
        "sh -c 'redis-cli -a 2>&1 VALUE PING'",
        "sh -c 'redis-cli -a 2>&1 <hidden> PING'",
    ),
    (
        "sh -c 'redis-benchmark -n 1000 >|out -a VALUE'",
        "sh -c 'redis-benchmark -n 1000 >|out -a <hidden>'",
    ),
)


@pytest.mark.parametrize(("args", "typed", "printed"), CLIENT_EXAMPLES)
def test_each_client_example_of_the_section_is_what_the_code_prints(
    repo_root: Path, args: tuple[str, ...], typed: str, printed: str
) -> None:
    shown = model.public_command(("pairbench", "run", "--", *args))

    assert shown == f"pairbench run -- {printed}"
    assert f"`{typed}` shows `{printed}`" in section(repo_root)


@pytest.mark.parametrize(("typed", "shown"), SUBSTITUTION_EXAMPLES)
def test_each_substitution_example_of_the_section_is_what_the_code_shows_and_hashes(
    repo_root: Path, typed: str, shown: str
) -> None:
    args = shlex.split(typed.replace("VALUE", "zqm-made-up"))

    assert f"`{typed}`" in section(repo_root)
    assert f"`{shown}`" in section(repo_root)
    assert model.public_command(args) == shown
    assert model.hashed_argv(args) == shlex.split(shown)


@pytest.mark.parametrize(("typed", "shown"), EVAL_EXAMPLES)
def test_each_eval_example_of_the_section_is_what_the_code_shows_and_hashes(
    repo_root: Path, typed: str, shown: str
) -> None:
    args = shlex.split(typed.replace("VALUE", "zqm-made-up"))

    assert EVAL_SENTENCE in section(repo_root)
    assert f"`{typed}` shows `{shown}`" in section(repo_root)
    assert model.public_command(args) == shown
    assert model.hashed_argv(args) == shlex.split(shown)


def test_the_backquote_example_of_the_section_is_what_the_code_shows_and_hashes(
    repo_root: Path,
) -> None:
    typed, shown = BACKQUOTE_EXAMPLE
    args = shlex.split(typed.replace("VALUE", "zqm-made-up"))

    assert BACKQUOTE_SENTENCE in section(repo_root)
    assert f"``{typed}`` shows ``{shown}``" in section(repo_root)
    assert model.public_command(args) == shown
    assert model.hashed_argv(args) == shlex.split(shown)


def test_the_section_says_where_else_an_eval_is_read_and_what_a_line_continuation_joins(
    repo_root: Path,
) -> None:
    text = section(repo_root)

    for sentence in EVAL_PLACES:
        assert sentence in text
    assert LINE_CONTINUATION in text


@pytest.mark.parametrize(("typed", "shown"), REDIRECTION_EXAMPLES)
def test_each_redirection_example_of_the_section_is_what_the_code_shows_and_hashes(
    repo_root: Path, typed: str, shown: str
) -> None:
    args = shlex.split(typed.replace("VALUE", "zqm-made-up"))

    assert f"`{typed}` shows `{shown}`" in section(repo_root)
    assert model.public_command(args) == shown
    assert model.hashed_argv(args) == shlex.split(shown)


def test_the_section_says_a_redirection_is_no_word_of_a_command(repo_root: Path) -> None:
    text = section(repo_root)

    assert (
        "a redirection such as `2>&1`, `>out` or `>|out` ends no command and is no word of it, "
        "so the option before it still takes the word after it"
    ) in text
    assert (
        "After `AUTH`, a word that another word of the same command follows, past any "
        "redirection such as `>out.log`, is the user name"
    ) in text


def test_the_section_says_where_a_client_command_ends(repo_root: Path) -> None:
    text = section(repo_root)

    assert (
        "Its options hold up to the end of its command. In a shell text an operator outside "
        "quotes ends the command, and one in quotes does not"
    ) in text
    assert (
        "In an argument list that no shell reads, no word ends the command, not even a word "
        "that is an operator on its own"
    ) in text
    assert "Substitutions inside substitutions are read eight deep" in text
    assert model._SHELL_DEPTH == 8

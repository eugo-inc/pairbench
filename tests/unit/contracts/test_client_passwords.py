# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""The password options of common benchmark clients, as the shown command hides them.

Each client takes its password in an option whose name says nothing of a
password (``redis-benchmark -a``, ``mysql -p``, ``ab -A``), so the option is
read with the program it belongs to. Every value here is made up; each
hidden one is a word of six small letters that no command writes by itself.
"""

from __future__ import annotations

import shlex

import pytest

from pairbench import model

LEAD = ("pairbench", "run", "--")
SHOWN_LEAD = "pairbench run -- "

# (arguments of the workload, the command the results show)
HIDDEN_FORMS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("redis-benchmark", "-a", "zqmsaa", "-n", "100"), "redis-benchmark -a '<hidden>' -n 100"),
    (("redis-benchmark", "-azqmsab", "-q"), "redis-benchmark '-a<hidden>' -q"),
    (("redis-cli", "-a", "zqmsac", "ping"), "redis-cli -a '<hidden>' ping"),
    (("valkey-benchmark", "-a", "zqmsad"), "valkey-benchmark -a '<hidden>'"),
    (("valkey-cli", "-a", "zqmsae"), "valkey-cli -a '<hidden>'"),
    (("memtier_benchmark", "-a", "zqmsaf", "-n", "10"), "memtier_benchmark -a '<hidden>' -n 10"),
    (("memtier_benchmark", "-azqmsag"), "memtier_benchmark '-a<hidden>'"),
    (
        ("memtier_benchmark", "--authenticate", "zqmsah"),
        "memtier_benchmark --authenticate '<hidden>'",
    ),
    (("memtier_benchmark", "--authenticate=zqmsai"), "memtier_benchmark '--authenticate=<hidden>'"),
    (("mysql", "-pzqmsaj", "benchdb"), "mysql '-p<hidden>' benchdb"),
    (("mysqlslap", "-pzqmsak", "--iterations=5"), "mysqlslap '-p<hidden>' --iterations=5"),
    (("mysqladmin", "-pzqmsal", "status"), "mysqladmin '-p<hidden>' status"),
    (("mariadb", "-pzqmsam"), "mariadb '-p<hidden>'"),
    (("mariadb-slap", "-pzqmsan"), "mariadb-slap '-p<hidden>'"),
    (("mariadb-admin", "-pzqmsao", "status"), "mariadb-admin '-p<hidden>' status"),
    (("sshpass", "-p", "zqmsap", "ssh", "bench-host"), "sshpass -p '<hidden>' ssh bench-host"),
    (("sshpass", "-pzqmsaq", "ssh", "bench-host"), "sshpass '-p<hidden>' ssh bench-host"),
    (("ab", "-A", "someuser:zqmsar", "-n", "10"), "ab -A 'someuser:<hidden>' -n 10"),
    (("ab", "-P", "proxyuser:zqmsas", "-n", "10"), "ab -P 'proxyuser:<hidden>' -n 10"),
    (("ab", "-Asomeuser:zqmsat"), "ab '-Asomeuser:<hidden>'"),
    (("ab", "-Pproxyuser:zqmsau"), "ab '-Pproxyuser:<hidden>'"),
    (("curl", "-u", "someuser:zqmsav", "x"), "curl -u 'someuser:<hidden>' x"),
    (("curl", "--user", "someuser:zqmsaw", "x"), "curl --user 'someuser:<hidden>' x"),
    (("curl", "--user=someuser:zqmsda", "x"), "curl '--user=someuser:<hidden>' x"),
    (("curl", "-usomeuser:zqmsdb", "x"), "curl '-usomeuser:<hidden>' x"),
    (("curl", "-Uproxyuser:zqmsdc", "x"), "curl '-Uproxyuser:<hidden>' x"),
    (("curl", "-U", "proxyuser:zqmsax", "x"), "curl -U 'proxyuser:<hidden>' x"),
    (("curl", "--proxy-user", "proxyuser:zqmsay", "x"), "curl --proxy-user 'proxyuser:<hidden>' x"),
    (("curl", "--proxy-user=proxyuser:zqmsaz", "x"), "curl '--proxy-user=proxyuser:<hidden>' x"),
)

# The same letters where they mean something else, and the database name after a ``-p``
# that stands alone: mysql then asks for the password, and the next word is no password.
SHOWN_FORMS: tuple[tuple[str, ...], ...] = (
    ("mysql", "-p", "benchdb"),
    ("mysqladmin", "-p", "status"),
    ("ab", "-p", "post.txt", "-n", "10"),
    ("curl", "-A", "agent/1.0", "x"),
    ("tool", "-a", "value"),
    ("ls", "-a"),
    ("tar", "-pxf", "x.tar"),
    ("tool", "-A", "user:value"),
    ("tool", "-P", "user:value"),
)


@pytest.mark.parametrize(("args", "shown"), HIDDEN_FORMS)
def test_a_client_password_option_is_hidden(args: tuple[str, ...], shown: str) -> None:
    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shown


@pytest.mark.parametrize(("args", "shown"), HIDDEN_FORMS)
def test_a_client_password_option_is_hidden_inside_sh_c(args: tuple[str, ...], shown: str) -> None:
    inner = " ".join(shlex.split(shown))

    assert model.public_command((*LEAD, "sh", "-c", shlex.join(args))) == SHOWN_LEAD + shlex.join(
        ["sh", "-c", inner]
    )


@pytest.mark.parametrize(("args", "shown"), HIDDEN_FORMS)
def test_a_client_password_option_is_hidden_in_one_text(args: tuple[str, ...], shown: str) -> None:
    assert model.public_words(shlex.join(args)) == " ".join(shlex.split(shown))


@pytest.mark.parametrize("args", SHOWN_FORMS)
def test_the_same_letters_elsewhere_are_shown(args: tuple[str, ...]) -> None:
    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(args)
    assert model.public_command((*LEAD, "sh", "-c", shlex.join(args))) == (
        SHOWN_LEAD + shlex.join(["sh", "-c", shlex.join(args)])
    )


@pytest.mark.parametrize(
    ("args", "shown"),
    [
        # The program named by a path, after env, sudo, docker exec or a shell.
        (("/usr/bin/redis-benchmark", "-a", "zqmsba"), ("redis-benchmark", "-a", "<hidden>")),
        (
            ("env", "BENCH_HOST=localhost", "redis-benchmark", "-a", "zqmsbb"),
            ("env", "BENCH_HOST=localhost", "redis-benchmark", "-a", "<hidden>"),
        ),
        (
            ("sudo", "-u", "bench", "mysql", "-pzqmsbc"),
            ("sudo", "-u", "bench", "mysql", "-p<hidden>"),
        ),
        (
            ("docker", "exec", "-i", "box", "redis-benchmark", "-a", "zqmsbd"),
            ("docker", "exec", "-i", "box", "redis-benchmark", "-a", "<hidden>"),
        ),
        (("bash", "-lc", "mysqlslap -pzqmsbe"), ("bash", "-lc", "mysqlslap -p<hidden>")),
        (
            ("sh", "-c", "./redis-benchmark -a zqmsbf -q"),
            ("sh", "-c", "./redis-benchmark -a <hidden> -q"),
        ),
        # A quoted value, and a value glued to its option in quotes.
        (
            ("sh", "-c", "redis-benchmark -a 'zqmsbg' -q"),
            ("sh", "-c", "redis-benchmark -a <hidden> -q"),
        ),
        (("sh", "-c", "mysql '-pzqmsbh' benchdb"), ("sh", "-c", "mysql '-p<hidden>' benchdb")),
        # The client of a word after a command separator.
        (
            ("sh", "-c", "true;redis-benchmark -a zqmsbi"),
            ("sh", "-c", "true;redis-benchmark -a <hidden>"),
        ),
        (("sh", "-c", "true && mysql -pzqmsbj"), ("sh", "-c", "true && mysql -p<hidden>")),
        # The command sshpass runs is read with its own options: ssh's -p is a port.
        (
            ("sshpass", "-p", "zqmsbk", "ssh", "-p", "2222", "bench-host"),
            ("sshpass", "-p", "<hidden>", "ssh", "-p", "2222", "bench-host"),
        ),
        (
            ("sshpass", "-p", "zqmsbl", "redis-benchmark", "-a", "zqmsbm"),
            ("sshpass", "-p", "<hidden>", "redis-benchmark", "-a", "<hidden>"),
        ),
        # A separator ends the client's command: what follows is read with its own program.
        (
            ("sh", "-c", "redis-benchmark -a zqmsbn; ls -a"),
            ("sh", "-c", "redis-benchmark -a <hidden>; ls -a"),
        ),
        (
            ("sh", "-c", "mysql -pzqmsbo benchdb | ab -p post.txt x"),
            ("sh", "-c", "mysql -p<hidden> benchdb | ab -p post.txt x"),
        ),
        # A separator right after a hidden glued value stays, so the next command stays apart.
        (
            ("sh", "-c", "mysqlslap -pzqmsbp; mysqladmin status"),
            ("sh", "-c", "mysqlslap -p<hidden>; mysqladmin status"),
        ),
        (
            ("sh", "-c", "memtier_benchmark -azqmsbq&& ls"),
            ("sh", "-c", "memtier_benchmark -a<hidden>&& ls"),
        ),
        (
            ("sh", "-c", "ab -Asomeuser:zqmsbr; ls"),
            ("sh", "-c", "ab -Asomeuser:<hidden>; ls"),
        ),
        (("sh", "-c", "tool --token=zqmsbs; ls"), ("sh", "-c", "tool --token=<hidden>; ls")),
    ],
)
def test_the_client_is_found_where_it_is_run(args: tuple[str, ...], shown: tuple[str, ...]) -> None:
    assert model.public_command((*LEAD, *args)) == SHOWN_LEAD + shlex.join(shown)


def test_ssh_options_after_sshpass_are_read_as_ssh_reads_them() -> None:
    text = "sshpass -f pass.txt ssh -p 2222 bench-host"

    assert model.public_words(text) == text


def test_the_capture_keeps_the_client_password_as_typed() -> None:
    argv = (*LEAD, "redis-benchmark", "-a", "zqmsca", "mysql", "-pzqmscb")

    assert model.redact_argv(argv) == argv

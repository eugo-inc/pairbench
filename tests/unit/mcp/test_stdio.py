# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""``pairbench mcp`` with the real SDK: a client handshake over standard input and output.

Skipped where the ``mcp`` extra is not installed; the other tests of this
folder use a fake of the SDK.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="needs the mcp extra (pip install pairbench[mcp])")

from pairbench.mcp import server

WAIT_S = 60.0
PROTOCOL_VERSION = "2025-06-18"


class Client:
    """A minimal client of the protocol: one JSON message per line."""

    def __init__(self, repo_root: Path, *args: str) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(repo_root / "src"), *filter(None, [env.get("PYTHONPATH")])]
        )
        self.process = subprocess.Popen(
            [sys.executable, "-m", "pairbench", "mcp", *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.seen: list[str] = []
        # Answers read while waiting for another: a server may answer calls out of order.
        self.early: dict[int, dict[str, Any]] = {}
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def reply(self, ident: int) -> dict[str, Any]:
        if ident in self.early:
            return self.early.pop(ident)
        while True:
            line = self.lines.get(timeout=WAIT_S)
            if line is None:
                raise AssertionError(f"the server ended before answering {ident}")
            self.seen.append(line)
            message: dict[str, Any] = json.loads(line)
            if message.get("id") == ident:
                return message
            if isinstance(message.get("id"), int):
                self.early[message["id"]] = message

    def close(self) -> tuple[int, str]:
        assert self.process.stdin is not None
        self.process.stdin.close()
        try:
            code = self.process.wait(timeout=WAIT_S)
        finally:
            if self.process.poll() is None:
                self.process.kill()
        rest = self.process.stderr.read() if self.process.stderr is not None else ""
        while True:
            line = self.lines.get(timeout=WAIT_S)
            if line is None:
                break
            self.seen.append(line)
        return code, rest


def handshake(client: Client) -> dict[str, Any]:
    client.send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "0"},
            },
        }
    )
    answer = client.reply(1)
    client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return answer


def test_a_client_lists_the_tools_and_calls_one(repo_root: Path) -> None:
    client = Client(repo_root)
    try:
        hello = handshake(client)
        client.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = client.reply(2)
        client.send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "explain", "arguments": {"term": "twin"}},
            }
        )
        called = client.reply(3)
    finally:
        code, _err = client.close()

    assert hello["result"]["serverInfo"]["name"] == "pairbench"
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == set(server.TOOL_NAMES) - set(server.RUN_TOOLS)
    content = called["result"]["content"]
    assert json.loads(content[0]["text"])["text"] == server.GLOSSARY["twin"]
    assert code == 0
    for line in client.seen:
        assert json.loads(line)["jsonrpc"] == "2.0"


def test_with_allow_run_the_run_tools_are_listed(repo_root: Path) -> None:
    client = Client(repo_root, "--allow-run")
    try:
        handshake(client)
        client.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = client.reply(2)
    finally:
        client.close()

    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == set(server.TOOL_NAMES)


def test_a_tool_that_prints_does_not_break_the_protocol_stream(repo_root: Path) -> None:
    client = Client(repo_root)
    try:
        handshake(client)
        client.send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "selftest", "arguments": {}},
            }
        )
        called = client.reply(2)
    finally:
        client.close()

    assert json.loads(called["result"]["content"][0]["text"])["passed"] is True
    for line in client.seen:
        assert json.loads(line)["jsonrpc"] == "2.0"


# What a client reads when it calls a run tool of a server started without --allow-run.
WITHOUT_ALLOW_RUN = (
    "this server was started without --allow-run, so it does not offer {tool}: start it with "
    "pairbench mcp --allow-run"
)
RUN_TOOL_CALLS = [
    ("run_start", {"sides": ["new=cmd:true", "old=cmd:true"], "rounds": "8"}),
    ("run_start", {"made_up_argument_a": 1}),
    ("run_start", {}),
    ("run_cancel", {"handle": "made-up-handle-a"}),
    ("run_cancel", {}),
]


def test_without_allow_run_a_run_tool_answers_how_to_start_the_server_with_it(
    repo_root: Path,
) -> None:
    client = Client(repo_root)
    try:
        handshake(client)
        for ident, (tool, arguments) in enumerate(RUN_TOOL_CALLS, start=2):
            client.send(
                {
                    "jsonrpc": "2.0",
                    "id": ident,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments},
                }
            )
        replies = [client.reply(ident) for ident in range(2, 2 + len(RUN_TOOL_CALLS))]
    finally:
        code, _err = client.close()

    for (tool, arguments), reply in zip(RUN_TOOL_CALLS, replies, strict=True):
        result = reply["result"]
        assert result.get("isError", False) is False, (tool, arguments, result)
        refused = json.loads(result["content"][0]["text"])["refusal"]
        assert (refused["code"], refused["exit_code"], refused["message"]) == (
            "E_USAGE",
            2,
            WITHOUT_ALLOW_RUN.format(tool=tool),
        ), (tool, arguments)
    assert code == 0

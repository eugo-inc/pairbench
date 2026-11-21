# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""What a published hash is taken over is a fixed point of the hiding.

``hashed_argv``, ``hashed_output``, ``fingerprint_inputs`` and ``config_inputs`` return the
values a published hash is the SHA-256 of, with the recognised secret forms hidden. Hiding
those values again changes nothing, for every recognised form. That is what lets a check of a
kept results file tell inputs written after hiding from inputs that still hold a secret.
"""

from __future__ import annotations

from typing import Any

import pytest

from pairbench import model
from pairbench.model import (
    HIDDEN,
    Experiment,
    LaunchSettings,
    canonical_json,
    config_sha256,
    fingerprint_of,
    hashed_argv,
    sha256_hex,
)

SECRET = "kiwi7"
RANDOM = "X1y2Z3x4Y5z6X7y8Z9x0Y1z2X3y4Z5x6"
# Each recognised form, as an argument list with ``{}`` standing for the secret.
FORMS: dict[str, tuple[str, ...]] = {
    "credential-option": ("made-up-tool", "--password", "{}"),
    "credential-option-with-equals": ("made-up-tool", "--api-key={}"),
    "credential-variable": ("env", "API_TOKEN={}", "made-up-tool"),
    "credential-header": ("curl", "-H", "Authorization: Bearer {}", "http://localhost:8000/v1"),
    "address-user-part": ("made-up-tool", "--url", "https://madeup:{}@made-up.example/v1"),
    "user-and-password": ("curl", "-u", "madeup:{}", "http://localhost:8000/"),
    "client-password-option": ("redis-benchmark", "-a", "{}"),
    "client-password-glued": ("mysql", "-p{}"),
    "name-in-program-text": ("python3", "-c", "import os; os.environ['API_KEY'] = '{}'"),
    "nested-shell-command": ("sh", "-c", "made-up-tool --token {}"),
    "random-looking-value": ("made-up-tool", "--model", RANDOM),
    "plus-slash-run": ("made-up-tool", f"{RANDOM}+/ab/{RANDOM}"),
    "glued-to-a-short-option": ("made-up-tool", f"-kab/{RANDOM}"),
    "random-part-of-a-path": ("made-up-tool", f"/made/up/{RANDOM}/w.bin"),
}
# An identify output with a header, an assignment, a random-looking value and plain lines. Its
# hash hides the credentials only: the random-looking value, a build id, is hashed as printed.
OUTPUT = (
    "made-up-tool 1.2\r\n"
    f"Authorization: Bearer {SECRET}\n"
    f"API_TOKEN={SECRET} MADE_UP_MODE=fast\n"
    f"build {RANDOM}\n"
    f"source https://madeup:{SECRET}@made-up.example/x\n"
    "\n"
    "last line"
)
OUTPUT_HIDDEN = (
    "made-up-tool 1.2\r\n"
    f"Authorization: {HIDDEN}\n"
    f"API_TOKEN={HIDDEN} MADE_UP_MODE=fast\n"
    f"build {RANDOM}\n"
    f"source https://{HIDDEN}@made-up.example/x\n"
    "\n"
    "last line"
)


def typed(form: tuple[str, ...]) -> list[str]:
    return [part.replace("{}", SECRET) for part in form]


@pytest.mark.parametrize("form", list(FORMS.values()), ids=list(FORMS))
def test_a_hidden_argument_list_is_a_fixed_point(form: tuple[str, ...]) -> None:
    once = hashed_argv(typed(form))

    assert SECRET not in canonical_json(once)
    assert hashed_argv(once) == once


@pytest.mark.parametrize("form", list(FORMS.values()), ids=list(FORMS))
def test_a_hidden_identify_output_is_a_fixed_point(form: tuple[str, ...]) -> None:
    once = model.hashed_output(" ".join(typed(form)) + "\nmade-up-tool 1.2\n")

    assert once.endswith("\nmade-up-tool 1.2\n")
    assert model.hashed_output(once) == once


def test_an_identify_output_of_several_lines_hides_each_form_on_its_own_line() -> None:
    once = model.hashed_output(OUTPUT)

    assert once == OUTPUT_HIDDEN
    assert model.hashed_output(once) == once


def test_the_fingerprint_is_the_hash_of_its_inputs_and_they_are_a_fixed_point() -> None:
    identity = {"executable": "/usr/bin/made-up-tool", "identify_output": OUTPUT}
    launch = LaunchSettings(
        env={"API_TOKEN": SECRET, "MADE_UP_FLAGS": f"--token {SECRET}"},
        env_pass=("HF_TOKEN",),
        mounts=("/work/made-up:/data:ro",),
    ).effective(args=typed(FORMS["credential-option"]), entrypoint="made-up-entry")

    once = model.fingerprint_inputs(identity, launch)

    assert fingerprint_of(identity, launch) == sha256_hex(canonical_json(once))
    assert SECRET not in canonical_json(once)
    assert once["identity"]["identify_output"] == OUTPUT_HIDDEN
    assert model.fingerprint_inputs(once["identity"], once["launch"]) == once


def command_config(secret: str) -> dict[str, Any]:
    return Experiment.from_json(
        {
            "workload": {"argv": ["made-up-load", "--token", secret]},
            "sides": {
                "a": {
                    "cmd": ["made-up-tool", "--password", secret, "{workload}"],
                    "baseline": True,
                    "launch": {"env": {"API_TOKEN": secret}},
                },
                "b": {
                    "image": "registry.example/made-up:1",
                    "entrypoint": "redis-benchmark",
                    "args": ["-a", secret],
                    "env": {"MADE_UP_URL": f"postgres://madeup:{secret}@made-up.example/db"},
                },
            },
            "launch": {"identify": ["made-up-tool", "-H", f"Authorization: Bearer {secret}"]},
        }
    ).to_json()


def serving_config(secret: str) -> dict[str, Any]:
    return Experiment.from_json(
        {
            "workload": {"driver": "guidellm", "levels": [1]},
            "sides": {
                "c": {
                    "baseline": True,
                    "serve": {
                        "image": "registry.example/made-up:1",
                        "args": ["--api-key", secret],
                        "probe": {"path": f"/v1/check?api_key={secret}"},
                    },
                },
                "d": {
                    "serve": {
                        "launcher": "host",
                        "command": ["made-up-server", "--token", secret],
                        "args": ["--port", "8000"],
                    }
                },
            },
        }
    ).to_json()


@pytest.mark.parametrize("make", [command_config, serving_config], ids=["command", "serving"])
def test_the_config_hash_is_the_hash_of_its_inputs_and_they_are_a_fixed_point(make: Any) -> None:
    once = model.config_inputs(make(SECRET))

    assert config_sha256(make(SECRET)) == sha256_hex(canonical_json(once))
    assert SECRET not in canonical_json(once)
    assert model.config_inputs(once) == once

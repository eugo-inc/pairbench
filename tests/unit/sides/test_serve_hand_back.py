# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Eugo, Inc.
"""A serving launch hands its container's files back however it ends.

The server's container may write into the launch folder as another user,
such as root. Whether the launch ends as it should, on an error, on an
interrupt or on a refusal after the server is stopped, one short container
gives those files back to the caller after the server is stopped and
removed, and before the launch's exception goes on. When that cannot be
done, a note names the launch folder every time, and the exception that
stopped the launch is the one that goes on, unless an interrupt stopped the
hand-back itself.

The tests cannot give files to another user, so the side is told the caller
is someone else until the hand-back has run.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from pairbench import api
from pairbench.errors import Refusal
from pairbench.model import LaunchSettings
from pairbench.sides import container, serve
from pairbench.sides.base import Completed

from .test_serve import (
    FAKE_SERVER,
    NAME,
    EngineStandIn,
    FakeEngine,
    FakeGpu,
    Load,
    container_kind,
    container_side,
    ctx,
)

FOLDER = ("artifacts", "0003-new")
REMOVE_SERVER = ("/usr/bin/docker", "rm", "--force", NAME)
KEPT = (
    "files a container of side new wrote in artifacts/0003-new of the run folder still belong "
    "to the user its image runs as, so other users may be able to read them and you may not be "
    "able to delete them: "
)


class HandBackEngine(FakeEngine):
    """A fake engine whose ``chown`` container and ``stop`` can be made to fail."""

    def __init__(
        self,
        *,
        chown: Callable[[], Completed] | None = None,
        stop_raises: BaseException | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.chown = chown
        self.stop_raises = stop_raises
        # For each removal of the server's container, whether every engine
        # client started so far had exited by then.
        self.clients_gone_at_remove: list[bool] = []

    def __call__(self, argv: tuple[str, ...]) -> Completed:
        if argv == REMOVE_SERVER and self.processes is not None:
            self.clients_gone_at_remove.append(
                all(process.exited() is not None for process in self.processes.started)
            )
        if argv[1] == "run" and "chown" in argv and self.chown is not None:
            self.calls.append(argv)
            return self.chown()
        done = super().__call__(argv)
        if argv[1] == "stop" and self.stop_raises is not None:
            raise self.stop_raises
        return done


@pytest.fixture
def script(tmp_path: Path) -> Path:
    path = tmp_path / "fake_server.py"
    path.write_text(FAKE_SERVER, encoding="utf-8")
    return path


def _chowns(engine: FakeEngine) -> list[tuple[str, ...]]:
    return [call for call in engine.calls if call[1] == "run" and "chown" in call]


def _seen_as_another_user_s(
    monkeypatch: pytest.MonkeyPatch, until: Callable[[], bool] = lambda: False
) -> None:
    look = container.foreign_entries

    def foreign(folder: Path, uid: int) -> list[Path]:
        return [] if until() else look(folder, uid + 1)

    monkeypatch.setattr(container, "foreign_entries", foreign)


def _launch(tmp_path: Path, load: Load) -> api.LaunchRequest:
    folder = tmp_path.joinpath(*FOLDER)
    folder.mkdir(parents=True)
    (folder / "export.txt").write_text("a made-up export\n", encoding="utf-8")
    return api.LaunchRequest(
        run_id="run-a",
        seq=3,
        phase="round",
        round=1,
        pos=1,
        name="new",
        artifacts=folder,
        load=load,
    )


def _raising(stop: BaseException) -> Load:
    def during(endpoint: api.Endpoint) -> None:
        raise stop

    return Load(during)


def _chown_error() -> Completed:
    raise RuntimeError("a made-up failure")


def _handed_back_once_after_the_server_is_removed(engine: FakeEngine) -> None:
    chowns = _chowns(engine)
    assert len(chowns) == 1
    assert engine.calls.index(chowns[0]) > engine.calls.index(REMOVE_SERVER)
    assert ("/usr/bin/docker", "rm", "--force", f"{NAME}-chown") in engine.calls


@pytest.mark.parametrize(
    "stop",
    [
        KeyboardInterrupt(),
        RuntimeError("a made-up failure"),
        Refusal("E_INTERNAL", "a made-up refusal"),
    ],
    ids=["interrupt", "error", "refusal"],
)
def test_a_serving_launch_stopped_during_its_load_hands_its_files_back_first(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop: BaseException
) -> None:
    processes = EngineStandIn(script, {})
    engine = HandBackEngine(processes=processes)
    _seen_as_another_user_s(monkeypatch, until=lambda: bool(_chowns(engine)))
    notes: list[tuple[str, str]] = []
    resolved = container_kind(engine, processes).resolve(container_side(), ctx(notes=notes))
    with pytest.raises(type(stop)) as caught:
        resolved.launch(_launch(tmp_path, _raising(stop)))
    assert caught.value is stop
    _handed_back_once_after_the_server_is_removed(engine)
    assert notes == []


def test_a_serving_launch_interrupted_while_its_server_stops_hands_its_files_back(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes = EngineStandIn(script, {})
    second = KeyboardInterrupt()
    engine = HandBackEngine(processes=processes, stop_raises=second)
    _seen_as_another_user_s(monkeypatch, until=lambda: bool(_chowns(engine)))
    notes: list[tuple[str, str]] = []
    resolved = container_kind(engine, processes).resolve(container_side(), ctx(notes=notes))
    with pytest.raises(KeyboardInterrupt) as caught:
        resolved.launch(_launch(tmp_path, Load()))
    assert caught.value is second
    _handed_back_once_after_the_server_is_removed(engine)
    assert notes == []


def test_a_serving_launch_whose_gpu_memory_is_not_released_hands_its_files_back(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes = EngineStandIn(script, {})
    engine = HandBackEngine(processes=processes)
    _seen_as_another_user_s(monkeypatch, until=lambda: bool(_chowns(engine)))
    gpu = FakeGpu(memory=(1000.0, 1064.5))
    resolved = container_kind(engine, processes).resolve(container_side(), ctx(gpu=gpu))
    with pytest.raises(Refusal) as caught:
        resolved.launch(_launch(tmp_path, Load()))
    assert caught.value.code == "E_GPU_NOT_RELEASED"
    _handed_back_once_after_the_server_is_removed(engine)


@pytest.mark.parametrize(
    ("chown", "reason"),
    [
        (
            lambda: Completed(125, "", "made-up engine failure"),
            "the engine could not run the container that runs chown (exit 125)",
        ),
        (_chown_error, "the hand-back stopped on an error (RuntimeError)"),
    ],
    ids=["engine-failed", "hand-back-error"],
)
def test_an_interrupted_serving_launch_whose_files_cannot_be_handed_back_names_the_folder(
    script: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chown: Callable[[], Completed],
    reason: str,
) -> None:
    _seen_as_another_user_s(monkeypatch)
    processes = EngineStandIn(script, {})
    engine = HandBackEngine(processes=processes, chown=chown)
    notes: list[tuple[str, str]] = []
    resolved = container_kind(engine, processes).resolve(container_side(), ctx(notes=notes))
    first = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt) as caught:
        resolved.launch(_launch(tmp_path, _raising(first)))
    assert caught.value is first
    assert notes == [("files_not_handed_back", KEPT + reason)]


def test_an_interrupt_during_the_hand_back_names_the_folder_and_goes_on(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seen_as_another_user_s(monkeypatch)
    processes = EngineStandIn(script, {})
    second = KeyboardInterrupt()

    def interrupted() -> Completed:
        raise second

    engine = HandBackEngine(processes=processes, chown=interrupted)
    notes: list[tuple[str, str]] = []
    resolved = container_kind(engine, processes).resolve(container_side(), ctx(notes=notes))
    with pytest.raises(KeyboardInterrupt) as caught:
        resolved.launch(_launch(tmp_path, _raising(RuntimeError("a made-up failure"))))
    assert caught.value is second
    assert ("/usr/bin/docker", "rm", "--force", f"{NAME}-chown") in engine.calls
    assert notes == [
        ("files_not_handed_back", KEPT + "an interrupt stopped the hand-back before it ended")
    ]


def test_every_stopped_serving_launch_whose_files_stay_is_named(
    script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seen_as_another_user_s(monkeypatch)
    processes = EngineStandIn(script, {})
    engine = HandBackEngine(processes=processes, chown=lambda: Completed(1))
    notes: list[tuple[str, str]] = []
    resolved = container_kind(engine, processes).resolve(container_side(), ctx(notes=notes))
    for seq in (3, 4):
        folder = tmp_path / "artifacts" / f"000{seq}-new"
        folder.mkdir(parents=True)
        launch = api.LaunchRequest(
            run_id="run-a",
            seq=seq,
            phase="round",
            round=1,
            pos=1,
            name="new",
            artifacts=folder,
            load=_raising(RuntimeError("a made-up failure")),
        )
        with pytest.raises(RuntimeError):
            resolved.launch(launch)
    assert [text for _code, text in notes] == [
        KEPT + "chown in the image exited with 1",
        KEPT.replace("0003-new", "0004-new") + "chown in the image exited with 1",
    ]


@pytest.fixture
def stand_in(script: Path) -> Iterator[EngineStandIn]:
    """The engine's stand-in; a server it started and the side left running is killed after."""
    processes = EngineStandIn(script, {})
    yield processes
    for process in processes.started:
        process.kill_session()


def _cut_short_after_the_engine_starts(
    monkeypatch: pytest.MonkeyPatch, where: str, stop: BaseException
) -> None:
    """Make the server's start stop once the engine's ``run`` command is running."""

    def raising(*args: Any, **kwargs: Any) -> Any:
        raise stop

    if where == "watcher":
        monkeypatch.setattr(container.PidWatcher, "start", raising)
    else:
        monkeypatch.setattr(serve, "LogReader", raising)


@pytest.mark.parametrize(
    "stop", [KeyboardInterrupt(), RuntimeError("a made-up failure")], ids=["interrupt", "error"]
)
@pytest.mark.parametrize("where", ["watcher", "output-reader"])
def test_a_serving_start_stopped_after_the_engine_runs_removes_the_server_and_hands_back(
    stand_in: EngineStandIn,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    where: str,
    stop: BaseException,
) -> None:
    processes = stand_in
    engine = HandBackEngine(processes=processes)
    _seen_as_another_user_s(monkeypatch, until=lambda: bool(_chowns(engine)))
    notes: list[tuple[str, str]] = []
    resolved = container_kind(engine, processes).resolve(container_side(), ctx(notes=notes))
    _cut_short_after_the_engine_starts(monkeypatch, where, stop)
    with pytest.raises(type(stop)) as caught:
        resolved.launch(_launch(tmp_path, Load()))
    assert caught.value is stop
    _handed_back_once_after_the_server_is_removed(engine)
    # The engine's client is down before the container is removed, so it
    # cannot start the container after the removal.
    assert engine.clients_gone_at_remove == [True]
    assert [process.exited() is not None for process in processes.started] == [True]
    assert notes == []


def test_a_serving_start_stopped_after_the_engine_runs_names_files_it_cannot_hand_back(
    stand_in: EngineStandIn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seen_as_another_user_s(monkeypatch)
    processes = stand_in
    engine = HandBackEngine(processes=processes, chown=lambda: Completed(125, "", "made-up"))
    notes: list[tuple[str, str]] = []
    resolved = container_kind(engine, processes).resolve(container_side(), ctx(notes=notes))
    first = KeyboardInterrupt()
    _cut_short_after_the_engine_starts(monkeypatch, "watcher", first)
    with pytest.raises(KeyboardInterrupt) as caught:
        resolved.launch(_launch(tmp_path, Load()))
    assert caught.value is first
    assert notes == [
        (
            "files_not_handed_back",
            KEPT + "the engine could not run the container that runs chown (exit 125)",
        )
    ]


def test_a_serving_launch_that_runs_past_its_timeout_hands_its_files_back(
    stand_in: EngineStandIn, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes = stand_in
    engine = HandBackEngine(processes=processes)
    _seen_as_another_user_s(monkeypatch, until=lambda: bool(_chowns(engine)))
    notes: list[tuple[str, str]] = []

    def past_the_end(endpoint: api.Endpoint) -> None:
        assert endpoint.deadline is not None
        time.sleep(max(0.0, endpoint.deadline - time.monotonic()) + 0.1)

    resolved = container_kind(engine, processes).resolve(
        container_side(), ctx(LaunchSettings(timeout_s=1.0), notes=notes)
    )
    outcome = resolved.launch(_launch(tmp_path, Load(past_the_end)))
    assert (outcome.rc, outcome.timed_out) == (1, True)
    _handed_back_once_after_the_server_is_removed(engine)
    assert notes == []

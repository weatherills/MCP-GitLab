"""service.py: starting, stopping, and restarting mcp-gitlab as a detached background process.

Orchestration (start/stop/restart, pid file handling, the terminate-then-kill escalation) is
tested with injected fakes, so it runs the same on every platform and never waits on a real
clock. `_default_spawn` and the POSIX liveness check are also exercised against a real short-lived
subprocess, since that needs no live GitLab and is safe to run for real; the Windows liveness
check needs a real Windows process and is exercised only by its platform dispatch.
"""

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mcp_gitlab import service


class FakeIsAlive:
    """is_alive(pid) that returns each entry in `sequence` in turn, then repeats the last one."""

    def __init__(self, sequence: list[bool]) -> None:
        self.sequence = sequence
        self.calls: list[int] = []

    def __call__(self, pid: int) -> bool:
        self.calls.append(pid)
        index = min(len(self.calls) - 1, len(self.sequence) - 1)
        return self.sequence[index]


def _no_sleep(seconds: float) -> None:
    return None


def test_start_spawns_and_records_the_pid(tmp_path: Path) -> None:
    pid_file = tmp_path / "mcp-gitlab.pid"
    log_file = tmp_path / "service.log"
    spawned: list[tuple[tuple[str, ...], Path]] = []

    def fake_spawn(argv: tuple[str, ...], given_log_file: Path) -> int:
        spawned.append((argv, given_log_file))
        return 4242

    pid = service.start(
        ("mcp-gitlab", "serve"),
        pid_file=pid_file,
        log_file=log_file,
        spawn=fake_spawn,
        is_alive=lambda _pid: False,
    )

    assert pid == 4242
    assert pid_file.read_text().strip() == "4242"
    assert spawned == [(("mcp-gitlab", "serve"), log_file)]


def test_start_raises_when_already_running(tmp_path: Path) -> None:
    pid_file = tmp_path / "mcp-gitlab.pid"
    pid_file.write_text("123\n")

    with pytest.raises(service.ServiceError, match="already running"):
        service.start(
            ("mcp-gitlab", "serve"),
            pid_file=pid_file,
            log_file=tmp_path / "service.log",
            spawn=lambda argv, log_file: 999,
            is_alive=lambda _pid: True,
        )


def test_start_replaces_a_stale_pid_file(tmp_path: Path) -> None:
    pid_file = tmp_path / "mcp-gitlab.pid"
    pid_file.write_text("123\n")

    pid = service.start(
        ("mcp-gitlab", "serve"),
        pid_file=pid_file,
        log_file=tmp_path / "service.log",
        spawn=lambda argv, log_file: 456,
        is_alive=lambda _pid: False,
    )

    assert pid == 456
    assert pid_file.read_text().strip() == "456"


def test_running_pid_removes_an_unparseable_pid_file(tmp_path: Path) -> None:
    pid_file = tmp_path / "mcp-gitlab.pid"
    pid_file.write_text("not-a-pid\n")

    assert service.running_pid(pid_file, is_alive=lambda _pid: True) is None
    assert not pid_file.exists()


def test_running_pid_is_none_without_a_pid_file(tmp_path: Path) -> None:
    assert service.running_pid(tmp_path / "missing.pid", is_alive=lambda _pid: True) is None


def test_stop_raises_when_not_running(tmp_path: Path) -> None:
    with pytest.raises(service.ServiceError, match="not running"):
        service.stop(pid_file=tmp_path / "missing.pid", is_alive=lambda _pid: False)


def test_stop_signals_then_removes_the_pid_file_once_the_process_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "mcp-gitlab.pid"
    pid_file.write_text("789\n")
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(service.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    is_alive = FakeIsAlive([True, True, True, False])

    pid = service.stop(pid_file=pid_file, sleep=_no_sleep, is_alive=is_alive)

    assert pid == 789
    assert signals == [(789, signal.SIGTERM)]
    assert not pid_file.exists()


def test_stop_escalates_to_kill_after_the_grace_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "mcp-gitlab.pid"
    pid_file.write_text("321\n")
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(service.os, "kill", lambda pid, sig: signals.append((pid, sig)))

    service.stop(pid_file=pid_file, grace=0.0, sleep=_no_sleep, is_alive=lambda _pid: True)

    expected_kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
    assert signals == [(321, signal.SIGTERM), (321, expected_kill_signal)]


def test_stop_wraps_a_failed_signal_in_a_service_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "mcp-gitlab.pid"
    pid_file.write_text("321\n")

    def fail(pid: int, sig: int) -> None:
        raise PermissionError("not yours to signal")

    monkeypatch.setattr(service.os, "kill", fail)

    with pytest.raises(service.ServiceError, match="Could not signal"):
        service.stop(pid_file=pid_file, is_alive=lambda _pid: True)


def test_restart_stops_the_old_process_and_starts_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "mcp-gitlab.pid"
    pid_file.write_text("111\n")
    log_file = tmp_path / "service.log"
    stopped: list[int] = []
    monkeypatch.setattr(service.os, "kill", lambda pid, sig: stopped.append(pid))

    pid = service.restart(
        ("mcp-gitlab", "serve"),
        pid_file=pid_file,
        log_file=log_file,
        sleep=_no_sleep,
        spawn=lambda argv, log_file: 222,
        is_alive=lambda checked_pid: checked_pid == 111 and checked_pid not in stopped,
    )

    assert stopped == [111]
    assert pid == 222
    assert pid_file.read_text().strip() == "222"


def test_restart_starts_fresh_when_nothing_was_running(tmp_path: Path) -> None:
    pid_file = tmp_path / "mcp-gitlab.pid"
    pid = service.restart(
        ("mcp-gitlab", "serve"),
        pid_file=pid_file,
        log_file=tmp_path / "service.log",
        sleep=_no_sleep,
        spawn=lambda argv, log_file: 333,
        is_alive=lambda _pid: False,
    )
    assert pid == 333


def test_default_pid_file_uses_the_environment_override(tmp_path: Path) -> None:
    override = tmp_path / "custom" / "pid"
    assert service.default_pid_file({"MCP_GITLAB_PID_FILE": str(override)}) == override


def test_default_log_file_uses_the_environment_override(tmp_path: Path) -> None:
    override = tmp_path / "custom" / "log"
    assert service.default_log_file({"MCP_GITLAB_SERVICE_LOG_FILE": str(override)}) == override


def test_default_pid_file_falls_back_to_the_home_directory() -> None:
    assert service.default_pid_file({}) == service.DEFAULT_STATE_DIR / "mcp-gitlab.pid"


def test_is_alive_dispatches_to_the_windows_checker_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service.sys, "platform", "win32")
    monkeypatch.setattr(service, "_is_alive_windows", lambda pid: pid == 42)
    assert service._is_alive(42) is True
    assert service._is_alive(7) is False


def test_is_alive_dispatches_to_the_posix_checker_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service, "_is_alive_posix", lambda pid: pid == 42)
    assert service._is_alive(42) is True
    assert service._is_alive(7) is False


def test_is_alive_windows_refuses_to_run_off_windows() -> None:
    if sys.platform == "win32":
        pytest.skip("this asserts the guard that only applies when sys.platform is not win32")
    with pytest.raises(AssertionError):
        service._is_alive_windows(os.getpid())


def test_is_alive_posix_is_false_once_the_process_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    def raiser(pid: int, sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(service.os, "kill", raiser)
    assert service._is_alive_posix(999999) is False


def test_is_alive_posix_is_true_for_a_process_owned_by_someone_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raiser(pid: int, sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(service.os, "kill", raiser)
    assert service._is_alive_posix(1) is True


def test_signal_ignores_a_process_that_is_already_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    def raiser(pid: int, sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(service.os, "kill", raiser)
    service._signal(999999, signal.SIGTERM)  # must not raise


@pytest.mark.skipif(sys.platform == "win32", reason="exercises the POSIX signal-0 liveness check")
def test_is_alive_posix_reflects_a_real_process() -> None:
    assert service._is_alive_posix(os.getpid()) is True

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        assert service._is_alive_posix(child.pid) is True
    finally:
        child.terminate()
        child.wait(timeout=5)
    # Once reaped, the pid is no longer a live process (and on most systems, no longer even
    # a zombie by the time wait() returns).
    assert service._is_alive_posix(child.pid) is False


@pytest.mark.skipif(sys.platform == "win32", reason="exercises POSIX process detachment")
def test_default_spawn_and_stop_manage_a_real_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "mcp-gitlab.pid"
    log_file = tmp_path / "service.log"
    script = "import time\nprint('running', flush=True)\ntime.sleep(30)\n"

    pid = service.start((sys.executable, "-c", script), pid_file=pid_file, log_file=log_file)
    try:
        assert pid_file.read_text().strip() == str(pid)
        deadline = time.monotonic() + 5
        while log_file.stat().st_size == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert b"running" in log_file.read_bytes()
        assert service._is_alive(pid) is True
    finally:
        service.stop(pid_file=pid_file, grace=5.0)
        # Unlike a real `service start` process (which exits right after spawning, so init
        # reparents and reaps the child), this test stays its parent: reap it, or a zombie
        # would still answer kill(pid, 0) and _is_alive would wrongly say it's still running.
        with contextlib.suppress(ChildProcessError):
            os.waitpid(pid, 0)

    assert not pid_file.exists()
    assert service._is_alive(pid) is False

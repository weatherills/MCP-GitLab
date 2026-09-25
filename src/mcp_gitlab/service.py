"""Run `mcp-gitlab serve` as a detached background process: `mcp-gitlab service start|stop|restart`.

The standalone Docker image (`standalone.py`) is the intended deployment (see `CLAUDE.md`); this
module exists for the alternative of running `mcp-gitlab` directly, without Docker, on any OS.
It stays OS-independent using only the standard library: `os.kill` terminates a process on POSIX
and Windows alike, so start/stop/restart need no platform-specific tool (no `schtasks`, no
`systemd` unit) — those belong to `deploy/windows/`, which wraps this instead of replacing it.
"""

import contextlib
import ctypes
import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from mcp_gitlab.core.logging import log_event

logger = logging.getLogger("mcp_gitlab.service")

DEFAULT_STATE_DIR = Path.home() / ".mcp-gitlab"
STOP_GRACE_SECONDS = 10.0
POLL_SECONDS = 0.2

Spawn = Callable[[Sequence[str], Path], int]
Sleep = Callable[[float], None]
IsAlive = Callable[[int], bool]


class ServiceError(Exception):
    """A `service` action could not be completed; the CLI reports this and exits non-zero."""


def default_pid_file(env: Mapping[str, str] | None = None) -> Path:
    override = (env if env is not None else os.environ).get("MCP_GITLAB_PID_FILE")
    return Path(override) if override else DEFAULT_STATE_DIR / "mcp-gitlab.pid"


def default_log_file(env: Mapping[str, str] | None = None) -> Path:
    override = (env if env is not None else os.environ).get("MCP_GITLAB_SERVICE_LOG_FILE")
    return Path(override) if override else DEFAULT_STATE_DIR / "service.log"


def running_pid(pid_file: Path, *, is_alive: IsAlive | None = None) -> int | None:
    """The PID in `pid_file` if that process is still alive; else None, clearing a stale file."""
    is_alive = is_alive or _is_alive
    try:
        content = pid_file.read_text().strip()
    except FileNotFoundError:
        return None
    try:
        pid = int(content)
    except ValueError:
        log_event(logger, logging.WARNING, "service_pid_file_invalid", pid_file=str(pid_file))
    else:
        if is_alive(pid):
            return pid
        log_event(logger, logging.INFO, "service_stale_pid_file", pid_file=str(pid_file), pid=pid)
    with contextlib.suppress(FileNotFoundError):
        pid_file.unlink()
    return None


def start(
    argv: Sequence[str],
    *,
    pid_file: Path,
    log_file: Path,
    spawn: Spawn | None = None,
    is_alive: IsAlive | None = None,
) -> int:
    """Spawn `argv` detached, record its pid in `pid_file`, and return that pid.

    Raises ServiceError if `pid_file` already names a live process.
    """
    spawn = spawn or _default_spawn
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    existing = running_pid(pid_file, is_alive=is_alive)
    if existing is not None:
        raise ServiceError(f"mcp-gitlab is already running (pid {existing}; see {pid_file}).")
    log_event(logger, logging.INFO, "service_starting", argv=list(argv), log_file=str(log_file))
    pid = spawn(argv, log_file)
    pid_file.write_text(f"{pid}\n")
    log_event(logger, logging.INFO, "service_started", pid=pid, pid_file=str(pid_file))
    return pid


def stop(
    *,
    pid_file: Path,
    grace: float = STOP_GRACE_SECONDS,
    sleep: Sleep = time.sleep,
    is_alive: IsAlive | None = None,
) -> int:
    """Signal the process named by `pid_file` to stop, wait up to `grace`, then force it.

    Raises ServiceError if `pid_file` names no live process.
    """
    is_alive = is_alive or _is_alive
    pid = running_pid(pid_file, is_alive=is_alive)
    if pid is None:
        raise ServiceError(f"mcp-gitlab is not running ({pid_file} names no live process).")
    log_event(logger, logging.INFO, "service_stopping", pid=pid)
    _signal(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while is_alive(pid) and time.monotonic() < deadline:
        sleep(POLL_SECONDS)
    if is_alive(pid):
        log_event(logger, logging.WARNING, "service_stop_timeout", pid=pid, grace_seconds=grace)
        _signal(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    else:
        log_event(logger, logging.INFO, "service_stopped", pid=pid)
    with contextlib.suppress(FileNotFoundError):
        pid_file.unlink()
    return pid


def restart(
    argv: Sequence[str],
    *,
    pid_file: Path,
    log_file: Path,
    grace: float = STOP_GRACE_SECONDS,
    spawn: Spawn | None = None,
    sleep: Sleep = time.sleep,
    is_alive: IsAlive | None = None,
) -> int:
    """Stop the running process, if any, then start a new one."""
    with contextlib.suppress(ServiceError):
        stop(pid_file=pid_file, grace=grace, sleep=sleep, is_alive=is_alive)
    return start(argv, pid_file=pid_file, log_file=log_file, spawn=spawn, is_alive=is_alive)


def _signal(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise ServiceError(f"Could not signal pid {pid}: {exc}.") from exc


def _is_alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _is_alive_windows(pid)
    return _is_alive_posix(pid)


def _is_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists, owned by someone else: alive either way.
        return True
    return True


def _is_alive_windows(pid: int) -> bool:
    if sys.platform == "win32":
        query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(query_limited_information, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    raise AssertionError("_is_alive_windows() called off Windows.")


def _default_spawn(argv: Sequence[str], log_file: Path) -> int:
    """Start `argv`, detached from this process's console/session, appending output to log_file."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "ab") as output:
        kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": output, "stderr": output}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(list(argv), **kwargs)
    return process.pid

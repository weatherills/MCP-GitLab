"""Entrypoint of the standalone image: Caddy serves HTTPS in front of the MCP server.

`python -m mcp_gitlab.standalone` runs two processes in one container and stops both when
either one exits:

- the MCP server, bound to loopback, so plaintext HTTP never leaves the container;
- Caddy, serving https://MCP_PUBLIC_HOST on MCP_HTTPS_PORT (8443 by default) and passing every
  request, with its caller's PAT, to the server.

TLS uses the operator's certificate when there is one: MCP_TLS_CERTFILE and MCP_TLS_KEYFILE, or
tls.crt and tls.key in /certs. Otherwise Caddy issues a certificate from a local CA it creates on
first start and keeps under XDG_DATA_HOME (/data in the image), and clients must trust that CA.

The server's Host allow-list is derived from MCP_PUBLIC_HOST, and MCP_ALLOWED_ORIGINS defaults to
the public origin. `--healthcheck` is the image's health check.
"""

import argparse
import http.client
import json
import logging
import os
import re
import signal
import socket
import ssl
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import NoReturn

from mcp_gitlab.core.logging import configure_logging, log_event, log_settings_from_env

logger = logging.getLogger("mcp_gitlab.standalone")

CADDYFILE = "/etc/caddy/Caddyfile"
CERTS_DIR = Path("/certs")
DEFAULT_HTTPS_PORT = 8443
UPSTREAM = ("127.0.0.1", 8080)
# Where Caddy keeps its local CA's root certificate, under its data directory.
LOCAL_CA_ROOT = Path("caddy/pki/authorities/local/root.crt")
POLL_SECONDS = 0.2

# Caddy terminates TLS, so the server behind it gets none of these.
_TLS_SETTINGS = ("MCP_TLS_CERTFILE", "MCP_TLS_KEYFILE", "MCP_TLS_TERMINATED_UPSTREAM")
_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_HOST_NAME = re.compile(rf"{_LABEL}(?:\.{_LABEL})*")


class StandaloneError(ValueError):
    """Settings the standalone image cannot start with."""


@dataclass(frozen=True)
class Child:
    """A process to run: its name in the logs, its command line, and its environment."""

    name: str
    argv: tuple[str, ...]
    env: Mapping[str, str]


@dataclass(frozen=True)
class Plan:
    public_host: str
    https_port: int
    # The operator's certificate and key, or None when Caddy's local CA issues one.
    certificate: tuple[Path, Path] | None
    upstream: tuple[str, int]
    server: Child
    caddy: Child


class _Exit(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def plan(env: Mapping[str, str], certs_dir: Path = CERTS_DIR) -> Plan:
    """The two processes to run with these settings; raises StandaloneError if they can't work."""
    host = public_host(env)
    port = https_port(env)
    certificate = find_certificate(env, certs_dir)
    upstream_host, upstream_port = UPSTREAM

    server_env = {key: value for key, value in env.items() if key not in _TLS_SETTINGS}
    server_env.update(
        MCP_BIND_HOST=upstream_host,
        MCP_BIND_PORT=str(upstream_port),
        # Caddy passes the client's Host header on; it has no port when the port is 443.
        MCP_ALLOWED_HOSTS=f"{host},{host}:*",
    )
    if not env.get("MCP_ALLOWED_ORIGINS"):
        server_env["MCP_ALLOWED_ORIGINS"] = f"https://{host},https://{host}:*"

    caddy_env = {
        **env,
        "MCP_PUBLIC_HOST": host,
        "MCP_HTTPS_PORT": str(port),
        "MCP_UPSTREAM": f"{upstream_host}:{upstream_port}",
        # The arguments of the Caddyfile's tls directive.
        "MCP_CADDY_TLS": "internal"
        if certificate is None
        else " ".join(f'"{path}"' for path in certificate),
    }
    return Plan(
        public_host=host,
        https_port=port,
        certificate=certificate,
        upstream=UPSTREAM,
        server=Child("mcp-gitlab", (sys.executable, "-m", "mcp_gitlab"), server_env),
        caddy=Child(
            "caddy", ("caddy", "run", "--config", CADDYFILE, "--adapter", "caddyfile"), caddy_env
        ),
    )


def public_host(env: Mapping[str, str]) -> str:
    host = env.get("MCP_PUBLIC_HOST", "").strip().lower()
    if not _HOST_NAME.fullmatch(host):
        raise StandaloneError(
            "MCP_PUBLIC_HOST must be the host name clients connect to, such as mcp.example.com, "
            f"with no scheme, port, or path (got {env.get('MCP_PUBLIC_HOST')!r})."
        )
    return host


def https_port(env: Mapping[str, str]) -> int:
    raw = env.get("MCP_HTTPS_PORT") or str(DEFAULT_HTTPS_PORT)
    if not raw.isdigit() or not 1 <= int(raw) <= 65535:
        raise StandaloneError(f"MCP_HTTPS_PORT must be a port from 1 to 65535 (got {raw!r}).")
    return int(raw)


def find_certificate(env: Mapping[str, str], certs_dir: Path) -> tuple[Path, Path] | None:
    """The operator's certificate and key, from the environment or certs_dir, if provided."""
    certfile, keyfile = env.get("MCP_TLS_CERTFILE"), env.get("MCP_TLS_KEYFILE")
    if certfile or keyfile:
        if not (certfile and keyfile):
            raise StandaloneError("MCP_TLS_CERTFILE and MCP_TLS_KEYFILE must be set together.")
        pair = (Path(certfile), Path(keyfile))
    else:
        pair = (certs_dir / "tls.crt", certs_dir / "tls.key")
        try:
            present = [_exists(path) for path in pair]
        except OSError as exc:
            raise StandaloneError(f"Cannot look in {certs_dir}: {exc.strerror}.") from exc
        if not any(present):
            return None
        if not all(present):
            missing = pair[present.index(False)]
            raise StandaloneError(
                f"{missing} is missing: provide tls.crt and tls.key together, or neither to use "
                "a certificate from Caddy's local CA."
            )
    for path in pair:
        if not os.path.isfile(path) or not os.access(path, os.R_OK):
            raise StandaloneError(
                f"Cannot read {path} as uid {os.getuid()}: it must be a file that user can read "
                f"(on the host, for example: chown {os.getuid()} <file>)."
            )
    return pair


def _exists(path: Path) -> bool:
    """Whether path exists; unlike Path.exists, an unreadable directory is an error."""
    try:
        path.stat()
    except FileNotFoundError:
        return False
    return True


def supervise(plan: Plan, *, ready_timeout: float = 60.0, grace: float = 8.0) -> int:
    """Run the server, then Caddy once the server listens, until either exits or a stop signal.

    Returns the container's exit status: 0 after SIGTERM or SIGINT; otherwise that of the process
    that stopped (1 if that was 0, since neither should stop on its own), 1 if the server never
    listened, or 127 if a process could not start.
    """
    stop: list[int] = []

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop.append(signum)

    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    running: dict[str, subprocess.Popen[bytes]] = {}
    try:
        _start(plan.server, running)
        _await_listener(plan.upstream, running, stop, ready_timeout)
        _start(plan.caddy, running)
        _watch(running, stop)
    except _Exit as exit_:
        return exit_.status
    finally:
        _stop_all(running, grace)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _start(child: Child, running: dict[str, subprocess.Popen[bytes]]) -> None:
    try:
        process = subprocess.Popen(child.argv, env=dict(child.env))
    except OSError as exc:
        log_event(logger, logging.ERROR, "process_not_started", process=child.name, detail=str(exc))
        raise _Exit(127) from exc
    running[child.name] = process
    log_event(logger, logging.INFO, "process_started", process=child.name, pid=process.pid)


def _check(running: Mapping[str, subprocess.Popen[bytes]], stop: Sequence[int]) -> None:
    """Raise _Exit once a stop signal has arrived or any process has exited."""
    if stop:
        log_event(logger, logging.INFO, "stopping", signal=signal.Signals(stop[0]).name)
        raise _Exit(0)
    for name, process in running.items():
        status = process.poll()
        if status is not None:
            log_event(logger, logging.ERROR, "process_exited", process=name, exit_status=status)
            raise _Exit(128 - status if status < 0 else status or 1)


def _await_listener(
    address: tuple[str, int],
    running: Mapping[str, subprocess.Popen[bytes]],
    stop: Sequence[int],
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while True:
        _check(running, stop)
        try:
            with socket.create_connection(address, timeout=1):
                return
        except OSError:
            pass
        if time.monotonic() >= deadline:
            log_event(logger, logging.ERROR, "server_not_ready", timeout_seconds=timeout)
            raise _Exit(1)
        time.sleep(POLL_SECONDS)


def _watch(running: Mapping[str, subprocess.Popen[bytes]], stop: Sequence[int]) -> NoReturn:
    while True:
        _check(running, stop)
        time.sleep(POLL_SECONDS)


def _stop_all(running: Mapping[str, subprocess.Popen[bytes]], grace: float) -> None:
    for process in running.values():
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + grace
    for name, process in running.items():
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            log_event(logger, logging.WARNING, "process_killed", process=name, grace_seconds=grace)
            process.kill()
            process.wait()


def healthcheck(env: Mapping[str, str], *, timeout: float = 2.0) -> int:
    """0 if /healthz answers ok through Caddy, over TLS, as it would for a client; else 1."""
    try:
        host, port = public_host(env), https_port(env)
    except StandaloneError as exc:
        print(f"unhealthy: {exc}")
        return 1
    # A liveness probe, not a trust check: in local CA mode only clients that trust that CA
    # can verify the certificate, and it names the public host rather than 127.0.0.1.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with (
            socket.create_connection(("127.0.0.1", port), timeout=timeout) as raw,
            context.wrap_socket(raw, server_hostname=host) as tls,
        ):
            connection = http.client.HTTPConnection(host, port, timeout=timeout)
            connection.sock = tls
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            body = response.read()
    except (OSError, http.client.HTTPException) as exc:
        print(f"unhealthy: {exc}")
        return 1
    try:
        healthy = response.status == 200 and json.loads(body).get("status") == "ok"
    except (ValueError, AttributeError):
        healthy = False
    if not healthy:
        print(f"unhealthy: /healthz answered {response.status}: {body[:200]!r}")
        return 1
    print("healthy")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mcp_gitlab.standalone",
        description="Run Caddy (HTTPS) in front of the GitLab MCP server, in one container.",
    )
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Fetch /healthz through Caddy and exit 0 if the server answers ok.",
    )
    args = parser.parse_args(argv)
    env = os.environ
    if args.healthcheck:
        return healthcheck(env)

    configure_logging(*log_settings_from_env(env))
    try:
        chosen = plan(env, CERTS_DIR)
    except StandaloneError as exc:
        log_event(logger, logging.ERROR, "configuration_error", detail=str(exc))
        return 2
    if chosen.certificate is None:
        data_home = Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        tls: dict[str, str] = {
            "tls": "local_ca",
            "root_certificate": str(data_home / LOCAL_CA_ROOT),
            "detail": "No certificate provided: clients must trust this CA's root certificate.",
        }
    else:
        tls = {"tls": "provided", "certificate": str(chosen.certificate[0])}
    log_event(
        logger,
        logging.INFO,
        "standalone_starting",
        public_host=chosen.public_host,
        https_port=chosen.https_port,
        **tls,
    )
    return supervise(chosen)


if __name__ == "__main__":
    sys.exit(main())

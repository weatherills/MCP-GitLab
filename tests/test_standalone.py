"""The standalone image's entrypoint: its settings, process supervision, health check, and Caddy.

The Caddy tests run the real binary against deploy/Caddyfile and are skipped when `caddy` is not
on PATH; CI installs the image's version.
"""

import email.message
import http.server
import json
import logging
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import trustme

from mcp_gitlab import standalone
from mcp_gitlab.standalone import Child, Plan, StandaloneError

REPO = Path(__file__).resolve().parents[1]
PAT = "glpat-standalone-test-0123456789"


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture(scope="module")
def ca() -> trustme.CA:
    return trustme.CA()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def wait_for(condition: Callable[[], object], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.05)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


# --- Settings ---------------------------------------------------------------------------------


def test_without_a_certificate_caddy_uses_its_local_ca(tmp_path: Path) -> None:
    chosen = standalone.plan({"MCP_PUBLIC_HOST": " MCP.Example.com "}, tmp_path / "certs")

    assert (chosen.public_host, chosen.https_port, chosen.certificate) == (
        "mcp.example.com",
        8443,
        None,
    )
    assert chosen.caddy.argv == (
        "caddy",
        "run",
        "--config",
        "/etc/caddy/Caddyfile",
        "--adapter",
        "caddyfile",
    )
    assert chosen.caddy.env["MCP_CADDY_TLS"] == "internal"
    assert chosen.caddy.env["MCP_PUBLIC_HOST"] == "mcp.example.com"
    assert chosen.caddy.env["MCP_HTTPS_PORT"] == "8443"
    assert chosen.caddy.env["MCP_UPSTREAM"] == "127.0.0.1:8080"
    assert chosen.upstream == ("127.0.0.1", 8080)


def test_the_server_listens_on_loopback_for_the_public_host_only(tmp_path: Path) -> None:
    env = {
        "MCP_PUBLIC_HOST": "mcp.example.com",
        "MCP_HTTPS_PORT": "9443",
        "MCP_BIND_HOST": "0.0.0.0",
        "MCP_ALLOWED_HOSTS": "anything.example",
        "MCP_TLS_TERMINATED_UPSTREAM": "true",
        "GITLAB_BASE_URL": "https://gitlab.example.com/api/v4",
    }
    server = standalone.plan(env, tmp_path).server

    assert server.argv == (sys.executable, "-m", "mcp_gitlab")
    assert server.env["MCP_BIND_HOST"] == "127.0.0.1"
    assert server.env["MCP_BIND_PORT"] == "8080"
    assert server.env["MCP_ALLOWED_HOSTS"] == "mcp.example.com,mcp.example.com:*"
    assert server.env["MCP_ALLOWED_ORIGINS"] == "https://mcp.example.com,https://mcp.example.com:*"
    assert "MCP_TLS_TERMINATED_UPSTREAM" not in server.env
    assert server.env["GITLAB_BASE_URL"] == "https://gitlab.example.com/api/v4"


def test_an_origin_allow_list_set_by_the_operator_is_kept(tmp_path: Path) -> None:
    env = {"MCP_PUBLIC_HOST": "mcp.example.com", "MCP_ALLOWED_ORIGINS": "http://localhost:6274"}
    assert standalone.plan(env, tmp_path).server.env["MCP_ALLOWED_ORIGINS"] == (
        "http://localhost:6274"
    )


def test_a_certificate_in_the_certs_directory_is_served(tmp_path: Path) -> None:
    (tmp_path / "tls.crt").write_text("certificate")
    (tmp_path / "tls.key").write_text("key")
    chosen = standalone.plan({"MCP_PUBLIC_HOST": "mcp.example.com"}, tmp_path)

    assert chosen.certificate == (tmp_path / "tls.crt", tmp_path / "tls.key")
    assert chosen.caddy.env["MCP_CADDY_TLS"] == f'"{tmp_path}/tls.crt" "{tmp_path}/tls.key"'


def test_certificate_files_named_in_the_environment_go_to_caddy_not_the_server(
    tmp_path: Path,
) -> None:
    (tmp_path / "chain.pem").write_text("certificate")
    (tmp_path / "private.pem").write_text("key")
    env = {
        "MCP_PUBLIC_HOST": "mcp.example.com",
        "MCP_TLS_CERTFILE": str(tmp_path / "chain.pem"),
        "MCP_TLS_KEYFILE": str(tmp_path / "private.pem"),
    }
    chosen = standalone.plan(env, tmp_path / "certs")

    assert chosen.certificate == (tmp_path / "chain.pem", tmp_path / "private.pem")
    assert "MCP_TLS_CERTFILE" not in chosen.server.env
    assert "MCP_TLS_KEYFILE" not in chosen.server.env


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "MCP_PUBLIC_HOST must be"),
        ({"MCP_PUBLIC_HOST": "https://mcp.example.com"}, "MCP_PUBLIC_HOST must be"),
        ({"MCP_PUBLIC_HOST": "mcp.example.com:443"}, "MCP_PUBLIC_HOST must be"),
        ({"MCP_PUBLIC_HOST": "mcp.example.com/mcp"}, "MCP_PUBLIC_HOST must be"),
        ({"MCP_PUBLIC_HOST": "mcp.example.com", "MCP_HTTPS_PORT": "0"}, "MCP_HTTPS_PORT must be"),
        ({"MCP_PUBLIC_HOST": "mcp.example.com", "MCP_HTTPS_PORT": "https"}, "MCP_HTTPS_PORT"),
        ({"MCP_PUBLIC_HOST": "mcp.example.com", "MCP_TLS_CERTFILE": "/x"}, "set together"),
        (
            {"MCP_PUBLIC_HOST": "h", "MCP_TLS_CERTFILE": "/no/cert", "MCP_TLS_KEYFILE": "/no/key"},
            "Cannot read /no/cert",
        ),
    ],
)
def test_unusable_settings_are_refused(tmp_path: Path, env: dict[str, str], message: str) -> None:
    with pytest.raises(StandaloneError, match=message):
        standalone.plan(env, tmp_path)


def test_half_a_certificate_is_refused(tmp_path: Path) -> None:
    (tmp_path / "tls.crt").write_text("certificate")
    with pytest.raises(StandaloneError, match="tls.key is missing"):
        standalone.plan({"MCP_PUBLIC_HOST": "mcp.example.com"}, tmp_path)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads files regardless of permissions")
def test_a_key_the_server_user_cannot_read_is_refused(tmp_path: Path) -> None:
    (tmp_path / "tls.crt").write_text("certificate")
    (tmp_path / "tls.key").write_text("key")
    (tmp_path / "tls.key").chmod(0)
    with pytest.raises(StandaloneError, match=r"Cannot read .*tls\.key as uid"):
        standalone.plan({"MCP_PUBLIC_HOST": "mcp.example.com"}, tmp_path)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads directories regardless of permissions")
def test_a_certs_directory_the_server_user_cannot_search_is_refused(tmp_path: Path) -> None:
    certs = tmp_path / "certs"
    certs.mkdir(mode=0)
    try:
        with pytest.raises(StandaloneError, match="Cannot look in"):
            standalone.plan({"MCP_PUBLIC_HOST": "mcp.example.com"}, certs)
    finally:
        certs.chmod(0o700)


# --- Supervision ------------------------------------------------------------------------------

LISTEN = """
    import socket, sys, time
    listener = socket.create_server(("127.0.0.1", {port}))
    time.sleep({seconds})
    sys.exit({status})
"""
RECORD_PID = """
    import os, pathlib, sys, time
    pathlib.Path({marker!r}).write_text(str(os.getpid()))
    time.sleep({seconds})
    sys.exit({status})
"""


def python(code: str) -> tuple[str, ...]:
    return (sys.executable, "-c", textwrap.dedent(code))


def fake_plan(port: int, server: tuple[str, ...], caddy: tuple[str, ...]) -> Plan:
    env = dict(os.environ)
    return Plan(
        public_host="localhost",
        https_port=8443,
        certificate=None,
        upstream=("127.0.0.1", port),
        server=Child("mcp-gitlab", server, env),
        caddy=Child("caddy", caddy, env),
    )


def test_when_one_process_exits_the_other_stops_and_its_status_is_returned(
    tmp_path: Path,
) -> None:
    port, marker = free_port(), tmp_path / "caddy.pid"
    plan = fake_plan(
        port,
        server=python(LISTEN.format(port=port, seconds=1.5, status=3)),
        caddy=python(RECORD_PID.format(marker=str(marker), seconds=60, status=0)),
    )
    started = time.monotonic()

    assert standalone.supervise(plan) == 3
    assert time.monotonic() - started < 10
    assert not alive(int(marker.read_text()))


@pytest.mark.parametrize(
    ("caddy", "status"),
    [
        ("import sys; sys.exit(0)", 1),  # neither process should stop on its own
        ("import sys; sys.exit(4)", 4),
        ("import os, signal; os.kill(os.getpid(), signal.SIGKILL)", 128 + signal.SIGKILL),
    ],
)
def test_the_exit_status_says_why_the_container_stopped(caddy: str, status: int) -> None:
    port = free_port()
    plan = fake_plan(
        port, server=python(LISTEN.format(port=port, seconds=60, status=0)), caddy=python(caddy)
    )
    assert standalone.supervise(plan) == status


def test_caddy_starts_only_once_the_server_listens(tmp_path: Path) -> None:
    port, marker = free_port(), tmp_path / "caddy.pid"
    plan = fake_plan(
        port,
        server=python("import sys, time; time.sleep(1); sys.exit(5)"),
        caddy=python(RECORD_PID.format(marker=str(marker), seconds=60, status=0)),
    )
    assert standalone.supervise(plan) == 5
    assert not marker.exists()


def test_a_server_that_never_listens_fails_the_start() -> None:
    port = free_port()
    sleep = python("import time; time.sleep(60)")
    started = time.monotonic()

    assert standalone.supervise(fake_plan(port, sleep, sleep), ready_timeout=1) == 1
    assert time.monotonic() - started < 10


def test_a_process_that_cannot_start_stops_the_container() -> None:
    port = free_port()
    plan = fake_plan(
        port,
        server=python(LISTEN.format(port=port, seconds=60, status=0)),
        caddy=("/nonexistent/caddy",),
    )
    assert standalone.supervise(plan) == 127


def test_a_process_that_ignores_sigterm_is_killed_after_the_grace_period(tmp_path: Path) -> None:
    port, marker = free_port(), tmp_path / "caddy.pid"
    stubborn = f"""
        import os, pathlib, signal, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        pathlib.Path({str(marker)!r}).write_text(str(os.getpid()))
        time.sleep(60)
    """
    plan = fake_plan(
        port, server=python(LISTEN.format(port=port, seconds=1.5, status=3)), caddy=python(stubborn)
    )
    started = time.monotonic()

    assert standalone.supervise(plan, grace=0.5) == 3
    assert time.monotonic() - started < 10
    assert not alive(int(marker.read_text()))


def test_sigterm_stops_both_processes_and_exits_0(tmp_path: Path) -> None:
    port, marker = free_port(), tmp_path / "caddy.pid"
    server = python(LISTEN.format(port=port, seconds=60, status=0))
    caddy = python(RECORD_PID.format(marker=str(marker), seconds=60, status=0))
    driver = f"""
        import sys
        from mcp_gitlab.standalone import Child, Plan, supervise
        plan = Plan(
            "localhost", 8443, None, ("127.0.0.1", {port}),
            Child("mcp-gitlab", {server!r}, {{}}), Child("caddy", {caddy!r}, {{}}),
        )
        sys.exit(supervise(plan))
    """
    supervisor = subprocess.Popen(python(driver))
    try:
        wait_for(lambda: marker.exists() and marker.read_text())
        supervisor.send_signal(signal.SIGTERM)
        assert supervisor.wait(timeout=10) == 0
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
    assert not alive(int(marker.read_text()))


# --- Health check -----------------------------------------------------------------------------


@dataclass
class Received:
    path: str
    headers: email.message.Message


@dataclass
class Stub:
    port: int
    requests: list[Received]
    server_names: list[str | None]


Handler = Callable[[http.server.BaseHTTPRequestHandler], None]


@contextmanager
def serve(handle: Handler, tls: ssl.SSLContext | None = None) -> Iterator[Stub]:
    """An HTTP(S) server on 127.0.0.1 that records each request and lets handle() answer it."""
    stub = Stub(0, [], [])

    class RequestHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            stub.requests.append(Received(self.path, self.headers))
            handle(self)

        do_POST = do_GET

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RequestHandler)
    if tls is not None:
        tls.sni_callback = lambda sock, name, context: stub.server_names.append(name)
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    stub.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield stub
    finally:
        server.shutdown()
        server.server_close()


def reply(status: int, body: bytes) -> Handler:
    def handle(request: http.server.BaseHTTPRequestHandler) -> None:
        request.send_response(status)
        request.send_header("Content-Type", "application/json")
        request.send_header("Content-Length", str(len(body)))
        request.end_headers()
        request.wfile.write(body)

    return handle


def serving_context(ca: trustme.CA, name: str) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert(name).configure_cert(context)
    return context


def test_the_health_check_fetches_healthz_over_tls_as_a_client_would(
    ca: trustme.CA, capsys: pytest.CaptureFixture[str]
) -> None:
    ok = reply(200, b'{"status": "ok", "version": "0.1.0"}')
    with serve(ok, serving_context(ca, "mcp.example.com")) as stub:
        env = {"MCP_PUBLIC_HOST": "mcp.example.com", "MCP_HTTPS_PORT": str(stub.port)}
        assert standalone.healthcheck(env) == 0

    assert capsys.readouterr().out == "healthy\n"
    [request] = stub.requests
    assert request.path == "/healthz"
    assert request.headers["Host"] == f"mcp.example.com:{stub.port}"
    assert stub.server_names == ["mcp.example.com"]


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (502, b"Bad Gateway"),
        (200, b'{"status": "starting"}'),
        (200, b"<html></html>"),
        (200, b'["ok"]'),
    ],
)
def test_the_health_check_fails_unless_the_server_answers_ok(
    ca: trustme.CA, capsys: pytest.CaptureFixture[str], status: int, body: bytes
) -> None:
    with serve(reply(status, body), serving_context(ca, "mcp.example.com")) as stub:
        env = {"MCP_PUBLIC_HOST": "mcp.example.com", "MCP_HTTPS_PORT": str(stub.port)}
        assert standalone.healthcheck(env) == 1
    assert capsys.readouterr().out.startswith(f"unhealthy: /healthz answered {status}")


def test_the_health_check_fails_when_nothing_listens(capsys: pytest.CaptureFixture[str]) -> None:
    env = {"MCP_PUBLIC_HOST": "mcp.example.com", "MCP_HTTPS_PORT": str(free_port())}
    assert standalone.healthcheck(env, timeout=1) == 1
    assert capsys.readouterr().out.startswith("unhealthy:")


def test_the_health_check_fails_without_a_public_host(capsys: pytest.CaptureFixture[str]) -> None:
    assert standalone.healthcheck({}) == 1
    assert "MCP_PUBLIC_HOST" in capsys.readouterr().out


# --- main -------------------------------------------------------------------------------------


def logged(capsys: pytest.CaptureFixture[str], event: str) -> dict[str, Any]:
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    [entry] = [line for line in lines if line["message"] == event]
    return entry


@pytest.fixture
def supervised(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Plan]:
    plans: list[Plan] = []

    def supervise(plan: Plan) -> int:
        plans.append(plan)
        return 0

    monkeypatch.setattr(standalone, "supervise", supervise)
    monkeypatch.setattr(standalone, "CERTS_DIR", tmp_path / "certs")
    return plans


def test_main_names_the_local_ca_clients_must_trust(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], supervised: list[Plan]
) -> None:
    monkeypatch.setenv("MCP_PUBLIC_HOST", "mcp.example.com")
    monkeypatch.setenv("XDG_DATA_HOME", "/data")

    assert standalone.main([]) == 0
    [plan] = supervised
    assert plan.public_host == "mcp.example.com"
    entry = logged(capsys, "standalone_starting")
    assert entry["tls"] == "local_ca"
    assert entry["root_certificate"] == "/data/caddy/pki/authorities/local/root.crt"


def test_main_names_the_certificate_it_serves(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    supervised: list[Plan],
    tmp_path: Path,
) -> None:
    (tmp_path / "chain.pem").write_text("certificate")
    (tmp_path / "private.pem").write_text("key")
    monkeypatch.setenv("MCP_PUBLIC_HOST", "mcp.example.com")
    monkeypatch.setenv("MCP_TLS_CERTFILE", str(tmp_path / "chain.pem"))
    monkeypatch.setenv("MCP_TLS_KEYFILE", str(tmp_path / "private.pem"))

    assert standalone.main([]) == 0
    entry = logged(capsys, "standalone_starting")
    assert (entry["tls"], entry["certificate"]) == ("provided", str(tmp_path / "chain.pem"))


def test_main_refuses_unusable_settings(
    capsys: pytest.CaptureFixture[str], supervised: list[Plan]
) -> None:
    assert standalone.main([]) == 2
    assert supervised == []
    assert "MCP_PUBLIC_HOST must be" in logged(capsys, "configuration_error")["detail"]


def test_main_runs_the_health_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(standalone, "healthcheck", lambda env: 7)
    assert standalone.main(["--healthcheck"]) == 7


# --- Caddy, with deploy/Caddyfile -------------------------------------------------------------

CADDY = shutil.which("caddy")
needs_caddy = pytest.mark.skipif(CADDY is None, reason="needs the caddy binary on PATH")


@dataclass
class Caddy:
    port: int
    trust: ssl.SSLContext
    log: Path
    process: "subprocess.Popen[bytes]"

    def client(self) -> httpx.Client:
        return httpx.Client(verify=self.trust, trust_env=False, timeout=5)

    def url(self, path: str) -> str:
        return f"https://localhost:{self.port}{path}"

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)


@contextmanager
def caddy(tmp_path: Path, upstream: int, ca: trustme.CA | None = None) -> Iterator[Caddy]:
    """Caddy as the entrypoint would run it, for localhost; with ca, serving its certificate."""
    port = free_port()
    env = {"MCP_PUBLIC_HOST": "localhost", "MCP_HTTPS_PORT": str(port)}
    if ca is not None:
        issued = ca.issue_cert("localhost")
        for blob in issued.cert_chain_pems:
            blob.write_to_path(str(tmp_path / "chain.pem"), append=True)
        issued.private_key_pem.write_to_path(str(tmp_path / "private.pem"))
        env.update(
            MCP_TLS_CERTFILE=str(tmp_path / "chain.pem"),
            MCP_TLS_KEYFILE=str(tmp_path / "private.pem"),
        )
    chosen = standalone.plan(env, tmp_path / "certs")
    caddyfile = str(REPO / "deploy" / "Caddyfile")
    argv = [caddyfile if arg == standalone.CADDYFILE else arg for arg in chosen.caddy.argv]
    data = tmp_path / "data"
    process_env = {
        **chosen.caddy.env,
        "MCP_UPSTREAM": f"127.0.0.1:{upstream}",
        "PATH": os.environ["PATH"],
        "XDG_DATA_HOME": str(data),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
    }
    if ca is None:
        root = data / standalone.LOCAL_CA_ROOT  # Caddy creates its CA on start
    else:
        root = tmp_path / "ca.pem"
        ca.cert_pem.write_to_path(str(root))
    log = tmp_path / "caddy.log"
    with log.open("wb") as output:
        process = subprocess.Popen(argv, env=process_env, stdout=output, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 20
        while not (root.exists() and _accepts(port)):
            if process.poll() is not None or time.monotonic() > deadline:
                raise AssertionError(f"Caddy did not start:\n{log.read_text()}")
            time.sleep(0.1)
        yield Caddy(port, ssl.create_default_context(cafile=str(root)), log, process)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def _accepts(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


@needs_caddy
@pytest.mark.parametrize("provided", [False, True], ids=["local_ca", "provided"])
def test_caddy_passes_each_request_with_its_headers_to_the_server(
    tmp_path: Path, ca: trustme.CA, provided: bool
) -> None:
    headers = {"PRIVATE-TOKEN": PAT, "Authorization": f"Bearer {PAT}", "X-MCP-Readonly": "true"}
    with (
        serve(reply(200, b"{}")) as upstream,
        caddy(tmp_path, upstream.port, ca if provided else None) as front,
        front.client() as client,
    ):
        response = client.post(front.url("/mcp"), headers=headers, content=b"{}")

    assert response.status_code == 200
    [request] = upstream.requests
    assert request.path == "/mcp"
    assert request.headers["Host"] == f"localhost:{front.port}"
    assert request.headers["Private-Token"] == PAT
    assert request.headers["Authorization"] == f"Bearer {PAT}"
    assert request.headers["X-MCP-Readonly"] == "true"
    assert request.headers["X-Forwarded-Proto"] == "https"


@needs_caddy
def test_caddy_answers_other_host_names_with_421(tmp_path: Path) -> None:
    with (
        serve(reply(200, b"{}")) as upstream,
        caddy(tmp_path, upstream.port) as front,
        front.client() as client,
    ):
        response = client.get(front.url("/mcp"), headers={"Host": "other.example"})

    assert response.status_code == 421
    assert "https://localhost/" in response.text
    assert upstream.requests == []


@needs_caddy
def test_caddy_streams_server_sent_events_as_they_are_written(tmp_path: Path) -> None:
    release = threading.Event()

    def stream(request: http.server.BaseHTTPRequestHandler) -> None:
        request.send_response(200)
        request.send_header("Content-Type", "text/event-stream")
        request.end_headers()
        request.wfile.write(b"data: first\n\n")
        request.wfile.flush()
        release.wait(10)
        request.wfile.write(b"data: second\n\n")

    with (
        serve(stream) as upstream,
        caddy(tmp_path, upstream.port) as front,
        front.client() as client,
        client.stream("GET", front.url("/mcp")) as response,
    ):
        lines = (line for line in response.iter_lines() if line)
        # Arrives while the server still holds the second event back.
        assert next(lines) == "data: first"
        release.set()
        assert next(lines) == "data: second"


@needs_caddy
def test_caddy_logs_no_request_headers_even_when_the_server_is_down(tmp_path: Path) -> None:
    with caddy(tmp_path, free_port()) as front, front.client() as client:
        response = client.post(
            front.url("/mcp"),
            headers={"PRIVATE-TOKEN": PAT, "Authorization": f"Bearer {PAT}"},
            content=b"{}",
        )
        front.stop()

    assert response.status_code == 502
    log = front.log.read_text()
    assert '"logger":"http.log.error"' in log  # Caddy logged the failed request...
    assert PAT not in log  # ...but none of its headers
    assert "Private-Token" not in log

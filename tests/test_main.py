import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mcp_gitlab import __main__ as entrypoint
from mcp_gitlab import service


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(entrypoint.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    return calls


def test_serves_on_loopback_by_default(served: list[dict[str, Any]]) -> None:
    assert entrypoint.main([]) == 0
    [kwargs] = served
    assert (kwargs["host"], kwargs["port"]) == ("127.0.0.1", 8080)
    assert kwargs["log_config"] is None
    assert kwargs["ssl_certfile"] is None


def test_invalid_configuration_exits_before_serving(
    monkeypatch: pytest.MonkeyPatch,
    served: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GITLAB_SKIP_TLS_VERIFY", "true")
    assert entrypoint.main([]) == 2
    assert served == []
    assert "invalid configuration" in capsys.readouterr().err


def test_public_plaintext_bind_is_refused(
    monkeypatch: pytest.MonkeyPatch, served: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("MCP_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.example.com")
    assert entrypoint.main([]) == 2
    assert served == []


def test_insecure_dev_flag_allows_public_plaintext(
    monkeypatch: pytest.MonkeyPatch, served: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("MCP_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.example.com")
    assert entrypoint.main(["--insecure-dev"]) == 0
    assert served[0]["host"] == "0.0.0.0"


def test_native_tls_files_reach_uvicorn(
    monkeypatch: pytest.MonkeyPatch, served: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("MCP_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp.example.com")
    monkeypatch.setenv("MCP_TLS_CERTFILE", "/tls/cert.pem")
    monkeypatch.setenv("MCP_TLS_KEYFILE", "/tls/key.pem")
    assert entrypoint.main([]) == 0
    assert (served[0]["ssl_certfile"], served[0]["ssl_keyfile"]) == (
        "/tls/cert.pem",
        "/tls/key.pem",
    )


def test_unknown_toolset_allowlist_exits_before_serving(
    monkeypatch: pytest.MonkeyPatch, served: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("GITLAB_MCP_TOOLSETS", "no_such_toolset")
    assert entrypoint.main([]) == 2
    assert served == []


def test_gitlab_token_is_ignored_with_a_warning(
    monkeypatch: pytest.MonkeyPatch,
    served: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-server-side-abcdefghij")
    assert entrypoint.main([]) == 0
    output = capsys.readouterr().out
    assert "gitlab_token_ignored" in output
    assert "glpat-server-side" not in output


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        entrypoint.main(["--version"])
    assert excinfo.value.code == 0
    assert "mcp-gitlab" in capsys.readouterr().out


@pytest.fixture
def service_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        entrypoint.service, "start", lambda argv, **kw: calls.setdefault("start", (argv, kw))
    )
    monkeypatch.setattr(entrypoint.service, "stop", lambda **kw: calls.setdefault("stop", kw) or 0)
    monkeypatch.setattr(
        entrypoint.service, "restart", lambda argv, **kw: calls.setdefault("restart", (argv, kw))
    )
    return calls


def test_service_start_spawns_the_server_module(service_calls: dict[str, Any]) -> None:
    assert entrypoint.main(["service", "start"]) == 0
    argv, kwargs = service_calls["start"]
    assert argv[-1] == "serve"
    assert isinstance(kwargs["pid_file"], Path)
    assert isinstance(kwargs["log_file"], Path)


def test_service_stop_and_restart_are_routed(service_calls: dict[str, Any]) -> None:
    assert entrypoint.main(["service", "stop"]) == 0
    assert "stop" in service_calls
    assert entrypoint.main(["service", "restart"]) == 0
    assert "restart" in service_calls


def test_service_error_is_reported_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fails(**kwargs: Any) -> int:
        raise service.ServiceError("mcp-gitlab is not running (no pid file).")

    monkeypatch.setattr(entrypoint.service, "stop", fails)
    assert entrypoint.main(["service", "stop"]) == 1
    err = capsys.readouterr().err
    assert "mcp-gitlab is not running" in err


def test_service_error_is_logged_as_a_structured_event(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fails(argv: Any, **kwargs: Any) -> int:
        raise service.ServiceError("mcp-gitlab is already running (pid 4242).")

    monkeypatch.setattr(entrypoint.service, "start", fails)
    assert entrypoint.main(["service", "start"]) == 1
    assert "service_action_failed" in capsys.readouterr().out

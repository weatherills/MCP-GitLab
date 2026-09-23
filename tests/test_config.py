from pathlib import Path

import pytest
from pydantic import ValidationError

from mcp_gitlab.config import ConfigurationError, Settings, check_transport_policy


def test_defaults() -> None:
    settings = Settings()
    assert str(settings.gitlab_base_url) == "https://gitlab.com/api/v4"
    assert settings.mcp_bind_host == "127.0.0.1"
    assert settings.mcp_stateless_http is True
    assert settings.mcp_json_response is False
    assert settings.allowed_hosts() == ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    assert "http://localhost:*" in settings.allowed_origins()
    assert settings.toolset_allowlist() is None


def test_self_hosted_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_BASE_URL", "https://gitlab.example.com/api/v4")
    assert Settings().gitlab_base_url.host == "gitlab.example.com"


def test_skip_tls_verify_refused_for_gitlab_com(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_SKIP_TLS_VERIFY", "true")
    with pytest.raises(ValidationError, match="refused against gitlab.com"):
        Settings()


def test_skip_tls_verify_allowed_for_self_hosted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_BASE_URL", "https://gitlab.example.com/api/v4")
    monkeypatch.setenv("GITLAB_SKIP_TLS_VERIFY", "true")
    assert Settings().gitlab_skip_tls_verify is True


def test_server_holds_no_gitlab_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-abcdefghijklmnopqrst")
    (tmp_path / ".env").write_text("GITLAB_TOKEN=glpat-from-dotenv-abcdefghij\n")
    settings = Settings()
    assert not hasattr(settings, "gitlab_token")
    assert "glpat-" not in repr(settings)


def test_empty_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_BASE_URL", "")
    assert str(Settings().gitlab_base_url) == "https://gitlab.com/api/v4"


def test_reads_dotenv_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("GITLAB_BASE_URL=https://gitlab.internal/api/v4\n")
    assert Settings().gitlab_base_url.host == "gitlab.internal"


def test_environment_overrides_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("GITLAB_BASE_URL=https://from-dotenv.example/api/v4\n")
    monkeypatch.setenv("GITLAB_BASE_URL", "https://from-env.example/api/v4")
    assert Settings().gitlab_base_url.host == "from-env.example"


def test_log_settings_are_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("LOG_FORMAT", "TEXT")
    settings = Settings()
    assert settings.log_level == "DEBUG"
    assert settings.log_format == "text"


def test_tls_files_must_be_paired() -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        Settings(mcp_tls_certfile="/tmp/cert.pem")


def test_non_loopback_bind_requires_allowed_hosts() -> None:
    with pytest.raises(ValidationError, match="MCP_ALLOWED_HOSTS is required"):
        Settings(mcp_bind_host="0.0.0.0")


def test_non_loopback_bind_rejects_browser_origins_by_default() -> None:
    settings = Settings(mcp_bind_host="0.0.0.0", mcp_allowed_hosts="mcp.example.com, mcp.internal")
    assert settings.allowed_hosts() == ["mcp.example.com", "mcp.internal"]
    assert settings.allowed_origins() == []


@pytest.mark.parametrize(
    ("host", "expected"),
    [("127.0.0.1", True), ("localhost", True), ("::1", True), ("[::1]", True), ("0.0.0.0", False)],
)
def test_loopback_detection(host: str, expected: bool) -> None:
    settings = Settings(mcp_bind_host=host, mcp_allowed_hosts="mcp.example.com")
    assert settings.is_loopback_bind is expected


def test_toolset_allowlist_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_MCP_TOOLSETS", "Projects, issues ,pipelines,")
    assert Settings().toolset_allowlist() == frozenset({"projects", "issues", "pipelines"})


def test_transport_policy_allows_loopback_plaintext() -> None:
    check_transport_policy(Settings(), insecure_dev=False)


def test_transport_policy_refuses_public_plaintext() -> None:
    settings = Settings(mcp_bind_host="0.0.0.0", mcp_allowed_hosts="mcp.example.com")
    with pytest.raises(ConfigurationError, match="Refusing to serve plaintext HTTP"):
        check_transport_policy(settings, insecure_dev=False)


@pytest.mark.parametrize(
    "overrides",
    [
        {"mcp_tls_certfile": "/tls/cert.pem", "mcp_tls_keyfile": "/tls/key.pem"},
        {"mcp_tls_terminated_upstream": True},
    ],
)
def test_transport_policy_accepts_tls(overrides: dict[str, object]) -> None:
    settings = Settings(mcp_bind_host="0.0.0.0", mcp_allowed_hosts="mcp.example.com", **overrides)
    check_transport_policy(settings, insecure_dev=False)


def test_transport_policy_insecure_dev_override() -> None:
    settings = Settings(mcp_bind_host="0.0.0.0", mcp_allowed_hosts="mcp.example.com")
    check_transport_policy(settings, insecure_dev=True)

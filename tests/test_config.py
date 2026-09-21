import pytest

from mcp_gitlab.config import Settings


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITLAB_BASE_URL", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    settings = Settings()
    assert str(settings.gitlab_base_url) == "https://gitlab.com/api/v4"
    assert settings.gitlab_token is None
    assert settings.mcp_bind_host == "127.0.0.1"


def test_self_hosted_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_BASE_URL", "https://gitlab.example.com/api/v4")
    settings = Settings()
    assert settings.gitlab_base_url.host == "gitlab.example.com"


def test_skip_tls_verify_refused_for_gitlab_com(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITLAB_BASE_URL", raising=False)
    monkeypatch.setenv("GITLAB_SKIP_TLS_VERIFY", "true")
    with pytest.raises(ValueError):
        Settings()


def test_skip_tls_verify_allowed_for_self_hosted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_BASE_URL", "https://gitlab.example.com/api/v4")
    monkeypatch.setenv("GITLAB_SKIP_TLS_VERIFY", "true")
    settings = Settings()
    assert settings.gitlab_skip_tls_verify is True


def test_toolset_allowlist_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_MCP_TOOLSETS", "projects, issues ,pipelines")
    settings = Settings()
    assert settings.toolset_allowlist() == ["projects", "issues", "pipelines"]


def test_toolset_allowlist_default_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITLAB_MCP_TOOLSETS", raising=False)
    settings = Settings()
    assert settings.toolset_allowlist() is None

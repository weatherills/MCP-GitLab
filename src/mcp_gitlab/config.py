"""Server configuration, loaded from environment variables and an optional `.env` file.

Mirrors docs/prd/PRD-00-architecture.md section 8, plus the settings needed to
implement sections 4.3, 9 and 10, which the PRD's table leaves implicit.
"""

import ipaddress
from typing import Any, Literal

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_ALLOWED_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")
LOOPBACK_ALLOWED_ORIGINS = ("http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*")


class ConfigurationError(ValueError):
    """Settings that are individually valid but combine into an unsafe deployment."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    gitlab_base_url: AnyHttpUrl = AnyHttpUrl("https://gitlab.com/api/v4")
    gitlab_ca_bundle: str | None = None
    gitlab_skip_tls_verify: bool = False
    gitlab_timeout_seconds: float = Field(default=30.0, gt=0)
    gitlab_max_retries: int = Field(default=3, ge=0, le=10)
    gitlab_max_response_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    gitlab_mcp_toolsets: str | None = None
    gitlab_mcp_read_only: bool = False
    gitlab_mcp_max_file_bytes: int = Field(default=1024 * 1024, gt=0)

    mcp_stateless_http: bool = True
    mcp_json_response: bool = False
    mcp_session_idle_timeout: int = Field(default=1800, gt=0)
    mcp_max_sessions: int | None = Field(default=None, gt=0)

    mcp_bind_host: str = "127.0.0.1"
    mcp_bind_port: int = Field(default=8080, ge=1, le=65535)
    mcp_allowed_hosts: str | None = None
    mcp_allowed_origins: str | None = None
    mcp_tls_certfile: str | None = None
    mcp_tls_keyfile: str | None = None
    mcp_tls_terminated_upstream: bool = False

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    @field_validator("log_level", "log_format", mode="before")
    @classmethod
    def _normalize_case(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return (
            value.upper()
            if value.lower() in {"debug", "info", "warning", "error"}
            else value.lower()
        )

    @model_validator(mode="after")
    def _validate_combinations(self) -> "Settings":
        if self.gitlab_skip_tls_verify and self.gitlab_base_url.host == "gitlab.com":
            raise ValueError(
                "GITLAB_SKIP_TLS_VERIFY is refused against gitlab.com; it is only for "
                "self-hosted instances with an internal CA (see PRD-00 section 7.4)."
            )
        if bool(self.mcp_tls_certfile) != bool(self.mcp_tls_keyfile):
            raise ValueError("MCP_TLS_CERTFILE and MCP_TLS_KEYFILE must be set together.")
        if not self.is_loopback_bind and not self.mcp_allowed_hosts:
            raise ValueError(
                "MCP_ALLOWED_HOSTS is required when MCP_BIND_HOST is not a loopback address: "
                "Host/Origin validation (PRD-00 section 4.3) needs the public hostname(s) "
                "clients will use, e.g. MCP_ALLOWED_HOSTS=mcp.example.com."
            )
        return self

    @property
    def is_loopback_bind(self) -> bool:
        host = self.mcp_bind_host.strip("[]")
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    @property
    def tls_enabled(self) -> bool:
        return bool(self.mcp_tls_certfile and self.mcp_tls_keyfile)

    def allowed_hosts(self) -> list[str]:
        if self.mcp_allowed_hosts:
            return _split_csv(self.mcp_allowed_hosts)
        return list(LOOPBACK_ALLOWED_HOSTS)

    def allowed_origins(self) -> list[str]:
        """Browser origins allowed to call /mcp; an empty list rejects every browser Origin."""
        if self.mcp_allowed_origins:
            return _split_csv(self.mcp_allowed_origins)
        return list(LOOPBACK_ALLOWED_ORIGINS) if self.is_loopback_bind else []

    def toolset_allowlist(self) -> frozenset[str] | None:
        """Parsed GITLAB_MCP_TOOLSETS, or None meaning "use each toolset's default"."""
        if not self.gitlab_mcp_toolsets:
            return None
        return frozenset(_split_csv(self.gitlab_mcp_toolsets.lower())) or None


def check_transport_policy(settings: Settings, *, insecure_dev: bool) -> None:
    """PRD-00 section 9: never serve plaintext HTTP beyond loopback without an explicit override."""
    if (
        settings.is_loopback_bind
        or settings.tls_enabled
        or settings.mcp_tls_terminated_upstream
        or insecure_dev
    ):
        return
    raise ConfigurationError(
        f"Refusing to serve plaintext HTTP on {settings.mcp_bind_host}. Set MCP_TLS_CERTFILE and "
        "MCP_TLS_KEYFILE, or MCP_TLS_TERMINATED_UPSTREAM=true when a reverse proxy or load "
        "balancer terminates TLS in front of this server, or pass --insecure-dev for local testing."
    )


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]

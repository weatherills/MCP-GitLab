"""Server configuration, loaded from environment variables.

Mirrors the reference table in docs/prd/PRD-00-architecture.md section 8.
"""

from pydantic import AnyHttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    gitlab_base_url: AnyHttpUrl = AnyHttpUrl("https://gitlab.com/api/v4")
    gitlab_token: str | None = None
    gitlab_ca_bundle: str | None = None
    gitlab_skip_tls_verify: bool = False

    gitlab_mcp_toolsets: str | None = None
    gitlab_mcp_read_only: bool = False

    mcp_session_idle_timeout: int = 1800
    mcp_max_sessions: int = 100

    mcp_bind_host: str = "127.0.0.1"
    mcp_bind_port: int = 8080

    @model_validator(mode="after")
    def _tls_verification_required_for_gitlab_com(self) -> "Settings":
        if self.gitlab_skip_tls_verify and self.gitlab_base_url.host == "gitlab.com":
            raise ValueError(
                "GITLAB_SKIP_TLS_VERIFY is refused against gitlab.com; it is only for "
                "self-hosted instances with an internal CA (see PRD-00 section 7.4)."
            )
        return self

    def toolset_allowlist(self) -> list[str] | None:
        """Parsed GITLAB_MCP_TOOLSETS, or None meaning "use the default toolset set"."""
        if not self.gitlab_mcp_toolsets:
            return None
        return [name.strip() for name in self.gitlab_mcp_toolsets.split(",") if name.strip()]

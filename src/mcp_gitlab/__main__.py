"""`mcp-gitlab` / `python -m mcp_gitlab`: validate configuration, then serve over HTTP(S)."""

import argparse
import logging
import os
import sys
from collections.abc import Sequence

import uvicorn
from pydantic import ValidationError

from mcp_gitlab import __version__
from mcp_gitlab.app import create_app
from mcp_gitlab.config import ConfigurationError, Settings, check_transport_policy
from mcp_gitlab.core.logging import configure_logging, log_event

logger = logging.getLogger("mcp_gitlab")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        settings = Settings()
    except ValidationError as exc:
        print(f"mcp-gitlab: invalid configuration:\n{exc}", file=sys.stderr)
        return 2
    configure_logging(settings.log_level, settings.log_format)
    try:
        check_transport_policy(settings, insecure_dev=args.insecure_dev)
        app = create_app(settings)
    except (ConfigurationError, ValueError) as exc:
        log_event(logger, logging.ERROR, "configuration_error", detail=str(exc))
        return 2

    if os.environ.get("GITLAB_TOKEN"):
        log_event(
            logger,
            logging.WARNING,
            "gitlab_token_ignored",
            detail="GITLAB_TOKEN is set but ignored: this server holds no credentials of its own, "
            "so every request must carry its caller's PAT.",
        )
    log_event(
        logger,
        logging.INFO,
        "starting",
        version=__version__,
        host=settings.mcp_bind_host,
        port=settings.mcp_bind_port,
        stateless=settings.mcp_stateless_http,
        tls=settings.tls_enabled,
    )
    uvicorn.run(
        app,
        host=settings.mcp_bind_host,
        port=settings.mcp_bind_port,
        ssl_certfile=settings.mcp_tls_certfile,
        ssl_keyfile=settings.mcp_tls_keyfile,
        log_config=None,
        server_header=False,
    )
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mcp-gitlab", description="HTTPS GitLab MCP server.")
    parser.add_argument(
        "--insecure-dev",
        action="store_true",
        help="Allow plaintext HTTP on a non-loopback address; local testing only "
        "(PRD-00 section 9).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())

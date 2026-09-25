"""`mcp-gitlab` / `python -m mcp_gitlab`: validate configuration, then serve over HTTP(S)."""

import argparse
import logging
import os
import sys
from collections.abc import Sequence

import uvicorn
from pydantic import ValidationError

from mcp_gitlab import __version__, service
from mcp_gitlab.app import create_app
from mcp_gitlab.config import ConfigurationError, Settings, check_transport_policy
from mcp_gitlab.core.logging import configure_logging, log_event, log_settings_from_env

logger = logging.getLogger("mcp_gitlab")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "service":
        return _service(args.service_action)
    # "serve" subcommand or default (no subcommand) both run server
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


def _service(action: str) -> int:
    """Run the server as a detached background process, tracked by a pid file.

    OS-independent (POSIX and Windows alike): see service.py. This is an alternative to running
    `mcp-gitlab` in the foreground, not a substitute for the standalone Docker image, which
    remains the intended deployment (CLAUDE.md); `deploy/windows/` wraps this for Windows users
    who want it to start automatically, as a courtesy.
    """
    configure_logging(*log_settings_from_env(os.environ))
    server_argv = (sys.executable, "-m", "mcp_gitlab", "serve")
    pid_file = service.default_pid_file()
    log_file = service.default_log_file()
    try:
        if action == "start":
            service.start(server_argv, pid_file=pid_file, log_file=log_file)
        elif action == "stop":
            service.stop(pid_file=pid_file)
        else:
            service.restart(server_argv, pid_file=pid_file, log_file=log_file)
    except service.ServiceError as exc:
        log_event(logger, logging.ERROR, "service_action_failed", action=action, detail=str(exc))
        print(f"mcp-gitlab service {action}: {exc}", file=sys.stderr)
        return 1
    return 0


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mcp-gitlab", description="HTTPS GitLab MCP server.")
    sub = parser.add_subparsers(dest="command")
    svc = sub.add_parser(
        "service", help="Run the server as a detached background process, tracked by a pid file."
    )
    svc.add_argument("service_action", choices=["start", "stop", "restart"])
    sub.add_parser("serve", help="Run the MCP server (default).")
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

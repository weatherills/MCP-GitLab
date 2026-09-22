"""Executes one tool call: resolve, enforce policy, validate, invoke, shape the outcome."""

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from mcp_gitlab.config import Settings
from mcp_gitlab.core.context import MISSING_TOKEN_MESSAGE, RequestContext
from mcp_gitlab.core.errors import (
    AuthenticationRequiredError,
    ConfirmationRequiredError,
    InvalidArgumentsError,
    ToolError,
    UnknownToolError,
)
from mcp_gitlab.core.logging import log_event
from mcp_gitlab.gitlab.client import GitLabClient
from mcp_gitlab.gitlab.pagination import Page
from mcp_gitlab.tools.model import RESERVED_ARGUMENTS, Action, ActionContext, ActionParams
from mcp_gitlab.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    structured: dict[str, Any]
    is_error: bool


class Dispatcher:
    def __init__(self, registry: ToolRegistry, gitlab: GitLabClient, settings: Settings) -> None:
        self._registry = registry
        self._gitlab = gitlab
        self._settings = settings

    async def call(
        self, tool_name: str, arguments: Mapping[str, Any], request: RequestContext
    ) -> ToolOutcome:
        started = time.perf_counter()
        action_name = arguments.get("action")
        outcome = "ok"
        try:
            _, action = self._registry.resolve(tool_name, action_name, request)
            if request.credentials is None:
                raise AuthenticationRequiredError(MISSING_TOKEN_MESSAGE)
            if action.destructive and arguments.get("confirm") is not True:
                raise ConfirmationRequiredError(
                    f"'{action.name}' is destructive; call again with confirm=true to proceed."
                )
            params = _validate(action, arguments)
            context = ActionContext(
                request=request,
                gitlab=self._gitlab.session(request.credentials.token),
                settings=self._settings,
            )
            return ToolOutcome(_structured(await action.handler(params, context)), is_error=False)
        except UnknownToolError:
            outcome = UnknownToolError.code
            raise
        except ToolError as exc:
            outcome = exc.code
            return ToolOutcome({"error": exc.to_payload()}, is_error=True)
        except Exception:
            outcome = "internal_error"
            logger.exception("Unhandled error in tool '%s'", tool_name)
            return ToolOutcome(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "Unexpected server error; the server log has details "
                        "for this request id.",
                        "retryable": False,
                        "request_id": request.request_id,
                    }
                },
                is_error=True,
            )
        finally:
            log_event(
                logger,
                logging.INFO,
                "tool_call",
                tool=tool_name,
                action=action_name if isinstance(action_name, str) else None,
                outcome=outcome,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                # Names only: values can hold file contents or secrets.
                arguments=sorted(key for key in arguments if key not in RESERVED_ARGUMENTS),
            )


def _validate(action: Action, arguments: Mapping[str, Any]) -> ActionParams:
    values = {key: value for key, value in arguments.items() if key not in RESERVED_ARGUMENTS}
    try:
        return action.params.model_validate(values)
    except ValidationError as exc:
        problems = [
            {
                "field": ".".join(str(part) for part in error["loc"]) or "(arguments)",
                "message": error["msg"],
            }
            for error in exc.errors(include_url=False, include_input=False)
        ]
        raise InvalidArgumentsError(
            f"Invalid arguments for action '{action.name}'.",
            details={
                "problems": problems,
                "accepted_parameters": sorted(action.params.model_fields),
            },
        ) from exc


def _structured(result: Any) -> dict[str, Any]:
    """MCP structured content must be a JSON object; normalise handler results into one."""
    if isinstance(result, Page):
        return result.to_dict()
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return {"items": result}
    if result is None:
        return {"success": True}
    return {"result": result}

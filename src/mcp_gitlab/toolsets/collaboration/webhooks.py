"""gitlab_webhooks: a project's webhooks (PRD-08 section 3).

Secrets are write-only (PRD-08 section 4): create and update accept a secret token and a
signing token, and no response carries either back, even if GitLab were to send one. Custom
headers and URL variables, which can hold credentials too, are shown by key only.
"""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import GitLabUnprocessableError
from mcp_gitlab.gitlab import Page, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, query, with_hint

HookId = Annotated[int, Field(ge=1, description="The webhook's ID, from list.")]
HookUrl = Annotated[str, Field(min_length=1, description="URL GitLab sends events to.")]
EventFlag = Annotated[
    bool | None, Field(default=None, description="Send this kind of event to the webhook.")
]
# The events GitLab can send a sample of from a project webhook.
Trigger = Literal[
    "push_events",
    "tag_push_events",
    "issues_events",
    "confidential_issues_events",
    "note_events",
    "merge_requests_events",
    "job_events",
    "pipeline_events",
    "wiki_page_events",
    "releases_events",
    "milestone_events",
    "emoji_events",
    "resource_access_token_events",
    "resource_deploy_token_events",
]

SECRET_FIELDS = frozenset({"token", "signing_token"})
KEYED_SECRETS = ("custom_headers", "url_variables")


class HookSettings(ActionParams):
    """What create and update share; anything unset keeps GitLab's default or current value."""

    name: str | None = Field(default=None, min_length=1, description="Name of the webhook.")
    description: str | None = Field(default=None, description="What the webhook is for.")
    token: str | None = Field(
        default=None,
        min_length=1,
        description="Secret GitLab sends in the X-Gitlab-Token header, so the receiver can "
        "check a request came from GitLab. Write-only: it is never returned.",
    )
    signing_token: str | None = Field(
        default=None,
        min_length=1,
        description="Key GitLab signs each request with (webhook-signature header): whsec_ "
        "followed by 32 random bytes in base64. GitLab 19.0 and later. Write-only.",
    )
    enable_ssl_verification: bool | None = Field(
        default=None, description="Verify the receiver's TLS certificate; on by default."
    )
    push_events: bool | None = Field(
        default=None,
        description="Send push events. On by default for a new webhook: pass false to leave "
        "them out.",
    )
    push_events_branch_filter: str | None = Field(
        default=None,
        description="Send push events only for matching branches, such as release/*.",
    )
    branch_filter_strategy: Literal["wildcard", "regex", "all_branches"] | None = Field(
        default=None,
        description="How push_events_branch_filter matches: wildcard (the default), regex, or "
        "all_branches.",
    )
    tag_push_events: EventFlag
    merge_requests_events: EventFlag
    issues_events: EventFlag
    confidential_issues_events: EventFlag
    note_events: EventFlag
    confidential_note_events: EventFlag
    job_events: EventFlag
    pipeline_events: EventFlag
    wiki_page_events: EventFlag
    deployment_events: EventFlag
    feature_flag_events: EventFlag
    releases_events: EventFlag
    milestone_events: EventFlag
    emoji_events: EventFlag
    resource_access_token_events: EventFlag
    resource_deploy_token_events: EventFlag


class ListHooksParams(PageParams):
    project: ProjectRef


class HookParams(ActionParams):
    project: ProjectRef
    hook_id: HookId


class _NewHook(ActionParams):
    project: ProjectRef
    url: HookUrl


class CreateHookParams(HookSettings, _NewHook):
    pass


class _ChangedHook(HookParams):
    url: HookUrl | None = Field(
        default=None,
        description="New URL. Changing it makes GitLab drop the secret token and custom "
        "headers: send token again to keep one.",
    )


class UpdateHookParams(HookSettings, _ChangedHook):
    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateHookParams":
        if not query(self, "hook_id"):
            raise ValueError("Nothing to update: set url, an event, or another setting.")
        return self


class HookTestParams(HookParams):
    trigger: Trigger = Field(description="The kind of sample event to send.")


async def list_hooks(params: ListHooksParams, ctx: ActionContext) -> Page:
    page = await ctx.gitlab.get_page(_hooks_path(params.project), params=params.page_query())
    return Page(items=[redact(hook) for hook in page.items], info=page.info)


async def get_hook(params: HookParams, ctx: ActionContext) -> Any:
    return redact(await ctx.gitlab.get(_hook_path(params)))


async def create_hook(params: CreateHookParams, ctx: ActionContext) -> Any:
    hook = await ctx.gitlab.post(_hooks_path(params.project), json_body=query(params))
    return _written(hook, params)


async def update_hook(params: UpdateHookParams, ctx: ActionContext) -> Any:
    hook = await ctx.gitlab.put(_hook_path(params), json_body=query(params, "hook_id"))
    return _written(hook, params, url_sent=params.url is not None)


async def delete_hook(params: HookParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_hook_path(params))
    return {"deleted": params.hook_id}


async def send_test_event(params: HookTestParams, ctx: ActionContext) -> Any:
    try:
        response = await ctx.gitlab.post(f"{_hook_path(params)}/test/{params.trigger}")
    except GitLabUnprocessableError as exc:
        hint = (
            "The receiver answered with an error, or GitLab has no sample data for this event "
            "yet (push_events needs a commit in the project); GitLab's message says which."
        )
        raise with_hint(exc, hint) from exc
    return {"hook_id": params.hook_id, "trigger": params.trigger, "gitlab_response": response}


def redact(hook: Any) -> Any:
    """A webhook as GitLab describes it, minus anything secret."""
    if not isinstance(hook, dict):
        return hook
    shown = {key: value for key, value in hook.items() if key not in SECRET_FIELDS}
    for key in KEYED_SECRETS:
        if key in shown:
            shown[key] = _keys_only(shown[key])
    return shown


def _keys_only(entries: Any) -> list[dict[str, Any]]:
    if isinstance(entries, dict):
        return [{"key": key} for key in entries]
    if isinstance(entries, list):
        return [{"key": entry.get("key")} for entry in entries if isinstance(entry, dict)]
    return []


def _written(hook: Any, params: HookSettings, *, url_sent: bool = False) -> Any:
    shown = redact(hook)
    if not isinstance(shown, dict):
        return shown
    notes = []
    if params.signing_token and shown.get("signing_token_present") is not True:
        notes.append(
            "GitLab did not confirm the signing token; signing tokens need GitLab 19.0 or later."
        )
    if url_sent and params.token is None and shown.get("token_present") is not True:
        notes.append(
            "If the URL changed, GitLab dropped the secret token and custom headers: send "
            "token again if the receiver checks it."
        )
    return {**shown, "note": " ".join(notes)} if notes else shown


def _hooks_path(project: int | str) -> str:
    return f"{project_path(project)}/hooks"


def _hook_path(params: HookParams) -> str:
    return f"{_hooks_path(params.project)}/{params.hook_id}"


WEBHOOKS_TOOL = Tool(
    name="gitlab_webhooks",
    title="GitLab project webhooks",
    description=(
        "List, create, update, delete, and test a project's webhooks: which events GitLab sends "
        "to which URL. Secret and signing tokens are write-only and never returned."
    ),
    actions=(
        Action("list", "List a project's webhooks.", ListHooksParams, list_hooks, Access.READ),
        Action("get", "Get one webhook's settings.", HookParams, get_hook, Access.READ),
        Action(
            "create",
            "Add a webhook. A new webhook gets push events unless push_events is false; other "
            "events are off unless set.",
            CreateHookParams,
            create_hook,
            Access.WRITE,
        ),
        Action(
            "update",
            "Change a webhook's URL, events, or other settings; unset ones stay as they are.",
            UpdateHookParams,
            update_hook,
            Access.WRITE,
        ),
        Action("delete", "Delete a webhook.", HookParams, delete_hook, Access.WRITE),
        Action(
            "test",
            "Send the webhook a sample event now, to check the receiver works.",
            HookTestParams,
            send_test_event,
            Access.WRITE,
        ),
    ),
)

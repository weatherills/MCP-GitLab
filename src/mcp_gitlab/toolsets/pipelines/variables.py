"""gitlab_ci_variables: project CI/CD variables, whose values are secrets (PRD-05 s.3-4).

Values never leave GitLab through this tool unless a caller asks for one with
get and reveal_value=true: list and every write response hide them, and they are
never logged. update keeps the current value server-side when none is given, so
changing a flag never needs the secret in the model's context.
"""

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import InvalidArgumentsError
from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, query

VariableKey = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9_]{1,255}$",
        description="Variable key: letters, digits, and underscores.",
    ),
]
EnvironmentScope = Annotated[
    str | None,
    Field(
        default=None,
        min_length=1,
        description="The variable's environment scope, such as production or * (all). create "
        "sets it; get, update, and delete use it to pick one variable when several share a key.",
    ),
]
Protected = Annotated[
    bool | None,
    Field(default=None, description="Expose the variable only to protected branches and tags."),
]
Masked = Annotated[bool | None, Field(default=None, description="Mask the value in job logs.")]
VariableType = Annotated[
    Literal["env_var", "file"] | None,
    Field(default=None, description="env_var (the default) or file."),
]
Description = Annotated[str | None, Field(default=None, description="What the variable is for.")]


class ListVariablesParams(PageParams):
    project: ProjectRef


class VariableParams(ActionParams):
    project: ProjectRef
    key: VariableKey
    environment_scope: EnvironmentScope


class GetVariableParams(VariableParams):
    reveal_value: bool = Field(
        default=False,
        description="Return the secret value too. Leave false unless you truly need it.",
    )


class CreateVariableParams(VariableParams):
    value: str = Field(
        description="The value. It is stored in GitLab, never echoed back or logged here."
    )
    protected: Protected
    masked: Masked
    variable_type: VariableType
    description: Description


class UpdateVariableParams(VariableParams):
    value: str | None = Field(
        default=None,
        description="The value. It is stored in GitLab, never echoed back or logged here.",
    )
    protected: Protected
    masked: Masked
    variable_type: VariableType
    description: Description

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateVariableParams":
        if not query(self, "key", "environment_scope"):
            raise ValueError("Nothing to update: set value or at least one flag.")
        return self


async def list_variables(params: ListVariablesParams, ctx: ActionContext) -> Page:
    page = await ctx.gitlab.get_page(
        f"{project_path(params.project)}/variables", params=params.page_query()
    )
    return Page(items=[hide_value(variable) for variable in page.items], info=page.info)


async def get_variable(params: GetVariableParams, ctx: ActionContext) -> Any:
    variable = await ctx.gitlab.get(_variable_path(params), params=_scope_filter(params))
    return variable if params.reveal_value else hide_value(variable)


async def create_variable(params: CreateVariableParams, ctx: ActionContext) -> Any:
    created = await ctx.gitlab.post(
        f"{project_path(params.project)}/variables", json_body=query(params)
    )
    return hide_value(created)


async def update_variable(params: UpdateVariableParams, ctx: ActionContext) -> Any:
    body = query(params, "key", "environment_scope")
    if params.value is None:
        # GitLab requires the value on every update; carry the current one over server-side.
        current = await ctx.gitlab.get(_variable_path(params), params=_scope_filter(params))
        if current.get("value") is None:
            raise InvalidArgumentsError(
                f"GitLab hides the value of '{params.key}' (masked and hidden), so it cannot be "
                "carried over: pass value to update this variable."
            )
        body["value"] = current["value"]
    updated = await ctx.gitlab.put(
        _variable_path(params), json_body=body, params=_scope_filter(params)
    )
    return hide_value(updated)


async def delete_variable(params: VariableParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_variable_path(params), params=_scope_filter(params))
    return {"deleted": params.key, "environment_scope": params.environment_scope}


def hide_value(variable: Any) -> Any:
    if not isinstance(variable, dict):
        return variable
    shown = {key: value for key, value in variable.items() if key != "value"}
    shown["value_hidden"] = True
    return shown


def _variable_path(params: VariableParams) -> str:
    return f"{project_path(params.project)}/variables/{encode_segment(params.key)}"


def _scope_filter(params: VariableParams) -> dict[str, Any]:
    if params.environment_scope is None:
        return {}
    return {"filter[environment_scope]": params.environment_scope}


CI_VARIABLES_TOOL = Tool(
    name="gitlab_ci_variables",
    title="GitLab CI/CD variables",
    description=(
        "Manage a project's CI/CD variables. Values are secrets: they are hidden everywhere "
        "except get with reveal_value=true, and never logged."
    ),
    actions=(
        Action(
            "list",
            "List variables: keys and settings, never values.",
            ListVariablesParams,
            list_variables,
            Access.READ,
        ),
        Action(
            "get",
            "Get one variable; its value only with reveal_value=true.",
            GetVariableParams,
            get_variable,
            Access.READ,
        ),
        Action("create", "Create a variable.", CreateVariableParams, create_variable, Access.WRITE),
        Action(
            "update",
            "Change a variable's value or settings; omit value to keep the current one.",
            UpdateVariableParams,
            update_variable,
            Access.WRITE,
        ),
        Action("delete", "Delete a variable.", VariableParams, delete_variable, Access.WRITE),
    ),
)

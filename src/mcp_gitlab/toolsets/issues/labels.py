"""gitlab_labels: a project's or a group's labels (PRD-04 section 3)."""

from typing import Annotated, Any

from pydantic import Field, model_validator

from mcp_gitlab.core.errors import GitLabNotFoundError
from mcp_gitlab.gitlab import Page, encode_segment
from mcp_gitlab.tools import Access, Action, ActionContext, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectOrGroup, query, with_hint

LabelRef = Annotated[
    Annotated[int, Field(ge=1)] | Annotated[str, Field(min_length=1)],
    Field(description="The label's ID or name."),
]
Color = Annotated[
    str | None,
    Field(
        default=None,
        min_length=1,
        description="Color as #RRGGBB or a CSS color name, such as #D9534F or red.",
    ),
]
Priority = Annotated[
    int | None,
    Field(
        default=None,
        ge=0,
        description="Priority in this project; lower numbers sort first. Project labels only.",
    ),
]
LabelDescription = Annotated[str | None, Field(default=None, description="What the label means.")]
INHERITED_HINT = (
    "A label the project inherits from a group is changed through that group: give group "
    "instead of project."
)


class ListLabelsParams(ProjectOrGroup, PageParams):
    search: str | None = Field(default=None, description="Only labels matching this keyword.")
    with_counts: bool | None = Field(
        default=None, description="Include open issue and merge request counts."
    )


class LabelParams(ProjectOrGroup):
    label: LabelRef


class CreateLabelParams(ProjectOrGroup):
    name: str = Field(min_length=1, description="Label name.")
    color: Color
    description: LabelDescription
    priority: Priority

    @model_validator(mode="after")
    def _valid_label(self) -> "CreateLabelParams":
        if self.color is None:
            raise ValueError("A new label needs a color.")
        _check_priority(self.group, self.priority)
        return self


class UpdateLabelParams(LabelParams):
    new_name: str | None = Field(default=None, min_length=1, description="New label name.")
    color: Color
    description: LabelDescription
    priority: Priority

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateLabelParams":
        if not query(self, "group", "label"):
            raise ValueError("Nothing to update: set new_name, color, description, or priority.")
        _check_priority(self.group, self.priority)
        return self


async def list_labels(params: ListLabelsParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(f"{params.owner_path()}/labels", params=query(params, "group"))


async def get_label(params: LabelParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_label_path(params))


async def create_label(params: CreateLabelParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{params.owner_path()}/labels", json_body=query(params, "group"))


async def update_label(params: UpdateLabelParams, ctx: ActionContext) -> Any:
    try:
        return await ctx.gitlab.put(_label_path(params), json_body=query(params, "group", "label"))
    except GitLabNotFoundError as exc:
        if _maybe_inherited(params, exc):
            raise with_hint(exc, INHERITED_HINT) from exc
        raise


async def delete_label(params: LabelParams, ctx: ActionContext) -> Any:
    try:
        await ctx.gitlab.delete(_label_path(params))
    except GitLabNotFoundError as exc:
        if _maybe_inherited(params, exc):
            raise with_hint(exc, INHERITED_HINT) from exc
        raise
    return {"deleted": params.label}


def _label_path(params: LabelParams) -> str:
    return f"{params.owner_path()}/labels/{encode_segment(str(params.label))}"


def _check_priority(group: int | str | None, priority: int | None) -> None:
    if group is not None and priority is not None:
        raise ValueError("priority is set per project, so group labels have none.")


def _maybe_inherited(params: LabelParams, exc: GitLabNotFoundError) -> bool:
    """A project lists the labels it inherits from its groups, but can't change them."""
    return params.project is not None and "Label Not Found" in str(
        exc.details.get("gitlab_message", "")
    )


LABELS_TOOL = Tool(
    name="gitlab_labels",
    title="GitLab labels",
    description="List, create, update, and delete a project's or a group's labels.",
    actions=(
        Action(
            "list",
            "List labels. A project's list includes the labels it inherits from its groups.",
            ListLabelsParams,
            list_labels,
            Access.READ,
        ),
        Action("get", "Get one label.", LabelParams, get_label, Access.READ),
        Action("create", "Create a label.", CreateLabelParams, create_label, Access.WRITE),
        Action(
            "update",
            "Rename a label or change its color, description, or priority.",
            UpdateLabelParams,
            update_label,
            Access.WRITE,
        ),
        Action(
            "delete",
            "Delete a label; it is removed from every issue and merge request.",
            LabelParams,
            delete_label,
            Access.WRITE,
        ),
    ),
)

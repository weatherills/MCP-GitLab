"""gitlab_labels: a project's labels (PRD-04 section 3)."""

from typing import Annotated, Any

from pydantic import Field, model_validator

from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import Access, Action, ActionContext, ActionParams, PageParams, Tool
from mcp_gitlab.toolsets.common import ProjectRef, query

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
    Field(default=None, ge=0, description="Priority; lower numbers sort first."),
]
LabelDescription = Annotated[str | None, Field(default=None, description="What the label means.")]


class ListLabelsParams(PageParams):
    project: ProjectRef
    search: str | None = Field(default=None, description="Only labels matching this keyword.")
    with_counts: bool | None = Field(
        default=None, description="Include open issue and merge request counts."
    )


class LabelParams(ActionParams):
    project: ProjectRef
    label: LabelRef


class CreateLabelParams(ActionParams):
    project: ProjectRef
    name: str = Field(min_length=1, description="Label name.")
    color: Color
    description: LabelDescription
    priority: Priority

    @model_validator(mode="after")
    def _needs_color(self) -> "CreateLabelParams":
        if self.color is None:
            raise ValueError("A new label needs a color.")
        return self


class UpdateLabelParams(LabelParams):
    new_name: str | None = Field(default=None, min_length=1, description="New label name.")
    color: Color
    description: LabelDescription
    priority: Priority

    @model_validator(mode="after")
    def _has_changes(self) -> "UpdateLabelParams":
        if not query(self, "label"):
            raise ValueError("Nothing to update: set new_name, color, description, or priority.")
        return self


async def list_labels(params: ListLabelsParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(f"{project_path(params.project)}/labels", params=query(params))


async def get_label(params: LabelParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(_label_path(params))


async def create_label(params: CreateLabelParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{project_path(params.project)}/labels", json_body=query(params))


async def update_label(params: UpdateLabelParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.put(_label_path(params), json_body=query(params, "label"))


async def delete_label(params: LabelParams, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(_label_path(params))
    return {"deleted": params.label}


def _label_path(params: LabelParams) -> str:
    return f"{project_path(params.project)}/labels/{encode_segment(str(params.label))}"


LABELS_TOOL = Tool(
    name="gitlab_labels",
    title="GitLab labels",
    description="List, create, update, and delete a project's labels.",
    actions=(
        Action(
            "list",
            "List labels, including those inherited from parent groups.",
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

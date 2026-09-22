"""A test-only toolset shaped like the real PRD toolsets, used to exercise the framework."""

from typing import Any

from pydantic import Field

from mcp_gitlab.core.context import Credentials, RequestContext
from mcp_gitlab.gitlab import Page, encode_segment, project_path
from mcp_gitlab.tools import (
    Access,
    Action,
    ActionContext,
    ActionParams,
    NoParams,
    PageParams,
    Tool,
    Toolset,
)

TOKEN = "glpat-testtokenabcdefghij"


class ListWidgetsParams(PageParams):
    project: str = Field(min_length=1, description="Project ID or namespace/path.")
    search: str | None = Field(default=None, description="Filter widgets by name.")


class WidgetRef(ActionParams):
    project: str = Field(min_length=1, description="Project ID or namespace/path.")
    widget: str = Field(min_length=1, description="Widget name.")


class CreateWidgetParams(WidgetRef):
    colour: str = Field(default="blue", description="Widget colour.")


async def list_widgets(params: ListWidgetsParams, ctx: ActionContext) -> Page:
    return await ctx.gitlab.get_page(
        f"{project_path(params.project)}/widgets",
        params={**params.page_query(), "search": params.search},
    )


async def get_widget(params: WidgetRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(
        f"{project_path(params.project)}/widgets/{encode_segment(params.widget)}"
    )


async def create_widget(params: CreateWidgetParams, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(
        f"{project_path(params.project)}/widgets",
        json_body={"name": params.widget, "colour": params.colour},
    )


async def delete_widget(params: WidgetRef, ctx: ActionContext) -> Any:
    await ctx.gitlab.delete(
        f"{project_path(params.project)}/widgets/{encode_segment(params.widget)}"
    )
    return {"deleted": params.widget}


async def explode(params: NoParams, ctx: ActionContext) -> Any:
    raise RuntimeError(f"internal detail that must not leak: {TOKEN}")


async def list_gadgets(params: NoParams, ctx: ActionContext) -> Any:
    return ["g1", "g2"]


WIDGETS = Tool(
    name="fake_widgets",
    description="Manage widgets in a project.",
    actions=(
        Action("list", "List widgets.", ListWidgetsParams, list_widgets, Access.READ),
        Action("get", "Get one widget.", WidgetRef, get_widget, Access.READ),
        Action("create", "Create a widget.", CreateWidgetParams, create_widget, Access.WRITE),
        Action(
            "delete", "Delete a widget.", WidgetRef, delete_widget, Access.WRITE, destructive=True
        ),
        Action("explode", "Always fails.", NoParams, explode, Access.READ),
    ),
)

GADGETS = Tool(
    name="fake_gadgets",
    description="Opt-in gadgets.",
    actions=(Action("list", "List gadgets.", NoParams, list_gadgets, Access.READ),),
)

FAKE_TOOLSET = Toolset(name="fake", description="Test widgets.", tools=(WIDGETS,))
OPTIONAL_TOOLSET = Toolset(
    name="optional", description="Not enabled by default.", tools=(GADGETS,), default_enabled=False
)
ALL_FAKE_TOOLSETS = (FAKE_TOOLSET, OPTIONAL_TOOLSET)


def request_context(
    *,
    token: str | None = TOKEN,
    toolsets: frozenset[str] | None = None,
    read_only: bool = False,
) -> RequestContext:
    return RequestContext(
        request_id="req-test",
        credentials=Credentials(token) if token else None,
        requested_toolsets=toolsets,
        read_only=read_only,
    )

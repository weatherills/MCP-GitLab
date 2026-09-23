"""Time tracking, shared by merge requests (PRD-03) and issues (PRD-04).

GitLab exposes the same endpoints on both: `/<collection>/:iid/time_estimate`,
`reset_time_estimate`, `add_spent_time`, `reset_spent_time`, and `time_stats`. Each toolset
passes its `NoteableRef` subclass and the parameter classes it built from the mixins below to
`time_tracking_actions`.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import Field

from mcp_gitlab.tools import Access, Action, ActionContext
from mcp_gitlab.toolsets.threads import NoteableRef

Duration = Annotated[
    str,
    Field(
        min_length=1,
        description="Duration in GitLab's format, such as 3h30m, 1d (8 hours), or 45m; a bare "
        "number means hours. For add_spent_time, a leading minus subtracts, as in -30m.",
    ),
]


class TimeEstimateFields(NoteableRef):
    duration: Duration


class SpentTimeFields(NoteableRef):
    duration: Duration
    summary: str | None = Field(
        default=None, min_length=1, description="What the time was spent on."
    )


async def get_time_stats(params: NoteableRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.get(f"{params.path()}/time_stats")


async def set_time_estimate(params: TimeEstimateFields, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(
        f"{params.path()}/time_estimate", json_body={"duration": params.duration}
    )


async def reset_time_estimate(params: NoteableRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{params.path()}/reset_time_estimate")


async def add_spent_time(params: SpentTimeFields, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{params.path()}/add_spent_time", json_body=params.fields())


async def reset_spent_time(params: NoteableRef, ctx: ActionContext) -> Any:
    return await ctx.gitlab.post(f"{params.path()}/reset_spent_time")


@dataclass(frozen=True)
class TimeTrackingParams:
    """The concrete parameter classes one toolset built from the mixins above."""

    ref: type[NoteableRef]
    estimate: type[TimeEstimateFields]
    spent: type[SpentTimeFields]


def time_tracking_actions(label: str, params: TimeTrackingParams) -> tuple[Action, ...]:
    """The time tracking actions for one kind of noteable, such as "issue"."""
    return (
        Action(
            "get_time_stats",
            f"Get the {label}'s time estimate and total time spent.",
            params.ref,
            get_time_stats,
            Access.READ,
        ),
        Action(
            "set_time_estimate",
            f"Set how long the {label} is expected to take.",
            params.estimate,
            set_time_estimate,
            Access.WRITE,
        ),
        Action(
            "reset_time_estimate",
            f"Clear the {label}'s time estimate.",
            params.ref,
            reset_time_estimate,
            Access.WRITE,
        ),
        Action(
            "add_spent_time",
            f"Record time spent on the {label}.",
            params.spent,
            add_spent_time,
            Access.WRITE,
        ),
        Action(
            "reset_spent_time",
            f"Clear all time recorded as spent on the {label}.",
            params.ref,
            reset_spent_time,
            Access.WRITE,
        ),
    )

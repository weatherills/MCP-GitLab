"""Parameter types and helpers shared across toolsets, so each means the same thing everywhere."""

from typing import Annotated, Any, Literal

from pydantic import Field, PrivateAttr, model_validator

from mcp_gitlab.core.errors import GitLabError
from mcp_gitlab.gitlab import group_path, project_path
from mcp_gitlab.tools import ActionParams

ProjectRef = Annotated[
    Annotated[int, Field(ge=1)] | Annotated[str, Field(min_length=1)],
    Field(description="Project ID, or its full path such as group/subgroup/project."),
]
NamespaceRef = Annotated[
    Annotated[int, Field(ge=1)] | Annotated[str, Field(min_length=1)],
    Field(description="Group or user namespace, as an ID or full path such as group/subgroup."),
]
GroupRef = Annotated[
    Annotated[int, Field(ge=1)] | Annotated[str, Field(min_length=1)],
    Field(description="Group ID, or its full path such as parent/child."),
]
Ref = Annotated[str, Field(min_length=1, description="Branch name, tag name, or commit SHA.")]
IsoDate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Date as YYYY-MM-DD.")]
Visibility = Literal["private", "internal", "public"]
ProtectedAccess = Literal["no_access", "developer", "maintainer"]

ACCESS_LEVELS: dict[str, int] = {"no_access": 0, "developer": 30, "maintainer": 40}


class ProjectOrGroup(ActionParams):
    """Parameters for something a project or a group owns, such as a label: exactly one of the
    two. `query(params, "group")` leaves both out of the GitLab fields."""

    project: ProjectRef | None = Field(
        default=None,
        description="Project ID, or its full path such as group/subgroup/project. Give project "
        "or group.",
    )
    group: GroupRef | None = Field(
        default=None,
        description="Group ID, or its full path such as parent/child. A group's own are shared "
        "by its subgroups and projects. Give project or group.",
    )
    _owner_path: str = PrivateAttr(default="")

    @model_validator(mode="after")
    def _one_owner(self) -> "ProjectOrGroup":
        if self.project is not None and self.group is None:
            self._owner_path = project_path(self.project)
        elif self.group is not None and self.project is None:
            self._owner_path = group_path(self.group)
        else:
            raise ValueError("Give exactly one of project or group.")
        return self

    def owner_path(self) -> str:
        """`/projects/:id` or `/groups/:id`, whichever was given."""
        return self._owner_path


def query(params: ActionParams, *exclude: str) -> dict[str, Any]:
    """The set parameters as GitLab query/body fields, minus path parameters."""
    return params.model_dump(exclude={"project", *exclude}, exclude_none=True)


def with_csv_labels(fields: dict[str, Any]) -> dict[str, Any]:
    """GitLab takes label lists as one comma-separated string."""
    if isinstance(fields.get("labels"), list):
        fields["labels"] = ",".join(fields["labels"])
    return fields


def with_hint(error: GitLabError, hint: str) -> GitLabError:
    """The same GitLab error, with advice on what to do next added to its message."""
    return type(error)(
        f"{error.message} {hint}", status=error.status, details={**error.details, "hint": hint}
    )

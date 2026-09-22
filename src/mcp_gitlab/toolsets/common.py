"""Parameter types and helpers shared across toolsets, so each means the same thing everywhere."""

from typing import Annotated, Any, Literal

from pydantic import Field

from mcp_gitlab.tools import ActionParams

ProjectRef = Annotated[
    Annotated[int, Field(ge=1)] | Annotated[str, Field(min_length=1)],
    Field(description="Project ID, or its full path such as group/subgroup/project."),
]
NamespaceRef = Annotated[
    Annotated[int, Field(ge=1)] | Annotated[str, Field(min_length=1)],
    Field(description="Group or user namespace, as an ID or full path such as group/subgroup."),
]
Ref = Annotated[str, Field(min_length=1, description="Branch name, tag name, or commit SHA.")]
Visibility = Literal["private", "internal", "public"]
ProtectedAccess = Literal["no_access", "developer", "maintainer"]

ACCESS_LEVELS: dict[str, int] = {"no_access": 0, "developer": 30, "maintainer": 40}


def query(params: ActionParams, *exclude: str) -> dict[str, Any]:
    """The set parameters as GitLab query/body fields, minus path parameters."""
    return params.model_dump(exclude={"project", *exclude}, exclude_none=True)

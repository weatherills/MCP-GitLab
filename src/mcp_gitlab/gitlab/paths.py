"""Path-segment encoding for GitLab REST paths (PRD-01 section 4, PRD-02 section 3)."""

from urllib.parse import quote


def encode_segment(value: str) -> str:
    """Percent-encode one path segment, "/" included (GitLab expects `group%2Fproject`)."""
    if not value:
        raise ValueError("A GitLab path segment cannot be empty.")
    return quote(value, safe="")


def encode_wildcard_path(value: str) -> str:
    """Encode a multi-segment path for a GitLab wildcard route (`*artifact_path`), keeping "/".

    Wildcard routes take literal slashes, so each segment is encoded on its own. "." and ".."
    segments are refused: a URL resolves them, which could step outside the intended route.
    """
    segments = value.strip("/").split("/")
    if not value.strip("/") or any(segment in ("", ".", "..") for segment in segments):
        raise ValueError(f"'{value}' is not a valid relative path.")
    return "/".join(quote(segment, safe="") for segment in segments)


def project_path(project: int | str) -> str:
    """`/projects/:id` for a numeric ID or a URL-encoded `namespace/project` path."""
    if isinstance(project, int):
        if project < 1:
            raise ValueError("A GitLab project ID must be a positive integer.")
        return f"/projects/{project}"
    if project.isdigit():
        return f"/projects/{int(project)}"
    return f"/projects/{encode_segment(project.strip())}"


def group_path(group: int | str) -> str:
    """`/groups/:id` for a numeric ID or a URL-encoded `parent/child` path."""
    if isinstance(group, int):
        if group < 1:
            raise ValueError("A GitLab group ID must be a positive integer.")
        return f"/groups/{group}"
    if group.isdigit():
        return f"/groups/{int(group)}"
    return f"/groups/{encode_segment(group.strip())}"

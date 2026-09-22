"""Path-segment encoding for GitLab REST paths (PRD-01 section 4, PRD-02 section 3)."""

from urllib.parse import quote


def encode_segment(value: str) -> str:
    """Percent-encode one path segment, "/" included (GitLab expects `group%2Fproject`)."""
    if not value:
        raise ValueError("A GitLab path segment cannot be empty.")
    return quote(value, safe="")


def project_path(project: int | str) -> str:
    """`/projects/:id` for a numeric ID or a URL-encoded `namespace/project` path."""
    if isinstance(project, int):
        if project < 1:
            raise ValueError("A GitLab project ID must be a positive integer.")
        return f"/projects/{project}"
    if project.isdigit():
        return f"/projects/{int(project)}"
    return f"/projects/{encode_segment(project.strip())}"

"""Outbound adapter for the GitLab REST API."""

from mcp_gitlab.gitlab.client import GitLabClient, GitLabResponse, GitLabSession
from mcp_gitlab.gitlab.pagination import Page, PageInfo
from mcp_gitlab.gitlab.paths import encode_segment, encode_wildcard_path, project_path

__all__ = [
    "GitLabClient",
    "GitLabResponse",
    "GitLabSession",
    "Page",
    "PageInfo",
    "encode_segment",
    "encode_wildcard_path",
    "project_path",
]

"""PRD-06 toolset `releases`: gitlab_releases and gitlab_release_links."""

import pytest

from tests.support import GitLabStub, StubResponse
from tests.toolsets.wire import Case, assert_wire, body_of, call

LIST = StubResponse(json=[])
P = "/projects/grp%2Fapp"
REL = f"{P}/releases/v1.2.0"
LINKS = f"{REL}/assets/links"
REF = {"project": "grp/app", "tag": "v1.2.0"}
PAGE = {"page": "1", "per_page": "20"}

CASES = [
    Case(
        "gitlab_releases",
        {"action": "list", "project": "grp/app", "order_by": "created_at"},
        "GET",
        f"{P}/releases",
        {**PAGE, "order_by": "created_at"},
        response=LIST,
    ),
    Case("gitlab_releases", {"action": "get", **REF}, "GET", REL),
    Case(
        "gitlab_releases",
        {
            "action": "create",
            **REF,
            "name": "1.2.0",
            "description": "## Changes\n- Login",
            "ref": "main",
            "released_at": "2026-10-01T12:00:00Z",
            "milestones": ["1.2"],
        },
        "POST",
        f"{P}/releases",
        body={
            "tag_name": "v1.2.0",
            "name": "1.2.0",
            "description": "## Changes\n- Login",
            "ref": "main",
            "released_at": "2026-10-01T12:00:00Z",
            "milestones": ["1.2"],
        },
        response=StubResponse(status=201, json={"tag_name": "v1.2.0"}),
    ),
    Case(
        "gitlab_releases",
        {"action": "update", **REF, "description": "Fixed notes"},
        "PUT",
        REL,
        body={"description": "Fixed notes"},
    ),
    Case(
        "gitlab_releases",
        {"action": "delete", **REF},
        "DELETE",
        REL,
        response=StubResponse(json={"tag_name": "v1.2.0"}),
    ),
    Case("gitlab_release_links", {"action": "list", **REF}, "GET", LINKS, PAGE, response=LIST),
    Case("gitlab_release_links", {"action": "get", **REF, "link_id": 3}, "GET", f"{LINKS}/3"),
    Case(
        "gitlab_release_links",
        {
            "action": "create",
            **REF,
            "name": "Linux binary",
            "url": "https://example.com/app-linux",
            "link_type": "package",
        },
        "POST",
        LINKS,
        body={
            "name": "Linux binary",
            "url": "https://example.com/app-linux",
            "link_type": "package",
        },
        response=StubResponse(status=201, json={"id": 3}),
    ),
    Case(
        "gitlab_release_links",
        {"action": "update", **REF, "link_id": 3, "direct_asset_path": "/binaries/app"},
        "PUT",
        f"{LINKS}/3",
        body={"direct_asset_path": "/binaries/app"},
    ),
    Case("gitlab_release_links", {"action": "delete", **REF, "link_id": 3}, "DELETE", f"{LINKS}/3"),
]


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_action_reaches_the_documented_endpoint(case: Case) -> None:
    await assert_wire(case)


async def test_deleting_a_release_says_the_tag_is_kept() -> None:
    stub = GitLabStub()
    stub.add("DELETE", REL, StubResponse(json={"tag_name": "v1.2.0"}))
    outcome = await call(stub, "gitlab_releases", {"action": "delete", **REF})
    assert outcome.structured["tag_kept"] is True
    assert "gitlab_tags" in outcome.structured["note"]


def test_release_delete_needs_no_confirmation() -> None:
    from mcp_gitlab.toolsets.releases.releases import RELEASES_TOOL

    delete = RELEASES_TOOL.action("delete")
    assert delete is not None and delete.destructive is False
    assert "tag is kept" in delete.description


async def test_tags_with_slashes_are_encoded() -> None:
    stub = GitLabStub()
    stub.add("GET", f"{P}/releases/release%2F2026", StubResponse(json={}))
    await call(
        stub, "gitlab_releases", {"action": "get", "project": "grp/app", "tag": "release/2026"}
    )
    assert stub.requests[-1].url.raw_path.decode().endswith("/releases/release%2F2026")


@pytest.mark.parametrize("released_at", ["2026-10-01", "2026-10-01T12:00:00+02:00"])
async def test_release_dates_accept_iso_8601(released_at: str) -> None:
    stub = GitLabStub()
    stub.add("PUT", REL, StubResponse(json={}))
    await call(stub, "gitlab_releases", {"action": "update", **REF, "released_at": released_at})
    assert body_of(stub.requests[-1]) == {"released_at": released_at}


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("gitlab_releases", {"action": "update", **REF}),
        ("gitlab_release_links", {"action": "update", **REF, "link_id": 3}),
        ("gitlab_releases", {"action": "update", **REF, "released_at": "next tuesday"}),
    ],
)
async def test_invalid_updates_are_rejected(tool: str, arguments: dict[str, object]) -> None:
    outcome = await call(GitLabStub(), tool, arguments)
    assert outcome.structured["error"]["code"] == "invalid_arguments"

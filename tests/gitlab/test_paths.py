import pytest

from mcp_gitlab.gitlab.paths import encode_segment, project_path


def test_encode_segment_encodes_slashes() -> None:
    assert encode_segment("group/sub/project") == "group%2Fsub%2Fproject"


def test_encode_segment_encodes_reserved_characters() -> None:
    assert encode_segment("feature/a b#c?d") == "feature%2Fa%20b%23c%3Fd"


def test_encode_segment_rejects_empty() -> None:
    with pytest.raises(ValueError):
        encode_segment("")


@pytest.mark.parametrize(
    ("project", "expected"),
    [(42, "/projects/42"), ("42", "/projects/42"), ("group/project", "/projects/group%2Fproject")],
)
def test_project_path(project: int | str, expected: str) -> None:
    assert project_path(project) == expected


def test_project_path_rejects_non_positive_ids() -> None:
    with pytest.raises(ValueError):
        project_path(0)

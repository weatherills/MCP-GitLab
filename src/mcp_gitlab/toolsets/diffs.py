"""Changed-files summaries first, full diff text only on request (PRD-00 section 10)."""

from collections.abc import Iterable, Mapping
from typing import Any

_DIFF_FLAGS = ("old_path", "new_path", "new_file", "renamed_file", "deleted_file")
# Only some endpoints send these (merge request diffs do); pass them on when present.
_OPTIONAL_FLAGS = ("too_large", "collapsed", "generated_file")
_COMMIT_FIELDS = ("id", "short_id", "title", "author_name", "authored_date")


def summarize_diffs(
    entries: Iterable[Mapping[str, Any]], include_diff_for: Iterable[str] = ()
) -> list[dict[str, Any]]:
    wanted = set(include_diff_for)
    return [
        summarize_diff(entry, entry.get("new_path") in wanted or entry.get("old_path") in wanted)
        for entry in entries
    ]


def summarize_diff(entry: Mapping[str, Any], include_diff: bool) -> dict[str, Any]:
    text = entry.get("diff") or ""
    # GitLab's default (non-unidiff) format has no file headers, so every +/- line is content.
    additions = sum(1 for line in text.splitlines() if line.startswith("+"))
    deletions = sum(1 for line in text.splitlines() if line.startswith("-"))
    summary: dict[str, Any] = {key: entry.get(key) for key in _DIFF_FLAGS}
    summary.update({key: entry[key] for key in _OPTIONAL_FLAGS if key in entry})
    summary.update(additions=additions, deletions=deletions)
    if include_diff:
        summary["diff"] = text
    return summary


def summarize_commit(commit: Mapping[str, Any]) -> dict[str, Any]:
    return {key: commit.get(key) for key in _COMMIT_FIELDS}

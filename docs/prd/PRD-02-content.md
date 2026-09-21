# PRD-02: Repository Content & Commits

**Status:** Draft · **Toolset name:** `repository` · **Depends on:** PRD-00, PRD-01 (project/branch identifiers)

## 1. Overview

Covers reading and writing the actual contents of a repository at a given ref: browsing the file
tree, reading/writing individual files, and inspecting commit history, diffs, and comparisons.
This is the toolset an AI coding agent uses most heavily once a project is identified.

## 2. Goals

- Browse the repository tree at any ref (branch, tag, or SHA).
- Read and write file content (single-file and atomic multi-file commits).
- Inspect commit history, individual commits, diffs, and branch/ref comparisons.
- Support cherry-pick and revert as first-class commit operations.

## 3. Functional Requirements

### `gitlab_repository_tree`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/repository/tree` | `path`, `ref`, `recursive`; paginated per PRD-00 §10 |

### `gitlab_files`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `get` | `GET /projects/:id/repository/files/:file_path` | Returns metadata + base64 content at `ref` |
| `get_raw` | `GET /projects/:id/repository/files/:file_path/raw` | Raw bytes; size-limited per §4 |
| `get_blame` | `GET /projects/:id/repository/files/:file_path/blame` | Per-line commit attribution |
| `create` | `POST /projects/:id/repository/files/:file_path` | Requires `branch`, `commit_message`, `content` |
| `update` | `PUT /projects/:id/repository/files/:file_path` | Same as create + `last_commit_id` to detect conflicting concurrent edits |
| `delete` | `DELETE /projects/:id/repository/files/:file_path` | Requires `branch`, `commit_message` |

### `gitlab_commits`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/repository/commits` | Filters: `ref_name`, `since`, `until`, `path`, `author` |
| `get` | `GET /projects/:id/repository/commits/:sha` | |
| `get_diff` | `GET /projects/:id/repository/commits/:sha/diff` | Returns changed-files list; see §4 for large-diff handling |
| `compare` | `GET /projects/:id/repository/compare?from=&to=` | Branch/tag/SHA comparison |
| `batch_commit` | `POST /projects/:id/repository/commits` | Atomic multi-file commit via the `actions[]` array (create/update/delete/move/chmod in one commit) — the preferred way to change more than one file at once |
| `cherry_pick` | `POST /projects/:id/repository/commits/:sha/cherry_pick` | Target branch |
| `revert` | `POST /projects/:id/repository/commits/:sha/revert` | Target branch |
| `list_statuses` | `GET /projects/:id/repository/commits/:sha/statuses` | CI status per commit |
| `list_comments` / `create_comment` | `GET`/`POST /projects/:id/repository/commits/:sha/comments` | |

## 4. Non-Functional Requirements

- **Large payload discipline (per PRD-00 §10):** `get_diff` and `compare` return a changed-files
  summary (paths + insertion/deletion counts) by default; full per-file diff text is fetched via a
  separate call/parameter (`include_diff_for: [<path>]`) so a large MR-sized commit doesn't blow
  out the response in one shot.
- File content is transmitted base64-encoded both directions to handle binary files safely;
  `get_raw` enforces a configurable max size (default 1&nbsp;MB) and returns a clear "too large,
  use get_raw with a byte range / clone instead" error above it rather than truncating silently.
- `update`/`delete` require `last_commit_id` (or equivalent) so the server surfaces GitLab's own
  conflict error when the file changed since the caller last read it, instead of silently
  overwriting a concurrent edit.
- Prefer `batch_commit` over sequential single-file `create`/`update` calls whenever a change spans
  more than one file, so the result is one atomic commit rather than several partial ones if a
  later file fails.

## 5. Out of Scope (v1)

- Repository archive download (zip/tar/tar.gz of a whole ref) — a bulk/binary transfer concern,
  not a typical AI-agent operation.
- Git LFS object management.
- Repository size/statistics endpoints, submodule management.

## 6. Open Questions

1. Default max size for `get_raw`/`get` file content (1 MB proposed) — does this match the largest
   files the intended workflows need to read?
2. Should `batch_commit` be the *only* write path (removing single-file `create`/`update`/`delete`)
   to force atomic commits, or keep both for simplicity on one-file edits?

## Sources

- GitLab Repositories API: https://docs.gitlab.com/api/repositories/
- GitLab Repository Files API: https://docs.gitlab.com/api/repository_files/
- GitLab Commits API: https://docs.gitlab.com/api/commits/

# PRD-02: Repository Content & Commits

**Status:** Draft · **Toolset name:** `repository` · **Depends on:** PRD-00, PRD-01 (project/branch identifiers)

> **Revised 2026-09-22 (still Draft).** Added `gitlab_files` `create_directory`, since creating
> directories and files is an explicit owner requirement (PRD-00 §2). File content now moves as text
> by default and as base64 only when needed (§4). The size cap is `GITLAB_MCP_MAX_FILE_BYTES`.
> **2026-09-23:** At the owner's request, `gitlab_commits` gains `update_submodule` and
> `list_contributors`; repository statistics come from PRD-01's `gitlab_projects` (`get` with
> `statistics`, and `get_languages`). Git LFS stays out: GitLab's REST API has no endpoints for it.

## 1. Overview

Covers reading and writing the actual contents of a repository at a given ref: browsing the file
tree, reading/writing individual files, and inspecting commit history, diffs, and comparisons.
This is the toolset an AI coding agent uses most heavily once a project is identified.

## 2. Goals

- Browse the repository tree at any ref (branch, tag, or SHA).
- Read and write file content (single-file and atomic multi-file commits), and create directories.
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
| `get` | `GET /projects/:id/repository/files/:file_path` | Returns metadata + content at `ref` (text or base64, see §4); size-limited per §4 |
| `get_raw` | `GET /projects/:id/repository/files/:file_path/raw` | Content only, same encoding rule; size-limited per §4 |
| `get_blame` | `GET /projects/:id/repository/files/:file_path/blame` | Per-line commit attribution |
| `create` | `POST /projects/:id/repository/files/:file_path` | Requires `branch`, `commit_message`, `content`; optional `start_branch` creates `branch` from an existing branch in the same commit |
| `update` | `PUT /projects/:id/repository/files/:file_path` | Same as create + `last_commit_id` to detect conflicting concurrent edits |
| `delete` | `DELETE /projects/:id/repository/files/:file_path` | Requires `branch`, `commit_message`, `last_commit_id` |
| `create_directory` | `POST /projects/:id/repository/files/:directory%2F.gitkeep` | Requires `branch`, `commit_message`. Git stores files, not directories, so this commits an empty `<directory>/.gitkeep` to make the directory exist |

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
| `list_contributors` | `GET /projects/:id/repository/contributors` | Commit, addition, and deletion counts per person on `ref` (the default branch if omitted); `order_by`, `sort` |
| `update_submodule` | `PUT /projects/:id/repository/submodules/:submodule` | Points an existing submodule at `commit_sha`, as one commit on `branch`; `commit_message` optional |

## 4. Non-Functional Requirements

- **Large payload discipline (per PRD-00 §10):** `get_diff` and `compare` return a changed-files
  summary (paths + insertion/deletion counts) by default; full per-file diff text is fetched via a
  separate call/parameter (`include_diff_for: [<path>]`) so a large MR-sized commit doesn't blow
  out the response in one shot.
- File content moves as text by default. Reads return base64 only when the content isn't valid
  UTF-8, and writes take `encoding: base64` for binary content. An `encoding` field says which, so
  binary files round-trip safely without every text edit paying base64's size and legibility cost.
  (Earlier drafts proposed base64 in both directions.)
- `get` and `get_raw` enforce `GITLAB_MCP_MAX_FILE_BYTES` (default 1&nbsp;MiB). Above it they return
  a clear `payload_too_large` error pointing at `get_blame` with a line range, or a clone, rather
  than truncating silently.
- **Directories:** creating a file at a new path (`create`, or `batch_commit` for several files)
  creates its parent directories implicitly. `create_directory` exists for the case where the caller
  wants a directory before it has any real content.
- `update`/`delete` require `last_commit_id` (or equivalent) so the server surfaces GitLab's own
  conflict error when the file changed since the caller last read it, instead of silently
  overwriting a concurrent edit.
- Prefer `batch_commit` over sequential single-file `create`/`update` calls whenever a change spans
  more than one file, so the result is one atomic commit rather than several partial ones if a
  later file fails.

## 5. Out of Scope (v1)

- Repository archive download (zip/tar/tar.gz of a whole ref) — a bulk/binary transfer concern,
  not a typical AI-agent operation.
- Git LFS object management: GitLab's REST API has no endpoints for LFS objects, which move
  through Git LFS itself.
- Adding or removing submodules: GitLab's API only updates an existing submodule's commit
  (`update_submodule`). Repository statistics are in PRD-01 (`gitlab_projects`).

## 6. Open Questions

1. Default max size for `get_raw`/`get` file content — implemented as `GITLAB_MCP_MAX_FILE_BYTES`
   with a 1&nbsp;MiB default. Does this match the largest files the intended workflows need to read?
2. Should `batch_commit` be the *only* write path (removing single-file `create`/`update`/`delete`)
   to force atomic commits, or keep both for simplicity on one-file edits? The implementation keeps
   both for now.

## Sources

- GitLab Repositories API: https://docs.gitlab.com/api/repositories/
- GitLab Repository Files API: https://docs.gitlab.com/api/repository_files/
- GitLab Commits API: https://docs.gitlab.com/api/commits/

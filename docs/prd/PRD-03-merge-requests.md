# PRD-03: Merge Requests & Code Review

**Status:** Draft · **Toolset name:** `merge_requests` · **Depends on:** PRD-00, PRD-01, PRD-02 (diffs share large-payload handling)

> **Revised 2026-09-22 (still Draft, now implemented).** `get_diff` uses GitLab's paginated
> `/diffs` endpoint because `/changes` is deprecated. `unapprove` is a `POST`. `approve` takes no
> `approval_password`. `list_approval_rules` needs GitLab Premium. Diff-line comments are built,
> which answers open question 2.

## 1. Overview

Merge requests are the deepest tool surface in every surveyed GitLab MCP server — this PRD covers
the full MR lifecycle plus the review mechanics (discussions, notes, approvals) built on top of it.

## 2. Goals

- CRUD merge requests, including state transitions (close/reopen/merge).
- Read MR diffs and commit lists with the same large-payload discipline as PRD-02.
- Review mechanics: discussions/threads, notes, approvals.
- Merge and rebase actions.

## 3. Functional Requirements

### `gitlab_merge_requests`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/merge_requests` | Filters: `state`, `target_branch`, `source_branch`, `author_id`, `assignee_id`, `labels`, `search` |
| `get` | `GET /projects/:id/merge_requests/:iid` | Includes `has_conflicts`, `merge_status`, `pipeline` summary |
| `create` | `POST /projects/:id/merge_requests` | `source_branch`, `target_branch`, `title`, `description`, `labels`, `assignee_ids`, `draft` (via title/description convention) |
| `update` | `PUT /projects/:id/merge_requests/:iid` | Title, description, labels, assignees, target branch |
| `close` / `reopen` | `PUT …?state_event=close\|reopen` | |
| `get_diff` | `GET /projects/:id/merge_requests/:iid/diffs` | Changed-files summary by default; per-file diff on request — same convention as PRD-02 §4. Paginated. (`/changes`, named in earlier drafts, was deprecated in GitLab 15.7 and is scheduled for removal in API v5.) |
| `list_commits` | `GET /projects/:id/merge_requests/:iid/commits` | |
| `merge` | `PUT /projects/:id/merge_requests/:iid/merge` | `squash`, `should_remove_source_branch`, `sha`, `auto_merge` (merge once checks pass; `merge_when_pipeline_succeeds` is sent too for GitLab before 17.11); **destructive/high-impact**, requires `confirm: true`. A refusal comes back as `merge_blocked` or `merge_pending` with `detailed_merge_status` and a `next_step` (§4) |
| `rebase` | `PUT /projects/:id/merge_requests/:iid/rebase` | Runs in the background; poll `get` with `include_rebase_in_progress` |

### `gitlab_mr_reviews`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list_discussions` | `GET /projects/:id/merge_requests/:iid/discussions` | Threaded comments, including inline/diff-anchored ones |
| `create_discussion` | `POST /projects/:id/merge_requests/:iid/discussions` | Optional diff position: `file_path` with `new_line` and/or `old_line` (and `old_path` for a renamed file). The server fills in the base, head, and start SHAs from the merge request's `diff_refs` |
| `reply_discussion` | `POST /projects/:id/merge_requests/:iid/discussions/:discussion_id/notes` | |
| `resolve_discussion` | `PUT /projects/:id/merge_requests/:iid/discussions/:discussion_id` | `resolved: true/false` |
| `list_notes` / `create_note` / `update_note` / `delete_note` | `.../notes` | Plain (non-inline) comments; `update_note`/`delete_note` take an optional `discussion_id` to edit a thread reply through `.../discussions/:discussion_id/notes/:note_id` |
| `list_approvals` | `GET /projects/:id/merge_requests/:iid/approvals` | |
| `approve` / `unapprove` | `POST /projects/:id/merge_requests/:iid/approve` / `POST .../unapprove` | Optional `sha` on approve. `approval_password` is deliberately not accepted: a user's password must never pass through an LLM tool call |
| `list_approval_rules` | `GET /projects/:id/merge_requests/:iid/approval_rules` | Read-only — see Out of Scope. GitLab Premium/Ultimate only; on Free the error says so and points at `list_approvals` |

## 4. Non-Functional Requirements

- `get_diff` and diff-anchored discussions inherit PRD-02 §4's large-payload discipline exactly:
  a changed-files summary first, full diff text per file on request.
- `merge` is treated with the same care as `gitlab_projects.delete` (PRD-01): requires
  `confirm: true`, and a conflict or failed-pipeline block must come back as a clear, actionable
  error (not a generic failure) since an agent calling this needs to know whether to rebase, wait
  on CI, or ask a human.
- Creating a discussion/note should support attaching to a specific diff position (file + line)
  so review comments land where a human reviewer would expect them, not just as a general MR
  comment.

## 5. Out of Scope (v1)

- **Creating/editing approval rules** (project-level governance config) — only reading existing
  rules and approving/unapproving against them. Rule authoring is an admin/governance concern,
  not a typical AI coding-agent action.
- **Draft notes / pending review batching** (submit several comments as one pending review) — v1
  posts discussions/notes immediately; batched draft reviews are a nice-to-have for later.
- Squash-on-merge commit message customization beyond GitLab's default squash behavior.

## 6. Open Questions

1. Should `merge` be excluded from the default toolset (like `gitlab_projects.delete` in PRD-01),
   requiring an explicit opt-in scope, given it changes the target branch's history?
2. Is inline/diff-position commenting (vs. only general MR comments) a v1 requirement, or can it
   wait? **Answered by implementation:** built. The caller gives a file and line numbers, and the
   server resolves the diff SHAs.

## Sources

- GitLab Merge Requests API: https://docs.gitlab.com/api/merge_requests/
- GitLab Discussions API: https://docs.gitlab.com/api/discussions/
- GitLab Merge Request Approvals API: https://docs.gitlab.com/api/merge_request_approvals/

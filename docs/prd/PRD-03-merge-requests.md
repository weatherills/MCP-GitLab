# PRD-03: Merge Requests & Code Review

**Status:** Draft · **Toolset name:** `merge_requests` · **Depends on:** PRD-00, PRD-01, PRD-02 (diffs share large-payload handling)

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
| `get_diff` | `GET /projects/:id/merge_requests/:iid/changes` | Changed-files summary by default; per-file diff on request — same convention as PRD-02 §4 |
| `list_commits` | `GET /projects/:id/merge_requests/:iid/commits` | |
| `merge` | `PUT /projects/:id/merge_requests/:iid/merge` | Squash/merge-commit options; **destructive/high-impact**, requires `confirm: true`; surfaces `merge_status`/conflict errors clearly |
| `rebase` | `PUT /projects/:id/merge_requests/:iid/rebase` | |

### `gitlab_mr_reviews`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list_discussions` | `GET /projects/:id/merge_requests/:iid/discussions` | Threaded comments, including inline/diff-anchored ones |
| `create_discussion` | `POST /projects/:id/merge_requests/:iid/discussions` | Optional `position` for inline/diff comments |
| `reply_discussion` | `POST /projects/:id/merge_requests/:iid/discussions/:discussion_id/notes` | |
| `resolve_discussion` | `PUT /projects/:id/merge_requests/:iid/discussions/:discussion_id` | `resolved: true/false` |
| `list_notes` / `create_note` / `update_note` / `delete_note` | `.../notes` | Plain (non-inline) comments |
| `list_approvals` | `GET /projects/:id/merge_requests/:iid/approvals` | |
| `approve` / `unapprove` | `POST`/`DELETE /projects/:id/merge_requests/:iid/approve`/`/unapprove` | |
| `list_approval_rules` | `GET /projects/:id/merge_requests/:iid/approval_rules` | Read-only — see Out of Scope |

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
   wait — it's meaningfully more complex to get the position payload right than a plain note?

## Sources

- GitLab Merge Requests API: https://docs.gitlab.com/api/merge_requests/
- GitLab Discussions API: https://docs.gitlab.com/api/discussions/
- GitLab Merge Request Approvals API: https://docs.gitlab.com/api/merge_request_approvals/

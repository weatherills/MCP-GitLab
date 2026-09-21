# PRD-04: Issues & Planning

**Status:** Draft · **Toolset name:** `issues` · **Depends on:** PRD-00, PRD-01

## 1. Overview

Covers issue tracking and the two organizing structures around it: labels and milestones, both
scoped to a project for v1.

## 2. Goals

- CRUD issues, including state transitions, and linking related issues.
- Comment on issues (notes and threaded discussions).
- Manage project labels and milestones, and query issues by them.

## 3. Functional Requirements

### `gitlab_issues`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/issues` | Filters: `state`, `labels`, `milestone`, `assignee_id`, `author_id`, `search` |
| `get` | `GET /projects/:id/issues/:iid` | |
| `create` | `POST /projects/:id/issues` | `title`, `description`, `labels`, `assignee_ids`, `milestone_id` |
| `update` | `PUT /projects/:id/issues/:iid` | |
| `close` / `reopen` | `PUT …?state_event=close\|reopen` | |
| `delete` | `DELETE /projects/:id/issues/:iid` | **Destructive**, requires `confirm: true`; note GitLab restricts this to owners/admins |
| `move` | `POST /projects/:id/issues/:iid/move` | Move to another project |
| `list_links` / `link` / `unlink` | `GET`/`POST`/`DELETE /projects/:id/issues/:iid/links` | Related-issue links |

### `gitlab_issue_notes`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list_discussions` / `create_discussion` / `reply_discussion` / `resolve_discussion` | `.../issues/:iid/discussions` | |
| `list_notes` / `create_note` / `update_note` / `delete_note` | `.../issues/:iid/notes` | |

### `gitlab_labels`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` / `get` | `GET /projects/:id/labels` | |
| `create` / `update` / `delete` | `POST`/`PUT`/`DELETE /projects/:id/labels` | Name, color, description, priority |

### `gitlab_milestones`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` / `get` | `GET /projects/:id/milestones` | |
| `create` / `update` / `delete` | `POST`/`PUT`/`DELETE /projects/:id/milestones` | Title, due date, description, state |
| `list_issues` | `GET /projects/:id/milestones/:id/issues` | |

## 4. Non-Functional Requirements

- `list` on issues follows PRD-00 §10 pagination; default filter excludes closed issues unless
  `state` is explicitly requested, matching GitLab's own API default.
- `delete` on issues requires `confirm: true` per this repo's destructive-action convention
  (PRD-01 §4); most tokens won't have permission for it anyway (owner/admin only in GitLab), so the
  server should surface GitLab's `403` clearly rather than a generic failure.

## 5. Out of Scope (v1)

- **Group-level labels and milestones** — v1 is project-scoped only; a project inherits and can
  display group labels/milestones for read purposes via the same `list` filters GitLab already
  applies, but creating/editing at the group level is out of scope.
- **Time tracking** (`/time_stats`, estimate/spend) — lower-usage feature, deferred.
- **Issue boards** (Kanban board configuration) — a UI-layer construct on top of labels/milestones;
  no dedicated tool needed since it adds no capability beyond `gitlab_labels`/`gitlab_milestones`.

## 6. Open Questions

1. Should `gitlab_issues.delete` be left out of the default toolset entirely, matching the
   equivalent decision for `gitlab_projects.delete` (PRD-01) and `merge` (PRD-03)?

## Sources

- GitLab Issues API: https://docs.gitlab.com/api/issues/
- GitLab Issue Links API: https://docs.gitlab.com/api/issue_links/
- GitLab Labels API: https://docs.gitlab.com/api/labels/
- GitLab Milestones API: https://docs.gitlab.com/api/milestones/

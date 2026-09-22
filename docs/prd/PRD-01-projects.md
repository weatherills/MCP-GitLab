# PRD-01: Projects & Repository Structure

**Status:** Draft · **Toolset name:** `projects` · **Depends on:** PRD-00 (transport, auth, pagination, error conventions)

> **Revised 2026-09-22 (still Draft).** Corrected `gitlab_tags` `create`: GitLab's Tags API takes no
> release notes. Clarified that `create` accepts a namespace path as well as an ID. Creating
> repositories and branches is an explicit owner requirement (PRD-00 §2).

## 1. Overview

Covers the project (repository) lifecycle itself and its two ref types — branches and tags — the
entry point for almost every other PRD, since every other tool call is scoped to a `project_id`
(or `namespace/path`) obtained here.

## 2. Goals

- Discover and manage GitLab projects the caller's token can see: list/search, get details,
  create, update settings, fork, archive/unarchive, star/unstar, delete.
- Manage branches, including protected branches.
- Manage tags, including protected tags.

## 3. Functional Requirements

Per PRD-00 §6, expose as coarse action-discriminated tools, not one tool per endpoint:

### `gitlab_projects`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects` | Filters: `search`, `owned`, `membership`, `visibility`, `archived`; paginated per PRD-00 §10 |
| `get` | `GET /projects/:id` | Accepts numeric id or URL-encoded `namespace/path` |
| `create` | `POST /projects` | Name/path, namespace (numeric ID or full path, resolved to an ID via `GET /namespaces/:id`), visibility, initialize-with-readme |
| `update` | `PUT /projects/:id` | Settings: description, visibility, default branch, merge method, etc. |
| `delete` | `DELETE /projects/:id` | **Destructive** — requires an explicit `confirm: true` argument; GitLab itself soft-deletes with a retention period, surface that in the response |
| `fork` | `POST /projects/:id/fork` | Optional target namespace |
| `archive` / `unarchive` | `POST /projects/:id/archive` / `/unarchive` | |
| `star` / `unstar` | `POST /projects/:id/star` / `/unstar` | |
| `list_forks` | `GET /projects/:id/forks` | |

### `gitlab_branches`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/repository/branches` | Supports `search` regex filter |
| `get` | `GET /projects/:id/repository/branches/:branch` | |
| `create` | `POST /projects/:id/repository/branches` | `branch`, `ref` |
| `delete` | `DELETE /projects/:id/repository/branches/:branch` | |
| `delete_merged` | `DELETE /projects/:id/repository/merged_branches` | Bulk — treat as destructive, require `confirm: true` |
| `protect` | `POST /projects/:id/protected_branches` | Push/merge access levels |
| `unprotect` | `DELETE /projects/:id/protected_branches/:name` | |
| `list_protected` | `GET /projects/:id/protected_branches` | |

### `gitlab_tags`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/repository/tags` | |
| `get` | `GET /projects/:id/repository/tags/:tag_name` | |
| `create` | `POST /projects/:id/repository/tags` | `tag_name`, `ref`; optional `message` makes an annotated tag. The Tags API takes no release notes; create a release with PRD-06 |
| `delete` | `DELETE /projects/:id/repository/tags/:tag_name` | |
| `protect` | `POST /projects/:id/protected_tags` | |
| `unprotect` | `DELETE /projects/:id/protected_tags/:name` | |
| `list_protected` | `GET /projects/:id/protected_tags` | |

## 4. Non-Functional Requirements

- All destructive actions (`delete` on projects/branches, `delete_merged`) require an explicit
  `confirm: true` argument and return the GitLab confirmation payload (e.g. soft-delete retention
  date), per this repo's general caution around irreversible operations.
- `list` actions follow PRD-00 §10 pagination conventions exactly (`page`/`per_page`, capped at
  100, metadata returned).
- Project identifiers accept both numeric ID and URL-encoded path (`group%2Fsubgroup%2Fproject`)
  everywhere GitLab's API does, since callers will often only know the path.

## 5. Out of Scope (v1)

- Project transfer between namespaces/groups, project import/export, badges, custom project
  templates — long-tail admin operations, deferred.
- CI/CD-specific project settings and variables — covered in PRD-05.
- Group (namespace) creation/settings — only group *membership lookups* are covered, in PRD-08.

## 6. Open Questions

1. Should `delete` be omitted entirely from the default toolset (available only when
   `GITLAB_MCP_TOOLSETS` explicitly includes a `projects:destructive` sub-scope), given how
   irreversible it is even with GitLab's retention window?

## Sources

- GitLab Projects API: https://docs.gitlab.com/api/projects/
- GitLab Branches API: https://docs.gitlab.com/api/branches/
- GitLab Protected Branches API: https://docs.gitlab.com/api/protected_branches/
- GitLab Tags API: https://docs.gitlab.com/api/tags/
- GitLab Protected Tags API: https://docs.gitlab.com/api/protected_tags/

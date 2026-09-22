# PRD-06: Releases

**Status:** Draft · **Toolset name:** `releases` · **Depends on:** PRD-00, PRD-01 (tags)

> **Revised 2026-09-22 (still Draft, now implemented).** Built as specified. The tag parameter is
> named `tag`, as in PRD-01's `gitlab_tags`. `create` can also create the tag (`ref`,
> `tag_message`) and set `milestones`. Asset links are managed only through
> `gitlab_release_links`.

## 1. Overview

Covers GitLab Releases, which sit on top of tags (PRD-01) and add release notes, metadata, and
downloadable/linked assets. The smallest of the functional PRDs.

## 2. Goals

- CRUD releases.
- Manage release links (asset URLs attached to a release).

## 3. Functional Requirements

### `gitlab_releases`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/releases` | |
| `get` | `GET /projects/:id/releases/:tag_name` | |
| `create` | `POST /projects/:id/releases` | `tag_name` (existing or newly created — can reference PRD-01 tag creation), `name`, `description` (release notes), `released_at` |
| `update` | `PUT /projects/:id/releases/:tag_name` | |
| `delete` | `DELETE /projects/:id/releases/:tag_name` | Deletes the release only, not the underlying tag — confirm this distinction in tool description so callers don't expect the tag to disappear. The response also says `tag_kept: true` |

### `gitlab_release_links`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` / `get` | `GET /projects/:id/releases/:tag_name/assets/links` | |
| `create` / `update` / `delete` | `POST`/`PUT`/`DELETE /projects/:id/releases/:tag_name/assets/links` | External URL + name + link type (`other`/`runbook`/`image`/`package`) |

## 4. Non-Functional Requirements

- `delete` is not marked destructive the way project/branch/MR deletion is (PRD-01/03) since it
  only removes release metadata, not the tag or any commits — noted explicitly so implementers
  don't over-apply the `confirm: true` convention where GitLab's own semantics are already
  low-risk.

## 5. Out of Scope (v1)

- **Release evidence** collection — a GitLab Premium+ feature, out of scope per PRD-00's
  Enterprise/Ultimate-tier exclusion.
- **CI/CD Catalog** component releases — a distinct, newer GitLab concept layered on top of
  releases; not part of core repository command coverage.

## 6. Open Questions

None currently — this is the most straightforward functional PRD and mirrors PRD-01's tag handling
closely.

## Sources

- GitLab Releases API: https://docs.gitlab.com/api/releases/
- GitLab Release Links API: https://docs.gitlab.com/api/releases/links/

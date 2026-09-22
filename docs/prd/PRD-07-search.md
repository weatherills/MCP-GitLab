# PRD-07: Search

**Status:** Draft · **Toolset name:** `search` · **Depends on:** PRD-00; results commonly chain into PRD-01/02/03/04 tools for full detail

> **Revised 2026-09-22 (still Draft, now implemented).** Scope lists follow GitLab's current docs:
> `groups` and `work_items` are added. Instance-wide and group searches of `blobs`, `commits`,
> `wiki_blobs`, and `notes` all need Advanced Search, a GitLab Premium feature. Advanced Search
> availability is detected per call, which answers open question 1.

## 1. Overview

Covers GitLab's search endpoints at three scopes — instance-wide, group, and project — giving an
agent a way to find a project, a piece of code, a commit, or an issue/MR without already knowing
exactly where it lives.

## 2. Goals

- Search across projects, issues, merge requests, milestones, users, commits, code (blobs), notes,
  and wiki pages, at global/group/project scope as each is available.
- Return compact, chainable results (IDs and paths) that other toolsets can then fetch in full,
  rather than duplicating full-content retrieval here.

## 3. Functional Requirements

### `gitlab_search`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `global` | `GET /search` | Instance-wide; `scope` ∈ `projects`, `groups`, `issues`, `work_items`, `merge_requests`, `milestones`, `snippet_titles`, `users` reliably; `blobs`, `commits`, `wiki_blobs`, and `notes` require GitLab **Advanced Search** (Premium, with Elasticsearch or exact code search) and are not guaranteed available — see §4 |
| `group` | `GET /groups/:id/search` | Same scopes as global except `snippet_titles`, bounded to one group/subgroup tree; group ID or full path |
| `project` | `GET /projects/:id/search` | `scope` ∈ `issues`, `work_items`, `merge_requests`, `milestones`, `notes`, `wiki_blobs`, `commits`, `blobs`, `users`; works via GitLab's basic (non-Elasticsearch) search, so `blobs`/`commits` are reliable here even without Advanced Search. Optional `ref` for code, commits, and wikis |

## 4. Non-Functional Requirements

- **Advanced Search dependency is a real constraint, not an edge case.** Global and group-level
  `blobs`/`commits` search requires GitLab Advanced Search (Elasticsearch), which many self-hosted
  "non-enterprise" instances (this repo's stated target) won't have configured. The tool must
  detect and surface GitLab's own "not available" response clearly (pointing the caller at
  project-scoped search as a fallback) rather than returning an empty result indistinguishable from
  "no matches."
- Search results return compact records (path, snippet/matched line, IDs) — full file content,
  full issue/MR bodies, etc. are fetched afterward via the relevant domain toolset (PRD-02's
  `gitlab_files.get`, PRD-04's `gitlab_issues.get`, etc.), keeping this tool's responses small per
  PRD-00 §10.
- Pagination follows PRD-00 §10 conventions; GitLab search endpoints paginate the same way as any
  other list endpoint.

## 5. Out of Scope (v1)

- Advanced Search administration (enabling/configuring Elasticsearch) — an instance-admin concern,
  not something this MCP server manages.
- Search result ranking/relevance tuning beyond what GitLab's API already returns.

## 6. Open Questions

1. Should the server probe and cache whether Advanced Search is available on the configured
   instance at startup (to give accurate scope-availability errors immediately), or just surface
   GitLab's response as-is per call? **Answered by implementation:** per call, which keeps the
   server stateless. A refused instance or group search of an Advanced Search scope becomes an
   `advanced_search_unavailable` error that points to project search. An empty result for such a
   scope carries the same caveat, since GitLab may return nothing rather than an error.

## Sources

- GitLab Search API: https://docs.gitlab.com/api/search/
- GitLab Advanced Search: https://docs.gitlab.com/user/search/advanced_search/

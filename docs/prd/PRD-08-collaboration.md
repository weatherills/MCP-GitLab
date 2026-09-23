# PRD-08: Collaboration, Access & Wikis

**Status:** Draft · **Toolset name:** `collaboration` · **Depends on:** PRD-00, PRD-01

> **Revised 2026-09-22 (still Draft, now implemented).** Checked against GitLab's source where
> its docs are wrong or silent. Webhook `update` takes `url` as optional, although the docs mark it
> required. Changing a webhook's URL makes GitLab drop its secret token and custom headers, so
> `update` warns when that may have happened. A wiki `update` without `format` would convert the
> page to markdown, so the tool keeps the page's current format. The wiki page list is not
> paginated. Roles now include `planner` (15) and `security_manager` (25). `get_current` also
> reports the token's name, scopes, and expiry, and `gitlab_users` is offered to tokens with only
> the `read_user` scope. The webhook signing token (GitLab 19.0 and later) is write-only, like the
> secret token. Not built: webhook custom headers and URL variables, and clearing a membership's
> end date. Open questions 1 and 2 stay open: removing yourself needs `confirm` only, and only
> project wikis are covered.
>
> **Revised 2026-09-23.** Added: `gitlab_snippets` (§5 had it as a Phase 2 candidate); webhook
> custom headers and URL variables, set on `create` and `update` or one at a time, and shown by
> key only; and `clear_expiry` on member `update`. When an `update` changes the URL and sets
> custom headers, the headers go in a second request, because GitLab clears them whenever the URL
> changes. Open question 2 is answered: group wikis need GitLab Premium, since the Community
> Edition's wiki API serves projects only.

## 1. Overview

Covers the remaining "common" (per the competitive survey, not universal but frequent) categories
that don't fit elsewhere: project membership/access, read-only user lookup, project wikis,
project webhooks, and snippets.

## 2. Goals

- Manage project membership and access levels.
- Look up users (current token identity, and search/get others) read-only.
- CRUD project wiki pages.
- CRUD project webhooks, including their custom headers and URL variables.
- CRUD snippets, a project's or the caller's own.

## 3. Functional Requirements

### `gitlab_members`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/members` (own) / `/members/all` (incl. inherited from group) | |
| `get` | `GET /projects/:id/members/:user_id` (direct) / `/members/all/:user_id` (incl. inherited) | |
| `add` | `POST /projects/:id/members` | `user_id` or `username`, `access_level`, optional `expires_at` |
| `update` | `PUT /projects/:id/members/:user_id` | Change access level/expiry; `clear_expiry` removes the end date (GitLab takes an explicit `null`); direct members only |
| `remove` | `DELETE /projects/:id/members/:user_id` | Direct members only; optional `unassign_issuables` |
| `list_group_members` | `GET /groups/:id/members` (own) / `/members/all` (incl. inherited) | Read-only, for context when a project's access comes from its group |

### `gitlab_users`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `get_current` | `GET /user` | Identity behind the calling token — useful for the agent to know "who am I" |
| `get` | `GET /users/:id` | Or by `username`, resolved with `GET /users?username=` |
| `search` | `GET /users?search=` | |

### `gitlab_wikis`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/wikis` | Not paginated by GitLab; page content only with `with_content` |
| `get` | `GET /projects/:id/wikis/:slug` | Optional `version`, `render_html` |
| `create` / `update` / `delete` | `POST /projects/:id/wikis`, `PUT`/`DELETE /projects/:id/wikis/:slug` | `title`, `content` (markdown), `format` |

### `gitlab_webhooks`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` / `get` | `GET /projects/:id/hooks[/:hook_id]` | GitLab never returns the secret token on read |
| `create` / `update` / `delete` | `POST /projects/:id/hooks`, `PUT`/`DELETE /projects/:id/hooks/:hook_id` | URL, event flags, secret token (write-only), `custom_headers` (GitLab 17.1 and later) and `url_variables` as `[{key, value}]` lists (write-only; `update` adds or replaces the ones named). When `update` changes the URL and sets custom headers, the headers follow in a second request |
| `test` | `POST /projects/:id/hooks/:hook_id/test/:trigger` | Fires a test event |
| `set_custom_header` / `delete_custom_header` | `PUT`/`DELETE /projects/:id/hooks/:hook_id/custom_headers/:key` | One header; the value is write-only |
| `set_url_variable` / `delete_url_variable` | `PUT`/`DELETE /projects/:id/hooks/:hook_id/url_variables/:key` | One `{placeholder}` in the URL; the value is write-only |

### `gitlab_snippets`
Every action takes an optional `project`: with it, the project's snippets
(`/projects/:id/snippets`); without it, personal snippets (`/snippets`).

| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/snippets`, `GET /snippets` | Without `project`, `scope` picks `mine` (the default), `public` (`/snippets/public`), or `all` (`/snippets/all`, GitLab 16.3 and later) |
| `get` | `GET .../snippets/:id` | Details and the list of files |
| `get_content` | `GET .../snippets/:id/raw`, or `.../files/:ref/:file_path/raw` | The first file, or the one named; `ref` defaults to `HEAD`. Text, or base64 when not UTF-8, capped by `GITLAB_MCP_MAX_FILE_BYTES` |
| `create` | `POST .../snippets` | `title`, `description`, `visibility` (`private` unless given: GitLab's own default for personal snippets is `internal`), and `content` with `file_name` or `files` |
| `update` | `PUT .../snippets/:id` | Title, description, visibility, or content: `content` and `file_name` for a one-file snippet, `files` with an `action` each (`create`, `update`, `delete`, `move`) for several |
| `delete` | `DELETE .../snippets/:id` | |

## 4. Non-Functional Requirements

- **Access levels are surfaced by name, not just GitLab's numeric enum** (10 Guest / 15 Planner /
  20 Reporter / 25 Security Manager / 30 Developer / 40 Maintainer / 50 Owner) — tools accept and
  return both, since a numeric-only interface is easy for an LLM caller to get subtly wrong.
- Webhook secret tokens are write-only end to end: accepted on `create`/`update`, never echoed back
  on `list`/`get` (matching GitLab's own API behavior, but called out explicitly per this repo's
  general handling of secrets alongside CI/CD variables in PRD-05 §4). Custom header and URL
  variable values are write-only too: responses name them by key only.
- `gitlab_members.remove` and `update` (especially lowering/removing Owner access) should be
  treated with the same explicit-`confirm` caution as other access-affecting destructive actions,
  since removing the wrong member (including, potentially, the caller) can lock out collaborators.

## 5. Out of Scope (v1)

- **Group creation/settings and SSO/SAML configuration** — admin-tier concerns, consistent with
  PRD-01's exclusion of group management.
- **Instance-level user administration** (create/block/delete a GitLab account) — requires
  instance-admin rights, out of scope for a repository-command server.
- **Group wikis** — GitLab Premium; the Community Edition's wiki API serves projects only
  (open question 2).

## 6. Open Questions

1. Should `gitlab_members.remove` targeting the token's own user be blocked outright (to prevent an
   agent from accidentally revoking its own access mid-session), rather than just requiring
   `confirm: true`?
2. Is project-wiki coverage sufficient for v1, or should group wikis be included alongside it?
   **Answered by implementation:** group wikis need GitLab Premium, which this server doesn't
   target (PRD-00 §3), so project wikis are the whole of it.

## Sources

- GitLab Members API: https://docs.gitlab.com/api/members/
- GitLab Users API: https://docs.gitlab.com/api/users/
- GitLab Wikis API: https://docs.gitlab.com/api/wikis/
- GitLab Webhooks API: https://docs.gitlab.com/api/project_webhooks/
- GitLab Project Snippets API: https://docs.gitlab.com/api/project_snippets/
- GitLab Snippets API: https://docs.gitlab.com/api/snippets/

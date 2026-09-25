# ANSWERING-SKILL.md

Hints for an LLM calling this server's MCP tools. Not implementation guidance (that's
[`CLAUDE.md`](CLAUDE.md) and [`LIMITATIONS.md`](LIMITATIONS.md)) — this is "how do I get GitLab to
do the thing" from the caller's side of the wire.

## The shape of every call

There are 26 tools, one per GitLab domain, each named `gitlab_<domain>` (e.g. `gitlab_issues`,
`gitlab_merge_requests`). Every tool takes the same envelope:

```json
{"action": "<action_name>", "confirm": true, ...action-specific fields}
```

- **`action` picks the operation.** Call `tools/list` (or just read the tool's schema) to see
  which actions a given tool has and what fields each one takes — don't guess a REST-style verb;
  actions are named like `list`, `get`, `create`, `update`, `delete`, `close`, `merge`, and
  domain-specific ones like `cherry_pick` or `take_ownership`.
- **`confirm: true` is required** on a small set of destructive/high-impact actions: project
  `delete` and `transfer`, branch `delete` and `delete_merged`, merge request `merge`, issue
  `delete`, pipeline `delete`, runner `delete`, and member `update`/`remove`. Calling one of these
  without `confirm` fails with `confirmation_required` — that's not a permissions problem, just
  call again with `confirm: true` once you actually mean it. Don't add `confirm` to other calls;
  it's rejected as an unknown/unused argument on actions that don't need it (`extra="forbid"` on
  all params).
- **Unknown or misspelled fields are rejected outright**, not silently ignored — if a call fails
  validation, check field names against the schema rather than retrying the same body.
- **The tool list itself may already be narrowed** to what your GitLab Personal Access Token
  (PAT) scopes support, or to what the deployment/session allows — if a tool you expect isn't
  listed, it may be scope- or config-gated rather than missing.

## Reading results

- **List actions return `{"items": [...], "pagination": {...}}`**, never the whole collection.
  `pagination` has `per_page`, `next_page`, `prev_page`, `total`, `total_pages`, `has_more`.
  `total`/`total_pages` can be `null` on very large collections — don't treat a missing total as
  zero, and drive further pagination off `has_more`/`next_page`, not off `total`.
  - Every list action takes `page` (default 1) and `per_page` (default 20, max 100). Ask for a
    bigger `per_page` up front instead of paging one item at a time if you want most of a small
    collection.
  - `gitlab_issues.list` and `gitlab_merge_requests.list` and `gitlab_pipelines.list` default to
    **open/active items only** — pass `state` explicitly if you want closed/merged/all.
- **Errors are structured**, not prose you have to parse: `{"code": "...", "message": "...",
  "retryable": bool, "details": {...}}`. Codes worth branching on:
  - `confirmation_required` → re-send with `confirm: true`.
  - `invalid_arguments` / `unknown_action` → fix the call, don't retry as-is.
  - `gitlab_not_found` / `gitlab_forbidden` / `gitlab_unauthorized` → check the ID/path, the PAT's
    permissions, or that the resource is actually reachable with this token.
  - `gitlab_conflict` → usually a stale `last_commit_id` on a file write, or a merge conflict.
  - `gitlab_rate_limited` / `gitlab_server_error` / `gitlab_unavailable` → `retryable: true`; back
    off and retry. Everything else defaults to non-retryable — don't loop on a `400`.
  - `payload_too_large` → the response or a file exceeded a size cap; see below.
  - `advanced_search_unavailable` → see the search section.
- **Diffs (commit, compare, and merge request) come back as a changed-file summary** —
  `old_path`/`new_path`, add/delete flags, addition/deletion counts — **not full diff text**,
  to keep responses small. Pass `include_diff_for: ["path/one", "path/two"]` to get the actual
  diff text for just the files you need to read closely.
- **File reads return `{"encoding": "text"|"base64", "content": ...}`.** Content is text unless
  it isn't valid UTF-8, in which case it's base64 — check `encoding` before treating `content` as
  a string you can read directly.
- **Secrets never come back by default.** CI/CD variable values, pipeline schedule variable
  values, webhook secret tokens/signing tokens/custom header values/URL variable values are
  write-only. If you need a CI/CD variable's actual value, call `gitlab_ci_variables.get` (or
  `gitlab_pipeline_schedules.get`) with `reveal_value: true` / `reveal_values: true` — without it
  you'll only see that the variable exists, not what it holds.

## Size limits — don't try to work around these

- Any single GitLab response is capped around 10 MiB; a file read is capped at 1 MiB
  (`payload_too_large` beyond that). For a large file, read part of it with `gitlab_files.get_blame`
  plus `range_start`/`range_end`, or don't try to read the whole thing through this server.
- There's no "download the whole repo/archive/artifact zip" action, on purpose — job artifacts
  are read one file at a time (`gitlab_jobs.list_artifacts` then `get_artifact_file`), and there's
  no repository archive download or project import/export tool at all.
- Job logs return the **last 500 lines** by default, ANSI color stripped. Use `offset` to page
  further back, or `full: true` for the whole log (still capped by the response size limit).

## Writing files and commits

- `gitlab_files.create/update/delete` each make **one commit per call**. To change several files
  atomically, use `gitlab_commits.batch_commit` instead of separate `gitlab_files` calls — separate
  calls means separate commits, which is usually not what you want for one logical change.
- `update` and `delete` on a file require `last_commit_id` (from a prior `get`). If someone else
  touched the file since, GitLab rejects the write as a conflict (`gitlab_conflict`) rather than
  silently overwriting — re-`get` the file and retry with the fresh `last_commit_id` rather than
  forcing anything.
- There's no "create an empty directory" concept in Git; `create_directory` commits a
  `<dir>/.gitkeep` placeholder file. Creating any real file under a new path also creates the
  directory — you don't need `create_directory` first.
- New/renamed submodule pointers use `gitlab_commits.update_submodule`; there's no way to add or
  remove a submodule through this server (GitLab's API doesn't support it).

## Comments and reviews: merge requests and issues share a shape

`gitlab_mr_reviews` and `gitlab_issue_notes` both expose the same comment actions
(`list_discussions`, `create_discussion`, `reply_discussion`, `list_notes`, `create_note`,
`update_note`, `delete_note`) because GitLab's discussion/notes API is identical for both. The
difference: **only merge request threads can be resolved** (`resolve_discussion` exists on
`gitlab_mr_reviews`, not on `gitlab_issue_notes` — GitLab's API has no way to resolve an issue
thread).

- A **thread** (`discussion`) is a chain of replies anchored to something (often a diff line); a
  **note** is a standalone top-level comment. Use `create_discussion` to start a thread you expect
  replies on, `create_note` for a drive-by comment. `list_notes` returns top-level comments *and*
  system notes (label changes, etc.) — pass `activity_filter: "only_comments"` on issues if you
  want to skip the system noise.
- To reply inside a thread, you need its `discussion_id` from `list_discussions` first — you can't
  reply by note ID alone.
- Editing/deleting a note that's a thread reply needs `discussion_id` as well as `note_id`.

### Reviewing a merge request end-to-end

1. `gitlab_merge_requests.get_diff` for the changed-file summary; add `include_diff_for` for the
   files you actually want to inspect.
2. `gitlab_mr_reviews.create_draft_note` per comment you want to leave (these are private until
   published) — anchoring one to a diff line needs the file path and line number(s); the tool
   fetches the MR's current `diff_refs` itself, you don't need to supply SHAs.
3. `gitlab_mr_reviews.publish_review` to publish every draft at once, optionally with a summary
   comment. Note: this publishes drafts and posts the summary as an ordinary comment — it does
   **not** set your reviewer state (approved/requested-changes) on GitLab < 19.2, and even on
   19.2+ that's a side effect of `bulk_publish`, not something to rely on. Use
   `gitlab_mr_reviews.approve`/`unapprove` separately for approval.
- `list_approval_rules` is read-only and only meaningful on GitLab Premium/Ultimate — expect it to
  be empty or unavailable on Free/CE.

## Merging

`gitlab_merge_requests.merge` needs `confirm: true`. Before calling it, `get` the MR and look at
`detailed_merge_status`/`has_conflicts`/`blocking_discussions_resolved` — merge failures come back
as either `merge_blocked` (something needs fixing, e.g. unresolved threads or a real conflict) or
`merge_pending` (retryable — e.g. CI still running), with a `next_step` hint in the error telling
you what to do. If the pipeline just needs to finish, pass `auto_merge: true` instead of polling
and retrying `merge` yourself — GitLab will merge automatically once checks pass. A real conflict
on the source branch can't be auto-resolved by this server; that needs a human or a rebase/merge
commit on the branch itself.

## Labels, milestones: project *or* group, never both

`gitlab_labels` and `gitlab_milestones` actions take **exactly one of `project` or `group`** — pick
whichever owns the label/milestone you mean. Passing both, or neither, fails validation. A
project's `list` includes labels/milestones it inherits from its group automatically; you can't
change a group-inherited label/milestone by passing `project` — GitLab answers `404`, and the
error message tells you to pass `group` instead.

## Time tracking

`gitlab_issues` and `gitlab_merge_requests` each carry the same time-tracking actions
(`get_time_stats`, `set_time_estimate`, `reset_time_estimate`, `add_spent_time`,
`reset_spent_time`). Durations use GitLab's shorthand (`3h30m`, `1d` = 8 hours, `45m`; a bare
number means hours); `add_spent_time` accepts a leading `-` to subtract time already logged.

## Search: pick the narrowest scope that could work

`gitlab_search` has three actions — `global`, `group`, `project` — each taking a `scope` (e.g.
`issues`, `merge_requests`, `milestones`, `users`, and, project/group only, `blobs` (code),
`commits`, `wiki_blobs`, `notes`). Prefer `project` search when you already know the project:
- Cross-project scopes (`blobs`, `commits`, `wiki_blobs`, `notes`) at the `global`/`group` level
  need GitLab **Advanced Search**, which most Free/CE instances don't have. Expect
  `advanced_search_unavailable` there, and fall back to a `project`-scoped search instead of
  retrying the same global search.
- `project` search of `blobs`/`commits` works without Advanced Search (it uses GitLab's basic
  per-project search), so it's the reliable way to grep code or commit messages when a global
  search of the same scope fails.

## Version- and edition-gated behavior

Some actions behave differently depending on the target GitLab instance — don't treat these as
bugs if you see them:
- Free/CE instances 403/404 or return empty on: `list_approval_rules`, group wikis, epics,
  instance/group-level Advanced Search scopes.
- `list_artifacts` needs GitLab 18.8 for a real file tree; older versions return archive metadata
  only.
- Webhook signing tokens need GitLab 19.0; custom headers need 17.1.
- `merge` with `auto_merge` also sends the legacy `merge_when_pipeline_succeeds` field so it works
  on GitLab before 17.11 too — you don't need to choose one or the other yourself.
- Reviewer state (approved/changes-requested) on `publish_review`/`bulk_publish` is only set by
  GitLab 19.2+; earlier versions silently ignore it. `list_reviewers` always shows current state
  regardless.

## What this server deliberately can't do

Don't spend retries on these — they're not implemented by design, not bugs:
- No stdio transport, no server-side/shared GitLab token — every call authenticates with the
  caller's own PAT, per request.
- No whole-repository or whole-artifact-archive downloads, no project import/export.
- No GitLab Premium/Ultimate features (epics, security scanning, compliance frameworks, group
  wikis, custom group project templates).
- No group/instance administration (creating groups, SSO/SAML, blocking users, authoring approval
  rules), no runner registration or token reset (GitLab would hand back a secret token).
- No Git LFS object access, no adding/removing submodules (only repointing an existing one).
- Tags can't carry release notes (GitLab's Tags API has none) — create a `gitlab_releases` entry
  for that instead.
- Issue threads can't be resolved (only merge request threads can — see above).
- `approval_password` is never accepted on an MR approval; a password must never pass through a
  tool call.

If a task seems to need one of these, say so rather than trying creative workarounds through the
tools that are available.

## Quick tool-to-action index

| Tool | Actions |
|---|---|
| `gitlab_projects` | list, get, get_languages, create, update, delete\*, fork, archive, unarchive, star, unstar, list_forks, transfer\*, list_transfer_locations |
| `gitlab_branches` | list, get, create, delete\*, delete_merged\*, protect, unprotect, list_protected |
| `gitlab_tags` | list, get, create, delete, protect, unprotect, list_protected |
| `gitlab_badges` | list, get, create, update, delete, preview |
| `gitlab_repository_tree` | list |
| `gitlab_files` | get, get_raw, get_blame, create, update, delete, create_directory |
| `gitlab_commits` | list, get, get_diff, compare, batch_commit, cherry_pick, revert, list_statuses, list_comments, create_comment, list_contributors, update_submodule |
| `gitlab_merge_requests` | list, get, create, update, close, reopen, get_diff, list_commits, merge\*, rebase, + time-tracking actions |
| `gitlab_mr_reviews` | list_discussions, create_discussion, reply_discussion, resolve_discussion, list_notes, create_note, update_note, delete_note, list_approvals, approve, unapprove, list_approval_rules, list_reviewers, list_draft_notes, create_draft_note, update_draft_note, delete_draft_note, publish_draft_note, publish_review |
| `gitlab_issues` | list, get, create, update, close, reopen, delete\*, move, list_links, link, unlink, + time-tracking actions |
| `gitlab_issue_notes` | list_discussions, create_discussion, reply_discussion, list_notes, create_note, update_note, delete_note |
| `gitlab_labels` | list, get, create, update, delete |
| `gitlab_milestones` | list, get, create, update, delete, list_issues, list_merge_requests |
| `gitlab_pipelines` | list, get, create, retry, cancel, delete\* |
| `gitlab_jobs` | list, get, retry, cancel, play, list_artifacts, get_artifact_file |
| `gitlab_ci_variables` | list, get, create, update, delete |
| `gitlab_pipeline_schedules` | list, get, list_pipelines, create, update, take_ownership, play, delete, create_variable, update_variable, delete_variable |
| `gitlab_runners` | list, get, update, list_jobs, assign, unassign, delete\* |
| `gitlab_releases` | list, get, create, update, delete |
| `gitlab_release_links` | list, get, create, update, delete |
| `gitlab_search` | global, group, project |
| `gitlab_members` | list, get, add, update\*, remove\*, list_group_members |
| `gitlab_users` | get_current, get, search |
| `gitlab_wikis` | list, get, create, update, delete |
| `gitlab_webhooks` | list, get, create, update, delete, test, set_custom_header, delete_custom_header, set_url_variable, delete_url_variable |
| `gitlab_snippets` | list, get, get_content, create, update, delete |

\* needs `confirm: true`.

For exact parameter names and types, use the live tool schema (`tools/list`) — this table is for
picking the right tool and action, not for guessing field names.

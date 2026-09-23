# PRD-05: CI/CD Pipelines & Jobs

**Status:** Draft · **Toolset name:** `pipelines` · **Depends on:** PRD-00, PRD-01

> **Revised 2026-09-22 (still Draft, now implemented).** `list_artifacts` uses GitLab's
> `/artifacts/tree` (18.8+) and falls back to the job's archive metadata, because the plain
> `/artifacts` endpoint downloads the whole archive. Variable values are hidden in every response,
> not only in `list`. `update` can keep a value without it passing through the model.
>
> **Revised 2026-09-23.** Added, from §5's former out-of-scope list: `gitlab_pipeline_schedules`
> and `gitlab_runners`. Schedule variable values are hidden as CI/CD variable values are.
> Registering a runner and resetting its tokens stay out of scope, because GitLab answers each
> with a secret token.

## 1. Overview

Covers triggering and inspecting CI/CD pipelines and their jobs, plus project-level CI/CD
variables, pipeline schedules, and runners. This is the toolset an agent uses to check whether its
own changes pass CI, read failure logs, and retry/cancel runs.

## 2. Goals

- List, inspect, trigger, retry, and cancel pipelines.
- List jobs within a pipeline, read job logs and artifacts, retry/cancel/play individual jobs.
- Manage project-level CI/CD variables.
- Manage pipeline schedules and their variables.
- See and manage the runners that run jobs.

## 3. Functional Requirements

### `gitlab_pipelines`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/pipelines` | Filters: `status`, `ref`, `sha`, `source` |
| `get` | `GET /projects/:id/pipelines/:id` | |
| `create` | `POST /projects/:id/pipeline` | `ref` + `variables[]`; uses the caller's PAT, not a separate trigger token (see Out of Scope) |
| `retry` | `POST /projects/:id/pipelines/:id/retry` | |
| `cancel` | `POST /projects/:id/pipelines/:id/cancel` | |
| `delete` | `DELETE /projects/:id/pipelines/:id` | **Destructive**, requires `confirm: true` |

### `gitlab_jobs`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/pipelines/:pipeline_id/jobs` | |
| `get` | `GET /projects/:id/jobs/:job_id` | |
| `get_log` | `GET /projects/:id/jobs/:job_id/trace` | Plain-text log: the last `tail_lines` (500) by default, `offset` pages from a line, `full` returns everything; color codes, section markers, and progress redraws are removed |
| `retry` / `cancel` / `play` | `POST /projects/:id/jobs/:job_id/retry`\|`/cancel`\|`/play` | `play` starts a manual job |
| `list_artifacts` | `GET /projects/:id/jobs/:job_id/artifacts/tree` | Files and directories inside the archive, with `path` and `recursive` (GitLab 18.8+). On older GitLab: the job's archive metadata from `GET /jobs/:job_id`. (`GET .../artifacts`, named in earlier drafts, downloads the whole archive) |
| `get_artifact_file` | `GET /projects/:id/jobs/:job_id/artifacts/*artifact_path` | One file from the archive, not the whole archive; capped by `GITLAB_MCP_MAX_FILE_BYTES`; `..` segments refused |

### `gitlab_ci_variables`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/variables` | Values redacted by default — see §4 |
| `get` | `GET /projects/:id/variables/:key` | Requires an explicit `reveal_value: true` to return the actual value |
| `create` / `update` / `delete` | `POST`/`PUT`/`DELETE /projects/:id/variables` | `key`, `value`, `protected`, `masked`, `environment_scope`, plus `variable_type` and `description`. Responses hide the value. `update` without `value` keeps the current one: the server reads it and sends it back, and it never reaches the caller. `environment_scope` picks the variable (`filter[environment_scope]`) when several share a key |

### `gitlab_pipeline_schedules`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/pipeline_schedules` | `scope`: `active` or `inactive` |
| `get` | `GET /projects/:id/pipeline_schedules/:schedule_id` | With the last pipeline and the variables; their values only with `reveal_values: true` (§4) |
| `list_pipelines` | `GET .../pipeline_schedules/:schedule_id/pipelines` | Oldest first, GitLab's order |
| `create` / `update` | `POST /projects/:id/pipeline_schedules` / `PUT .../:schedule_id` | `description`, `ref`, `cron`, `cron_timezone`, `active`. `create` makes the caller the schedule's owner; its pipelines run with the owner's permissions |
| `take_ownership` | `POST .../:schedule_id/take_ownership` | |
| `play` | `POST .../:schedule_id/play` | Runs the pipeline now |
| `delete` | `DELETE .../:schedule_id` | |
| `create_variable` / `update_variable` / `delete_variable` | `POST .../:schedule_id/variables`, `PUT`/`DELETE .../variables/:key` | `key`, `value`, `variable_type`. Responses never include the value |

### `gitlab_runners`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/runners`, `GET /groups/:id/runners`, or `GET /runners` | A project's list includes instance runners; with neither `project` nor `group`, the runners the caller can manage. Filters: `type`, `status`, `paused`, `tag_list` |
| `get` | `GET /runners/:id` | `include_projects: false` leaves out the projects list |
| `update` | `PUT /runners/:id` | `description`, `paused`, `tag_list`, `run_untagged`, `locked`, `access_level`, `maximum_timeout`, `maintenance_note` |
| `list_jobs` | `GET /runners/:id/jobs` | `job_status` (GitLab's `status`) and `sort` |
| `assign` / `unassign` | `POST /projects/:id/runners` / `DELETE /projects/:id/runners/:runner_id` | Lets a project use a project runner, or stops it |
| `delete` | `DELETE /runners/:id` | **Destructive**, requires `confirm: true`: bringing the runner back means registering it again on its machine |

## 4. Non-Functional Requirements

- **Job logs can be very large.** `get_log` supports an `offset`/`tail_lines` parameter (default:
  last ~500 lines) rather than returning a potentially multi-MB trace in full every time, matching
  PRD-00 §10's large-payload discipline; a `full: true` override is available for when the whole
  log is genuinely needed. The server still downloads the whole log, up to
  `GITLAB_MAX_RESPONSE_BYTES`, because GitLab's trace endpoint has no range parameter.
- **Downloads may redirect.** GitLab can hand logs and artifact files off to object storage or a
  CDN. Those redirects are followed without the PAT on any other origin (PRD-00 §7.2).
- **Artifacts are fetched per-file, never as a bulk archive download** — `list_artifacts` returns
  the file listing/metadata, `get_artifact_file` fetches one file. Downloading the whole artifacts
  zip is out of scope (bulk binary transfer, same reasoning as repository archive downloads in
  PRD-02).
- **CI/CD variable values are treated as secrets by default:** `list` never returns values (only
  keys + flags), `get` requires an explicit opt-in to reveal a value, and no variable value is ever
  written to logs — even though GitLab's own API will return them to a sufficiently-scoped token,
  this server adds a deliberate extra step before surfacing one to an LLM context window.
  Pipeline schedule variables get the same treatment: every response hides their values except
  `get` with `reveal_values: true`.
- **No action hands back a runner token.** Registering a runner (`POST /user/runners`) and
  resetting a runner's authentication token or a registration token each answer with a token, so
  none of them is offered.
- `create`/`update` on pipelines/jobs should surface GitLab's pipeline/job status enums as-is
  (`pending`, `running`, `success`, `failed`, `canceled`, `skipped`, `manual`) rather than
  re-mapping them, so callers can rely on GitLab's own documented values.

## 5. Out of Scope (v1)

- **Pipeline trigger tokens** (`/projects/:id/triggers` management, and pipeline creation via a
  trigger token rather than a user PAT) — a separate, non-PAT auth mechanism outside this repo's
  PAT-centric charter (PRD-00 §7).
- **Registering runners and resetting their tokens** — GitLab answers with a secret token (§4).
  Instance-wide runner listing (`GET /runners/all`) needs an administrator.
- **Pipeline schedule inputs** (`inputs`, for pipelines that declare `spec:inputs`) — not built
  yet; schedule variables cover the common case.
- Bulk artifact archive download (see §4).

## 6. Open Questions

1. Default `tail_lines` for `get_log` (500 proposed) — enough context for typical CI failure
   triage without regularly needing `full: true`?
2. Should `gitlab_ci_variables.get` with `reveal_value: true` be excluded from the default toolset
   the same way other sensitive/destructive actions are, requiring explicit opt-in scope?

## Sources

- GitLab Pipelines API: https://docs.gitlab.com/api/pipelines/
- GitLab Jobs API: https://docs.gitlab.com/api/jobs/
- GitLab Project-level CI/CD Variables API: https://docs.gitlab.com/api/project_level_variables/
- GitLab Pipeline Schedules API: https://docs.gitlab.com/api/pipeline_schedules/
- GitLab Runners API: https://docs.gitlab.com/api/runners/

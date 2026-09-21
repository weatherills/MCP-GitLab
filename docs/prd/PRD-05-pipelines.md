# PRD-05: CI/CD Pipelines & Jobs

**Status:** Draft · **Toolset name:** `pipelines` · **Depends on:** PRD-00, PRD-01

## 1. Overview

Covers triggering and inspecting CI/CD pipelines and their jobs, plus project-level CI/CD
variables. This is the toolset an agent uses to check whether its own changes pass CI, read
failure logs, and retry/cancel runs.

## 2. Goals

- List, inspect, trigger, retry, and cancel pipelines.
- List jobs within a pipeline, read job logs and artifacts, retry/cancel/play individual jobs.
- Manage project-level CI/CD variables.

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
| `get_log` | `GET /projects/:id/jobs/:job_id/trace` | Plain-text log; size-limited/tail-able per §4 |
| `retry` / `cancel` / `play` | `POST /projects/:id/jobs/:job_id/retry`\|`/cancel`\|`/play` | `play` starts a manual job |
| `list_artifacts` | `GET /projects/:id/jobs/:job_id/artifacts` metadata | |
| `get_artifact_file` | `GET /projects/:id/jobs/:job_id/artifacts/:artifact_path` | One file from the archive, not the whole archive |

### `gitlab_ci_variables`
| Action | GitLab endpoint | Notes |
|---|---|---|
| `list` | `GET /projects/:id/variables` | Values redacted by default — see §4 |
| `get` | `GET /projects/:id/variables/:key` | Requires an explicit `reveal_value: true` to return the actual value |
| `create` / `update` / `delete` | `POST`/`PUT`/`DELETE /projects/:id/variables` | `key`, `value`, `protected`, `masked`, `environment_scope` |

## 4. Non-Functional Requirements

- **Job logs can be very large.** `get_log` supports an `offset`/`tail_lines` parameter (default:
  last ~500 lines) rather than returning a potentially multi-MB trace in full every time, matching
  PRD-00 §10's large-payload discipline; a `full: true` override is available for when the whole
  log is genuinely needed.
- **Artifacts are fetched per-file, never as a bulk archive download** — `list_artifacts` returns
  the file listing/metadata, `get_artifact_file` fetches one file. Downloading the whole artifacts
  zip is out of scope (bulk binary transfer, same reasoning as repository archive downloads in
  PRD-02).
- **CI/CD variable values are treated as secrets by default:** `list` never returns values (only
  keys + flags), `get` requires an explicit opt-in to reveal a value, and no variable value is ever
  written to logs — even though GitLab's own API will return them to a sufficiently-scoped token,
  this server adds a deliberate extra step before surfacing one to an LLM context window.
- `create`/`update` on pipelines/jobs should surface GitLab's pipeline/job status enums as-is
  (`pending`, `running`, `success`, `failed`, `canceled`, `skipped`, `manual`) rather than
  re-mapping them, so callers can rely on GitLab's own documented values.

## 5. Out of Scope (v1)

- **Pipeline trigger tokens** (`/projects/:id/triggers` management, and pipeline creation via a
  trigger token rather than a user PAT) — a separate, non-PAT auth mechanism outside this repo's
  PAT-centric charter (PRD-00 §7).
- **CI/CD schedules** (`/projects/:id/pipeline_schedules`) — deferred; not core to an interactive
  coding-agent workflow.
- **Runners management** (registering/editing project runners).
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

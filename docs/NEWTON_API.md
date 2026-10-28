# Newton local app and API (v1)

Start from the authoritative project folder:

```powershell
cd "C:\Users\rober\Desktop\Ai agent\Horizon_Sprint_01"
python -m newton.api --mode mock
```

Open the private local browser link printed by the server. The token is in the URL
fragment, is removed from the address bar after loading, and is held in that tab's
session storage. It is not an OpenAI API key. Keep that local token private. No worker
starts when the server starts, a session is created, or an approval is changed.
`--port 0` chooses a free port; the default is 8765. Ctrl+C stops the server and waits
for an explicitly requested running task to finish. There is no cancellation promise
for an already-started remote model call.

The app includes chat, separate approval switches, invocation counts, coarse task
progress, changed-file previews, current test results, plans and execution traces.
Click **Try a mock task** to exercise the complete interface. Its files and three
passing checks are explicitly simulated; nothing is written to source files. The mock
is not an LLM and cannot answer arbitrary questions. Normal local commands such as
`help`, `show changes`, and `run tests` use the real controller and can run real local
checks even in mock mode; the UI labels those results separately from simulated checks.

## Connecting the real Newton later

```powershell
python -m newton.api --mode codex
```

Create a session and explicitly confirm its displayed budget, then approve **Live work**.
Personal-file reading requires its separate confirmation. Both approvals are in memory
and expire after server restart; they are scoped to the selected app session. Personal
file approval never grants external writes. In browser chat, `enable files` directs you
to the approval switch without invoking a model. `quit` revokes the loaded session
permissions; stop the HTTP server with Ctrl+C in its terminal. Budget increases have their own confirmation.
The existing subscription-only worker, one-invocation-per-message rule, persisted count,
no-retry policy, file validation, isolated worktrees and independent tests are reused.
There is no API billing fallback or automatic model switch. Explicit provider/model selection is available through session preferences. One invocation can contain multiple
internal model calls; this does not enforce an exact subscription/token cap.

This initial app is bound to one project chosen at server launch. `--project PATH`
selects a different project explicitly. Ordinary coding remains the existing supported
Python `src`/`tests` workflow. A first implementation still requires a clean committed
project baseline. App session metadata lives under `runs/newton_api_mock` or
`runs/newton_api_codex`. It never replaces `runs/newton/latest.json` from the terminal.
Browser mock sessions always start separately; live app sessions may resume their own
saved app metadata. They do not automatically inherit terminal worktrees or conversation.

The API accepts only one task at a time across all loaded sessions, including local tests.
A second request returns HTTP 409; it is not queued or retried automatically. Approvals,
budget changes and file previews also wait until the current task finishes. Progress
polling is GET-only and never invokes a worker. Refreshing the page reconnects to an
existing loaded session/task rather than resubmitting the message. There is no background
planning, agent collaboration, or automatic execution of another step. Progress states
are coarse; token streaming and interrupt/cancel endpoints are not part of v1.

## API contract for the frontend

Base URL: the printed `http://127.0.0.1:PORT/api`.
All API requests require `Authorization: Bearer LOCAL_TOKEN`. JSON POST requests require
`Content-Type: application/json`. Unknown request fields are rejected; clients cannot
change provider/model, change mode, pass arbitrary shell commands or bypass approvals through
message options. The server mode is fixed by its launch command.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/info` | API version, mode, project, loaded session IDs, limits and active task |
| POST | `/sessions` | Create a session; returns 201 |
| GET | `/sessions/{session_id}` | Budget, permissions, current plan, workspace and last/active task |
| POST | `/sessions/{session_id}/approvals` | Explicit live-work, personal-file, or budget approval |
| POST | `/sessions/{session_id}/messages` | Start one requested task; returns 202 with a run ID |
| GET | `/runs/{run_id}` | Read task state and result |
| GET | `/runs/{run_id}/trace` | Metadata trace, or clearly labeled simulated demo events |
| GET | `/sessions/{session_id}/files?path=src/example.py` | Read bounded workspace text, or a labeled virtual demo file |

Create a mock session with `{}`. For a new live session use
`{"confirm_new_budget": true}` after the user confirms its displayed budget. Resume
saved live **app** progress with `{"resume": "latest"}` or `{"resume": "SESSION_ID"}`.
If no saved live session exists, creation still requires `confirm_new_budget: true`.
A resume never silently raises the saved budget. Use a separately confirmed budget
command if the saved limit needs changing.

Approval requests:

```json
{"kind": "live_work", "allow": true}
```

```json
{"kind": "personal_files", "allow": false}
```

```json
{"kind": "budget", "allow": true, "command": "add budget 10"}
```

The frontend must display the affected budget or user-folder scope before confirming.
The authenticated local client represents the owner; a third-party client should build
its own equivalent confirmation interface. Approval changes do not start a worker.

Send a message:

```json
{"message": "demo", "read_only": false}
```

`demo` is a reserved mock-only UI demonstration. A real task in live mode is an ordinary
natural-language request. `read_only: true` prevents edits even for an explicit request.
Do not automatically repeat a POST after a network failure: the task may have started.
Check the session's `active_job` / `last_job` and poll the existing run instead.

Example task response (fields may grow compatibly within API v1):

```json
{
  "run_id": "32_HEX_CHARACTERS",
  "session_id": "32_HEX_CHARACTERS",
  "mode": "mock",
  "status": "completed",
  "result": {
    "reply": "Mock demonstration: no model was called or source files written.",
    "status": "mock_completed",
    "simulated": true,
    "changed_files": ["src/newton_demo.py"],
    "file_paths": [],
    "verification": {"tests_run": 3, "tests_passed": true, "simulated": true},
    "budget": {"live_used": 0, "live_limit": 50, "live_remaining": 50}
  },
  "error": null
}
```

Run states: `queued`, `running`, `completed`, `failed`. `completed` means the request
finished, not that its task succeeded: inspect `result.status` and current verification.
For example, `approval_required`, `budget_exhausted`, `checks_failed`, and
`clarification_required` remain distinct controller outcomes. Missing verification means
no current test result. The controller still leaves semantic correctness unverified.
The API run ID identifies an orchestration job; canonical Horizon trace events can have
a different underlying controller run ID.

Error bodies have `{"error": "CODE"}`. Common codes/statuses:

- 400: invalid input or a protected/unsupported file operation.
- 401: missing/invalid local token.
- 403: unexpected Host or a cross-origin browser request.
- 404: run/session/route not found.
- 409: task already running, session limit, or new live budget confirmation required.
- 413: request body above 32000 bytes.
- 415: JSON content type required.

Up to eight sessions and the most recent 100 task records are retained in server memory.
Chat messages and HTTP task records are not saved as a raw durable transcript. Existing
controller summaries, reports and metadata traces retain their documented behavior.
No tokens or message bodies are written to HTTP access logs.

## Working in parallel with your friend

Agree on this contract first. One person can edit `newton/web/` and build the interface
against the mock server. The other can work on the Python controller/API and reliability
traces. Each developer should use their own checkout/branch and local mock process;
frontend work does not need a model call or personal-file permission. Use a task with
`message: "demo"` for predictable files/tests/traces and `help` for a real local command.
The app and API are served together; separate frontend origins need a same-origin dev
proxy rather than a permissive CORS change.

This is a local prototype, not a public multi-user deployment. It binds only to
127.0.0.1, uses a fresh per-process token, validates Host/Origin, serves only bundled
assets, renders model text as text, and keeps file previews inside the selected
workspace. Do not expose this process or its private token to the internet. Authentication,
per-user authorization and deployment isolation would be separate implementation work.

Validation uses synthetic temporary projects, mocked Codex workers, real local unittest
runs and HTTP requests. The mock browser flow was exercised manually, including chat,
file preview and the execution trace. No live Codex worker was launched for implementation.


## Teacher styles and provider selection

Restart the local server to load this update. `--mode mock` remains entirely offline;
`--mode codex` is the compatibility name for the live-enabled server, initially using Codex.
In the app, open **Teaching & connection** to select Teacher, Supervisor, or Concise.
Provider choices are ChatGPT/Codex, Claude Code, and Gemini CLI; each needs its own setup.
Claude and Gemini adapters are experimental and have only been tested with simulated workers.
Gemini requires a specific model identifier (no auto routing). See NEWTON.md for setup/limits.

GET `/api/info` now includes `providers` (installed flag, login instructions, authentication
not checked) and `response_styles`. Session responses include `provider`, `model`, and
`response_style`; budget objects add `prevented_invocations` without changing live usage.

POST `/api/sessions/{id}/preferences` accepts only:

```json
{"provider":"claude","model":"","response_style":"supervisor","confirm_provider_change":true}
```

Provider/model changes require explicit confirmation, retain usage/history, clear personal
excerpts and revoke live-work/personal-file approval. The app then asks for normal live-work
approval before the next live request. Style-only changes are local and need no new approval.
Updates are rejected while a task is running. Mock servers cannot become live via this route.
Provider choice is never taken from model output or automatically changed after an error.

Prevented requests expose a zero-invocation report/trace. The app displays their cumulative
count separately. `tool_results_ready` includes actual collected evidence, visible in **Local
evidence**; it is not a claim the model has interpreted newly executed checks. A user follow-up
can request interpretation within the one-invocation/message rule. No automatic extra reviewer,
retry or background model call is added. Account-side overage must be disabled by the user;
the app cannot enforce an exact token/subscription-percentage/monetary cap.


## Educational study pilot

See [Newton Study guide](NEWTON_STUDY.md) for the Ontario mechanics pilot, local profiles, interactive diagrams, flashcards, practice, sources, limits and offline/live test instructions.


## Newton Hub

Double-click Newton.cmd (a Desktop entry is available on this machine) for the local home screen and Activity dashboard. See the [hub guide](NEWTON_HUB.md) for launch controls, metadata-only Langfuse export and remaining Docker setup.

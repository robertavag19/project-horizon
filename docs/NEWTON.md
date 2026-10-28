# Newton conversational agent: Economy mode

Newton is a personal technical teacher and project supervisor. It explains concepts,
challenges assumptions, and performs clear authorized development tasks. Your current
goal takes priority; Horizon is background project history. This is role/prompt and
workflow engineering around existing models, not training a new model.

## Start and resume

```powershell
cd "C:\Users\rober\Desktop\Ai agent\Horizon_Sprint_01"
python -m newton
```

The latest session resumes automatically. `python -m newton --resume latest` does the
same explicitly. `--resume SESSION_ID` selects an older session. To start separately,
use `--new-session`, or say `start a new session` and confirm its fresh session budget.
Previous worktrees are retained; nothing is merged, pushed or deleted automatically.
Exit an older running Newton process before loading this upgrade.

Talk naturally. For example:

```text
Launch budget: 0 used, 50 total, 50 remaining; at most 1 invocation per message; no retries.
Authorize live work within this budget for this launch [y/N]? y
Newton> Help me plan a small benchmark for Horizon Study.
Newton> Implement the first small step and add focused tests.
Newton> Explain what you changed.
Newton> Show changes.
Newton> Run tests.
Newton> Check acceptance criteria.
Newton> Stop here; we will continue tomorrow.
```

The first two messages use at most two worker invocations in total. The remaining
commands above are deterministic local operations with no model inference. `/plan`,
`/review`, `/status`, `/diff`, `/tests`, `/help`, `/connections` and `/quit` remain optional
shortcuts. Ordinary discussion/investigation/planning/review are classified in the
same structured model response as the answer, not by a separate routing model.

## Personal files and books: optional approval for each launch

Newton asks separately from the live-worker budget:

```text
Do you want to allow Newton to access your personal files for this launch [y/N]?
```

Choose `y` to permit reading/searching under your Windows user folder
(`C:\Users\rober`). Enter or `n` leaves access disabled and project tools still work.
No scan starts just because access was granted. The permission is held only in memory,
never in session metadata; restarting asks again. `enable files` prompts again locally;
`disable files` immediately revokes access and clears selected excerpts. `file access`
shows its status. Mock mode does not ask at startup, but `enable files` is available.
One-off `--task` calls do not inherit or implicitly grant personal-file access.

These commands are local and do not invoke a model:

```text
Newton> find files physics
Newton> list folder "C:\Users\rober\Documents"
Newton> read file "C:\Users\rober\Documents\Physics.pdf" pages 10-12
Newton> file access
Newton> disable files
```

After reading, ask a normal question such as `Explain the example on page 10`.
The selected excerpt is supplied to that one worker invocation within the existing
context budget. You can also ask `Summarize "C:\Users\rober\Documents\Physics.pdf"
pages 10-12` directly. Only selected excerpts are sent to Codex; there is no automatic
whole-home index, background crawler or model-assisted file search. A model can request
`find_files`/`read_file` using the same single structured response, but interpreting a
new tool result requires the next user message, not an automatic second worker call.

Filename searches inspect at most 1000 directory entries, to depth 8, with a cooperative
three-second scan deadline. `scan_truncated` means results may be incomplete; narrow the
folder using `list folder` or give an exact path. Junctions, symlinks, reparse points,
network paths, hidden folders, AppData, credential-like filenames, binary files and
paths outside the user folder are excluded. These exclusions reduce accidental exposure;
they do not recognize every possible secret embedded in an ordinary document.

Text files are capped at 2 MB and selected excerpts at 12000 characters. PDF files are
capped at 50 MB, with at most five pages per read (three by default). PDF parsing itself
is local; extraction is text-only and may lose formulas or diagram information. Scanned
pages report `ocr_required` rather than inventing text; no cloud OCR or paid fallback is
used. Encrypted PDFs are unsupported. Page numbers are physical PDF page numbers.
`pypdf` is optional and has been installed in the current Newton Python environment;
on another installation, use `python -m pip install pypdf` or install the project's
`documents` extra. Parsing and OS filesystem operations are not hard real-time limits.

The selected personal-file excerpt is transient, is replaced on the next read, and is
cleared on revocation, restart, project switching, or `forget memory`. The usual bounded
model answer and summary may still contain facts quoted from an earlier approved read;
revocation prevents further reading rather than erasing already-produced answers.
Personal source bodies are not added to metadata-only execution traces.
The worker also disables its native shell, image/file viewing, apps/plugins, browser,
computer-use, goals and subagent features so the supported workflow uses the coordinator's
approved document tools. Feature names were checked against the installed CLI; see the
[official configuration reference](https://developers.openai.com/codex/config-reference/).
This approval is an application control, not a replacement for Windows account security
or a guarantee against bugs in external PDF parsers or future CLI versions. No live
worker was launched to validate the updated feature configuration during implementation.

## Working on another project

With personal-file reading enabled, select an existing Git project explicitly:

```text
Newton> use project "C:\Users\rober\Desktop\OtherPythonProject"
```

Newton asks before switching or creating/resuming that project's session metadata.
A new session has its own displayed default budget of 50; counters in existing sessions
are preserved. Live-work approval and file-access approval are requested for the selected
session. Coding still requires an explicit task and edits remain in its isolated Git
worktree. Merely approving personal-file reading cannot authorize edits, deletion or
publishing. The existing controller supports its Python `src`/`tests` workflow and allowed
text/document paths; this is not unrestricted editing/execution for every project type.
Non-Git folders can be read, but are not silently initialized or treated as coding projects.

## Clear requests and clarification follow-ups

After approving live work for this launch, ask naturally:

```text
Newton> I want you to create src/angular_motion.py with angular velocity and acceleration functions. Add tests.
```

Clear requests such as `create`, `can you create`, `I want you to add`, and `please fix`
authorize the corresponding bounded local edits. Meaningful assumptions should be stated;
reasonable defaults should be used for reversible local work. Newton should ask only when
missing information materially changes the result. `Explain how to create...`, planning,
review, explicit negations and `--read-only` do not authorize edits. Request recognition
is local and bounded, not a separate model call or a guarantee of understanding every phrasing.

If Newton asks a necessary clarification, it saves the original authorized task and its
specific question. An answer such as `Use radians and seconds` continues that task after
a restart too. `Yes` confirms only one identifiable pending yes/no action; it does not
answer an either/or question or grant permission without a pending task. `No`, `cancel`,
a new replacement task, or `forget memory` clears pending clarification. Discussion
about a pending task does not itself grant edit permission. When named source paths are
supplied, proposed edits must stay within them and corresponding test files; ordinary
path validation and committed-test protection still apply.

New explicit tasks move the previous plan and criteria into bounded task history,
including unresolved review states, rather than blocking new work. `show previous tasks`
reads that history locally; older reports and worktree files remain available. Up to
three task snapshots are kept in session metadata. Continuing the same plan still waits
for review of a step marked `needs_review`.

After edits, the coordinator writes the actual changed paths, current test results, and
unfinished work into the reply and saved result. Model claims that application is pending
do not override successful application. A response proposing no edits cannot complete
an authorized implementation; it is reported as `implementation_not_applied`. Tests
from earlier turns are not attached to a new answer or failure. The last successfully
applied and tested change is retained separately from the latest result; semantic
correctness remains unverified. A failure after writing files reports those paths and
whether current checks finished. There are no automatic retries or extra model calls.

## Strict allowance controls

- **One live worker invocation maximum per message.** No automatic retries, reviewer
  models, parallel agents, background tasks, or execution of the next plan step.
- **50 live worker invocations per session by default.** Counters persist across
  restart and are reserved before launching. A failed or timed-out call can consume
  allowance and does not automatically refund its slot.
- Each live interactive launch previews used, total and remaining counts and asks once
  for authorization. After approval, normal messages run within the remaining budget
  without repeated prompts. Restarting or switching sessions requires fresh approval.
  Declining leaves local tools usable without inference. Approval is never saved to disk.
- Existing sessions retain their saved limit and historical usage. On launch Newton
  offers a separate explicit confirmation before adopting the new default of 50.
  Declining that migration preserves the previous limit; restarting never resets usage.
- At the cap, local tools continue to work. `set budget 50` means a total limit of 50;
  if four are used, 46 remain. `add budget 10` adds to the greater of usage or limit,
  so even an old counter of 4/3 becomes 4/14, with ten available slots. Both require
  confirmation and start no worker. `increase budget by N` remains an alias for add.
  Positive total limits up to 1000 are supported; this is a local invocation guard,
  not a subscription allowance. A budget change does not authorize a declined launch.
- One CLI invocation can contain multiple internal model calls. **This is not an exact
  token, subscription-percentage, or monthly allowance cap.** No hard token cap is
  enforced by this coordinator. Keep tasks small and approve only useful calls.
- A worker socket/process timeout is not a guarantee of exact billing or immediate
  server-side inference cancellation. The coordinator terminates its child process
  tree on local timeout/cancellation and preserves the reserved invocation count.

One-off live tasks must opt in explicitly:

```powershell
python -m newton --task "Explain the current controller" --approve-live
```

Without `--approve-live`, this prints a budget preview and does not launch a worker.
The flag applies to that one message, not the whole interactive session. `--read-only`
rejects edits even for an implementation request. `--worker-timeout 30` lowers the
worker process timeout (maximum 600 seconds). See the configurable limits below.
`--json` shows detailed local diagnostics.
`--doctor` checks installation and sign-in with no model call. `--mock` is an offline
demonstration, not a substitute LLM. The old `devtools.cli` launcher forwards to this
Economy entry point and no longer enables automatic retries.

## Free local tools

Use ordinary phrases without slash commands:

- `help`, `status`, `show plan`, `explain what you changed`
- `list files`, `read src/horizon/agent.py`, `search citation`
- `show changes` (includes bounded previews of new, untracked files)
- `run tests`, `can you run the tests?`, `check acceptance criteria`
- `cancel the plan`, `show previous tasks`, `forget memory`, `connections`, `quit`

These do not invoke a model. Tests use the fixed Python unittest command, not an
arbitrary shell command. File tools reject traversal, hidden folders, credentials,
symlink escapes, unsupported paths and oversized files. Inventory scans are bounded.
A model may request at most three permitted local tools in one response. Their results
are returned locally; Newton does not launch a second worker to interpret them in the
same message. Continue with a new message within an approved launch if further inference is needed.

## Context, plans and verification

Relevant sources are selected locally from a bounded inventory. Default supplied
source content is at most 12,000 characters across five files; individual full files
are limited to 6,000 characters by default. These source limits are configurable below. This does not include the worker's system instructions,
schemas or bounded memory and is not a token estimate. Excerpts and omitted files are
marked. A full replacement of an existing file requires a complete supplied snapshot
and an unchanged content hash. Oversized/omitted files may require a smaller task.

A structured response distinguishes discussion, investigation, planning, implementation,
review and clarification. Read-only intents cannot propose edits. Local authorization recognizes clear implementation requests and scoped clarification
answers. Model-generated memory cannot grant or revoke that permission; unfamiliar or
ambiguous requests may still need clarification. At most one plan step is worked on per message.
Plans have at most six steps. Valid edits are limited to five files/40,000 replacement
characters, with per-file limits. Committed tests and Newton's own controls/configuration
are protected. New untracked tests may be repaired in a new user-requested message.
JSON/JSONL benchmark fixtures are permitted under docs/examples.

After edits, the coordinator runs tests independently and applies supported acceptance
checks: file existence, expected text, or test success. Criteria are model-proposed,
not expert ground truth. Manual/semantic criteria remain unverified. Passing tests does
not prove task fulfillment. A changed step waits in `needs_review`; after checking it,
say `accept step STEP_ID`. Only then may a user-requested `continue` work on the next step.
Failures stop and are reported; a correction needs a new message and invocation slot.

## Configurable limits for complex questions

A larger invocation budget permits more interactions; it does not itself make an answer
more capable. No model, reasoning setting or billing provider is changed by this upgrade.
Timeout and context/reply defaults remain conservative. Configure these fields in
`newton.toml` under `[agent]` before restarting:

| Setting | Default | Allowed range | Effect |
| --- | --- | --- | --- |
| `max_live_invocations` | 50 | 1-1000 | Initial cap for new sessions; existing sessions need confirmed migration |
| `worker_timeout` | 90 seconds | 1-600 | Stops a slow child process; a failed call still uses its slot |
| `turn_timeout` | 180 seconds | 10-900 | Overall turn deadline, including local work |
| `context_chars` | 12000 | 2000-64000 | Total selected source characters |
| `context_files` | 5 | 1-10 | Maximum source files selected |
| `context_file_chars` | 6000 | 1000-20000 | Maximum characters per selected source file |
| `reply_chars` | 1800 | 256-12000 | Maximum answer characters accepted from the worker |

The effective worker timeout cannot exceed the time left in the turn. Raising only
`worker_timeout` does not override `turn_timeout`. Local tests retain their separate
90-second ceiling. The turn deadline is checked between local operations, not a hard
wall-clock bound on every filesystem operation. Context limits produce marked excerpts
or omitted files; incomplete files still cannot be replaced. A reply exceeding
`reply_chars` is rejected with no retry, rather than silently accepted. The adapter also
rejects a complete structured response larger than 60000 characters. These are character
limits, not output-token settings. Saved last-reply memory stays capped at 1800 characters
and the summary at 1500, even when a longer answer is displayed.

For a longer answer and more processing time on one launch:

```powershell
python -m newton --worker-timeout 300 --turn-timeout 450 --reply-chars 6000
```

`--context-chars` also overrides the source budget for a launch. File count and per-file
limits are set in `newton.toml`. Larger limits can consume more subscription allowance;
there is no hard token or subscription-percentage cap.

## Durable memory and privacy

Session metadata lives under `runs/newton/SESSION_ID`, excluded from Git. It contains
invocation counters, goal, bounded summary/last reply, plan, acceptance criteria,
user decisions, verification metadata and the worktree/report identifiers. It also saves
the bounded current task request (up to 1000 characters), pending question (up to 1000),
scoped authorization, up to three prior task snapshots, latest execution outcome, and
last applied/tested outcome. These fields support clarification follow-ups and distinguish
current checks from earlier work. Full raw
conversation and hidden reasoning are not saved. `forget memory` clears goal, summary,
last reply, plan, decisions, task context and archived summaries, without resetting
counters or deleting code/reports.

Execution JSONL traces contain normalized intent/action/outcome metadata, validation
failures, timing and reported numeric usage. Missing usage and cost remain unknown.
Source text, tool result bodies and raw worker replies are not written into traces.
Reports include file identifiers and acceptance descriptions. Test diagnostics are
bounded transient context, not durable transcript memory. Known credential patterns
are rejected/redacted, but these heuristics are not a guarantee that every possible
secret or personal detail can be identified. Use synthetic/public materials and never
put credentials into goals, code snapshots or personal preferences.

Atomic state writes, per-session locks and revision checks prevent concurrent/stale
processes overwriting newer counters. Stale processes must resume. A crash can leave
`active.lock`; verify that its worker is stopped before manually clearing a stale lock.
Older session metadata is backed up as `legacy-session-v1.json` when migrated. Historical
attempts are conservatively counted; an old session may already be at its new cap.
No budget is silently reset during migration. Old pre-Economy metadata initially retains
the previous three-invocation guard until a higher limit is explicitly approved.

## Architecture and current limits

- `newton/conversation.py`: durable Economy session, local actions and one-step execution.
- `newton/task_context.py`: local request recognition and scoped clarification continuation.
- `newton/personal_files.py`: approval-gated read-only personal files and PDF page extraction.
- `newton/decisions.py`, `decision.schema.json`: validated intent, plan, edits and tool requests.
- `newton/project_tools.py`: selective context, local tools and stale-file checks.
- `newton/worker.py`: one-shot Codex subscription adapter and offline mock.
- `devtools/`: reused process, authentication, worktree, test and edit validation helpers.
- `newton/session.py`: legacy library interface retained for earlier experiments/tests;
  the supported CLI runs the new Economy controller.

Codex is the default live connection and requires ChatGPT sign-in. Experimental
Claude Code and Gemini CLI adapters can be selected explicitly; setup and live validation
are still required. No API-key fallback or credit purchases are performed. The direct
OpenAI API adapter is parked and never used by Newton. Web-chat histories are not imported.
Models run remotely; selected context is sent only to the explicitly selected provider.

This upgrade is verified offline using simulated worker decisions, including an
interactive plan-to-implementation flow, launch approval across restarts, confirmed
budget migration/extensions, configurable reply/context limits, natural creation requests,
clarification continuation, task replacement and execution-derived completion memory. No live worker was
launched during the budget upgrade. Live authentication, answer quality and the updated
conversational protocol remain unverified by these offline tests. A live smoke test
requires separate approval for at most one invocation.

## Local app entry point

`python -m newton.api --mode mock` launches a loopback-only browser app and API. Open
the private link printed by the server. Mock demo files and test results are labeled
as simulated. Real local commands still work, but mock mode makes no model calls.
See [NEWTON_API.md](NEWTON_API.md) for the API contract, separate approval switches,
app-specific session storage, live-mode opt-in and parallel frontend/backend workflow.


## Teaching and evidence

Teacher is the default response style. Use these free local commands at any time:

```text
style teacher
style supervisor
style concise
providers
status
```

Teacher gives a direct answer, the key concept and a useful worked example for substantial
questions. Supervisor assesses the approach, assumptions, tradeoffs and acceptance criteria.
Concise gives the essential answer. All styles ask for evidence-based claims, explicit
uncertainty, units/domain restrictions for physics/math, and references to supplied files
or PDF pages. Simple questions should stay short; teaching does not add confirmation gates.
These instructions do not guarantee factual accuracy and are not independent fact checking.
There is no web-search tool in this Newton workflow.

When a model requests local checks, the coordinator runs them and displays the evidence as
`tool_results_ready`. The model has not yet read these results and must not present them as
verified conclusions. Ask a follow-up to interpret the collected results; this uses one new
invocation, without automatic chaining. Bounded project-tool observations are kept in memory
for that process only. Personal excerpts remain subject to the existing read permission.
Completion messages for edits are generated from actual coordinator outcomes, so a stale
worker statement such as “application is pending” cannot override applied changes/test results.

## Prevented invocations

Newton checks launch approval, remaining budget, missing CLI/authentication, and known edit
blockers before reserving an invocation. In particular, a new isolated coding workspace
requires a clean committed baseline, and explicitly named committed tests remain protected.
A blocked request has an `invocation_prevented` trace, a report with `worker_invocations: 0`,
and no current verification. Its count is displayed separately as **prevented before launch**;
it does not subtract from the session allowance. Earlier successful work remains recorded.
Local commands are free operations, not prevented model calls.

A timeout/failure after a worker is launched still consumes its reserved slot; there is no
refund or automatic retry. Blocking an invalid worker proposal after it returns cannot save
that already-used invocation. Preflight cannot foresee every invalid response.

## Choose a provider or model

Exit the old Newton process first. Existing progress and invocation usage survive switching:

```powershell
python -m newton --provider codex --style teacher
python -m newton --provider claude --style supervisor
# Replace MODEL_ID with a specific model available to your Google account:
python -m newton --provider gemini --model MODEL_ID --style teacher
```

`--model MODEL_ID` explicitly changes the model; `--model ""` clears a saved override.
Changing provider without a model resets the override to that CLI's default. Gemini requires
an explicit non-auto model before live work, to avoid its automatic model router. Newton
never picks a larger model for a harder question. Saved provider/model/style are restored;
launch approval is always fresh. Profile defaults for new sessions live in `newton.toml`.

| Connection | Requirement | Status of this implementation |
| --- | --- | --- |
| ChatGPT / Codex | Existing Codex CLI with ChatGPT sign-in | Existing adapter, extended with explicit model selection |
| Claude | Current Claude Code CLI, `claude auth login` with a claude.ai account | Experimental adapter, offline tests only |
| Gemini | Current Gemini CLI, cached Google sign-in, explicit model | Experimental adapter, offline tests only |
| Mock | No account | Offline demonstrations and testing |

ChatGPT is accessed through Codex, not by automating the ChatGPT website. A ChatGPT
subscription does not sign you into Claude or Gemini. Newton does not install CLIs, open
login flows, buy credits, use API-key billing, or fall back to another provider automatically.
`providers` checks executable availability only. `connections` (or `--doctor --provider NAME`)
checks local CLI/auth configuration without an inference prompt; Gemini cached credentials
are not proof that a login is still valid. An unsupported CLI version or missing login stops
before an invocation is reserved. Install/sign in using the providers' official instructions.

Provider child processes receive no API-key/routing environment variables. Claude requires
`authMethod=claude.ai`; API-key, Console/token and third-party routes are rejected. Its
restricted/safe CLI modes disable ambient customizations and native tools. Gemini enforces
Google OAuth, disables hooks/extensions/MCP/agents, supplies a deny-tools policy and turns
credit overage off. Both run from a temporary directory and must return the existing strict
JSON decision contract; Newton alone applies permitted edits and runs tests.

**Billing and limits:** a single CLI invocation may contain multiple internal model calls.
The 50/session, 1/message limits and timeouts are not exact token, subscription-percentage,
or monetary caps. Account sign-in alone does not prove that provider-side paid overage is
disabled. Disable usage credits/paid overage in your account before authorizing live work.
Newton does not enable or purchase those services and cannot verify every account-level
billing policy. This integration is intended for personal, unmanaged CLI installations;
organization-managed settings may impose additional behavior. Provider CLIs may maintain
their own logs according to their settings; Newton's traces store metadata, not raw prompts.

No limits were silently raised: worker timeout 90s, turn timeout 180s, selected project context
12,000 characters, reply 1,800 characters, 5 files of up to 6,000 characters each. Existing
flags configure these bounds. An overlong structured reply is rejected, not silently retried;
a timeout can interrupt a longer task. Ask one focused question at a time.

Official references used for adapter design:
- [Codex authentication](https://developers.openai.com/codex/auth)
- [Claude Code authentication](https://code.claude.com/docs/en/authentication)
- [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Gemini CLI authentication](https://geminicli.com/docs/get-started/authentication/)
- [Gemini CLI configuration](https://geminicli.com/docs/reference/configuration/)
- [Gemini CLI model routing](https://geminicli.com/docs/cli/model-routing/)

## Offline validation and a small manual check

The automated suite uses simulated workers and temporary Git projects; it does not establish
that a live provider is currently reachable or that educational answers are factually correct.
Restart Newton, select your configured provider, review the budget, and approve the launch.
Try: “Explain centripetal acceleration with units and a worked example, under 1,500 characters.”
Check the result against a textbook. Use `style supervisor` and ask it to critique your solution.
Check `status` after each live question: one invocation at most. `style`, `status`, `providers`,
file searches and local tests must not increase the counter. No live tests were run during
implementation. Broader providers require a new reviewed adapter and offline auth/tool/billing
boundary tests; arbitrary user-supplied executable commands are not accepted.


## Educational study pilot

See [Newton Study guide](NEWTON_STUDY.md) for the Ontario mechanics pilot, local profiles, interactive diagrams, flashcards, practice, sources, limits and offline/live test instructions.

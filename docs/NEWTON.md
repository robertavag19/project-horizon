# Newton conversational agent: Economy mode

Newton is the personal development assistant. Horizon Reliability remains the main
research project and Horizon Study remains its first experimental agent. This is
workflow engineering with a subscribed Codex model, not model training.

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
Newton> Help me plan a small benchmark for Horizon Study.
Maximum for this message: 1 live invocation, no automatic retries.
Authorize at most 1 live Codex invocation for this message [y/N]? y
Newton> Implement the first small step and add focused tests.
Authorize at most 1 live Codex invocation for this message [y/N]? y
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

## Strict allowance controls

- **One live worker invocation maximum per message.** No automatic retries, reviewer
  models, parallel agents, background tasks, or execution of the next plan step.
- **Three live worker invocations per session by default.** Counters persist across
  restart and are reserved before launching. A failed or timed-out call can consume
  allowance and does not automatically refund its slot.
- Each live message previews its one-invocation budget and requires approval. A new
  confirmation is not requested midway through that bounded task.
- At the cap, local tools continue to work. Say `increase budget by 1` to request an
  explicit extension and confirm it. The extension starts no worker automatically.
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
worker process timeout (maximum 90 seconds). `--json` shows detailed local diagnostics.
`--doctor` checks installation and sign-in with no model call. `--mock` is an offline
demonstration, not a substitute LLM. The old `devtools.cli` launcher forwards to this
Economy entry point and no longer enables automatic retries.

## Free local tools

Use ordinary phrases without slash commands:

- `help`, `status`, `show plan`, `explain what you changed`
- `list files`, `read src/horizon/agent.py`, `search citation`
- `show changes` (includes bounded previews of new, untracked files)
- `run tests`, `can you run the tests?`, `check acceptance criteria`
- `cancel the plan`, `forget memory`, `connections`, `quit`

These do not invoke a model. Tests use the fixed Python unittest command, not an
arbitrary shell command. File tools reject traversal, hidden folders, credentials,
symlink escapes, unsupported paths and oversized files. Inventory scans are bounded.
A model may request at most three permitted local tools in one response. Their results
are returned locally; Newton does not launch a second worker to interpret them in the
same message. Continue with a new approved message if further inference is needed.

## Context, plans and verification

Relevant sources are selected locally from a bounded inventory. Default supplied
source content is at most 12,000 characters across five files; individual full files
are limited to 6,000 characters. This does not include the worker's system instructions,
schemas or bounded memory and is not a token estimate. Excerpts and omitted files are
marked. A full replacement of an existing file requires a complete supplied snapshot
and an unchanged content hash. Oversized/omitted files may require a smaller task.

A structured response distinguishes discussion, investigation, planning, implementation,
review and clarification. Read-only intents cannot propose edits. A conservative local
authorization gate additionally requires a clear implementation request; unfamiliar
phrasing may need clarification. At most one plan step is worked on per message.
Plans have at most six steps. Valid edits are limited to five files/40,000 replacement
characters, with per-file limits. Committed tests and Newton's own controls/configuration
are protected. New untracked tests may be repaired as a separately approved message.
JSON/JSONL benchmark fixtures are permitted under docs/examples.

After edits, the coordinator runs tests independently and applies supported acceptance
checks: file existence, expected text, or test success. Criteria are model-proposed,
not expert ground truth. Manual/semantic criteria remain unverified. Passing tests does
not prove task fulfillment. A changed step waits in `needs_review`; after checking it,
say `accept step STEP_ID`. Only then may an approved `continue` work on the next step.
Failures stop and are reported; a correction needs a new message and invocation slot.

## Durable memory and privacy

Session metadata lives under `runs/newton/SESSION_ID`, excluded from Git. It contains
invocation counters, goal, bounded summary/last reply, plan, acceptance criteria,
user decisions, verification metadata and the worktree/report identifiers. Full raw
conversation and hidden reasoning are not saved. `forget memory` clears goal, summary,
last reply, plan and decisions, without resetting counters or deleting code/reports.

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
No budget is silently reset during migration.

## Architecture and current limits

- `newton/conversation.py`: durable Economy session, local actions and one-step execution.
- `newton/decisions.py`, `decision.schema.json`: validated intent, plan, edits and tool requests.
- `newton/project_tools.py`: selective context, local tools and stale-file checks.
- `newton/worker.py`: one-shot Codex subscription adapter and offline mock.
- `devtools/`: reused process, authentication, worktree, test and edit validation helpers.
- `newton/session.py`: legacy library interface retained for earlier experiments/tests;
  the supported CLI runs the new Economy controller.

Codex is the only connected live worker. It requires supported ChatGPT sign-in and
rejects API-key fallback. No credits are purchased. The direct OpenAI API adapter is
parked and is never used by Newton. Claude/Gemini/web chat histories are not connected.
The model still runs remotely, and selected project context is sent to Codex.

This upgrade is verified offline using simulated worker decisions, including an
interactive plan-to-implementation flow. The new conversational schema has not been
verified with a live worker. A live smoke test requires separate approval for at most
one invocation; none was launched during the upgrade.

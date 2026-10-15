# Newton: your personal development agent

Newton is the personal development coordinator. Horizon Reliability remains the
research software and Horizon Study remains its first experimental agent. Newton
is configured with preferences and session context; no model training is performed.
Only Codex is connected, through verified ChatGPT sign-in and the plan allowance.
No direct paid API or other chatbot subscription is used automatically.

## Start talking to Newton

```powershell
cd "C:\Users\rober\Desktop\Ai agent\Horizon_Sprint_01"
python -m newton --doctor
python -m newton
```

Type tasks directly at `Newton>`. For example:

```text
/plan Build a ten-task benchmark for Horizon Study with independently specified reference passages.
Implement the first small step from that plan and add focused tests.
/review
/status
/tests
/quit
```

The plan and replies from the last two exchanges are supplied as bounded context in
the same process. Follow-ups see the same pending worktree changes, so they can build
on previous tasks without copying between chats. Each worker invocation is a new
Codex session; Newton supplies continuity. It is not direct access to your old chats.

A task may produce at most ten text-file edits. Committed tests remain protected;
new untracked tests can be repaired. The coordinator runs tests independently and
allows one repair attempt by default. A model's completed status and passing tests
still require human review against the task's acceptance criteria.

Other commands:
- `/connections`: verify the configured worker's sign-in; no model call.
- `/diff`: display pending tracked diffs and untracked file names.
- `/new`: create a fresh session, leaving old work preserved.
- `/help`: list commands.

## Save progress and customize behavior

Newton prints a resume command, for example:

```powershell
python -m newton --resume YOUR_SESSION_ID
```

Workspace ID, report IDs and statuses are saved locally under `runs/newton` and
ignored by Git. Conversation text stays in memory and is not restored after exit.
Code changes remain in the worktree. A lock prevents concurrent use of one session;
if a process crashes and leaves `active.lock`, inspect that session before removing
the stale lock. Existing development coordinator commands remain available.

`newton.toml` controls the name, Codex/mock worker, instructions, timeout, repair count
and task limit. Keep secrets out of this tracked file. Commit profile edits before
starting a new workspace. Defaults allow five tasks per session and one repair per
task, to bound consumption. `/new` explicitly starts a fresh allowance budget. These
limits are not exact token caps and do not bypass your subscription's usage limits.

For an offline demonstration:

```powershell
python -m newton --mock
```

The mock exercises session handling but does not implement tasks. To use one command:

```powershell
python -m newton --task "Add a small benchmark fixture under examples and document its acceptance checks"
```

Newton's files are in `newton/`; reusable worktree and worker code remains in
`devtools/`. Workers receive bounded source snapshots and propose structured edits;
the coordinator validates and writes them locally. Arbitrary shell actions, installs,
browsing, file deletion, Git merges/pushes and other bots are not added to its tools.
Use small task stages. If needed context exceeds snapshot limits, Newton should
report blocked instead of inventing missing files. No live worker transcript is
saved in Horizon traces; only normalized metadata and final report information.


## Rejected worker responses

A validation rejection is a failed attempt, not a test result. `Tests: 0` means the
coordinator did not run tests after rejecting the proposal. Reports now include the
exact rule in `last_error` and whether the task was read-only. Normalized worker
events are retained even when the final edit proposal is rejected; source text and
raw replies remain excluded from traces.

Examples include `blocked_status_with_edits` (the worker reported blocked while also
proposing edits), `read_only_edit_rejected`, `invalid_edit_fields`, and
`invalid_edit_content`. For a validation rejection Newton may request a corrected
response within the existing repair budget. It does not relax path restrictions or
protective checks. A genuinely blocked response must propose no edits. The model's
job is to propose changes; the coordinator writes them and runs tests.

After a Newton code update, exit the running Python process with `/quit` and restart
using its printed `--resume` command so the updated modules are loaded.

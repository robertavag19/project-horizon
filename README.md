# Project Horizon — Sprint 01: Trace-first experimental baseline

**Status: research prototype with a deterministic baseline, bounded agent controller, and optional OpenAI adapter. Live model behavior has not yet been tested. Factual answer correctness is not automatically verified.**

This repo establishes a runnable, free-to-use test harness for our longer-term goal: measuring where AI agents deviate, how serious deviations are, when they recover, and whether outcomes are actually correct. We first prove that we can ingest a document, use tools in a bounded workflow, log an observable execution trace, and detect a known citation error. **The newer controller and opt-in LLM adapter are described below; the original baseline remains available.**

## Quick start on Windows (PowerShell)

1. Install Python 3.11 or newer and Git. Open this folder in VS Code.
2. In the project directory, run:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m horizon.cli --question "What is centripetal acceleration?"
python -m horizon.cli --question "What is centripetal acceleration?" --inject wrong_citation
python -m horizon.cli --question "What is centripetal acceleration?" --inject drop_evidence
```

If `py` is unavailable, use `python -m venv .venv` instead. No external Python packages, API keys, accounts or GPU needed.

Each run writes a JSONL trace in `runs/` and prints a summary. Inspect the trace in VS Code.

## Why the original baseline is not an AI agent

The current program uses deterministic keyword retrieval and excerpts, not an LLM. It demonstrates instrumentation and evaluation plumbing; it does **not** autonomously decide actions, assess factual answer quality, or measure real model accuracy. It does, however, record known injected errors and an example of fixing an invalid citation ID. Do not market it as a functioning intelligent tutor.

## First experiments

| Run | Expected event | Why it matters |
|---|---|---|
| `--inject none` | cited excerpt present | Normal workflow baseline |
| `--inject wrong_citation` | invalid ID detected and fixed | Controlled error detection and recovery |
| `--inject drop_evidence` | can't answer | Detect unavailable evidence; avoid making up an answer |

**Important:** Validation of a citation ID is much weaker than checking if the cited passage actually supports the claim. The future evaluator must test semantic correctness using curated ground-truth tasks and expert/manual review.

## Roadmap from the original baseline

Add a provider interface and a bounded controller that lets a real model choose among `search_sources`, `read_passage`, and `finish_answer`, while preserving tracing and a free mock adapter for tests. Then build 30-50 source-grounded benchmark tasks with reference answers. Keep model keys out of source code, do not log private user content, constrain tool calls, and ask before any paid API calls.

## Project separation

- **Horizon Reliability** — core experimental method / prospective technology.
- **Horizon Study** — a first useful test agent that may later become its own public product.

See `docs/NEXT_CODEX_PROMPT.md` and `docs/RESEARCH_METRICS.md`.

## Sprint 02 increment: bounded controller, offline provider

The original `--mode baseline` remains available. The new controller accepts actions
from a replaceable provider. The included `MockProvider` is deterministic: **no LLM,
network connection, API key, or paid call is used**. The optional OpenAI provider is described below; mock remains the default.

From the project folder in PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m horizon.cli --mode agent --expected-passage P001
python -m horizon.cli --mode agent --inject wrong_citation --expected-passage P001
python -m horizon.cli --mode agent --inject drop_evidence --expected-passage P001
python -m horizon.cli --mode agent --max-steps 2
```

The last command deliberately exhausts the action budget and exits with code 1.
Completed answers and abstentions exit with code 0. Abstention is structurally valid,
but is not automatically successful on an answerable benchmark task.

- `models.py`, `providers.py`, `tools.py`, `agent.py`: Study actions, source tools,
  provider interface, and bounded controller. A provider can choose a different valid
  path; the controller does not force a search/read sequence.
- `tracing.py`, `evaluation.py`: Reliability event recording and independent structural
  final checks, separate from the provider's assertions.
- All actions have strict argument schemas. Answers require existing citation IDs
  that the agent actually read. Rejected submissions go back to the provider.
- A run has a maximum of 8 actions by default (configurable to 100). Each action has
  a step index linking provider events, tool events, checks, and fault injection.
- Traces include a schema version, task/run IDs, event sequence, UTC timestamps,
  durations, evaluator provenance and explicit termination reason. Prompts, source
  text, answer text, arbitrary provider IDs and raw exception messages are excluded.
  Use non-identifying task IDs. Answers appear in CLI output, not JSONL traces.
- The document limit is 1 MB and the CLI accepts UTF-8 `.txt` only. Passage IDs are
  positional within one document; multiple-document stable IDs and PDF ingestion
  remain future work.
- `wrong_citation` modifies the first answered submission. The controller records
  the exact injection step and rejects it. The provider must submit a correction.
  `drop_evidence` removes the first search result. Injection application is reported
  separately from the requested injection.
- Recovery means a rejected structural submission was followed by an accepted
  answered submission. It does not establish semantic correction or recovery probability.
- Final evaluation reports citation/read checks and, when explicitly supplied,
  whether the reference passage is cited in the final submission. It does not grade
  factual correctness, severity, detector precision/recall, or causal impact.
- The elapsed-time budget is checked before and after provider calls; it **cannot
  interrupt a blocked synchronous provider call**. A future network adapter must
  enforce request timeouts, token/cost budgets and explicit live-call opt-in. Usage
  and cost are currently unknown (`null`), not measured zeros.

Next: validate the adapter in one explicitly approved live run, then add a ten-task
source-grounded reference suite. Keep live calls disabled by default.


## Paid API adapter (parked; not our current workflow)

`openai_provider.py` lets GPT-4.1 mini choose the same structured actions as the mock.
It uses the Python standard library, so no new packages need installing. The model
runs remotely; retrieval, action validation, tracing and evaluation run locally.
The question and previously read source passages are sent to OpenAI. Use the included
public/synthetic physics example for the first test. No student/private data.

Default runs still use the baseline or mock. Setting a key alone never enables calls.
Live runs require all three flags: `--mode agent --provider openai --allow-paid-api`.
The last flag is explicit approval for that command to incur API charges. ChatGPT/Codex
sign-in is not used by this adapter: it requires an OpenAI API key.

After agreeing to a live test, copy `.env.example` to `.env` and edit the key there
locally. Never paste the key into a chat. The CLI reads only `OPENAI_API_KEY` from
`.env`, or uses that variable from your environment when present. `.env` is ignored
by Git. Do not put a real key in `.env.example`.

```powershell
cd "C:\Users\rober\Desktop\Ai agent\Horizon_Sprint_01"
$env:PYTHONPATH = "src"
# Run only after approving API spending and setting the key locally:
python -m horizon.cli --mode agent --provider openai --allow-paid-api --max-steps 4 --expected-passage P001
```

Controls and limitations:

- At most four API requests per provider instance; 512 output tokens per request.
  Each CLI invocation creates a new instance and a new budget. There is no monthly cap.
- Maximum 16,000 UTF-8 JSON request bytes, with a cumulative 30,000-token conservative
  reservation budget (request bytes + 1,024 framing allowance + output limit).
  This is a byte-based estimate, not exact tokenization or a guaranteed billing ceiling.
- Request socket timeout is 10 seconds; no automatic retries. The controller also
  checks its elapsed-time budget between calls. A socket timeout is not a hard
  whole-run deadline; an interrupted request can still incur charges.
- Strict function schemas, one call at a time, and controller-side argument checks.
  The actual model call and matching tool output are preserved in memory between steps.
  A citation rejection is passed back to the model; Python does not substitute an answer.
- `store: false` disables response storage for later API retrieval; it is not a claim
  of zero provider data retention. Raw model output, keys, source text and hidden
  reasoning are not written into Horizon traces.
- Usage returned by the API is traced. Estimated USD cost uses standard GPT-4.1 mini
  rates checked on 2026-10-13: $0.40/million input tokens and $1.60/million output
  tokens, ignoring cache discounts. It is not an invoice. Missing usage or a failed
  request is recorded as unknown, not free.
- The first adapter supports only GPT-4.1 mini. Budget limits reject requests before
  sending them; provider errors terminate the run with a sanitized reason.
- Offline API tests simulate responses and the transport. Passing them does not prove
  that authentication, billing, model access, or live answer quality works.

Official references:
- https://developers.openai.com/api/docs/guides/function-calling
- https://developers.openai.com/api/docs/models/gpt-4.1-mini


## Current development workflow: subscription-based Codex coordinator

This is a development assistant for working on Horizon, separate from the Study agent.
It uses the installed Codex CLI with **ChatGPT sign-in**, not an OpenAI API key. Model
inference is remote and consumes your plan allowance; it is not offline or unlimited.
The direct paid API adapter above is parked and remains opt-in. Do not enable it for
this workflow.

You can launch the coordinator without setting PYTHONPATH:

```powershell
cd "C:\Users\rober\Desktop\Ai agent\Horizon_Sprint_01"
python -m devtools.cli --doctor
python -m devtools.cli --worker mock --task "Exercise the development workflow"
python -m devtools.cli --read-only --task "Inspect the source and suggest the smallest improvement. Do not edit files."
python -m devtools.cli --task "Add a focused test for empty source documents and document the behavior."
```

The first command checks installation and authentication, with no model inference.
If authentication is rejected, run `codex login` and choose ChatGPT. The CLI must be
available on PATH or in the Windows desktop app installation. The coordinator
automatically checks `%LOCALAPPDATA%/OpenAI/Codex/bin/*/codex.exe` when PATH discovery
fails. You may set `HORIZON_CODEX_PATH` to a specific executable. No API key is needed. The mock worker contacts no service.

For each task the coordinator:
1. Requires a clean Git project with committed HEAD and verifies ChatGPT sign-in.
2. Creates a branch `codex/dev-...` and worktree under `runs/development/<run_id>`.
   Your working checkout is preserved; ignored `.env` files are not copied.
3. Invokes Codex via `codex exec --json`, with an explicit ChatGPT login restriction,
   API-key/access-token environment variables removed, OpenAI provider selected,
   user config ignored, web search/MCP/hooks disabled, and a read-only worker sandbox.
4. Supplies at most 64 KB of permitted source snapshots to Codex, which returns
   structured file edits. The coordinator validates every path before writing in the
   worktree. At most ten text files per attempt; existing tests, hidden folders,
   credentials and config files cannot be overwritten. New tests are allowed.
5. Runs `unittest discover` independently using the same Python interpreter.
6. Returns failed test output for at most one repair attempt by default (`--max-repairs`
   allows 0, 1 or 2). Each attempt is a new ephemeral Codex session with the task,
   existing worktree changes, and failure context. No cross-chat copying is required.
7. Leaves the worktree and report for review. No automatic commits, merge or push.

Structured worker summaries distinguish completed from blocked tasks. A blocked
task exits with code 1 even when tests pass. The summary is a model assertion, not
independent proof of fulfillment. Reports distinguish tests passing from task fulfillment: `tests_passed_review_required`
means tests passed, not that every requested behavior was verified. Open the worktree
path printed in `report.json` in VS Code to inspect changes. Use `git diff` there.
Worktrees are retained for review; this increment does not automatically clean them up.

Default worker timeout is 180 seconds; test timeout is 90 seconds. On timeout the
coordinator terminates its child process tree. It does not enforce a Codex token cap;
keep tasks small and retries low to conserve your plan allowance. The `--read-only` command
rejects all proposed edits and disables repairs. The worker always uses a read-only
sandbox; only the coordinator applies validated edits.

The local JSONL trace stores only normalized event metadata, tool/command status,
numeric usage where supplied, test counts and repair events. Prompts, raw commands,
test output, worker replies and hidden reasoning are excluded from stored traces/reports.
The final worker reply is displayed in CLI output only. Codex's own data handling
still applies. Paths/changed filenames are included in the local report. Use synthetic
materials. The coding worker is more capable than Study's three-tool controller; it is
not a replacement model adapter for Study and does not automatically add Claude access.

Official documentation:
- https://learn.chatgpt.com/docs/auth
- https://learn.chatgpt.com/docs/non-interactive-mode


## Newton: personal development agent

The development coordinator is now named **Newton**, separate from Horizon Reliability
and Horizon Study. Start `python -m newton` from this folder to type tasks directly.
Newton supports `/plan`, `/review`, `/status`, `/diff`, `/tests`, `/connections`,
`/new` and `/quit`. Follow-up tasks reuse one isolated worktree; progress can be
resumed with the printed session ID. Conversations stay in memory only.

Preferences live in `newton.toml`. This is customization and workflow engineering,
not model training. Codex is the only connected worker for now, using the verified
ChatGPT sign-in. The paid API adapter remains parked. See `docs/NEWTON.md` for examples,
limits and the distinction between Newton's role and Horizon's research components.

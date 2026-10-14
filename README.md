# Project Horizon — Sprint 01: Trace-first experimental baseline

**Status: research scaffold, not a model-powered study agent and not an AI-accuracy detector.**

This repo establishes a runnable, free-to-use test harness for our longer-term goal: measuring where AI agents deviate, how serious deviations are, when they recover, and whether outcomes are actually correct. We first prove that we can ingest a document, use tools in a bounded workflow, log an observable execution trace, and detect a known citation error. **Next sprint: attach a genuine language-model adapter and a bounded model-driven action loop.**

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

## Why this is not an AI agent yet

The current program uses deterministic keyword retrieval and excerpts, not an LLM. It demonstrates instrumentation and evaluation plumbing; it does **not** autonomously decide actions, assess factual answer quality, or measure real model accuracy. It does, however, record known injected errors and an example of fixing an invalid citation ID. Do not market it as a functioning intelligent tutor.

## First experiments

| Run | Expected event | Why it matters |
|---|---|---|
| `--inject none` | cited excerpt present | Normal workflow baseline |
| `--inject wrong_citation` | invalid ID detected and fixed | Controlled error detection and recovery |
| `--inject drop_evidence` | can't answer | Detect unavailable evidence; avoid making up an answer |

**Important:** Validation of a citation ID is much weaker than checking if the cited passage actually supports the claim. The future evaluator must test semantic correctness using curated ground-truth tasks and expert/manual review.

## Next sprint: genuine model-driven study agent

Add a provider interface and a bounded controller that lets a real model choose among `search_sources`, `read_passage`, and `finish_answer`, while preserving tracing and a free mock adapter for tests. Then build 30-50 source-grounded benchmark tasks with reference answers. Keep model keys out of source code, do not log private user content, constrain tool calls, and ask before any paid API calls.

## Project separation

- **Horizon Reliability** — core experimental method / prospective technology.
- **Horizon Study** — a first useful test agent that may later become its own public product.

See `docs/NEXT_CODEX_PROMPT.md` and `docs/RESEARCH_METRICS.md`.

## Sprint 02 increment: bounded controller, offline provider

The original `--mode baseline` remains available. The new controller accepts actions
from a replaceable provider. The included `MockProvider` is deterministic: **no LLM,
network connection, API key, or paid call is used**. A real provider is the next increment.

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

Next: add a ten-task source-grounded reference suite, then a real structured-tool LLM
adapter with request timeouts and spending controls. Keep live calls disabled by default.

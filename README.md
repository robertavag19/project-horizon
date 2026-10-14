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

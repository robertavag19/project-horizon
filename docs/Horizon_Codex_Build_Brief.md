# PROJECT HORIZON — CODEX ENGINEERING HANDOFF
**Working app name:** Horizon Study  
**Phase:** MVP-0 / local-first proof of concept  
**Date:** October 2026

## 1. Read this first
You are assisting on Project Horizon, an early-stage experimental AI agent product for students and general learners. Build a **small, working source-grounded research and study agent**, not a generic all-purpose chatbot or a large enterprise platform. A second purpose is to provide transparent experimental traces so we can study agent errors and recovery.

**Do not assume any code or infrastructure exists.** Inspect the repository and machine before changing files. Propose the smallest working vertical slice. Prefer tests, explicit assumptions, reproducibility, and readable code. Never claim tests passed unless you ran them.

## 2. Product hypothesis
A learner gives the agent a question plus a few source documents. The agent retrieves relevant evidence, composes a helpful answer, links major claims to specific source passages, acknowledges unsupported claims, and optionally generates a short comprehension quiz. The key UX idea is *inspectable evidence*.

Example user request: “Using these physics notes, explain centripetal acceleration, cite the relevant sections, and give me three questions.”

Expected output:
- Plain-language answer with evidence references to document/page/passage IDs.
- Distinction between supported and unsupported assertions.
- Three questions with answer explanations (as a second increment; do not block MVP on this).
- A run ID through which a developer can inspect the execution trajectory.

## 3. Separate the two products
**Horizon Study** (user facing): document upload/text entry, ask question, cited answer, practice questions, lightweight history.

**Horizon Reliability Lab** (research only, not exposed in public UI initially): structured agent-event tracing, reference evaluation, controlled fault injection, error analysis, recovery and cost metrics.

Do not implement heavy predictive scoring in MVP-0. Collect clean experimental data first.

## 4. MVP-0 scope — implement in sequence
1. **Project foundation:** Python project, pinned dependencies, README, `.env.example`, `.gitignore`, automated tests, basic linting.
2. **Document ingestion:** Accept `.txt` and small text-based PDFs; extract passages preserving source document, page or section if available, and stable passage IDs. Show errors for image-only PDFs rather than silently claiming to read them. Avoid OCR at first.
3. **Retrieval:** Local, reproducible passage search (start with keyword/SQLite FTS5 or a simple sparse ranking; no vector database required). Include selected evidence with the question.
4. **Minimal agent controller:** Bounded loop with a small allowlist of tools (`search_sources`, `read_passage`, `finish_answer`). Tool results are structured, actions are validated, maximum step count is enforced. Use a model-provider adapter so backend can be swapped. A deterministic/mock adapter must be supported for unit tests.
5. **Grounded response:** Answer with passage IDs; validate that cited IDs exist, and mark unsupported claims/limitations. Do not present AI confidence as calibrated probability.
6. **Trace recorder:** Record run ID, task ID, step index, timestamp, model/tool action kind, sanitized tool arguments, result metadata, source IDs, latency and token/cost metadata when available, final answer, and verifier results. Store local JSONL or SQLite. No private reasoning or secrets.
7. **CLI demonstration:** Commands for loading example source materials and running one question. A simple Streamlit or minimal web UI may follow after a working CLI.
8. **Basic grading/test harness:** Known-answer test cases and deterministic checks for citation IDs, retrieval recall, basic exact-answer checks, and successful run completion. Capture failures honestly.

## 5. Out of scope for MVP-0
- Training or fine-tuning foundation models.
- Multi-agent teams or elaborate autonomous plans.
- NVIDIA NeMo as a mandatory dependency.
- User accounts, payments, social features, production-scale hosting.
- Unrestricted browsing, external messaging, file deletion, or irreversible actions.
- Sensitive document processing or full educational compliance claims.
- Claims that generated explanations are guaranteed correct.
- Predictive recovery models without labeled data and baselines.

## 6. Suggested repository structure
```
horizon-study/
  README.md
  pyproject.toml
  .env.example
  .gitignore
  src/horizon/
    __init__.py
    cli.py
    config.py
    models.py             # typed task, source, tool, event objects
    ingestion.py          # text and PDF extraction
    retrieval.py          # sparse local search
    agent.py              # bounded decision/action loop
    tools.py              # allowlisted tool operations
    providers.py          # API and mock adapters
    grounding.py          # citation/excerpt validation
    tracing.py            # structured events
    evaluation.py         # offline deterministic metrics
  tests/
    test_ingestion.py
    test_retrieval.py
    test_agent.py
    test_grounding.py
    test_tracing.py
    fixtures/
  examples/
    sample_notes.txt
    tasks.jsonl
  docs/
    research_questions.md
    decisions.md
```
Adjust structure to actual repository if it exists; avoid unnecessary dependencies.

## 7. Agent design and event schema
Agent loop: User goal -> retrieve source evidence -> inspect passages -> compose answer -> validate citations -> finalize. The controller—not the model alone—enforces authorized tools and step budgets.

Example JSON event (illustrative fields; adjust to actual types):
```json
{
  "run_id": "run_001",
  "task_id": "task_001",
  "step_index": 3,
  "timestamp_utc": "2026-10-12T00:00:00Z",
  "event_type": "tool_result",
  "tool_name": "read_passage",
  "arguments_sanitized": {"passage_id": "doc1:p4"},
  "source_ids": ["doc1:p4"],
  "result_status": "ok",
  "latency_ms": 120,
  "evaluator_flags": []
}
```

Avoid logging secrets, student-identifying information, sensitive file contents, or model hidden reasoning. If model provider supports tool calls, use its documented structured interface; never parse executable commands from arbitrary model text.

## 8. Two research datasets / scoring framework
**Dataset A — error position and progression:** run, step, type of suspected deviation, first observed location, evidence, whether later steps changed the state.

**Dataset B — deviation and consequences:** rule/expert-referenced severity, persistence, recovery outcome, final quality, actual post-state (if applicable), uncertainty, verifier cost.

Do **not** label every unusual trajectory step as a defect: alternate valid paths exist. Separate observed facts from evaluator hypotheses. Secondary LLM judgments are *not* ground truth; calibrate against expert labels or deterministic checks.

## 9. Experiments (after MVP-0 works)
- Curate a set of 30–50 small tasks with known answers and source passages.
- Measure passage retrieval recall, answer correctness, supported-claim rate, citation validity, latency and model cost.
- Introduce seeded failures (irrelevant retrieval, ambiguous evidence, misleading tool reply, dropped passage), noting the exact injection point.
- Compare agent with no validation vs final-only validation vs full step evaluation.
- Examine recoverable vs persistent errors.
- Only later test a selective-verification policy against those baselines. Define false alarms, missed consequential defects, coverage, and overall resource use.
- For causal impact, replay under controlled conditions with and without injected fault where possible; merely correlating an early error with a bad final result is insufficient.

## 10. Acceptance criteria for first demonstrable milestone
A new developer should be able to:
1. Follow README setup instructions on Windows.
2. Load a small included `.txt` note or text-based PDF.
3. Ask an answerable question and get a readable response with **existing, traceable passage IDs**.
4. Inspect a structured run log and see tool calls, observations and final answer.
5. Run unit tests without a paid API using the mock model adapter.
6. Run a small evaluation suite and see output metrics.
7. Demonstrate appropriate refusal/uncertainty when no source supports the answer.

The first milestone is not production-ready and must be labeled accordingly.

## 11. Practical environment and security
- Target Python 3.11+ unless actual dependency compatibility suggests otherwise.
- Use Python virtual environment or `uv`; avoid system-wide package installs.
- Use Git for version control; create understandable commits.
- Put model keys in environment variables, never client code or git history.
- If using hosted model APIs, document charges and do not place calls in uncontrolled loops. Bound tokens, tool calls, retries, file size, concurrency and total spending.
- Treat document content as untrusted; separate source text from system instructions to mitigate prompt injection.
- Prototype with synthetic/public/permitted documents. No third-party student data without privacy review and consent.

## 12. NVIDIA NeMo usage plan
Do **not** install a heavy agent framework merely for its own sake. Once baseline tracing and evaluation work, compare our local event schema to NVIDIA NeMo Agent Toolkit's observation and evaluation tools, including custom evaluators. Consider integrating its plugin system if it offers a real advantage; preserve model- and framework-neutral research data.

Docs: https://github.com/NVIDIA/NeMo-Agent-Toolkit
Evaluation: https://docs.nvidia.com/nemo/agent-toolkit/latest/improve-workflows/evaluate.html
Custom evaluators: https://github.com/NVIDIA/NeMo-Agent-Toolkit/blob/develop/docs/source/extend/custom-components/custom-evaluator.md

## 13. Reading resources
ReAct paper: https://arxiv.org/abs/2210.03629
Anthropic Building Effective Agents: https://www.anthropic.com/engineering/building-effective-agents
OpenAI Agents SDK Quickstart: https://openai.github.io/openai-agents-python/quickstart/

## 14. First instruction to Codex
**Inspect the current workspace and propose a minimal implementation plan for milestone 1. Then implement the smallest end-to-end CLI vertical slice: load a sample note, retrieve relevant passages, answer through a replaceable model adapter (including a no-cost deterministic mock), validate cited passage IDs, and save a structured execution trace. Add a few focused automated tests, run them, and report precisely what works, what fails, and how to run the demo on Windows. Do not add external-service accounts or spend API money without asking.**

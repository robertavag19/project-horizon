# Codex / Claude next-step handoff

**Latest controlling update: Newton Economy conversation.** The supported CLI now uses
one structured decision/worker invocation per user message, a persisted 50-invocation
default session cap, and zero automatic retries. Live interactive work requires a budget
preview and approval once per process launch; restarting requires fresh approval.
Existing sessions keep their counters and require explicit approval to adopt a higher cap.
Routine status/search/read/diff/tests are local. Budget commands require confirmation.
Do not launch reviewer models or parallel/background workers, or use API billing.

Personal-file reading/searching is optional and requires a separate explicit approval
on every launch. The grant is memory-only; revocation clears selected excerpts. Do not
scan the user's profile or launch workers as part of implementation tests. Use synthetic
files. Personal access is read-only, excludes credentials/AppData/links, and never grants
editing authority. Project switching requires its own explicit confirmation. PDF support
uses optional local pypdf text extraction with page references; no paid/OCR fallback.

Clear conversational implementation requests now authorize bounded edits directly.
Clarification answers inherit only their saved task scope; an ambiguous yes grants no
permission. New tasks archive old plans and criteria. Completion memory and current
verification come from coordinator outcomes, with prior applied/tested work retained
separately. Do not reintroduce repeated permission prompts or stale-memory permission gates.

The conversational upgrade has been tested offline; no live worker was launched during
its implementation. Next: after the user explicitly approves a one-invocation budget,
perform at most one small live smoke test. Then continue Horizon's reference suite one
approved step at a time. See docs/NEWTON.md. Earlier notes below are historical and
must not override these current spending controls.


**Current implementation update:** the bounded Study controller and mock provider are
implemented. The direct OpenAI API adapter is parked: the user does not want separate
API spending. Do not enable it or request an API key for the current workflow.

The local development coordinator (`python -m devtools.cli`) now uses subscription-only
Codex ChatGPT sign-in. It supplies bounded source snapshots, validates structured file
edits in an isolated worktree, runs tests independently and limits repair attempts.
Read-only and actual edit tasks were validated live using the plan allowance. The
implementation suite has 54 passing tests; a generated empty-document test produced
55 passing tests in its retained demonstration worktree. No automatic merge or push.

Next: review the generated change, build the ten-task reference evaluation suite, and
choose a no-separate-API-cost inference path for Study itself. The development
coordinator is not a Study model adapter and does not add Claude access automatically.
The original Sprint 02 acceptance criteria below remain a roadmap, not a completion claim.

Project Horizon is primarily agent reliability research, not just a tutoring app. Review the current README and tests, and review the separate detailed Project Horizon strategy and engineering briefs if provided. **Study defaults to a deterministic mock; the separate development coordinator has been tested with real subscription-based Codex.**

Goal of Sprint 02: implement a genuine small study agent that uses an LLM to decide when to search/read evidence and when to finish, not merely a fixed script. Preserve bounded tool execution and detailed event tracing. Use a provider-independent model adapter, a deterministic test adapter for free CI tests, and an optional real provider that only activates when explicitly configured. Never make API calls by default; disclose potential cost. Provide commands, tests, known limitations and a reproducible 10-task evaluation example.

Acceptance criteria:
1. A model genuinely selects among allowlisted tools `search_sources`, `read_passage`, `finish_answer`.
2. Maximum action steps, timeouts, token budget, and safe tool argument validation are enforced by the controller.
3. Sources are referenced by stable IDs, with automated ID checks; distinguish that from semantic factual verification.
4. JSONL traces contain timestamps, action names, tool outcomes, fault injection identifiers, validation flags, and duration; no secrets, hidden reasoning, or student personal data.
5. One known erroneous citation is detected; an agent can attempt correction; final outcome is independently checked.
6. A deterministic test path passes without API keys.
7. Avoid unnecessary app UI, complex orchestration, fine-tuning, NeMo installation, or database setup in this sprint.
8. Propose—but do not implement without approval—how to adopt NVIDIA NeMo and how to measure recovery probability and cost-aware selective intervention.

Do not use "accuracy", "precision" or "recovery probability" as metrics unless operational definitions and validated labels exist. Include test counts and honest failure analysis.

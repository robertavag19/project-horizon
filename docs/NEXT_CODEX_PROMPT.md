# Codex / Claude next-step handoff

**Implementation update:** the bounded controller, mock provider, and opt-in OpenAI
Responses adapter are now implemented. Live API behavior has not yet been tested.
Next: obtain explicit paid-call approval, set a key locally, inspect one live trace,
then create the ten-task reference evaluation suite. Follow the current README; the
original acceptance criteria below remain the roadmap, not a completion claim.

Project Horizon is primarily agent reliability research, not just a tutoring app. Review the current README and tests, and review the separate detailed Project Horizon strategy and engineering briefs if provided. **This repository is only a deterministic trace-testing baseline, not a real AI agent.**

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

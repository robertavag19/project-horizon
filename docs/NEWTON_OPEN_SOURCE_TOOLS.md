# Open-source tools for Newton — reviewed 2026-10-28

## Adopted now: Py-FSRS 6.3.2

Source: https://github.com/open-spaced-repetition/py-fsrs
Pinned release: https://github.com/open-spaced-repetition/py-fsrs/releases/tag/v6.3.2
Licence: MIT (https://github.com/open-spaced-repetition/py-fsrs/blob/v6.3.2/LICENSE).
Upstream code is installed as a package, not copied into this repository. Its distribution includes its licence. Preserve upstream notices if redistributing packages.

Why it fits: Newton previously offered fixed review intervals. FSRS updates per-card review scheduling from recall ratings and prior review state. It runs locally, needs no API key, downloads no model weights, and uses no model invocations. This adds a study capability without replacing the existing controller.

Installed in the original project's .venv: fsrs==6.3.2 and typing-extensions==4.16.0. Requirements are pinned in requirements-study.txt and the optional study dependency group. No global Python packages were changed. Optimizer extras and training packages were not installed.

## Use it

Stop an old Newton server, then start this Python environment in PowerShell/Dockterms:

~~~powershell
cd "C:\Users\rober\Desktop\Ai agent\Horizon_Sprint_01"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m newton.api --mode mock --port 0
~~~

Open the printed private link. In Study tools > Study profile, select the existing learner, change **Flashcard schedule (local)** to **FSRS**, and save. Load an original starter deck if necessary, preview/accept it, then rate a card. Its next due date and FSRS state are saved locally. This works in mock mode with zero AI calls.

The previous simple schedule remains the default. Old profiles load with that default. Selecting FSRS does not rewrite existing due dates or replay old ratings: the new scheduler takes effect on the next rating. FSRS starts fresh for cards without FSRS state. Switching to simple clears FSRS state when that card is next rated; switching back begins a new state. Review history remains recorded. Editing a card clears its schedule state, invalidates verification and deactivates its deck for review.

FSRS uses its default parameters and a 0.9 target retention with random interval fuzzing disabled for reproducibility. Target retention is a scheduler setting, not a measured mastery or factual-accuracy percentage. Ratings remain self-reported recall, not independent grading. No learner-specific optimizer has been run. Other FSRS versions are rejected until tested. Missing packages produce a clear error without changing the saved review or silently switching algorithms.

Scheduling state is local and is excluded from exported portable decks and model context. The existing local profile export intentionally includes progress. No external account or telemetry is added by this integration.

For a fresh checkout:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-study.txt
~~~

The new environment includes the scheduler, not every optional document parser. To read PDFs in that environment, install the existing documents dependency separately (pypdf); text sources, original lessons and flashcards do not require it. This integration does not add OCR.

## Other candidates and the decision

| Tool | Where it helps | Decision for Newton |
| --- | --- | --- |
| Docling — https://github.com/docling-project/docling | Structured document conversion, PDF layouts/tables and OCR | Strong candidate for importing books later. Needs a separate small prototype to measure dependencies, local processing time, extraction accuracy and model-asset requirements. Not installed or used. Keep file approval, excerpt limits and page locators. |
| Pydantic AI — https://github.com/pydantic/pydantic-ai | Typed model outputs, tools and provider integrations | Potential future controller library. Newton already has structured contracts and subscription CLI adapters; replacing them now would require a compatibility layer and explicit preservation of one-call budgets and billing/authentication constraints. Not installed. |
| LangGraph — https://github.com/langchain-ai/langgraph | Persistent workflow state, durable execution and human oversight | Useful if Newton later needs resumable multi-step workflows. Current bounded single-step operation does not justify a migration. Automatic workflow continuation must remain opt-in. Not installed. |
| Rank-BM25 — https://github.com/dorianbrown/rank_bm25 | Local keyword document ranking without paid embeddings | Candidate once the source library is larger. Compare retrieval fixtures against Newton's existing bounded lexical search first; adding a dependency alone does not prove better answers. Not installed. |

These are different layers, not interchangeable complete agents. Open-source software does not itself include free hosted inference or turn a web-chat subscription into a general API. Provider connection choices must continue to use their supported authentication and billing paths.

The next useful experiment is a small Docling book-import prototype using one explicitly selected public or permitted PDF, with no live AI workers. Preserve the existing reader until a comparison demonstrates better extraction. Do not automatically add all frameworks, scrape private chatbot sessions, or run arbitrary repository setup scripts.

## Verification

Focused tests cover actual upstream FSRS output, persistence across store reload, deterministic scheduling, default migration, missing/wrong dependency handling, edit reset, portable export, timezone validation and backdated-review rejection. The unchanged controller is still the only live-worker gateway.

Run:

~~~powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_study_schedule.py -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m pip check
node --check newton/web/study.js
~~~

No live worker, paid API, model training or background agent was used during this integration. Browser testing of the new dropdown remains a manual check; syntax and local scheduling behavior are tested offline.

Validation on 2026-10-28: 229 tests ran in 235.559 seconds; OK, 4 skipped (225 passed). The fresh scheduler environment omits the optional PDF parser, so PDF-dependent checks are among the skips. All six scheduler tests passed using actual fsrs 6.3.2. JavaScript syntax, dependency consistency (pip check) and git diff --check passed. No live AI workers ran. The new profile dropdown has not had a browser walkthrough in this change.

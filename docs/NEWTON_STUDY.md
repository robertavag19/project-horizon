# Newton Study: first educational release

This is a local educational prototype, not a qualified teacher, complete Canadian curriculum, or trained model. General development remains available. Study preferences and retrieved references guide the existing provider; uploading a book does not train it.

## Start and try it without model usage

In PowerShell or Dockterms (not at the Newton> prompt):

~~~powershell
cd "C:\Users\rober\Desktop\Ai agent\Horizon_Sprint_01"
$env:PYTHONPATH = "src"
python -m newton.api --mode mock --port 0
~~~

Open the private local link printed by the server. Keep that link private. Restart an old server to load the new Python code, then refresh its browser tab. The app remains loopback-only with its existing token/origin checks.

1. Open **Study tools**, enter an optional nickname, choose **Use Ontario SPH3U 2008 pilot**, then **Create learner**.
2. In **Explain**, click **Load original starter lesson**. This loads explicitly labelled original fixtures, not an AI answer.
3. Inspect the lesson's source buttons and **What was checked?** details.
4. In **Visualize**, move motion sliders and the circular-motion angle slider. Values, tables and vectors update locally. Reduced motion defaults on; playback is optional.
5. In **Flashcards**, reveal answers, edit a card, accept the draft, then use Again/Hard/Good/Easy.
6. In **Practise**, try 5 m/s for +20 m over 4 s. Try an incorrect unit and compare feedback. Open responses are saved ungraded with a rubric.
7. In **Progress**, inspect attempts and self-ratings. They are not mastery estimates.
8. Reload the app and select the same learner to resume. Local study data persists independently of the conversation.
9. Confirm the invocation count stays unchanged for all these actions.

Generation is disabled in mock mode. Do not expect mock chat to answer arbitrary questions.

## Live generation, only when explicitly authorized

Stop the mock server with Ctrl+C and launch:

~~~powershell
python -m newton.api --mode codex --port 0
~~~

Create/resume a session, inspect its budget, and use **Live work** or **Enable live work** beside a blocked message. Approval never automatically resends a blocked message. Personal-file approval remains separate. Choose the same saved study profile.

Use **Explain**, **Flashcards**, or **Practise**, enter a topic and select **Generate with Newton**. Each explicit generation action has a maximum of one live invocation. Cards default to five, maximum ten. Examples:
- Explain average velocity using +20 m in 4 s.
- Make five flashcards from this lesson.
- Test my understanding of velocity-time graphs.
- Give me a hint, not the full answer.

Ordinary conversational explanations remain supported. Explicit study generation returns structured saved artifacts. The model may ask a necessary clarification rather than return an artifact; malformed or oversized output stops with a recoverable error, without retry.

Suggested first live evaluation: **one invocation maximum** for “Explain average velocity for +20 m displacement over 4 s, show a worked example with units, and cite the supplied velocity note.” Check the answer against 5 m/s, its actual source, assumptions, vocabulary preference and verification record. Do not run the other scenarios automatically. This live evaluation has NOT been performed during implementation.

Default session limit remains 50, maximum one invocation per message, historical usage preserved, fresh approval per launch and explicit confirmation for budget changes. No automatic retries, reviewers, parallel workers, background generation, provider/model fallback or API-key billing. One CLI invocation can contain multiple internal model calls: these limits are not an exact token, allowance-percentage or monetary cap.

## Terminal access

~~~powershell
python -m newton
~~~

Local commands: study help, study create NAME, study select ID, study ontario, study general, study profile, study demo, study sources velocity, study progress, study export, study reset confirm, study delete confirm.

An explicit live example is:
study ask explain Explain average velocity for +20 m over 4 s.

The CLI prints structured artifacts, formulas, tables, sources and verification details as a text fallback. To use sliders or review controls, start the local app in a separate terminal and select the same learner. Pasting python -m newton.api into Newton is detected locally and does not execute a shell or consume an invocation.

## Implemented scope and official references

Canada has provincial/territorial education systems; this release does not invent a national curriculum.
- CMEC overview: https://cmec.ca/299/Education-in-Canada-An-Overview/index.html
- Ontario curriculum portal: https://www.dcp.edu.gov.on.ca/en/curriculum/secondary-science/downloads
- Official reference PDF: https://www.edu.gov.on.ca/eng/curriculum/secondary/2009science11_12.pdf

Checked on 2026-10-26 against the **2008 revised** Ontario Grades 11–12 Science PDF: Grade 11 university-preparation Physics, SPH3U; selected expectations B2.1 (motion terminology), B2.2 (motion graphs), B3.1 (velocity/speed/acceleration) and C3.3 (qualitative Newton's laws).
The catalogue records authority, edition, source URL, document checksum, selected paraphrases and locators. Printed pages 184, 185 and 187 differ from zero-based PDF indexes 185, 186 and 188. This is a small reference mapping, not full-course accreditation or a guarantee of current adoption by every school.

Exact Ontario/course/version selection is required for these mappings. Other selections remain general practice/mapping pending. Circular motion is explicitly enrichment without an SPH3U alignment claim. English original mechanics notes are supplied; French and other-language teaching have not been evaluated. No independent teacher has reviewed the lesson material.

Official curriculum descriptions, original Newton notes, personal excerpts and generated drafts have distinct provenance. The PDF and copyrighted books are not redistributed in Git. “Locator exists” is not proof that the source supports every claim.

## Teaching, checking and review

Profiles specify province/course/version, subject, knowledge, goal, vocabulary, language, depth, hint preference and teacher/supervisor/concise style. Current instructions override preferences. Guidance requires direct answers when requested, assumptions, respectful correction, graduated hints and no learning-style or intelligence diagnoses. These are instructions, not a guarantee that every live response follows them.

Locally checked formulas: average velocity, average acceleration, net force for constant mass and centripetal acceleration. Supported units are explicitly enumerated in study_math.py. Inputs must be finite, dimensionally compatible and within bounds; positive elapsed time/radius/mass are required. Display uses six significant digits; grading compares full precision with 0.5% relative or 1e-8 absolute tolerance. Formula evaluation does not establish that a model chose the correct formula for its word problem.

Motion visuals use x=x0+v0*t+0.5*a*t*t and v=v0+a*t with 61 samples. Circular vectors are tangent/inward; fixed arrow lengths show direction rather than magnitude. Playback uses angular speed v/r and no model calls. Slider bounds, text/table alternatives and reduced-motion controls are included.

Every artifact separates structure, source-locator validity, numerical checks, curriculum mapping, human review and remaining uncertainty. Open-ended feedback is formative guidance, never an official grade. Requesting model feedback is a separate explicitly labelled invocation.

Decks have stable IDs/revisions, sources, objectives, draft acceptance, safe JSON import/export and CSV export. Ratings are self-reported recall. Simple fixed schedule: Again=10 minutes, Hard=1 day, Good=3 days, Easy=7 days, measured from the rating; it is not an optimized learning model. Edits invalidate checks and deactivate the deck until accepted again. Attempts are stored separately from question keys.

## Data and usage

Local study records live under runs/study (ignored by Git). They contain preferences, activities, selected private excerpts, attempts and self-ratings. Export, reset and delete are explicit local controls. Local profiles are not authenticated user accounts or encrypted storage.

Private import is explicit and bounded to up to three PDF pages or three text lines, with at most 3,000 characters per selected chunk. OCR is not implemented; scanned/no-text PDFs are reported honestly. Personal-source retrieval requires current file approval; revocation excludes these sources from future provider context and clears transient excerpts. Saved activities/excerpts remain local until reset/deleted.

Retrieval is deterministic lexical matching, not paid embeddings: up to three relevant chunks, normally 4,500 characters, with selected preferences and evidence bounded to 6,000 characters within the existing total context limit. Only actual included locators are accepted from generated artifacts. Explicit “this lesson” follow-ups carry relevant source references from the latest activity, not the entire chat history.

Only generation sends the question, bounded relevant excerpts and necessary preferences to the selected provider. Existing permitted project context can also be included within the shared bound. Personal books, complete learner histories and learner answers are not put into execution traces. Study reports carry IDs/status/counts; study response text is not kept as the conversation's last-reply memory. Study artifact storage intentionally retains its educational content.

## Architecture, compatibility and bounds

The existing controller remains the single worker gateway and permission/budget authority. StudyService is shared by CLI and API; StudyStore handles isolated local records and atomic writes. study_library retrieves sources; study_math checks calculations; study_contract validates artifacts. Trusted frontend templates render data as text/SVG, never execute model HTML/scripts or expression strings.

Base decision schema stays compatible. Only an explicit educational request selects education.schema.json and version-2 decisions with an education payload. The nested artifact schema is version 1. Model-generated study requests cannot edit source files or launch local tools. Saved conversation records receive an optional study_profile_id; no automatic curriculum/profile migration or budget increase occurs.

Implementation stages: inspect/baseline; profile/library/contracts; teaching/numeric checks; UI tools; offline evaluation/documentation. Existing coding edits/worktree validation and provider adapters are preserved.

Bounds: four blocks, 24,000 artifact characters, ten cards total, five practice questions total, six study-plan steps. Existing defaults remain 12,000 source-context characters, 1,800 reply characters, 90-second worker timeout and 180-second turn timeout unless the user's newton.toml explicitly overrides them. A long task can time out; a response exceeding bounds is rejected instead of silently truncated or retried. Portable imports must use the raw schema exported by Newton, not a saved profile record with internal fields.

Storage bounds: twenty profiles, twenty private sources/profile, fifty activities/profile, 200 recent attempts, 1,000 recent self-ratings and 2 MB/profile. These are prototype limits, not unlimited archiving. A stale .lock after process termination may require manual inspection before removal; do not remove a lock while Newton is writing.

## API for a separate app

Existing token authentication, origin checks and one-active-task guard apply.
- GET /api/sessions/{id}/study: profiles, selected profile, artifacts, progress and permitted source metadata.
- POST to the same route: {"action":"create","args":{"profile":{"nickname":"Learner"}}}.
- Local actions also include select, update_profile, demo, source, search, import_source, accept_deck, edit_card, review, attempt, export_deck, import_deck, export_profile, visualization, reset and delete. Reset/delete require confirm:true.
- POST /api/sessions/{id}/messages: existing text field plus optional study_action of explain, visualize, flashcards, practice or plan. This is the only study-generation path.
- Completed runs can include educational_artifact with a stable ID, origin, revision and validated bundle. Rendering verification must not treat source existence as factual certification.

Read study.py for exact argument fields; unknown fields are rejected. Reuse education.schema.json rather than designing incompatible client payloads. Current API remains local-only, not suitable for public multi-user hosting.

## Offline tests and educational evaluation

~~~powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -q
python -m newton.study_evaluate
node --check newton/web/study.js
node --check newton/web/study-math.js
~~~

The versioned education/evaluation-v1.json contains 26 development-authored scenarios. Ten have deterministic checks (six numerical goldens, four retrieval cases); sixteen are teaching/rubric scenarios requiring separate evaluation. No runtime worker generated and self-approved expected answers. All live-teaching results remain not_evaluated. Software tests are separate from educational-quality measurement.

Known limitations: small English mechanics content set, lexical rather than semantic retrieval, no OCR, no broad symbolic algebra, no complete provincial curricula, no validated French pilot, no adaptive mastery model, no live provider validation of rich artifacts, no independent expert review. Correct JSON and passing software tests cannot guarantee teaching accuracy.

## Extending the pilot

For another province/course, first inspect its official curriculum; add authority/course/version and expectation metadata with verified locators/checksums and permission status to the catalogue. Add an explicit matching rule and separation tests; do not relabel Ontario content. Keep unsupported choices marked pending until checked.

For another source, add licensed/original material and bounded chunks with stable IDs, provenance, language/version and locators; add retrieval fixtures. Personal books remain private imports outside Git. Review factual claims separately from citation checks.

For another visualization, add a strict schema variant, trusted Python equations and frontend renderer with matching bounds, units, text alternative and domain/geometry tests. Never accept arbitrary executable code from a model. Extending allowed artifact output must remain an explicit versioned change.


## Optional open-source scheduling

An opt-in FSRS scheduler is now available in the study profile. Simple intervals remain the default. See [open-source tool review and setup](NEWTON_OPEN_SOURCE_TOOLS.md) for the project virtual-environment launch command, scheduler migration behavior, dependency versions, limitations and other evaluated tools.

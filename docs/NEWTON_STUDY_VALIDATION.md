# Study release validation

Validation completed 2026-10-26 against the original Desktop project.

- Baseline: 191 tests run, OK, 2 skipped.
- Final suite: 223 tests run in 88.010 seconds, OK, 2 skipped (221 passed).
- The earlier PDF extraction regression was fixed; final suite includes it.
- JavaScript syntax checks passed for app.js, study.js and study-math.js.
- git diff --check passed.
- Versioned educational evaluation: 26 scenarios; all 10 deterministic calculation/retrieval checks passed. Sixteen teaching rubrics remain pending human/live evaluation.
- Browser mock walkthrough verified profile creation and Ontario selection, loading the original lesson, source details, keyboard slider interaction, accepting a deck, saving a recall rating, numerical practice feedback and saved progress. Invocation display remained 0/50.
- Browser progress showed one saved attempt and one self-rated review. A final screenshot could not be saved after the browser session expired.
- No live provider workers, paid model APIs, embeddings or training were used.

Software checks do not establish live teaching quality. The guide proposes one separately authorized live invocation as the next evaluation. At validation time, changes had not been committed or pushed; consult Git for the current publication status. Existing user changes were preserved.

Launch and manual test instructions: NEWTON_STUDY.md.

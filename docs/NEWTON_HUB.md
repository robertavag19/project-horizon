# Newton Hub

## Open Newton

Double-click **Newton.cmd on your Desktop**. It opens the local hub in your normal browser, using the project's virtual environment. No terminal commands, environment variables or slash commands are needed. Keep the project in its current location, or update the Desktop entry after moving it.

The hub home screen provides:
- Start Newton: resume the current/latest browser session, confirm its actual remaining budget once, then ask naturally.
- Study tools: profiles, lessons, diagrams, decks and practice.
- Run tests and Show changes: existing local project workflows, with zero model invocations.
- Activity: recent outcomes, failures, prevented calls, duration, reported token counts and available test results.
- Stop hub: close the server when no task is active and expire its approvals.

The project also contains **Newton Demo.cmd**, which opens mock mode. It uses a separate mock server and history; ordinary mock chat is not an LLM. Existing terminal/API entry points still work.

Opening the hub, local tools and reviewing Activity do not launch workers. Start Newton confirms the displayed used/total/remaining budget once for this launch; later normal messages can use that remaining allowance. Fresh server launches need fresh approval. Local-only entry points may initialize a session with live work off; they cannot authorize a worker. Starting live work preserves its saved usage. Personal-file access still requires its separate approval. Switching models/providers retains the existing explicit controls.

The launcher reuses an existing healthy hub for the same project/mode. It keeps an ignored local discovery file under runs/hub, including the private local token, to reopen the correct tab. It validates the project/mode/loopback address before reusing it. A known dead-process lock is reclaimed; an unresponsive live owner is left untouched. Launch errors create runs/hub/launcher-error.txt. Do not share discovery files or private local links. Closing a browser tab does not stop the hub; use Stop hub.

Fallback for diagnosing a launch issue:

~~~powershell
cd "C:\Users\rober\Desktop\Ai agent\Horizon_Sprint_01"
.\.venv\Scripts\python.exe -m newton.hub
~~~

For mock mode add --mode mock. For a diagnostic terminal without automatically opening a browser add --no-browser.

## What changed in workflow control

The hub is a simpler front end over Newton's existing controller. It reuses the existing coding workspace, tests, permissions and study tools. It is not a Dify installation or a drag-and-drop graph designer. Each request still completes one bounded step; it does not automatically execute a plan.

This removes repeated terminal setup and improves visibility. It does not promise faster provider inference or better factual accuracy from the same model. No paid APIs, provider fallback, extra reviewer agents, parallel workers or background model work were added. The 50-invocation default and one-invocation-per-message control remain. A CLI invocation can contain multiple internal model calls and cannot enforce an exact token or subscription-percentage cap.

## Observe Newton locally

Open **Activity**. The view retains the latest 500 recorded actions per mode and displays the newest 100. It persists across restart. Command-line-only runs from before the hub are not backfilled. Simple local study mutations are counted; moving a diagram slider or flipping a card remains a local UI operation and does not create a model call or individual trace.

Recorded metadata includes outcome category, safe status code, provider, duration, invocation delta, prevented delta, available usage counters and test summary. Timelines use the controller's recorded event names and step order; they are not hidden model reasoning or exact internal model-call spans. Mock test results remain explicitly simulated. Token usage can be unavailable; no subscription percentage, cost or fabricated model name is estimated.

No prompts, responses, learner names, book passages, filenames or file paths are copied into these activity records or Langfuse exports. Existing full task results and source-view controls remain in their existing local records. Activity recording failure is reported separately and must not replace a successful task result.

## Langfuse integration: connector ready, dashboard pending

Newton implements an explicit, metadata-only **local Langfuse** connection. No external Langfuse server has been started or verified: Docker Desktop is absent on this machine. The local Newton Activity view works independently now.

Langfuse's official local deployment requires Docker and Docker Compose:
https://langfuse.com/self-hosting/deployment/docker-compose

To complete the external dashboard:
1. Install and start Docker Desktop for Windows from its official source. Windows may request administrator approval, virtualization/WSL setup or a restart. This implementation did not change those system settings or accept installation terms.
2. Deploy the official Langfuse local Compose stack after reviewing its current instructions, generating the requested secrets and restricting exposed services to loopback for local use. Do not start its example with unchanged placeholder credentials or expose it to the public network.
3. Open the local Langfuse dashboard, create a local organization/project, and obtain its project public and secret keys. These authenticate tracing; they are not LLM API billing keys.
4. In Newton > Activity > Connect local Langfuse, enter its loopback URL and those project keys. Save locally. Never paste keys into Newton chat or commit them.
5. Choose a specific completed record and click **Send metadata to local Langfuse**. No automatic export, retry or task replay occurs. Check the corresponding trace in Langfuse to verify ingestion end to end.

The connector accepts only http://127.0.0.1:PORT or http://localhost:PORT (normalized to literal loopback). Hosted endpoints, custom paths, redirects and non-loopback destinations are rejected. This first implementation intentionally has no hosted export or external telemetry. Connection credentials are stored under ignored runs/hub/langfuse.json, readable by the local OS account; they are not encrypted by Newton. Disconnect removes this local connection file without deleting remote traces or activity history.

Export uses the supported OTLP HTTP/JSON endpoint /api/public/otel/v1/traces, Basic project-key authentication and x-langfuse-ingestion-version:4. It does not use the deprecated legacy ingestion endpoint. Parent/child IDs are deterministic from a run ID. The root is a request span; a live CLI invocation adds a generation observation with available input/output tokens. Its timing is explicitly labelled as coarse request boundaries, not exact model-only latency. Event observations preserve sequence, not precise phase duration. Cached token counts remain metadata and are not double-counted into the standard usage fields. No model is fabricated for automatic cost estimation.

Reference: https://langfuse.com/integrations/native/opentelemetry

HTTP acceptance is reported as accepted_by_collector, not proof of dashboard visibility. A malformed response, rejected/partial batch, unavailable collector or timeout produces a local error and leaves task results/history intact. Exports do not follow redirects or make automatic retries. The implementation uses the public OpenTelemetry contract directly, avoiding an SDK's global automatic capture and new runtime dependencies.

## Development and verification

New files: newton/hub.py (launcher), newton/observability.py (local journal and exporter), newton/web/hub.js and hub.css (controls), Desktop/project launch entries, and tests/test_newton_hub.py. The API gains authenticated GET/POST /api/hub and confirmed POST /api/hub/stop; all existing origin, token, path and single-task controls remain.

API actions: open_local, start, configure_langfuse, disconnect_langfuse, export. Starting live work checks the confirmed budget against current state. An optional session_id keeps the selected conversation rather than switching to an older loaded one. No endpoint can launch a worker merely by opening a view or changing tracing configuration.

Validation on 2026-10-28:
- Full offline suite after the main integration: 241 tests run in 89.374 seconds; OK, 4 skipped (optional PDF/environment checks included among skips).
- After the selected-session fix: all 13 focused hub tests passed in 5.216 seconds.
- Existing API suite: 13 passed. JavaScript syntax and git diff --check passed.
- Browser mock walkthrough: Home -> conversation -> simulated task -> Activity, displaying one simulated record and 0/50 live invocations; local Langfuse setup clearly reports missing Docker.
- Repeated launcher invocation reused the already-running mock instance.
- Actual local HTTP test collector verified OTLP payload, parent/child IDs, usage fields, authentication/version headers, partial-error handling and no redirect/retry. This collector is a test fixture, not a real Langfuse deployment.
- No live AI worker or paid model API was used. External Langfuse end-to-end dashboard verification remains pending Docker deployment and local project credentials.

Run offline checks:

~~~powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_newton_hub.py -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
node --check newton/web/hub.js
~~~

At validation time, changes were local and uncommitted; consult Git for the current publication status. No system-wide packages, Docker installation, hosted telemetry or model billing changes were made.

The hub environment also retains the existing pypdf 6.21.1 parser (installed from the cached official package). Its 15 focused file/PDF-access tests passed, with 1 Windows privilege skip. This avoids losing PDF support when moving from the older global Python launch to the new project launcher.

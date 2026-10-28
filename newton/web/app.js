'use strict';
const $ = id => document.getElementById(id);
let token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('newton-token') || '';
if (token) sessionStorage.setItem('newton-token', token);
if (location.hash) history.replaceState(null, '', location.pathname);
let session = null, info = null, busy = false, currentRun = null;
const doneRuns = new Set();
function notice(text, error = false) { $('notice').textContent = text; $('notice').classList.toggle('error', error); }
async function api(path, body) {
  const response = await fetch('/api' + path, {method: body === undefined ? 'GET' : 'POST', headers: {'Authorization': 'Bearer ' + token, ...(body === undefined ? {} : {'Content-Type': 'application/json'})}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error === 'local_token_required' ? 'Open the private browser link printed by the server to connect.' : data.error.replaceAll('_', ' '));
  return data;
}
function controls() {
  $('message').disabled = !session || busy;
  $('send').disabled = !session || busy;
  for (const id of ['tests', 'changes', 'help', 'add-budget', 'new-session']) $(id).disabled = busy || (!session && id !== 'new-session');
  $('demo').disabled = !session || busy || info?.mode !== 'mock';
  $('files-permission').disabled = !session || busy;
  $('live-permission').disabled = !session || busy || info?.mode !== 'codex';
  for (const id of ['response-style', 'save-preferences']) $(id).disabled = !session || busy;
  for (const id of ['provider', 'model']) $(id).disabled = !session || busy || info?.mode === 'mock';
}
function message(role, text) {
  $('welcome')?.remove();
  const card = document.createElement('div'); card.className = 'message ' + role;
  const label = document.createElement('span'); label.className = 'message-label'; label.textContent = role === 'user' ? 'YOU' : 'NEWTON';
  card.append(label, document.createTextNode(text)); $('messages').append(card); $('messages').scrollTop = $('messages').scrollHeight;
}
function progress(status, detail = '') {
  $('task-status').textContent = status; $('task-detail').textContent = detail;
  $('task-dot').className = 'status-dot ' + (busy ? 'running' : status.toLowerCase().includes('fail') ? 'failed' : currentRun ? 'done' : '');
}
function renderSession(value) {
  session = value; sessionStorage.setItem('newton-session', value.session_id);
  $('session-name').textContent = 'Session · ' + value.session_id.slice(0, 12);
  $('budget').textContent = `${value.budget.live_used} / ${value.budget.live_limit}`;
  $('budget-detail').textContent = `${value.budget.live_remaining} slots remaining · ${value.budget.prevented_invocations || 0} prevented before launch${value.mode === 'mock' ? ' · no live calls' : ''}`;
  $('files-permission').checked = value.permissions.personal_files;
  $('live-permission').checked = value.permissions.live_work;
  $('workspace').textContent = value.workspace;
  $('provider').value = value.provider; $('model').value = value.model; $('response-style').value = value.response_style;
  $('mode').textContent = value.mode === 'mock' ? 'MOCK · NO MODEL CALLS' : value.provider.toUpperCase() + ' · ' + value.response_style.toUpperCase();
  connectionStatus();
  if (window.NewtonStudy) window.NewtonStudy.refresh();
  if(window.NewtonHub)window.NewtonHub.refresh();
  $('plan').replaceChildren();
  if (!value.plan.length) $('plan').textContent = 'No active plan.';
  for (const step of value.plan) { const item = document.createElement('div'); item.className = 'plan-step'; item.textContent = `${step.description} · ${step.state}`; $('plan').append(item); }
  controls();
}
async function refresh() { if (session) renderSession(await api('/sessions/' + session.session_id)); }
function results(result) {
  if (result.status === 'approval_required') {
    const b = document.createElement('button'); b.className = 'primary approval-action'; b.textContent = 'Enable live work';
    b.disabled = info.mode === 'mock';
    b.addEventListener('click', () => { $('live-permission').checked = true; permission('live_work', $('live-permission')); });
    $('messages').append(b);
  }
  if (result.educational_artifact) {
    const b = document.createElement('button'); b.className = 'secondary'; b.textContent = 'Open saved study activity';
    b.addEventListener('click', () => window.NewtonStudy.open('explain')); $('messages').append(b);
  }
  $('tool-results').replaceChildren();
  if (!(result.tool_results || []).length) $('tool-results').textContent = 'No local tool results in this task.';
  for (const item of result.tool_results || []) {
    const button = document.createElement('button'); button.className = 'file-link'; button.textContent = item.name + ' · view collected evidence';
    button.addEventListener('click', () => view('Local evidence · ' + item.name, JSON.stringify(item.result, null, 2))); $('tool-results').append(button);
  }
  $('files').replaceChildren();
  const names = result.changed_files || [];
  if (!names.length) $('files').textContent = 'No files changed in this task.';
  for (const name of names) {
    const button = document.createElement('button'); button.className = 'file-link'; button.textContent = (result.simulated ? 'DEMO · ' : '') + name;
    button.addEventListener('click', async () => { try { const data = await api(`/sessions/${session.session_id}/files?path=${encodeURIComponent(name)}`); view(name, (data.simulated ? 'SIMULATED FILE — not written to disk\n\n' : '') + data.text + (data.truncated ? '\n\n[Excerpt only]' : '')); } catch (error) { notice(error.message, true); } });
    $('files').append(button);
  }
  $('test-results').replaceChildren();
  if (!result.verification) $('test-results').textContent = 'No checks in this task.';
  else {
    const check = result.verification, card = document.createElement('div'); card.className = 'test-card' + (check.tests_passed ? '' : ' failed');
    card.textContent = `${check.tests_run} tests · ${check.tests_passed ? 'passed' : 'not passed'}`;
    const label = document.createElement('small'); label.textContent = check.simulated ? 'Simulated results · not executed' : 'Executed locally · not proof of overall correctness'; card.append(label); $('test-results').append(card);
  }
}
function view(title, text) { $('viewer-title').textContent = title; $('viewer-content').textContent = text; $('viewer').showModal(); }
async function poll(identity) {
  currentRun = identity; busy = true; controls(); $('trace').disabled = false;
  try {
    while (true) {
      const run = await api('/runs/' + identity);
      progress(run.status === 'queued' ? 'Task accepted' : run.status === 'running' ? 'Working on your request' : 'Task finished', `Run ${identity.slice(0, 10)} · ${info.mode === 'mock' ? 'mock mode' : 'at most one live invocation'}`);
      if (['completed', 'failed'].includes(run.status)) {
        busy = false;
        if (run.result) {
          results(run.result);
          if (!doneRuns.has(identity)) message('assistant', run.result.reply);
          const resultStatus = run.result.status;
          progress(resultStatus.replaceAll('_', ' '), run.result.simulated ? 'Demonstration only · no source files written' : 'Review the current files and test results');
          if (resultStatus === 'approval_required') notice('Live work is off. Use the Live work switch to approve this session, then send your task again.');
          else if (resultStatus === 'budget_exhausted') notice('No invocation slots remain. Add slots explicitly to continue.');
          else if (resultStatus === 'budget_approval_required') notice('Use “Add 10 slots” to confirm a budget change without a model call.');
        } else { progress('Task failed', run.error); if (!doneRuns.has(identity)) message('assistant', 'Task stopped: ' + run.error + '. No automatic retry.'); }
        if(run.observability_error)notice('Task finished, but local activity recording failed. Task results are still available.',true);
        doneRuns.add(identity); await refresh(); controls(); return;
      }
      await new Promise(resolve => setTimeout(resolve, 650)); // Read-only progress checks; never resubmit a message.
    }
  } catch (error) { busy = false; controls(); notice(error.message + '. The task may still be running; refresh to check. Your message was not automatically resubmitted.', true); }
}
async function send(text, studyAction = null) {
  if (!session || busy || !text.trim()) return;
  busy = true; controls(); message('user', text); $('message').value = ''; progress('Starting your task', 'No automatic retries');
  try { const run = await api(`/sessions/${session.session_id}/messages`, {message: text, read_only: false, ...(studyAction ? {study_action: studyAction} : {})}); await poll(run.run_id); }
  catch (error) { busy = false; controls(); notice(error.message + '. No automatic resubmission.', true); }
}
async function createSession() {
  if (info.mode === 'codex' && !confirm('Start a new session with a total budget of ' + info.limits.default_session_budget + ' live invocations? Live work will still be off until approved.')) return;
  try {
    renderSession(await api('/sessions', {confirm_new_budget: info.mode === 'codex'}));
    $('messages').replaceChildren(); $('files').textContent = 'No files changed in this session.'; $('test-results').textContent = 'No checks in this session.';
    currentRun = null; $('trace').disabled = true; progress('Ready when you are', 'New session · permissions are off');
    message('assistant', info.mode === 'mock' ? 'You’re in mock mode. Try a mock task to preview file links, test results and traces without changing source files or calling a model. Local commands such as help and run tests still work.' : 'Session created. Approve Live work to ask Newton a question. Personal-file access has a separate approval.');
  } catch (error) { notice(error.message, true); }
}
async function permission(kind, checkbox) {
  const allow = checkbox.checked;
  const text = kind === 'personal_files' ? `Allow Newton to read and search ${session.permissions.personal_root} for this server session? Selected excerpts may be sent to ${session.provider} when answering. This does not authorize editing personal files.` : `Authorize ${session.provider} (${session.model || 'CLI default'}) for this session: ${session.budget.live_remaining} remaining of ${session.budget.live_limit} total invocations, at most one per message, with no automatic retries? This is not an exact token or subscription-percentage cap. Disable paid overage/usage credits in your provider account first; Newton cannot verify all account-level billing settings.`;
  if (allow && !confirm(text)) { checkbox.checked = false; return; }
  try { renderSession(await api(`/sessions/${session.session_id}/approvals`, {kind, allow})); notice(kind === 'personal_files' ? (allow ? 'Personal file reading approved. No scan has started.' : 'Personal file access revoked; selected excerpts cleared.') : (allow ? 'Live work approved for this session. No worker has started yet.' : 'Live work disabled.')); }
  catch (error) { checkbox.checked = !allow; notice(error.message, true); }
}
function connectionStatus() {
  const provider = info?.providers?.find(item => item.id === $('provider').value);
  $('provider-status').textContent = provider ? `${provider.installed ? 'Installed; sign-in checked before live work.' : 'Setup required.'} ${provider.account}. Sign in locally: ${provider.login}${provider.id === 'gemini' ? '. Select a specific model; automatic routing is not allowed.' : ''}` : 'Mock mode never calls a model.';
}
$('provider').addEventListener('change', () => { $('model').value = ''; connectionStatus(); });
$('save-preferences').addEventListener('click', async () => {
  if (!session || busy) return;
  const provider = $('provider').value, model = $('model').value.trim(), response_style = $('response-style').value;
  const changed = provider !== session.provider || model !== session.model;
  if (changed && !confirm(`Switch to ${provider} (${model || 'CLI default'})? Your usage counter is preserved. Future messages and bounded task context will go to this provider. Live-work and personal-file approvals will be cleared. No model starts now. Provider account limits and any account-level charges remain your responsibility.`)) { renderSession(session); return; }
  try {
    renderSession(await api(`/sessions/${session.session_id}/preferences`, {provider, model, response_style, confirm_provider_change: changed}));
    notice(changed ? 'Connection saved. Approve Live work before your next question. Sign in to this provider locally if needed.' : 'Response style saved locally; no model call used.');
  } catch (error) { notice(error.message, true); }
});
$('composer').addEventListener('submit', event => { event.preventDefault(); send($('message').value); });
$('message').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(event.target.value); } });
$('new-session').addEventListener('click', createSession);
$('demo').addEventListener('click', () => send('demo'));
$('tests').addEventListener('click', () => send('run tests'));
$('changes').addEventListener('click', () => send('show changes'));
$('help').addEventListener('click', () => send('help'));
$('files-permission').addEventListener('change', () => permission('personal_files', $('files-permission')));
$('live-permission').addEventListener('change', () => permission('live_work', $('live-permission')));
$('add-budget').addEventListener('click', async () => { if (!session || !confirm('Add 10 available invocation slots? No worker starts now.')) return; try { renderSession(await api(`/sessions/${session.session_id}/approvals`, {kind: 'budget', allow: true, command: 'add budget 10'})); notice('Budget increased. No model was called.'); } catch (error) { notice(error.message, true); } });
$('trace').addEventListener('click', async () => { if (!currentRun) return; try { const trace = await api('/runs/' + currentRun + '/trace'); view(trace.simulated ? 'Simulated execution trace' : 'Execution trace', JSON.stringify(trace.events, null, 2)); } catch (error) { notice(error.message, true); } });
$('close-viewer').addEventListener('click', () => $('viewer').close());
(async () => {
  try {
    info = await api('/info'); $('mode').textContent = info.mode === 'mock' ? 'MOCK · NO MODEL CALLS' : 'CODEX · APPROVAL REQUIRED';
    $('project-root').textContent = info.project_root;
    $('live-description').textContent = info.mode === 'mock' ? 'Unavailable in mock mode' : 'One approval for this server session';
    notice(info.mode === 'mock' ? 'Mock mode: no model calls. Demo files and checks are simulated; local commands can run real checks.' : 'Live work and personal-file reading are both off until you approve them.');
    if(window.NewtonHub)window.NewtonHub.refresh();
    const saved = sessionStorage.getItem('newton-session');
    const identity = info.sessions.includes(saved) ? saved : info.sessions[0];
    if (identity) { renderSession(await api('/sessions/' + identity)); if (session.active_job || session.last_job) await poll(session.active_job || session.last_job); }
    else if (info.mode === 'mock') await createSession();
    else { controls(); notice('Select New session to begin. No worker has started.'); }
  } catch (error) { notice(error.message, true); controls(); }
})();

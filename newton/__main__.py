"""Natural conversation entry point; deterministic commands never contact a model."""
from argparse import ArgumentParser
from dataclasses import replace
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))

from devtools.workers import WorkerError
from devtools.coordinator import git
from .conversation import ConversationSession
from .profile import load_profile
from .providers import AccountWorker, PROVIDERS
from .teaching import STYLES
from .worker import ConversationWorker, ConversationMock


def show(result, debug=False):
    if debug:
        print(json.dumps(result, indent=2))
        return
    print('\nNewton: ' + result['reply'])
    print('Result: ' + result['status'])
    if result.get('changed_files'):
        print('Changed: ' + ', '.join(result['changed_files']))
    if result.get('verification'):
        checked = result['verification']
        print(f"Checks: {checked['tests_run']} tests; passed={checked['tests_passed']}.")
    if result.get('verification_output'):
        print(result['verification_output'])
    if result.get('acceptance_checks'):
        for check in result['acceptance_checks']:
            print(f"Acceptance {check['id']}: {check['verdict']} ({check['provenance']}).")
    for item in result.get('tool_results', []):
        print(item['name'] + ': ' + json.dumps(item['result'], indent=2))
    if result.get('educational_artifact'):
        artifact = result['educational_artifact']
        print('Study artifact: ' + artifact['id'])
        for block in artifact['bundle']['blocks']:
            print(block['type'] + ': ' + block['title'])
            print(json.dumps(block, ensure_ascii=False, indent=2))
        print('Open the local app and select the same study profile to review cards and interact with visuals.')
    if result.get('workspace'):
        print('Workspace: ' + result['workspace'])
    budget = result['budget']
    print(f"Economy: {budget['live_used']}/{budget['live_limit']} live invocations used; {budget['live_remaining']} remaining. No automatic retries.")
    print('Prevented before launch: ' + str(budget.get('prevented_invocations', 0)) + ' requests (not charged to this counter).')
    if result.get('report_file'):
        print('Details: ' + result['report_file'])


def approve_launch(session):
    if session.profile.worker == 'mock':
        return False
    print('Connection: ' + session.profile.worker + '; model: ' + (session.profile.model or 'CLI default'))
    print('Only the selected account login is allowed; no API-key fallback. Disable paid overage/usage credits in the provider account before authorizing live work. Newton cannot verify all account-level billing settings.')
    budget = session.budget()
    if budget['live_limit'] < session.profile.max_live_invocations:
        print(f"Saved budget: {budget['live_used']} used, {budget['live_limit']} total, {budget['live_remaining']} remaining.")
        answer = input(f'Migrate this saved session to a total limit of {session.profile.max_live_invocations}, preserving usage [y/N]? ')
        if answer.lower().strip() == 'y':
            show(session.respond(f'set budget {session.profile.max_live_invocations}', approve_budget=True))
    budget = session.budget()
    print(f"Launch budget: {budget['live_used']} used, {budget['live_limit']} total, {budget['live_remaining']} remaining; at most 1 invocation per message; no retries.")
    answer = input('Authorize live work within this budget for this launch [y/N]? ')
    approved = answer.lower().strip() == 'y'
    if not approved:
        print('Local-only mode for this launch. Restart Newton to authorize live work.')
    return approved


def approve_files(session):
    session.personal_files.revoke()
    session.pending_context = []
    print('Personal file access: ' + str(session.personal_files.root))
    print('Read/search only for this launch. Selected excerpts may be sent to the selected provider when answering. Credential folders, AppData and links are excluded. No scanning starts now.')
    answer = input('Do you want to allow Newton to access your personal files for this launch [y/N]? ')
    session.personal_files.approved = answer.lower().strip() == 'y'
    print('Personal file reading ' + ('enabled.' if session.personal_files.approved else 'disabled. Project tools still work.'))
    return session.personal_files.approved


def main():
    parser = ArgumentParser(description='Newton technical teacher and supervisor: account-based CLI connections')
    parser.add_argument('--task')
    parser.add_argument('--resume', nargs='?', const='latest')
    parser.add_argument('--new-session', action='store_true')
    parser.add_argument('--doctor', action='store_true')
    parser.add_argument('--read-only', action='store_true')
    parser.add_argument('--mock', action='store_true')
    parser.add_argument('--provider', choices=tuple(PROVIDERS))
    parser.add_argument('--model', help='explicit model identifier; omitted keeps the saved choice')
    parser.add_argument('--style', choices=tuple(STYLES))
    parser.add_argument('--approve-live', action='store_true', help='authorize at most one worker invocation for --task')
    parser.add_argument('--worker-timeout', type=int, default=None)
    parser.add_argument('--turn-timeout', type=int)
    parser.add_argument('--context-chars', type=int)
    parser.add_argument('--reply-chars', type=int)
    parser.add_argument('--json', action='store_true', help='show detailed local diagnostic output')
    args = parser.parse_args()
    if args.new_session and args.resume:
        parser.error('choose --new-session or --resume')
    if args.approve_live and not args.task:
        parser.error('--approve-live applies only to a single --task, never a whole interactive session')
    if args.mock and (args.provider or args.model):
        parser.error('mock mode cannot select a live provider or model')
    project_root = PROJECT
    try:
        profile = load_profile(project_root)
        if args.worker_timeout is not None:
            if not 1 <= args.worker_timeout <= 600:
                parser.error('Economy worker-timeout must be between 1 and 600 seconds')
            profile = replace(profile, worker_timeout=args.worker_timeout)
        overrides = {name: getattr(args, name) for name in ('turn_timeout', 'context_chars', 'reply_chars') if getattr(args, name) is not None}
        if overrides:
            profile = replace(profile, **overrides)
        if args.mock:
            profile = replace(profile, worker='mock')
        if args.provider:
            profile = replace(profile, worker=args.provider, model=args.model or '')
        elif args.model is not None:
            profile = replace(profile, model=args.model)
        if args.style:
            profile = replace(profile, response_style=args.style)
        if args.doctor:
            worker = (ConversationMock() if profile.worker == 'mock' else
                      ConversationWorker(timeout=profile.worker_timeout, model=profile.model) if profile.worker == 'codex' else
                      AccountWorker(profile.worker, timeout=profile.worker_timeout, model=profile.model))
            print(json.dumps({'agent': profile.name, 'mode': 'economy', 'worker': profile.worker,
                              **worker.preflight(PROJECT)}, indent=2))
            return
        session_id = args.resume or (None if args.new_session else ConversationSession.latest_id(project_root))
        session = ConversationSession(project_root, profile, session_id=session_id)
        if args.provider or args.model is not None:
            session.configure_provider(args.provider or session.profile.worker, args.model if args.model is not None else ('' if args.provider else session.profile.model))
        if args.style:
            session.respond('style ' + args.style)
        profile = session.profile
        print(f'{profile.name} | Economy | {profile.worker} | {profile.response_style} | {project_root}')
        print('Model: ' + (profile.model or 'selected CLI default'))
        print('At most 1 live worker invocation per message; session budget ' + str(session.state['live_limit']) + '.')
        print('One invocation may contain internal model calls. There is no hard token or subscription-percentage cap.')
        if args.task:
            print('This task budget: at most 1 live invocation; 0 automatic retries.')
            result = session.respond(args.task, approve_live=args.approve_live, force_read_only=args.read_only)
            show(result, args.json)
            if result['status'] in ('approval_required', 'budget_exhausted'):
                print('Use interactive mode to approve one task, or --task "..." --approve-live.')
                raise SystemExit(2)
            if result['status'] not in ('local', 'answered', 'planned', 'clarification_required', 'changes_tested_review_required', 'tool_results_ready', 'study_artifact_saved', 'shell_command_in_chat', 'exit'):
                raise SystemExit(1)
            return
        launch_approved = approve_launch(session)
        if profile.worker != 'mock':
            approve_files(session)
        print('Talk naturally. Local/free: help, status, run tests, list files, show changes, show plan, quit.')
        print('Progress resumes automatically. Raw conversation is not replayed; a bounded summary is saved locally.')
        while True:
            try:
                message = input(f'{profile.name}> ').strip()
                if not message:
                    continue
                if message.lower().strip() == 'enable files':
                    approve_files(session)
                    continue
                if message.lower().startswith('style '):
                    show(session.respond(message), args.json)
                    profile = session.profile
                    continue
                if message.lower().startswith('use project '):
                    target = session.personal_files.path(message[12:].strip(), directory=True)
                    if Path(git(target, 'rev-parse', '--show-toplevel')).resolve() != target:
                        raise WorkerError('select_the_git_project_root')
                    answer = input(f'Switch to {target}? New sessions have a {profile.max_live_invocations}-invocation budget and edits stay in an isolated worktree [y/N]? ')
                    if answer.lower().strip() == 'y':
                        launch_approved = False
                        session.personal_files.revoke()
                        candidate = ConversationSession(target, profile, session_id=ConversationSession.latest_id(target))
                        project_root, session = target, candidate
                        profile = session.profile
                        launch_approved = approve_launch(session)
                        approve_files(session)
                    continue
                if message.lower().strip() in ('/new', 'new session', 'start a new session'):
                    answer = input(f'Start a separate session with a fresh budget of {profile.max_live_invocations} live invocations? No worker starts now [y/N]: ')
                    if answer.lower().strip() == 'y':
                        launch_approved = False
                        session = ConversationSession(project_root, profile)
                        print('Fresh session created. Previous work is preserved.')
                        launch_approved = approve_launch(session)
                        if profile.worker != 'mock':
                            approve_files(session)
                    continue
                if message.lower().strip() in ('resume latest', '/resume'):
                    launch_approved = False
                    session = ConversationSession(project_root, profile, session_id='latest')
                    profile = session.profile
                    print('Latest progress loaded.')
                    launch_approved = approve_launch(session)
                    if profile.worker != 'mock':
                        approve_files(session)
                    continue
                if message.startswith('/plan '):
                    message = 'Plan ' + message[6:]
                elif message == '/review':
                    message = 'Review pending work and acceptance criteria without editing files.'
                result = session.respond(message, approve_live=launch_approved, force_read_only=args.read_only)
                if result['status'] == 'approval_required':
                    show(result)
                    print('Live work is not authorized for this launch. Restart Newton to approve it. Local commands still work.')
                    continue
                elif result['status'] == 'budget_approval_required':
                    show(result)
                    answer = input('Approve this explicit budget change [y/N]? ')
                    if answer.lower().strip() == 'y':
                        result = session.respond(message, approve_budget=True)
                    else:
                        print('Budget unchanged.')
                        continue
                show(result, args.json)
                if result['status'] == 'exit':
                    break
            except (WorkerError, ValueError, OSError) as error:
                print('Newton: ' + str(error))
            except (EOFError, KeyboardInterrupt):
                print('\nStopped. Resume progress with python -m newton.')
                break
    except (EOFError, KeyboardInterrupt):
        print('\nStopped. No additional work authorized.')
    except (WorkerError, ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()

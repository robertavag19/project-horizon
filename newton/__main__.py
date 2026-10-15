"""Natural conversation entry point; deterministic commands never contact a model."""
from argparse import ArgumentParser
from dataclasses import replace
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))

from devtools.workers import WorkerError
from .conversation import ConversationSession
from .profile import load_profile
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
    if result.get('workspace'):
        print('Workspace: ' + result['workspace'])
    budget = result['budget']
    print(f"Economy: {budget['live_used']}/{budget['live_limit']} live invocations used; {budget['live_remaining']} remaining. No automatic retries.")
    if result.get('report_file'):
        print('Details: ' + result['report_file'])


def main():
    parser = ArgumentParser(description='Newton conversational agent: Economy mode, ChatGPT sign-in only')
    parser.add_argument('--task')
    parser.add_argument('--resume', nargs='?', const='latest')
    parser.add_argument('--new-session', action='store_true')
    parser.add_argument('--doctor', action='store_true')
    parser.add_argument('--read-only', action='store_true')
    parser.add_argument('--mock', action='store_true')
    parser.add_argument('--approve-live', action='store_true', help='authorize at most one worker invocation for --task')
    parser.add_argument('--worker-timeout', type=int, default=None)
    parser.add_argument('--json', action='store_true', help='show detailed local diagnostic output')
    args = parser.parse_args()
    if args.new_session and args.resume:
        parser.error('choose --new-session or --resume')
    if args.approve_live and not args.task:
        parser.error('--approve-live applies only to a single --task, never a whole interactive session')
    try:
        profile = load_profile(PROJECT)
        if args.worker_timeout is not None:
            if not 1 <= args.worker_timeout <= 90:
                parser.error('Economy worker-timeout must be between 1 and 90 seconds')
            profile = replace(profile, worker_timeout=args.worker_timeout)
        if args.mock:
            profile = replace(profile, worker='mock')
        if args.doctor:
            worker = ConversationMock() if profile.worker == 'mock' else ConversationWorker(timeout=profile.worker_timeout)
            print(json.dumps({'agent': profile.name, 'mode': 'economy', 'worker': profile.worker,
                              **worker.preflight(PROJECT)}, indent=2))
            return
        session_id = args.resume or (None if args.new_session else ConversationSession.latest_id(PROJECT))
        session = ConversationSession(PROJECT, profile, session_id=session_id)
        print(f'{profile.name} | Economy | {profile.worker} | {PROJECT}')
        print('At most 1 live worker invocation per message; session budget ' + str(session.state['live_limit']) + '.')
        print('One invocation may contain internal model calls. There is no hard token or subscription-percentage cap.')
        if args.task:
            print('This task budget: at most 1 live invocation; 0 automatic retries.')
            result = session.respond(args.task, approve_live=args.approve_live, force_read_only=args.read_only)
            show(result, args.json)
            if result['status'] in ('approval_required', 'budget_exhausted'):
                print('Use interactive mode to approve one task, or --task "..." --approve-live.')
                raise SystemExit(2)
            if result['status'] not in ('local', 'answered', 'planned', 'clarification_required', 'changes_tested_review_required', 'exit'):
                raise SystemExit(1)
            return
        print('Talk naturally. Local/free: help, status, run tests, list files, show changes, show plan, quit.')
        print('Progress resumes automatically. Raw conversation is not replayed; a bounded summary is saved locally.')
        while True:
            try:
                message = input(f'{profile.name}> ').strip()
                if not message:
                    continue
                if message.lower().strip() in ('/new', 'new session', 'start a new session'):
                    answer = input('Start a separate session with a fresh budget of up to 3 live invocations? No worker starts now [y/N]: ')
                    if answer.lower().strip() == 'y':
                        session = ConversationSession(PROJECT, profile)
                        print('Fresh session created. Previous work is preserved.')
                    continue
                if message.lower().strip() in ('resume latest', '/resume'):
                    session = ConversationSession(PROJECT, profile, session_id='latest')
                    print('Latest progress loaded.')
                    continue
                if message.startswith('/plan '):
                    message = 'Plan ' + message[6:]
                elif message == '/review':
                    message = 'Review pending work and acceptance criteria without editing files.'
                result = session.respond(message, force_read_only=args.read_only)
                if result['status'] == 'approval_required':
                    show(result)
                    answer = input('Authorize at most 1 live Codex invocation for this message [y/N]? ')
                    if answer.lower().strip() == 'y':
                        result = session.respond(message, approve_live=True, force_read_only=args.read_only)
                    else:
                        print('Not run. No live invocation used.')
                        continue
                elif result['status'] == 'budget_approval_required':
                    show(result)
                    answer = input('Approve this explicit budget increase [y/N]? ')
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
    except (WorkerError, ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()

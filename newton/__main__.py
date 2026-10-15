"""Run `python -m newton` for a persistent interactive development session."""
from argparse import ArgumentParser
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))

from devtools.coordinator import git, run_tests
from devtools.workers import CodexWorker, MockWorker, WorkerError
from .profile import load_profile
from .session import Session

HELP = '''Type a task in plain English. Newton works in an isolated worktree.
/plan <goal>  Plan a larger task without editing files
/review       Review pending work without editing files
/status       Show session, worktree and changes
/diff         Show tracked-file diff and untracked file names
/tests        Run local tests (no model call)
/connections  Check the configured worker's subscription sign-in
/new          Start a fresh session; previous work is preserved
/quit         Exit; progress is saved, conversation text is not
'''


def show_report(report):
    print('\n' + report['worker_reply'])
    print(f"Status: {report['status']} | Tests: {report['tests_run']} | Passed: {report['tests_passed']}")
    if report.get('last_error'):
        print('Last rejected attempt: ' + report['last_error'])
    print('Workspace: ' + report['worktree'])
    print('Report: ' + report['report_file'])


def main():
    parser = ArgumentParser(description='Newton personal development agent (Codex subscription)')
    parser.add_argument('--task')
    parser.add_argument('--resume')
    parser.add_argument('--doctor', action='store_true')
    parser.add_argument('--read-only', action='store_true')
    parser.add_argument('--mock', action='store_true', help='offline demo; no model inference')
    args = parser.parse_args()
    try:
        profile = load_profile(PROJECT)
        if args.mock:
            from dataclasses import replace
            profile = replace(profile, worker='mock')
        if args.doctor:
            worker = MockWorker() if profile.worker == 'mock' else CodexWorker(timeout=profile.worker_timeout)
            print(json.dumps({'agent': profile.name, 'worker': profile.worker, **worker.preflight(PROJECT)}, indent=2))
            return
        session = Session(PROJECT, profile, session_id=args.resume)
        print(f'{profile.name} | {profile.worker} | No paid API adapter. Live work uses plan allowance.')
        print('Session: ' + session.session_id)
        if args.task:
            report = session.run(args.task, read_only=args.read_only)
            show_report(report)
            print(session.status()['resume'])
            if report['status'] != 'tests_passed_review_required':
                raise SystemExit(1)
            return
        print(HELP)
        while True:
            try:
                task = input(f'{profile.name}> ').strip()
                if not task:
                    continue
                if task in ('/quit', '/exit'):
                    print('Resume: ' + session.status()['resume'])
                    break
                if task == '/help':
                    print(HELP)
                elif task == '/status':
                    print(json.dumps(session.status(), indent=2))
                elif task == '/connections':
                    print(json.dumps(session.worker().preflight(PROJECT), indent=2))
                elif task == '/diff':
                    print(git(session.workspace(), 'diff'))
                    print(git(session.workspace(), 'status', '--short'))
                elif task == '/tests':
                    result = run_tests(session.workspace())
                    print(result.output)
                elif task == '/new':
                    session = Session(PROJECT, profile)
                    print('New session: ' + session.session_id)
                elif task.startswith('/plan '):
                    show_report(session.run('Plan small sequential implementation steps with acceptance checks; do not edit. Goal: ' + task[6:], read_only=True))
                elif task == '/review':
                    show_report(session.run('Review current source snapshots and recent session context. Identify defects, missing acceptance checks and the next small step. Do not edit.', read_only=True))
                elif task.startswith('/'):
                    print('Unknown command. Use /help.')
                else:
                    show_report(session.run(task, read_only=args.read_only))
            except (WorkerError, ValueError, OSError) as error:
                print('Newton: ' + str(error))
            except (EOFError, KeyboardInterrupt):
                print('\nResume: ' + session.status()['resume'])
                break
    except (WorkerError, ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()

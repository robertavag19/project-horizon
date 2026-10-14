"""Launch a development task or check subscription authentication."""
from argparse import ArgumentParser
import json
from pathlib import Path
import sys

# Also support running the script from the project root without PYTHONPATH setup.
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))

from .coordinator import coordinate
from .workers import CodexWorker, MockWorker, WorkerError


def main():
    parser = ArgumentParser(description='Horizon local development coordinator (ChatGPT sign-in only)')
    parser.add_argument('--task')
    parser.add_argument('--worker', choices=['codex', 'mock'], default='codex')
    parser.add_argument('--doctor', action='store_true')
    parser.add_argument('--read-only', action='store_true')
    parser.add_argument('--max-repairs', type=int, default=1)
    parser.add_argument('--worker-timeout', type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.worker_timeout <= 600:
        parser.error('worker-timeout must be between 1 and 600 seconds')
    try:
        worker = MockWorker() if args.worker == 'mock' else CodexWorker(timeout=args.worker_timeout, read_only=args.read_only)
        if args.doctor:
            print(json.dumps(worker.preflight(PROJECT), indent=2))
            return
        if not args.task:
            parser.error('supply --task or --doctor')
        result = coordinate(PROJECT, args.task, worker, max_repairs=0 if args.read_only else args.max_repairs)
    except (WorkerError, ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    if result['status'] != 'tests_passed_review_required':
        raise SystemExit(1)


if __name__ == '__main__':
    main()

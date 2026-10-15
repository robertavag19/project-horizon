"""Compatibility launcher. Live tasks use Newton's persistent Economy budget."""
from argparse import ArgumentParser
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))


def main():
    parser = ArgumentParser(description='Newton compatibility launcher (Economy mode)')
    parser.add_argument('--task')
    parser.add_argument('--worker', choices=['codex', 'mock'], default='codex')
    parser.add_argument('--doctor', action='store_true')
    parser.add_argument('--read-only', action='store_true')
    parser.add_argument('--max-repairs', type=int, default=0)
    parser.add_argument('--worker-timeout', type=int, default=90)
    parser.add_argument('--approve-live', action='store_true')
    args = parser.parse_args()
    if args.max_repairs != 0:
        parser.error('Economy mode disables automatic retries; request a correction as a new message')
    if not 1 <= args.worker_timeout <= 90:
        parser.error('Economy worker-timeout must be between 1 and 90 seconds')
    forwarded = ['newton', '--worker-timeout', str(args.worker_timeout)]
    if args.task:
        forwarded += ['--task', args.task]
    if args.worker == 'mock':
        forwarded.append('--mock')
    if args.doctor:
        forwarded.append('--doctor')
    if args.read_only:
        forwarded.append('--read-only')
    if args.approve_live:
        forwarded.append('--approve-live')
    from newton.__main__ import main as newton_main
    original = sys.argv
    try:
        sys.argv = forwarded
        return newton_main()
    finally:
        sys.argv = original


if __name__ == '__main__':
    main()

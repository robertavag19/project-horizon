"""CLI for the original baseline and the offline provider-driven controller."""
from argparse import ArgumentParser
from pathlib import Path
import json

from .core import run_baseline
from .agent import run_agent
from .providers import MockProvider


def main() -> None:
    parser = ArgumentParser(description='Project Horizon reliability sandbox')
    parser.add_argument('--mode', choices=['baseline', 'agent'], default='baseline')
    parser.add_argument('--document', default='examples/physics_notes.txt')
    parser.add_argument('--question', default='What is centripetal acceleration?')
    parser.add_argument('--log-dir', default='runs')
    parser.add_argument('--inject', choices=['none', 'drop_evidence', 'wrong_citation'], default='none')
    parser.add_argument('--expected-passage', default=None)
    parser.add_argument('--max-steps', type=int, default=8)
    parser.add_argument('--max-duration-seconds', type=float, default=30)
    parser.add_argument('--task-id', default='study_task')
    args = parser.parse_args()
    try:
        document = Path(args.document)
        if document.stat().st_size > 1_000_000:
            parser.error('document exceeds 1 MB limit')
        if document.suffix.lower() != '.txt':
            parser.error('only UTF-8 .txt files are supported by this CLI')
        text = document.read_text(encoding='utf-8')
        if args.mode == 'agent':
            result = run_agent(text, args.question, Path(args.log_dir), MockProvider(),
                inject=args.inject, expected_passage=args.expected_passage,
                max_steps=args.max_steps, max_duration_seconds=args.max_duration_seconds,
                task_id=args.task_id)
        else:
            result = run_baseline(text, args.question, Path(args.log_dir),
                inject=args.inject, expected_passage=args.expected_passage or 'P001')
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))
    if args.mode == 'agent' and result['termination_reason'] not in ('completed', 'abstained'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()

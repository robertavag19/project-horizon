"""Usage: python -m horizon.cli --question 'What is centripetal acceleration?'"""
from argparse import ArgumentParser
from pathlib import Path
import json

from .core import run_baseline


def main() -> None:
    parser = ArgumentParser(description="Project Horizon deterministic agent-reliability sandbox")
    parser.add_argument("--document", default="examples/physics_notes.txt")
    parser.add_argument("--question", default="What is centripetal acceleration?")
    parser.add_argument("--log-dir", default="runs")
    parser.add_argument("--inject", choices=["none", "drop_evidence", "wrong_citation"], default="none")
    parser.add_argument("--expected-passage", default="P001")
    args = parser.parse_args()
    text = Path(args.document).read_text(encoding="utf-8")
    result = run_baseline(text, args.question, Path(args.log_dir), inject=args.inject, expected_passage=args.expected_passage)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

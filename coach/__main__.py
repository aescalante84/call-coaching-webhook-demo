"""CLI:  python3 -m coach score <transcript.txt>   |   python3 -m coach serve [--port N]"""
import argparse
import json
import sys

from .scorer import get_scorer, load_rubric
from .server import serve


def main():
    p = argparse.ArgumentParser(prog="coach", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score", help="score one transcript file and print the result")
    s.add_argument("file")
    s.add_argument("--scorer", choices=["rules", "llm"], default=None)

    v = sub.add_parser("serve", help="run the webhook server")
    v.add_argument("--port", type=int, default=8080)
    v.add_argument("--scorer", choices=["rules", "llm"], default=None)

    args = p.parse_args()
    if args.cmd == "score":
        with open(args.file, encoding="utf-8") as f:
            transcript = f.read()
        result = get_scorer(args.scorer).score(transcript, load_rubric())
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        serve(args.port, args.scorer)


if __name__ == "__main__":
    main()

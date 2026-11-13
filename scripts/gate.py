"""Ship gate: fail if the routed policy regresses or any configuration produces a postable bad entry.

Usage: python scripts/gate.py [--policy haiku_escalate_sonnet] [--min-accuracy 0.98]
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--policy", default="haiku_escalate_sonnet")
ap.add_argument("--min-accuracy", type=float, default=0.98)
args = ap.parse_args()

rows = [json.loads(l) for l in (ROOT / "results" / "actions.jsonl").open()]
policy = [r for r in rows if r["config"] == args.policy]
acc = sum(r["correct"] for r in policy) / len(policy)
unsafe = sum(r["unsafe_valid_entry"] for r in rows)
print(f"{args.policy}: accuracy {acc:.1%} (min {args.min_accuracy:.0%}); postable bad entries across all configs: {unsafe}")
sys.exit(0 if acc >= args.min_accuracy and unsafe == 0 else 1)

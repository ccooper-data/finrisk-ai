"""Run the fixed five-seed validation sensitivity experiment, never a seed contest."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from finrisk.modeling.seed_sweep import run_seed_sweep


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run_seed_sweep(args.cohort, args.out_dir)
    print(json.dumps({key: report[key] for key in ("status", "seeds", "summary")}, indent=2))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())

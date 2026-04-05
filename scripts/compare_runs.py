"""
compare_runs.py — compare two PEA pipeline run summaries side by side.

Usage:
    python scripts/compare_runs.py data/validation/baseline_summary.json data/raw/summary_<run_id>.json

To save the current run as the new baseline:
    python scripts/compare_runs.py --set-baseline data/raw/summary_<run_id>.json
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

BASELINE_PATH = Path("data/validation/baseline_summary.json")


def _load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _pct_change(old: float, new: float) -> str:
    if old == 0:
        return "+∞" if new > 0 else "—"
    change = (new - old) / old * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%"


def _compare_dicts(label: str, old: dict, new: dict, all_keys: bool = True):
    keys = sorted(set(list(old.keys()) + list(new.keys()))) if all_keys else sorted(old.keys())
    print(f"\n  {label}")
    print(f"  {'':30s} {'baseline':>10s} {'new run':>10s} {'change':>10s}")
    print(f"  {'-'*62}")
    for k in keys:
        a = old.get(k, 0)
        b = new.get(k, 0)
        print(f"  {k:30s} {a:>10} {b:>10} {_pct_change(a, b):>10s}")


def compare(baseline_path: str, new_path: str):
    baseline = _load(baseline_path)
    new = _load(new_path)

    print(f"\n{'='*66}")
    print(f"  PEA Run Comparison")
    print(f"  Baseline : {baseline.get('run_id', baseline_path)}")
    print(f"  New run  : {new.get('run_id', new_path)}")
    print(f"{'='*66}")

    # Top-level counts
    print(f"\n  {'METRIC':30s} {'baseline':>10s} {'new run':>10s} {'change':>10s}")
    print(f"  {'-'*62}")
    for key, label in [
        ("total_events", "total events"),
        ("total_failures", "failures"),
    ]:
        a = baseline.get(key, 0)
        b = new.get(key, 0)
        print(f"  {label:30s} {a:>10} {b:>10} {_pct_change(a, b):>10s}")

    _compare_dicts("Events by country", baseline.get("events_by_country", {}), new.get("events_by_country", {}))
    _compare_dicts("Events by type", baseline.get("events_by_type", {}), new.get("events_by_type", {}))
    _compare_dicts("Events by turmoil level", baseline.get("events_by_turmoil_level", {}), new.get("events_by_turmoil_level", {}))
    _compare_dicts("Events by confidence", baseline.get("events_by_confidence", {}), new.get("events_by_confidence", {}))

    print(f"\n{'='*66}\n")


def set_baseline(source_path: str):
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source_path, BASELINE_PATH)
    run_id = _load(source_path).get("run_id", source_path)
    print(f"Baseline saved: {BASELINE_PATH}  (run_id: {run_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare two PEA run summaries")
    parser.add_argument("--set-baseline", metavar="SUMMARY_JSON", help="Save a summary as the new baseline")
    parser.add_argument("new_run", nargs="?", help="New run summary JSON to compare against baseline")
    parser.add_argument("baseline", nargs="?", default=str(BASELINE_PATH), help="Baseline summary JSON (default: data/validation/baseline_summary.json)")
    args = parser.parse_args()

    if args.set_baseline:
        set_baseline(args.set_baseline)
    elif args.new_run:
        baseline_file = args.baseline
        if not Path(baseline_file).exists():
            print(f"No baseline found at {baseline_file}. Run with --set-baseline first.")
            sys.exit(1)
        compare(baseline_file, args.new_run)
    else:
        parser.print_help()

#!/usr/bin/env python3
# ABOUTME: Exports schema-validated benchmark run records from a history file into results/ JSON files.
# ABOUTME: Each file is self-contained, so results can be committed, shared, and diffed per run.
import argparse
import json
import os
from typing import List, Optional

from result_schema import validate_run_record


def _filename_for(record: dict) -> str:
    safe_timestamp = (
        record["timestamp"]
        .replace(":", "")
        .replace("-", "")
        .replace(".", "_")
        .replace("T", "T")
    )
    return f"{safe_timestamp}_{record['id'][:8]}.json"


def export_runs(history_file: str, out_dir: str, limit: Optional[int] = None) -> List[str]:
    """Export run records from a history file to individual JSON files.

    Only runs carrying a validated record (schema_version >= 1) are exported;
    legacy entries without records are skipped. Returns the written paths.
    """
    with open(history_file) as f:
        history = json.load(f)

    runs = history.get("runs", [])
    eligible = [run for run in runs if "record" in run]
    if limit is not None:
        eligible = eligible[-limit:]

    os.makedirs(out_dir, exist_ok=True)

    written: List[str] = []
    for run in eligible:
        record = run["record"]
        errors = validate_run_record(record)
        if errors:
            raise ValueError(
                f"Run {run.get('id')} failed schema validation, refusing to export: "
                + "; ".join(errors)
            )
        path = os.path.join(out_dir, _filename_for(record))
        with open(path, "w") as f:
            json.dump(record, f, indent=2)
        written.append(path)

    return sorted(written)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export validated benchmark run records to individual JSON files."
    )
    parser.add_argument('--history-file', type=str, default='benchmark_history.json',
                        help='Path to the benchmark history file. Default: benchmark_history.json')
    parser.add_argument('--out-dir', type=str, default='results',
                        help='Directory to write run record files to. Default: results')
    parser.add_argument('--limit', type=int, default=None,
                        help='Export only the N most recent runs. Default: all')
    args = parser.parse_args()

    if not os.path.exists(args.history_file):
        parser.error(f"History file not found: {args.history_file}")

    written = export_runs(args.history_file, args.out_dir, args.limit)
    print(f"Exported {len(written)} run record(s) to {args.out_dir}")
    for path in written:
        print(f"  {path}")


if __name__ == "__main__":
    main()

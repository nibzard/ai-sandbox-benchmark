# ABOUTME: Unit tests for exporting benchmark run records to results/ JSON files.
# ABOUTME: Lives outside tests/ so the comparator does not load it as a sandbox workload.
import json
import os

from metrics import BenchmarkHistory, BenchmarkTimingMetrics
from export_results import export_runs


def add_run(history: BenchmarkHistory, timestamp: str) -> None:
    def test_fake():
        pass

    metrics = BenchmarkTimingMetrics()
    metrics.add_metric("Code Execution", 0.1)
    history.add_benchmark_run(
        results={"test_fake": {"run_1": {"local": {"metrics": metrics, "output": None}}}},
        providers=["local"],
        tests={1: test_fake},
        timestamp=timestamp,
        metadata={"warmup_runs": 0, "measurement_runs": 1, "target_region": "eu"},
    )


def make_history(tmp_path) -> BenchmarkHistory:
    history = BenchmarkHistory(str(tmp_path / "history.json"))
    add_run(history, "2026-09-16T10:00:00")
    add_run(history, "2026-09-17T11:00:00")
    return history


def test_export_writes_one_valid_file_per_record(tmp_path):
    history = make_history(tmp_path)
    out_dir = tmp_path / "results"
    written = export_runs(history.history_file, str(out_dir))

    assert len(written) == 2
    files = list(out_dir.glob("*.json"))
    assert len(files) == 2

    from result_schema import validate_run_record
    for path in files:
        with open(path) as f:
            record = json.load(f)
        assert validate_run_record(record) == []


def test_export_limit_takes_most_recent(tmp_path):
    history = make_history(tmp_path)
    out_dir = tmp_path / "results"
    written = export_runs(history.history_file, str(out_dir), limit=1)

    assert len(written) == 1
    with open(written[0]) as f:
        record = json.load(f)
    assert record["timestamp"] == "2026-09-17T11:00:00"


def test_export_skips_legacy_runs_without_records(tmp_path):
    history = make_history(tmp_path)
    # Append a legacy run entry (pre-schema format: no "record" key)
    history.history["runs"].insert(0, {"id": "legacy", "timestamp": "2026-01-01T00:00:00"})
    history.save_history()

    out_dir = tmp_path / "results"
    written = export_runs(history.history_file, str(out_dir))
    assert len(written) == 2


def test_export_filenames_are_unique_and_sorted(tmp_path):
    history = make_history(tmp_path)
    out_dir = tmp_path / "results"
    written = export_runs(history.history_file, str(out_dir))
    names = [os.path.basename(p) for p in written]
    assert len(names) == len(set(names))
    assert names == sorted(names)

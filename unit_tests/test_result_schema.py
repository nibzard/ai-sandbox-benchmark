# ABOUTME: Unit tests for the benchmark run record JSON schema and its validation.
# ABOUTME: Lives outside tests/ so the comparator does not load it as a sandbox workload.
import json
import os

from metrics import BenchmarkTimingMetrics, BenchmarkHistory
from result_schema import SCHEMA_VERSION, validate_run_record


def make_record() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "id": "0d0ee1d8-6b50-4f34-9f71-1b8e15c1e5a0",
        "timestamp": "2026-09-17T12:00:00",
        "providers": ["local"],
        "tests": [{"id": 1, "name": "test_calculate_primes"}],
        "metadata": {
            "total_duration": 12.5,
            "warmup_runs": 1,
            "measurement_runs": 2,
            "target_region": "eu",
            "command_line_args": {"runs": 2},
        },
        "results": {
            "test_1": {
                "run_1": {
                    "local": {
                        "total_time": 300.0,
                        "stats": {
                            "Code Execution": {
                                "mean": 100.0,
                                "std": 1.0,
                                "min": 99.0,
                                "max": 101.0,
                                "median": 100.0,
                                "p95": 101.0,
                                "p99": 101.0,
                                "samples": 2,
                            }
                        },
                        "error": None,
                    }
                }
            }
        },
    }


def test_valid_record_passes():
    assert validate_run_record(make_record()) == []


def test_missing_required_field_fails():
    record = make_record()
    del record["timestamp"]
    errors = validate_run_record(record)
    assert any("timestamp" in error for error in errors)


def test_wrong_type_fails():
    record = make_record()
    record["providers"] = "local"
    errors = validate_run_record(record)
    assert errors != []


def test_stats_entry_requires_percentiles():
    record = make_record()
    stats = record["results"]["test_1"]["run_1"]["local"]["stats"]["Code Execution"]
    del stats["p95"]
    errors = validate_run_record(record)
    assert any("p95" in error for error in errors)


def test_empty_stats_for_failed_runs_allowed():
    record = make_record()
    record["results"]["test_1"]["run_1"]["local"] = {
        "total_time": 0,
        "stats": {},
        "error": "provider timeout",
    }
    assert validate_run_record(record) == []


def make_fake_results() -> dict:
    metrics = BenchmarkTimingMetrics()
    metrics.add_metric("Workspace Creation", 0.2)
    metrics.add_metric("Code Execution", 0.5)
    metrics.add_metric("Cleanup", 0.01)
    failed = BenchmarkTimingMetrics()
    failed.add_error("boom")
    return {
        "test_1": {
            "run_1": {"local": {"metrics": metrics, "output": None}},
            "run_2": {"local": {"metrics": failed, "output": None, "error": "boom"}},
        }
    }


def test_history_run_record(tmp_path):
    def test_fake():
        pass

    history = BenchmarkHistory(str(tmp_path / "history.json"))
    run_id = history.add_benchmark_run(
        results=make_fake_results(),
        providers=["local"],
        tests={1: test_fake},
        metadata={"warmup_runs": 1, "measurement_runs": 2, "target_region": "eu"},
    )

    with open(history.history_file) as f:
        stored = json.load(f)
    run_entry = next(r for r in stored["runs"] if r["id"] == run_id)
    assert run_entry["schema_version"] == SCHEMA_VERSION
    assert validate_run_record(run_entry["record"]) == []

    reloaded = BenchmarkHistory(str(tmp_path / "history.json"))
    assert reloaded.history["runs"], "history must survive a save/reload cycle"

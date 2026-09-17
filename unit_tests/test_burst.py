# ABOUTME: Unit tests for the burst-mode benchmark probe merging and payload.
# ABOUTME: Lives outside tests/ so the comparator does not load it as a sandbox workload.
import json

from burst import BURST_TEST_ID, merge_probe_results, test_burst_tti
from metrics import BenchmarkHistory, BenchmarkTimingMetrics


def make_probe(provider: str, values_ms: list, error: str = None):
    metrics = BenchmarkTimingMetrics()
    for value in values_ms:
        metrics.add_metric("Code Execution", value / 1000)
    if error:
        # Mirror run_test_on_provider, which records the error on the metrics object
        metrics.add_error(error)
    return (provider, {"metrics": metrics, "output": "ok"}, error)


def test_probe_payload_is_minimal_single_run():
    payload = test_burst_tti()
    assert payload["config"]["single_run"] is True
    assert "code" in payload
    assert len(payload["code"]) < 500, "probe payload must stay small"


def test_merge_pools_samples_per_provider():
    probes = [
        make_probe("local", [100.0]),
        make_probe("local", [300.0]),
        make_probe("local", [200.0]),
    ]
    merged = merge_probe_results(probes)
    stats = merged["local"]["metrics"].get_statistics()["Code Execution"]
    assert stats["samples"] == 3
    assert stats["median"] == 200.0
    assert stats["p95"] == 290.0


def test_merge_keeps_providers_separate():
    probes = [
        make_probe("local", [100.0]),
        make_probe("e2b", [500.0]),
    ]
    merged = merge_probe_results(probes)
    assert set(merged.keys()) == {"local", "e2b"}
    assert merged["local"]["metrics"].get_statistics()["Code Execution"]["samples"] == 1


def test_merge_counts_probe_errors():
    probes = [
        make_probe("local", [100.0]),
        make_probe("local", [200.0]),
        make_probe("local", [], error="provider timeout"),
    ]
    merged = merge_probe_results(probes)
    assert merged["local"]["probe_errors"] == 1
    assert "error" not in merged["local"], "run-level error only when every probe fails"


def test_merge_marks_run_failed_when_all_probes_fail():
    probes = [
        make_probe("local", [], error="boom"),
        make_probe("local", [], error="boom"),
    ]
    merged = merge_probe_results(probes)
    assert merged["local"]["error"] == "boom"


def test_burst_results_validate_and_store(tmp_path):
    probes = [make_probe("local", [100.0]), make_probe("local", [200.0])]
    merged = merge_probe_results(probes)
    overall = {"test_burst_tti": {"run_1": merged}}

    history = BenchmarkHistory(str(tmp_path / "history.json"))
    history.add_benchmark_run(
        results=overall,
        providers=["local"],
        tests={BURST_TEST_ID: test_burst_tti},
        metadata={
            "warmup_runs": 0,
            "measurement_runs": 1,
            "target_region": "eu",
            "burst_size": 2,
            "mode": "burst",
        },
    )

    with open(history.history_file) as f:
        stored = json.load(f)
    run_entry = stored["runs"][0]
    assert run_entry["schema_version"] == 1
    assert run_entry["record"]["metadata"]["burst_size"] == 2
    assert run_entry["record"]["tests"][0]["slug"] == "burst_tti"
    assert run_entry["record"]["results"]["test_burst_tti"]["run_1"]["local"]["probe_errors"] == 0

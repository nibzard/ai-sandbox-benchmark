# ABOUTME: Unit tests for percentile statistics in EnhancedTimingMetrics.
# ABOUTME: Lives outside tests/ so the comparator does not load it as a sandbox workload.
import numpy as np

from metrics import BenchmarkTimingMetrics, EnhancedTimingMetrics


def make_metrics_with_values(name: str, values_ms: list) -> EnhancedTimingMetrics:
    metrics = EnhancedTimingMetrics()
    for value in values_ms:
        metrics.add_metric(name, value / 1000)
    return metrics


def test_statistics_include_median_and_percentiles():
    metrics = make_metrics_with_values("Code Execution", [1.0, 2.0, 3.0, 4.0, 5.0])
    stats = metrics.get_statistics()["Code Execution"]
    assert stats["median"] == 3.0
    assert stats["p95"] == 4.8
    assert stats["p99"] == 4.96
    assert stats["samples"] == 5


def test_statistics_keep_mean_std_min_max():
    metrics = make_metrics_with_values("Code Execution", [1.0, 2.0, 3.0, 4.0, 5.0])
    stats = metrics.get_statistics()["Code Execution"]
    assert stats["mean"] == np.mean([1.0, 2.0, 3.0, 4.0, 5.0])
    assert stats["std"] == np.std([1.0, 2.0, 3.0, 4.0, 5.0])
    assert stats["min"] == 1.0
    assert stats["max"] == 5.0


def test_single_sample_has_all_percentiles_equal():
    metrics = make_metrics_with_values("Cleanup", [7.0])
    stats = metrics.get_statistics()["Cleanup"]
    assert stats["median"] == 7.0
    assert stats["p95"] == 7.0
    assert stats["p99"] == 7.0
    assert stats["samples"] == 1


def test_internal_execution_values_stay_in_milliseconds():
    metrics = BenchmarkTimingMetrics()
    metrics.add_metric("Internal Execution", 42.0)
    stats = metrics.get_statistics()["Internal Execution"]
    assert stats["median"] == 42.0
    assert stats["samples"] == 1


def test_outliers_do_not_move_median():
    stable = make_metrics_with_values("Code Execution", [10.0] * 9 + [10_000.0])
    stats = stable.get_statistics()["Code Execution"]
    assert stats["median"] == 10.0
    assert stats["mean"] > 10.0

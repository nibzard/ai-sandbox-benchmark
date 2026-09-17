#!/usr/bin/env python3
# ABOUTME: Burst-mode benchmark that launches N concurrent sandbox probes per provider.
# ABOUTME: Measures sandbox start and execution percentiles under load; results store in run history.
import argparse
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from comparator import SandboxExecutor, ResultsVisualizer, log_benchmark, test_key
from metrics import BenchmarkHistory, BenchmarkTimingMetrics

# Test id 0 is reserved for the burst probe; comparator ids start at 1.
BURST_TEST_ID = 0

PROBE_CODE = "import time\nprint('burst probe ready')"


def test_burst_tti() -> Dict[str, Any]:
    """Minimal probe payload: create a sandbox, run one command, tear it down."""
    return {
        "config": {
            "single_run": True,
            "description": "Concurrency probe measuring sandbox create, execute and teardown under burst load",
        },
        "code": PROBE_CODE,
    }


test_burst_tti.meta = {
    "slug": "burst_tti",
    "description": "Concurrency probe: sandbox create, execute and teardown under burst load",
    "single_run": True,
    "info_test": False,
}


def merge_probe_results(
    probes: List[Tuple[str, Dict[str, Any], Optional[Exception]]]
) -> Dict[str, Dict[str, Any]]:
    """Merge per-probe results into one entry per provider.

    Each probe contributes its raw samples so downstream statistics pool every
    probe. A run-level error is only set when every probe for a provider failed.
    """
    merged: Dict[str, Dict[str, Any]] = {}

    for probe in probes:
        if isinstance(probe, BaseException):
            log_benchmark(f"Burst probe crashed outside the provider wrapper: {probe}")
            continue

        provider, results, error = probe
        entry = merged.setdefault(
            provider, {"metrics": BenchmarkTimingMetrics(), "output": None, "probe_errors": 0, "probes": 0}
        )
        entry["probes"] += 1

        for metric_name, values in results["metrics"].metrics.items():
            entry["metrics"].metrics.setdefault(metric_name, []).extend(values)
        for probe_error in results["metrics"].errors:
            entry["metrics"].add_error(probe_error)

        if error:
            entry["probe_errors"] += 1
        if entry["output"] is None and results.get("output"):
            entry["output"] = results["output"]

    for entry in merged.values():
        if entry["probes"] > 0 and entry["probe_errors"] == entry["probes"]:
            entry["error"] = entry["metrics"].errors[-1] if entry["metrics"].errors else "all probes failed"

    return merged


async def run_burst(
    executor_obj: SandboxExecutor,
    providers: List[str],
    burst_size: int,
    target_region: str,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Launch burst_size concurrent probes per provider and return merged results."""
    with ThreadPoolExecutor(max_workers=max(1, burst_size * len(providers))) as pool:
        tasks = [
            executor_obj.run_test_on_provider(test_burst_tti, provider, pool, target_region)
            for provider in providers
            for _ in range(burst_size)
        ]
        probes = await asyncio.gather(*tasks, return_exceptions=True)

    return {test_key(test_burst_tti): {"run_1": merge_probe_results(probes)}}


async def run(args) -> None:
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    if not providers:
        log_benchmark("No providers selected for the burst run.")
        return

    if "daytona" in providers:
        print("Note: the Daytona provider serializes API calls internally, so its burst")
        print("numbers reflect client-side serialization, not provider concurrency.\n")

    executor_obj = SandboxExecutor(
        warmup_runs=args.warmup_runs,
        measurement_runs=1,
        num_concurrent_providers=len(providers),
    )
    history = BenchmarkHistory(args.history_file)

    # Warm up with one sequential probe per provider so the first burst can be
    # compared against a known-good single start.
    if args.warmup_runs > 0:
        log_benchmark(f"Running {args.warmup_runs} sequential warmup probe(s) per provider")
        with ThreadPoolExecutor(max_workers=len(providers)) as pool:
            warmup_tasks = [
                executor_obj.run_test_on_provider(test_burst_tti, provider, pool, args.target_region)
                for provider in providers
            ]
            await asyncio.gather(*warmup_tasks, return_exceptions=True)

    overall: Dict[str, Dict[str, Any]] = {test_key(test_burst_tti): {}}
    start_time = time.time()

    for run in range(1, args.runs + 1):
        log_benchmark(f"Burst run {run}/{args.runs}: launching {args.burst_size} concurrent probes per provider")
        burst_results = await run_burst(executor_obj, providers, args.burst_size, args.target_region)
        overall[test_key(test_burst_tti)][f"run_{run}"] = burst_results[test_key(test_burst_tti)]["run_1"]

    total_duration = time.time() - start_time
    log_benchmark(f"All burst runs completed in {total_duration:.2f} seconds")

    tests = {BURST_TEST_ID: test_burst_tti}
    metadata = {
        "total_duration": total_duration,
        "warmup_runs": args.warmup_runs,
        "measurement_runs": args.runs,
        "target_region": args.target_region,
        "burst_size": args.burst_size,
        "mode": "burst",
    }
    history.add_benchmark_run(
        results=overall,
        providers=providers,
        tests=tests,
        metadata=metadata,
    )
    log_benchmark(f"Burst results saved to history file: {history.history_file}")

    ResultsVisualizer.print_detailed_comparison(
        overall,
        tests,
        args.runs,
        args.warmup_runs,
        providers,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a burst benchmark: N concurrent sandbox starts per provider."
    )
    parser.add_argument('--providers', '-p', type=str, default='local',
                        help='Comma-separated list of providers to test. Default: local')
    parser.add_argument('--burst-size', '-b', type=int, default=10,
                        help='Number of concurrent probes per provider per run. Default: 10')
    parser.add_argument('--runs', '-r', type=int, default=1,
                        help='Number of burst repetitions. Default: 1')
    parser.add_argument('--warmup-runs', '-w', type=int, default=0,
                        help='Sequential warmup probes per provider before the burst. Default: 0')
    parser.add_argument('--target-region', type=str, default='eu',
                        help='Target region (eu, us, asia). Default: eu')
    parser.add_argument('--history-file', type=str, default='benchmark_history.json',
                        help='Path to the benchmark history file. Default: benchmark_history.json')
    args = parser.parse_args()

    if args.burst_size < 1:
        parser.error("--burst-size must be at least 1.")
    if args.runs < 1:
        parser.error("--runs must be at least 1.")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()

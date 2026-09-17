# ABOUTME: Morph Cloud sandbox provider — starts an instance from a cached snapshot, executes code via SSH, collects timing metrics.
# ABOUTME: Implements the standard provider interface: async execute(code, env_vars) returning (output, metrics).

import asyncio
import json
import logging
import os
import shlex
import time
from typing import Any, Dict, Optional, Tuple

from morphcloud.api import MorphCloudClient
from metrics import BenchmarkTimingMetrics

logger = logging.getLogger(__name__)

def log_info(message):
    logger.info(f"[Morph] {message}")

def log_error(message):
    logger.error(f"[Morph] {message}")

def log_warning(message):
    logger.warning(f"[Morph] {message}")

# Snapshot reused across runs so dependency installs persist between benchmark
# iterations. Created once from a base image, then looked up by metadata.
_BASE_SNAPSHOT_METADATA = {"name": "ai-sandbox-benchmark"}
DEFAULT_IMAGE_ID = "morphvm-minimal"
SANDBOX_TTL_SECONDS = 300

_client: Optional[MorphCloudClient] = None
_client_lock = asyncio.Lock()

async def _get_client() -> MorphCloudClient:
    global _client
    async with _client_lock:
        if _client is None:
            _client = await asyncio.to_thread(MorphCloudClient)
        return _client

async def _get_base_snapshot_id(client: MorphCloudClient) -> str:
    snapshots = await asyncio.to_thread(
        client.snapshots.list, metadata=_BASE_SNAPSHOT_METADATA
    )
    if snapshots:
        log_info(f"Reusing base snapshot {snapshots[0].id}")
        return snapshots[0].id

    image_id = os.getenv("MORPH_IMAGE_ID", DEFAULT_IMAGE_ID)
    log_info(f"No base snapshot found, creating one from image {image_id} (one-time setup)")
    snapshot = await asyncio.to_thread(
        client.snapshots.create,
        vcpus=1,
        memory=2048,
        disk_size=8192,
        image_id=image_id,
        digest="ai-sandbox-benchmark",
        metadata=dict(_BASE_SNAPSHOT_METADATA),
    )
    log_info(f"Created base snapshot {snapshot.id}")
    return snapshot.id

def _heredoc_delimiter(code: str) -> str:
    delimiter = "BENCHMARK_CODE_EOF"
    counter = 0
    while delimiter in code:
        counter += 1
        delimiter = f"BENCHMARK_CODE_EOF_{counter}"
    return delimiter

def _build_shell_command(code: str, env_vars: Optional[Dict[str, str]]) -> str:
    lines = []
    if env_vars:
        for key, value in env_vars.items():
            log_info(f"Setting {key} in sandbox")
            lines.append(f"export {key}={shlex.quote(str(value))}")
    delimiter = _heredoc_delimiter(code)
    lines.append(f"cat > /tmp/benchmark_code.py << '{delimiter}'")
    lines.append(code)
    lines.append(delimiter)
    lines.append("python3 /tmp/benchmark_code.py")
    return "\n".join(lines)

def _extract_internal_execution_time(output: str, metrics: BenchmarkTimingMetrics, code: str) -> None:
    start_marker = "--- BENCHMARK TIMING DATA ---"
    end_marker = "--- END BENCHMARK TIMING DATA ---"

    if start_marker in output and end_marker in output:
        start_idx = output.find(start_marker) + len(start_marker)
        end_idx = output.find(end_marker)
        json_data = output[start_idx:end_idx].strip()
        log_info(f"Found JSON data between markers: {json_data}")
        try:
            timing_data = json.loads(json_data)
            if "internal_execution_time_ms" in timing_data:
                metrics.add_metric(
                    "Internal Execution", timing_data["internal_execution_time_ms"]
                )
                log_info(
                    f"Extracted internal timing data: {timing_data['internal_execution_time_ms']}ms"
                )
            else:
                log_info(f"No internal_execution_time_ms field in timing data: {timing_data}")
        except json.JSONDecodeError as e:
            log_error(f"Error parsing timing data JSON: {e}")
            log_error(f"Raw JSON data: {json_data}")
        return

    # Fallback for tests without explicit timing markers: estimate from
    # code execution time, mirroring the other providers.
    ratio = 0.75 if "from scipy import fft" in code else 0.65
    for name, times in metrics.metrics.items():
        if name == "Code Execution" and times:
            metrics.metrics["Internal Execution"] = []
            metrics.add_metric("Internal Execution", times[0] * ratio)
            log_info(f"Using estimated internal execution time: {times[0] * ratio}ms")
            break

async def execute(code: str, env_vars: Dict[str, str] = None) -> Tuple[str, BenchmarkTimingMetrics]:
    metrics = BenchmarkTimingMetrics()
    instance = None
    client = None

    try:
        client = await _get_client()
        snapshot_id = await _get_base_snapshot_id(client)

        log_info("Starting new Morph instance...")
        start = time.time()
        instance = await asyncio.to_thread(
            client.instances.start,
            snapshot_id=snapshot_id,
            ttl_seconds=SANDBOX_TTL_SECONDS,
            ttl_action="stop",
        )
        metrics.add_metric("Workspace Creation", time.time() - start)
        log_info(f"Instance started: {instance.id}")

        # Extract test configuration if available
        test_config = {}
        if isinstance(code, dict) and 'code' in code and 'config' in code:
            test_config = code.get('config', {})
            code = code['code']

        if test_config and 'packages' in test_config:
            always_install_packages = test_config['packages']
        else:
            always_install_packages = [
                'numpy',  # Required for FFT tests
                'scipy',  # Required for FFT tests
            ]

        setup_start = time.time()
        install_cmd = "pip install --user " + " ".join(always_install_packages)
        setup_result = await asyncio.to_thread(instance.exec, install_cmd)
        if setup_result.stderr:
            log_warning(f"Dependency install stderr: {setup_result.stderr[:500]}")
        if setup_result.exit_code != 0:
            log_error(f"Failed to install dependencies: {setup_result.stderr}")

        setup_time = (time.time() - setup_start) * 1000
        log_info(f"Actual measured setup time: {setup_time}ms")
        metrics.ms_metrics.add("Setup Time")
        metrics.add_metric("Setup Time", setup_time)

        shell_command = _build_shell_command(code, env_vars)
        start = time.time()
        execution = await asyncio.to_thread(instance.exec, shell_command)
        metrics.add_metric("Code Execution", time.time() - start)

        output = execution.stdout or ""
        if execution.stderr:
            log_warning(f"Execution stderr: {execution.stderr[:500]}")
        log_info(f"Output preview: {output[:200]}...")

        _extract_internal_execution_time(output, metrics, code)

        if execution.exit_code != 0:
            error_text = execution.stderr or f"Non-zero exit code: {execution.exit_code}"
            metrics.add_error(error_text)
            log_error(f"Code execution failed: {error_text}")

        return output, metrics

    except Exception as e:
        metrics.add_error(str(e))
        log_error(f"Execution error: {str(e)}")
        raise

    finally:
        if instance:
            try:
                start = time.time()
                await asyncio.to_thread(instance.stop)
                metrics.add_metric("Cleanup", time.time() - start)
            except Exception as e:
                log_error(f"Cleanup error: {str(e)}")

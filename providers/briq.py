# ABOUTME: Briq provider - runs each test in a fresh Briq sandbox through the briq-cloud Python client.
# ABOUTME: Implements the standard provider interface: async execute(code, env_vars) returning (output, metrics).

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from briq_cloud import AsyncBriq, BriqError

from metrics import BenchmarkTimingMetrics

logger = logging.getLogger(__name__)


def log_info(message: str) -> None:
    logger.info(f"[Briq] {message}")


def log_error(message: str) -> None:
    logger.error(f"[Briq] {message}")


def log_warning(message: str) -> None:
    logger.warning(f"[Briq] {message}")


# The sizes Briq offers. Anything else is refused before a request is made.
SIZES = ("small", "medium", "large", "xlarge")
DEFAULT_SIZE = "small"

# Same default packages as the other providers, so setup time stays comparable.
DEFAULT_PACKAGES = ["numpy", "scipy"]

TEST_SCRIPT_PATH = "/tmp/benchmark_test.py"
SETUP_LOG_PATH = "/tmp/briq_setup.log"


def _read_config() -> Dict[str, Any]:
    """Read Briq settings at call time.

    The comparator loads .env after this module is imported, so the values
    cannot be read at import time.
    """
    size = os.getenv("BRIQ_SIZE", DEFAULT_SIZE)
    if size not in SIZES:
        raise ValueError(
            f"BRIQ_SIZE must be one of {', '.join(SIZES)}, got {size!r}"
        )
    return {
        "size": size,
        "image": os.getenv("BRIQ_IMAGE") or None,
        "create_timeout": float(os.getenv("BRIQ_CREATE_TIMEOUT_SECONDS", "180")),
        "setup_timeout": float(os.getenv("BRIQ_SETUP_TIMEOUT_SECONDS", "600")),
        "exec_timeout": float(os.getenv("BRIQ_EXEC_TIMEOUT_SECONDS", "900")),
    }


def _extract_test_config(code: Any) -> Tuple[str, Dict[str, Any]]:
    """Accept both a plain code string and the {code, config} test format."""
    if isinstance(code, dict) and "code" in code:
        return code["code"], code.get("config") or {}
    return code, {}


def _build_setup_command(packages: List[str]) -> str:
    if not packages:
        return "true"
    # The sandbox image is Ubuntu with Python. pip is installed only if it is
    # missing. PIP_BREAK_SYSTEM_PACKAGES is set by the caller (PEP 668).
    return (
        "{ python3 -m pip --version >/dev/null 2>&1 || "
        "{ apt-get update -qq && "
        "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-pip; }; } "
        f"> {SETUP_LOG_PATH} 2>&1 && "
        f"python3 -m pip install --quiet {' '.join(packages)} >> {SETUP_LOG_PATH} 2>&1; "
        f"ec=$?; tail -n 5 {SETUP_LOG_PATH}; exit $ec"
    )


def _output_of(result: Any) -> str:
    """Join stdout and stderr: the other providers return one combined stream."""
    return (result.stdout or "") + (result.stderr or "")


async def execute(code: str, env_vars: Optional[Dict[str, str]] = None) -> Tuple[str, BenchmarkTimingMetrics]:
    metrics = BenchmarkTimingMetrics()
    client: Optional[AsyncBriq] = None
    sandbox = None

    try:
        api_key = os.getenv("BRIQ_API_KEY")
        if not api_key:
            raise ValueError("BRIQ_API_KEY environment variable is not set")
        cfg = _read_config()
        # BRIQ_API_URL is read by the client itself.
        client = AsyncBriq(api_key=api_key)

        code, test_config = _extract_test_config(code)
        packages = test_config.get("packages", DEFAULT_PACKAGES)

        start = time.time()
        sandbox = await client.create_sandbox(
            size=cfg["size"],
            image=cfg["image"],
            wait_timeout=cfg["create_timeout"],
        )
        metrics.add_metric("Workspace Creation", time.time() - start)
        log_info(f"Created sandbox {sandbox.id}")

        # Environment variables go with each command only. They are never
        # stored in the sandbox's configuration.
        run_env = {str(k): str(v) for k, v in (env_vars or {}).items()}

        setup_start = time.time()
        setup = await sandbox.exec(
            _build_setup_command(packages),
            env={"PIP_BREAK_SYSTEM_PACKAGES": "1"},
            timeout=cfg["setup_timeout"],
        )
        setup_time_ms = (time.time() - setup_start) * 1000
        metrics.ms_metrics.add("Setup Time")
        metrics.add_metric("Setup Time", setup_time_ms)
        log_info(f"Setup finished in {setup_time_ms:.0f}ms (exit {setup.exit_code})")
        if setup.timed_out or setup.exit_code != 0:
            tail = _output_of(setup)[-500:]
            log_error(f"Setup failed: {tail}")
            metrics.add_error(
                f"Briq setup failed with exit code {setup.exit_code}: {tail}"
            )

        await sandbox.write_file(TEST_SCRIPT_PATH, code.encode("utf-8"))

        start = time.time()
        run = await sandbox.exec(
            ["python3", "-u", TEST_SCRIPT_PATH],
            env=run_env or None,
            timeout=cfg["exec_timeout"],
        )
        metrics.add_metric("Code Execution", time.time() - start)

        output = _output_of(run)
        log_info(f"Output preview: {output[:200]}")
        if run.timed_out:
            metrics.add_error(f"Test code timed out after {cfg['exec_timeout']:.0f}s")
        elif run.exit_code != 0:
            metrics.add_error(
                f"Test code exited with code {run.exit_code}: {output[-500:]}"
            )

        if output and metrics.extract_internal_timing(output):
            log_info("Extracted internal timing data from test output")

        return output, metrics

    except Exception as e:
        metrics.add_error(str(e))
        log_error(f"Execution error: {e}")
        raise

    finally:
        if sandbox is not None:
            try:
                start = time.time()
                await sandbox.destroy()
                metrics.add_metric("Cleanup", time.time() - start)
            except BriqError as e:
                log_error(f"Cleanup error: {e} (sandbox {sandbox.id} may still exist)")
            except Exception as e:
                log_error(f"Cleanup error: {e}")
        if client is not None:
            try:
                await client.close()
            except Exception as e:
                log_error(f"Client close error: {e}")

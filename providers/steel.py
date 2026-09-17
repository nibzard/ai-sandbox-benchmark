# ABOUTME: Steel computers provider — provisions a full Linux computer per run through the Steel HTTP API.
# ABOUTME: Implements the standard provider interface: async execute(code, env_vars) returning (output, metrics).

import asyncio
import base64
import logging
import os
import shlex
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from metrics import BenchmarkTimingMetrics

logger = logging.getLogger(__name__)


def log_info(message: str) -> None:
    logger.info(f"[Steel] {message}")


def log_error(message: str) -> None:
    logger.error(f"[Steel] {message}")


def log_warning(message: str) -> None:
    logger.warning(f"[Steel] {message}")


API_BASE_URL = "https://api.steel.dev"


def _read_config() -> Dict[str, Any]:
    """Read Steel settings at call time.

    The comparator loads .env after this module is imported, so the values
    cannot be read at import time.
    """
    return {
        "api_base": os.getenv("STEEL_API_BASE", API_BASE_URL),
        "create_timeout": int(os.getenv("STEEL_CREATE_TIMEOUT_SECONDS", "180")),
        "setup_timeout": int(os.getenv("STEEL_SETUP_TIMEOUT_SECONDS", "600")),
        "exec_timeout": int(os.getenv("STEEL_EXEC_TIMEOUT_SECONDS", "900")),
        "vcpu": int(os.getenv("STEEL_VCPU", "2")),
        "memory_mib": int(os.getenv("STEEL_MEMORY_MIB", "2048")),
    }


# The default Steel Debian image has no Python. It is installed on every run
# before the test code can execute.
BOOTSTRAP_COMMAND = (
    "apt-get update -qq && "
    "DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-pip"
)

# Same default packages as the other providers, so setup time stays comparable.
DEFAULT_PACKAGES = ["numpy", "scipy"]

# Statuses a computer passes through before it is usable.
TRANSITIONAL_STATUSES = {"creating", "starting", "pending", "provisioning", "resuming"}

TEST_SCRIPT_PATH = "/tmp/benchmark_test.py"


class SteelApiError(Exception):
    """Raised when the Steel computers API returns an unrecoverable error."""


class SteelClient:
    """Synchronous client for the Steel computers preview API."""

    def __init__(self, api_key: str, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "steel-api-key": api_key,
            "content-type": "application/json",
            # The API rejects the default python-urllib user agent.
            "User-Agent": "ai-sandbox-benchmark",
        })

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        idempotent: bool = True,
    ) -> Dict[str, Any]:
        """Call the API, retrying only failures that provably had no effect.

        For non-idempotent requests a retry can duplicate work server-side
        (for example a second computer), so those retry only when the
        connection failed before the request reached the server.
        """
        url = f"{self.base_url}{path}"
        last_error: Exception = SteelApiError(f"{method} {path} failed")
        for attempt in range(3):
            try:
                response = self.session.request(method, url, json=body, timeout=timeout)
                if response.status_code < 400:
                    return response.json() if response.content else {}
                error = SteelApiError(
                    f"{method} {path} -> HTTP {response.status_code}: {response.text[:200]}"
                )
                if response.status_code != 429 and response.status_code < 500:
                    raise error
                # A 5xx response is ambiguous: the server may already have
                # done the work. A 429 was refused before any work.
                if response.status_code >= 500 and not idempotent:
                    raise error
                last_error = error
            except requests.exceptions.RequestException as e:
                last_error = SteelApiError(f"{method} {path} failed: {e}")
                # Connection errors never reached the server, so they are
                # always safe to retry. Timeouts after the request was sent
                # are not.
                if not idempotent and not isinstance(e, requests.exceptions.ConnectionError):
                    raise last_error
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
        raise last_error

    def create_computer(self, vcpu: int, memory_mib: int) -> Dict[str, Any]:
        # Not idempotent: a blind retry after a lost response would start a
        # second computer that never gets cleaned up.
        return self._request(
            "POST", "/v1/computers",
            body={"vcpu": vcpu, "memoryMib": memory_mib},
            idempotent=False,
        )

    def get_computer(self, computer_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/computers/{computer_id}")

    def wait_until_running(self, computer_id: str, timeout_seconds: int) -> Dict[str, Any]:
        deadline = time.time() + timeout_seconds
        while True:
            computer = self.get_computer(computer_id)
            status = computer.get("status")
            if status == "running":
                return computer
            if status not in TRANSITIONAL_STATUSES:
                raise SteelApiError(
                    f"Computer {computer_id} entered unexpected status {status!r}"
                )
            if time.time() >= deadline:
                raise SteelApiError(
                    f"Computer {computer_id} not running after {timeout_seconds}s "
                    f"(status {status!r})"
                )
            time.sleep(2)

    def exec_command(self, computer_id: str, command: str, timeout_seconds: int) -> Dict[str, Any]:
        body = {"command": command, "stream": False, "timeoutSeconds": timeout_seconds}
        return self._request(
            "POST", f"/v1/computers/{computer_id}/exec", body=body,
            timeout=timeout_seconds + 60,
        )

    def delete_computer(self, computer_id: str) -> Dict[str, Any]:
        return self._request("DELETE", f"/v1/computers/{computer_id}")


def _extract_test_config(code: Any) -> Tuple[str, Dict[str, Any]]:
    """Accept both a plain code string and the {code, config} test format."""
    if isinstance(code, dict) and "code" in code:
        return code["code"], code.get("config") or {}
    return code, {}


def _build_setup_command(packages: List[str]) -> str:
    pip_install = (
        f"python3 -m pip install --user --quiet --break-system-packages {' '.join(packages)}"
        if packages
        else "true"
    )
    # Debian 13 enforces PEP 668, so --break-system-packages is required.
    return (
        f"{BOOTSTRAP_COMMAND} > /tmp/steel_setup.log 2>&1 && "
        f"{pip_install} >> /tmp/steel_setup.log 2>&1; "
        f"ec=$?; tail -n 5 /tmp/steel_setup.log; exit $ec"
    )


def _build_run_command(code: str, env_vars: Optional[Dict[str, str]]) -> str:
    # Base64 keeps the code safe from shell quoting rules.
    encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
    exports = "".join(
        f"export {key}={shlex.quote(str(value))}; "
        for key, value in (env_vars or {}).items()
    )
    return (
        f"{exports}"
        f"printf %s '{encoded}' | base64 -d > {TEST_SCRIPT_PATH} && "
        f"python3 -u {TEST_SCRIPT_PATH} 2>&1"
    )


async def execute(code: str, env_vars: Dict[str, str] = None) -> Tuple[str, BenchmarkTimingMetrics]:
    metrics = BenchmarkTimingMetrics()
    client: Optional[SteelClient] = None
    computer_id: Optional[str] = None

    try:
        api_key = os.getenv("STEEL_API_KEY")
        if not api_key:
            raise ValueError("STEEL_API_KEY environment variable is not set")
        cfg = _read_config()
        client = SteelClient(api_key, cfg["api_base"])

        code, test_config = _extract_test_config(code)
        packages = test_config.get("packages", DEFAULT_PACKAGES)

        start = time.time()
        computer = await asyncio.to_thread(client.create_computer, cfg["vcpu"], cfg["memory_mib"])
        computer_id = computer.get("id")
        if not computer_id:
            raise SteelApiError(f"Create response did not contain an id: {computer}")
        await asyncio.to_thread(client.wait_until_running, computer_id, cfg["create_timeout"])
        metrics.add_metric("Workspace Creation", time.time() - start)
        log_info(f"Created computer {computer_id}")

        setup_start = time.time()
        setup = await asyncio.to_thread(
            client.exec_command, computer_id, _build_setup_command(packages), cfg["setup_timeout"]
        )
        setup_time_ms = (time.time() - setup_start) * 1000
        metrics.ms_metrics.add("Setup Time")
        metrics.add_metric("Setup Time", setup_time_ms)
        log_info(f"Setup finished in {setup_time_ms:.0f}ms (exit {setup.get('exitCode')})")
        if setup.get("exitCode") != 0:
            tail = (setup.get("output") or "")[-500:]
            log_error(f"Setup failed: {tail}")
            metrics.add_error(
                f"Steel setup failed with exit code {setup.get('exitCode')}: {tail}"
            )

        start = time.time()
        run = await asyncio.to_thread(
            client.exec_command, computer_id, _build_run_command(code, env_vars), cfg["exec_timeout"]
        )
        metrics.add_metric("Code Execution", time.time() - start)

        output = run.get("output") or ""
        log_info(f"Output preview: {output[:200]}")
        if run.get("truncated"):
            log_warning("Output was truncated by the Steel API")
        if run.get("timedOut"):
            metrics.add_error(f"Test code timed out after {cfg['exec_timeout']}s")
        elif run.get("exitCode") != 0:
            metrics.add_error(
                f"Test code exited with code {run.get('exitCode')}: {output[-500:]}"
            )

        if output and metrics.extract_internal_timing(output):
            log_info("Extracted internal timing data from test output")

        return output, metrics

    except Exception as e:
        metrics.add_error(str(e))
        log_error(f"Execution error: {e}")
        raise

    finally:
        if client and computer_id:
            try:
                start = time.time()
                await asyncio.to_thread(client.delete_computer, computer_id)
                metrics.add_metric("Cleanup", time.time() - start)
            except Exception as e:
                log_error(f"Cleanup error: {e}")

# ABOUTME: Unit tests for the Briq provider, with a fake briq-cloud client (no network).
# ABOUTME: Lives outside tests/ so the comparator does not load it as a sandbox workload.
import asyncio
import json
from types import SimpleNamespace

import pytest

import comparator
from providers import briq as briq_provider

TIMING_OUTPUT = (
    "hello\n--- BENCHMARK TIMING DATA ---\n"
    + json.dumps({"internal_execution_time_ms": 12.5})
    + "\n--- END BENCHMARK TIMING DATA ---\n"
)


def result(stdout="", stderr="", exit_code=0, timed_out=False):
    return SimpleNamespace(stdout=stdout, stderr=stderr, exit_code=exit_code, timed_out=timed_out)


class FakeSandbox:
    id = "bq_fake"

    def __init__(self, results, destroy_error=None):
        self.results = list(results)
        self.destroy_error = destroy_error
        self.execs = []
        self.files = {}
        self.destroyed = False

    async def exec(self, command, *, cwd=None, env=None, stdin=None, timeout=60.0, on_output=None):
        self.execs.append({"command": command, "env": env, "timeout": timeout})
        return self.results.pop(0)

    async def write_file(self, path, data, *, mode=None):
        self.files[path] = data

    async def destroy(self):
        self.destroyed = True
        if self.destroy_error:
            raise self.destroy_error


class FakeClient:
    instances = []

    def __init__(self, sandbox, create_error=None, api_key=None, **kwargs):
        self.sandbox = sandbox
        self.create_error = create_error
        self.api_key = api_key
        self.create_args = None
        self.closed = False

    async def create_sandbox(self, **kwargs):
        self.create_args = kwargs
        if self.create_error:
            raise self.create_error
        return self.sandbox

    async def close(self):
        self.closed = True


@pytest.fixture
def install_client(monkeypatch):
    monkeypatch.setenv("BRIQ_API_KEY", "test-key")
    for name in ("BRIQ_SIZE", "BRIQ_IMAGE"):
        monkeypatch.delenv(name, raising=False)
    clients = []

    def install(sandbox, create_error=None):
        def factory(api_key=None, **kwargs):
            client = FakeClient(sandbox, create_error=create_error, api_key=api_key, **kwargs)
            clients.append(client)
            return client

        monkeypatch.setattr(briq_provider, "AsyncBriq", factory)
        return clients

    return install


def run(code, env_vars=None):
    return asyncio.run(briq_provider.execute(code, env_vars))


def test_provider_is_registered():
    assert comparator.provider_executors["briq"] is briq_provider.execute


def test_extract_test_config_accepts_plain_and_dict_code():
    assert briq_provider._extract_test_config("print(1)") == ("print(1)", {})
    code, config = briq_provider._extract_test_config({"code": "x", "config": {"packages": ["a"]}})
    assert (code, config) == ("x", {"packages": ["a"]})


def test_setup_command_installs_packages_and_skips_when_empty():
    command = briq_provider._build_setup_command(["numpy", "scipy"])
    assert "python3 -m pip install --quiet numpy scipy" in command
    assert briq_provider._build_setup_command([]) == "true"


def test_missing_api_key_fails_before_any_request(monkeypatch):
    monkeypatch.delenv("BRIQ_API_KEY", raising=False)
    created = []
    monkeypatch.setattr(briq_provider, "AsyncBriq", lambda **kw: created.append(kw))
    with pytest.raises(ValueError, match="BRIQ_API_KEY"):
        run("print(1)")
    assert created == []


@pytest.mark.parametrize("size", ["tiny", "2xlarge", "SMALL", "xs"])
def test_unsupported_size_fails_before_any_request(monkeypatch, install_client, size):
    sandbox = FakeSandbox([])
    clients = install_client(sandbox)
    monkeypatch.setenv("BRIQ_SIZE", size)
    with pytest.raises(ValueError, match="BRIQ_SIZE"):
        run("print(1)")
    assert all(client.create_args is None for client in clients)
    assert not sandbox.destroyed


@pytest.mark.parametrize("size", ["small", "medium", "large", "xlarge"])
def test_supported_sizes_reach_create(monkeypatch, install_client, size):
    sandbox = FakeSandbox([result(), result("ok")])
    clients = install_client(sandbox)
    monkeypatch.setenv("BRIQ_SIZE", size)
    run("print(1)")
    assert clients[0].create_args["size"] == size


def test_default_size_is_small(install_client):
    sandbox = FakeSandbox([result(), result("ok")])
    clients = install_client(sandbox)
    run("print(1)")
    assert clients[0].create_args["size"] == "small"
    assert clients[0].create_args["image"] is None


def test_happy_path_returns_output_metrics_and_cleans_up(install_client):
    sandbox = FakeSandbox([result(), result(TIMING_OUTPUT)])
    clients = install_client(sandbox)
    output, metrics = run({"code": "print('hello')", "config": {"packages": ["numpy"]}})

    assert "hello" in output
    assert clients[0].api_key == "test-key"
    assert sandbox.files[briq_provider.TEST_SCRIPT_PATH] == b"print('hello')"
    assert "numpy" in sandbox.execs[0]["command"]
    assert sandbox.execs[1]["command"] == ["python3", "-u", briq_provider.TEST_SCRIPT_PATH]
    assert sandbox.destroyed and clients[0].closed

    stats = metrics.get_statistics()
    for name in ("Workspace Creation", "Setup Time", "Code Execution", "Internal Execution", "Cleanup"):
        assert name in stats, name
    assert stats["Internal Execution"]["median"] == 12.5
    assert not metrics.errors


def test_env_vars_go_to_the_test_command_only(install_client):
    sandbox = FakeSandbox([result(), result("ok")])
    clients = install_client(sandbox)
    run("print(1)", {"OPENAI_API_KEY": "secret-value"})

    assert clients[0].create_args.get("env") is None
    assert clients[0].create_args.get("secret_env") is None
    assert sandbox.execs[1]["env"] == {"OPENAI_API_KEY": "secret-value"}
    assert "secret-value" not in str(sandbox.execs[0])


def test_no_env_vars_passes_no_env(install_client):
    sandbox = FakeSandbox([result(), result("ok")])
    install_client(sandbox)
    run("print(1)")
    assert sandbox.execs[1]["env"] is None


def test_stderr_is_part_of_the_output(install_client):
    sandbox = FakeSandbox([result(), result("out\n", "warn\n")])
    install_client(sandbox)
    output, _ = run("print(1)")
    assert output == "out\nwarn\n"


def test_failed_setup_is_recorded_and_the_test_still_runs(install_client):
    sandbox = FakeSandbox([result("pip failed", exit_code=1), result("ok")])
    install_client(sandbox)
    output, metrics = run("print(1)")
    assert output == "ok"
    assert any("setup failed" in e for e in metrics.errors)
    assert sandbox.destroyed


def test_nonzero_exit_and_timeout_are_recorded(install_client):
    sandbox = FakeSandbox([result(), result("boom", exit_code=2)])
    install_client(sandbox)
    _, metrics = run("print(1)")
    assert any("exited with code 2" in e for e in metrics.errors)

    sandbox = FakeSandbox([result(), result("", exit_code=None, timed_out=True)])
    install_client(sandbox)
    _, metrics = run("print(1)")
    assert any("timed out" in e for e in metrics.errors)


def test_exec_failure_still_destroys_the_sandbox(install_client):
    class Broken(FakeSandbox):
        async def exec(self, *args, **kwargs):
            raise RuntimeError("connection lost")

    sandbox = Broken([])
    clients = install_client(sandbox)
    with pytest.raises(RuntimeError, match="connection lost"):
        run("print(1)")
    assert sandbox.destroyed and clients[0].closed


def test_create_failure_raises_and_closes_the_client(install_client):
    sandbox = FakeSandbox([])
    clients = install_client(sandbox, create_error=RuntimeError("quota"))
    with pytest.raises(RuntimeError, match="quota"):
        run("print(1)")
    assert not sandbox.destroyed
    assert clients[0].closed


@pytest.mark.parametrize("destroy_error", [RuntimeError("gone"), briq_provider.BriqError("network", "gone")])
def test_cleanup_failure_does_not_hide_the_result(install_client, destroy_error):
    sandbox = FakeSandbox([result(), result("ok")], destroy_error=destroy_error)
    clients = install_client(sandbox)
    output, metrics = run("print(1)")
    assert output == "ok"
    assert len(metrics.errors) == 1
    assert "Cleanup failed: gone" in metrics.errors[0]
    assert "sandbox bq_fake may still exist" in metrics.errors[0]
    assert clients[0].closed

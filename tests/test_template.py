"""
Template for creating new benchmark tests.

Copy this file, rename it to test_<your_name>.py, and adjust TEST_META and the
test code. The comparator discovers every test_<your_name>.py module in this
directory that defines a test_ function.
"""
from tests.test_utils import create_test_config

# Declarative test contract: the harness reads this instead of calling the test
# function to learn how to orchestrate the test. "slug" must be unique and
# stable; it becomes the history and results key (test_<slug>).
TEST_META = {
    "slug": "template",
    "description": "Template for new benchmark tests",
    "single_run": False,  # True: run once per benchmark session, ignoring --runs
    "info_test": False,   # True: render as an information report, not a timing table
}


def test_template():
    """
    Template test function that demonstrates the recommended test structure.

    This is a docstring that should describe what the test does and what it measures.
    """
    # Runtime payload configuration: environment variables and packages the
    # sandboxed code needs. Orchestration flags live in TEST_META, not here.
    config = create_test_config(
        env_vars=[],  # List any environment variables needed
        packages=["numpy"],  # List required packages
    )

    # Return the test configuration and code
    return {
        "config": config,
        "code": """
import time
import json

# Standardized timing decorator
def benchmark_timer(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        return {
            "result": result,
            "execution_time_ms": (time.time() - start) * 1000
        }
    return wrapper

# Install any required packages
try:
    import numpy as np
    print("Successfully imported numpy")
except ImportError:
    print("Installing numpy...")
    import sys
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "numpy"])
    import numpy as np

@benchmark_timer
def run_benchmark():
    arr = np.random.random((1000, 1000))
    for _ in range(10):
        np.dot(arr, arr.T)
    return "Benchmark completed successfully"

test_result = run_benchmark()
print(test_result["result"])
print(f'Execution Time: {test_result["execution_time_ms"] / 1000:.2f}s')

# Print timing in a standardized JSON format that can be parsed by the benchmark
print("\\n\\n--- BENCHMARK TIMING DATA ---")
print(json.dumps({"internal_execution_time_ms": test_result["execution_time_ms"]}))
print("--- END BENCHMARK TIMING DATA ---")
"""
    }

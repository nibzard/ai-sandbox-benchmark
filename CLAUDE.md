# AI Sandbox Benchmark Commands & Style Guide

## Commands
- Run all benchmarks: `python comparator.py`
- Run specific tests: `python comparator.py --tests 1,2 --providers daytona,e2b`
- Run single test: `python comparator.py --tests 1 --providers daytona`
- Run on local machine: `python comparator.py --providers local`
- Adjust runs: `python comparator.py --runs 5 --warmup-runs 2`
- Change region: `python comparator.py --target-region us`
- Burst benchmark: `python burst.py --providers local --burst-size 10`
- Unit tests: `python -m pytest unit_tests`
- Export run records: `python export_results.py --out-dir results --limit 5`

## Testing Setup
- Start CodeSandbox service first: `cd providers && node codesandbox-service.js`
- Ensure environment variables are set in .env file (not needed when using only the local provider)
- Some tests will run only once regardless of `--runs` parameter (those with `single_run = True` property)

## Code Style
- Imports: standard library first, then third-party, then local imports
- Type hints: Use Python typing module for all functions and classes
- Error handling: Use try/except blocks with specific exceptions
- Naming: snake_case for functions/variables, CamelCase for classes
- Async: Use asyncio for concurrent operations
- Documentation: Use docstrings for all public functions and classes

## Providers Implementation
- All provider modules must implement an `execute(code, ...)` function
- Always properly handle resource cleanup in finally blocks
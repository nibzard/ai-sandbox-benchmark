# Provider Implementations for AI Sandbox Benchmark

This directory contains implementations for various sandbox providers supported by the AI Sandbox Benchmark project.

## Supported Providers

The benchmark currently supports the following execution environments:

- **Daytona** - Cloud-based code execution environment (daytona.py)
- **e2b** - Code interpreter environment (e2b.py)
- **CodeSandbox** - Browser-based sandbox environment (codesandbox.py)
- **Modal** - Serverless compute platform (modal.py)
- **Local** - Local machine execution for baseline comparison (local.py)
- **Morph** - Morph Cloud platform for secure AI code execution (morph.py)
- **Steel** - Full Linux computers accessed through the Steel API (steel.py)

## Provider Setup Instructions

### CodeSandbox

1. **Install Node.js Dependencies and Start the CodeSandbox Service**

   Before running benchmarks with CodeSandbox, start the CodeSandbox service:

   ```bash
   npm install && node providers/codesandbox-service.js
   ```
   This service handles the communication between the benchmark and the CodeSandbox API.

### Daytona

Daytona requires API credentials to access their cloud-based execution environment:

1. Create a Daytona account at [daytona.io](https://daytona.io)
2. Get your API key from the Daytona dashboard
3. Add to your `.env` file:
   ```
   DAYTONA_API_KEY=your_daytona_api_key
   DAYTONA_SERVER_URL=your_daytona_server_url
   ```

#### Warm Pools Feature

The Daytona implementation includes support for their warm sandbox pools, which significantly improves workspace creation time:

- Automatically pings Daytona's API before creating workspaces to activate warm pools
- Measures and tracks warmup time in performance metrics
- Use `daytona.list_workspaces(target_region)` to manually activate warm pools

### e2b

e2b requires an API key for their code execution environment:

1. Create an account at [e2b.io](https://e2b.io)
2. Obtain your API key from your account settings
3. Add to your `.env` file:
   ```
   E2B_API_KEY=your_e2b_api_key
   ```

### Modal

Modal uses CLI-based authentication instead of API keys:

1. Create an account at [modal.com](https://modal.com)
2. Install the Modal Python package: `pip install modal`
3. Authenticate with Modal: `modal setup` (if this doesn't work, try `python -m modal setup`)

### Local Provider

The local provider runs tests directly on your machine without any additional setup, making it useful for establishing baseline performance.

### Morph

Morph requires an API key for accessing their sandbox environment:

1. Create an account at [cloud.morph.so](https://cloud.morph.so)
2. Get your API key from https://cloud.morph.so/web/api-keys
3. Add to your `.env` file:
   ```
   # Required
   MORPH_API_KEY=your_morph_api_key

   # Optional configuration (uncomment if needed)
   # MORPH_BASE_URL=https://cloud.morph.so/api  # Default API URL
   # MORPH_SSH_HOSTNAME=ssh.cloud.morph.so      # Default SSH hostname
   # MORPH_SSH_PORT=22                          # Default SSH port
   ```
4. Install the Morph Cloud SDK: `pip install morphcloud`

### Steel

Steel provides full Linux computers through an HTTP API (private beta / preview):

1. Activate computer access at [app.steel.dev/computer-access](https://app.steel.dev/computer-access)
2. Get your API key at [app.steel.dev/settings/api-keys](https://app.steel.dev/settings/api-keys)
3. Add to your `.env` file:
   ```
   STEEL_API_KEY=your_steel_api_key

   # Optional configuration (uncomment if needed)
   # STEEL_API_BASE=https://api.steel.dev     # Default API URL
   # STEEL_VCPU=2                             # Machine size (default: 2 vCPU)
   # STEEL_MEMORY_MIB=2048                    # Machine memory (default: 2048 MiB)
   # STEEL_EXEC_TIMEOUT_SECONDS=900           # Per-command timeout (default: 900)
   ```

Note: the default Steel Debian image ships without Python. The provider installs
`python3` and `pip` with `apt`, then the test packages with `pip`, as part of the
measured setup time. Each test run creates a fresh computer and deletes it when
done.

## Provider Configuration

Provider-specific settings can be configured in the `config.yml` file in the project root:

```yaml
# Environment variables to pass to sandboxes
env_vars:
  pass_to_sandbox:
    - OPENAI_API_KEY
    # Add other variables as needed

# Provider-specific settings
providers:
  daytona:
    default_region: eu
```

## Implementation Details

Each provider module implements an `execute(code, ...)` function that handles:

1. Creating and configuring the execution environment
2. Executing the provided code
3. Collecting and returning results
4. Cleaning up resources

The provider implementation handles measuring its own performance metrics including workspace creation time, execution time, and cleanup time.

## Adding New Providers

To add a new provider:

1. Create a new Python file in the `providers` directory (e.g., `newprovider.py`)
2. Implement the required interface, following the pattern of existing providers
3. Make sure to properly handle resource cleanup in finally blocks
4. Update `__init__.py` to expose your new provider
5. Add provider-specific documentation to this README
# ffai-workflow-adapters

[![PyPI](https://img.shields.io/pypi/v/ffai-workflow-adapters.svg)](https://pypi.org/project/ffai-workflow-adapters/)
[![Docs](https://readthedocs.org/projects/ffai-workflow-adapters/badge/?version=latest)](https://ffai-workflow-adapters.readthedocs.io/en/latest/)
[![CI](https://github.com/antquinonez/ffai-workflow-adapters/actions/workflows/ci.yml/badge.svg)](https://github.com/antquinonez/ffai-workflow-adapters/actions/workflows/ci.yml)

External workflow adapters for [ffai](https://pypi.org/project/ffai/) — define and execute LLM workflows from Airtable, Excel, and other tabular sources. Each row in a spreadsheet becomes a workflow step (name, prompt, model, temperature, etc.).

**Documentation**: https://ffai-workflow-adapters.readthedocs.io/en/latest/

## Installation

```bash
pip install ffai-workflow-adapters
```

With optional adapters:

```bash
pip install ffai-workflow-adapters[airtable]
pip install ffai-workflow-adapters[excel]
pip install ffai-workflow-adapters[all]
```

Or with uv:

```bash
uv pip install ffai-workflow-adapters
uv pip install ffai-workflow-adapters[airtable]
```

## Quick Start

```python
import asyncio
import os

from dotenv import load_dotenv
from ffai import FFAI
from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient
from ffai_workflow_adapters import load_workflow_airtable, write_workflow_results

load_dotenv()


async def main():
    from ffai_workflow_adapters import get_config

    config = get_config()
    client_cfg = config.clients.get_client_type(config.clients.default_client)
    client = AsyncFFLiteLLMClient(
        model_string=f"{client_cfg.provider_prefix}{client_cfg.default_model}",
        api_key=os.environ.get(client_cfg.api_key_env, ""),
    )
    ffai = FFAI(client)

    base_id = os.environ["AIRTABLE_BASE_ID"]
    spec = load_workflow_airtable(base_id, "Workflow Steps", view="basic", name="my_workflow")

    result = await ffai.execute_workflow(spec)

    write_workflow_results(base_id, "_results", result)


asyncio.run(main())
```

## How It Works

1. **Define** your workflow as rows in Airtable or Excel — each row is a step with a name, prompt, model, and optional parameters
2. **Load** the table into a `WorkflowSpec` using the adapter for your data source
3. **Execute** with ffai — steps run sequentially, with `{{step.response}}` interpolation chaining outputs between steps
4. **Write back** results (response, tokens, cost, duration) to your data source

### Example Workflow Table

| name | prompt | client | history | temperature |
|------|--------|--------|---------|-------------|
| `topic` | `Name a famous scientific discovery and explain it in one sentence.` | `litellm-mistral-small` | | `0.7` |
| `explain` | `Given this discovery: {{topic.response}} — write a paragraph about its impact.` | `litellm-gpt-4o-mini` | `topic` | `0.5` |

## Adapters

| Adapter | Install | Documentation |
|---------|---------|---------------|
| Airtable | `pip install ffai-workflow-adapters[airtable]` | [Airtable adapter guide](docs/airtable.md) |
| Excel | `pip install ffai-workflow-adapters[excel]` | [Excel adapter guide](docs/excel.md) |

## Configuration

Uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) with YAML files and environment variable overrides.

### Config Files

| File | Purpose |
|------|---------|
| `config/main.yaml` | Retry and resilience settings |
| `config/adapters.yaml` | Per-adapter field maps, passthrough columns, named variants |
| `config/clients.yaml` | LLM client definitions (LiteLLM providers) |
| `config/logging.yaml` | Logging configuration |

### Priority (highest to lowest)

1. Explicit constructor kwargs
2. Environment variables (nested delimiter `__`, e.g., `RETRY__MAX_ATTEMPTS=5`)
3. Merged YAML files from `config/`

### Clients

Define named clients in `config/clients.yaml` and reference them by name in your data source's `client` column:

```yaml
default_client: litellm-mistral-small

client_types:
  litellm-mistral-small:
    type: litellm
    api_key_env: MISTRAL_API_KEY
    provider_prefix: "mistral/"
    default_model: mistral-small-latest

  litellm-gpt-4o-mini:
    type: litellm
    api_key_env: OPENAI_API_KEY
    provider_prefix: "openai/"
    default_model: gpt-4o-mini
    fallbacks:
      - mistral/mistral-small-latest
```

### Resilience

Airtable operations are protected by rate limiting, circuit breakers, and retries with exponential backoff. All settings are in `config/main.yaml` and tunable via environment variables:

```yaml
resilience:
  rate_limit:
    requests_per_second: 5.0
    burst: 10
  circuit_breaker:
    failure_threshold: 5
    recovery_timeout_seconds: 30
    half_open_max_calls: 3
  batch:
    chunk_size: 10
    max_concurrency: 3
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MISTRAL_API_KEY` | Yes | Mistral API key (default model) |
| `OPENAI_API_KEY` | For GPT models | OpenAI API key |
| `AIRTABLE_API_KEY` | For Airtable | Airtable personal access token |
| `AIRTABLE_BASE_ID` | For Airtable | Airtable base ID |

## API Reference

### `load_workflow_airtable(base_id, table_name, *, ...)`

Load a workflow spec from an Airtable table. Supports `view`, `adapter` (named variant), `name`, `defaults`, `clients`, `tools`, and more.

### `write_workflow_results(base_id, table_name, result, *, ...)`

Write workflow execution results back to an Airtable table. Creates one record per step.

### `load_workflow_excel(path, *, ...)`

Load a workflow spec from an Excel `.xlsx` file. Supports `sheet`, `adapter`, `name`, `defaults`, `clients`, `tools`.

### `write_workflow_results_excel(result, path=None, *, sheet=None, adapter=None, spec=None, run_id=None)`

Write results to an Excel file. `path` and `sheet` default to values from `config/adapters.yaml`. Pass `spec=` to include passthrough columns. Pass `run_id=` for a custom run ID (auto-generated if omitted).

### `get_config()`

Get the global configuration singleton.

### `reload_config()`

Reload configuration from YAML files.

## License

MIT

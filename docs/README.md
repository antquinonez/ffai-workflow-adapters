# ffai-workflow-adapters

External workflow adapters for [ffai](https://pypi.org/project/ffai/) — load and execute workflows from Airtable, Google Sheets, and other tabular sources.

## Installation

```bash
pip install ffai-workflow-adapters

# With Airtable support
pip install ffai-workflow-adapters[airtable]

# With Excel support
pip install ffai-workflow-adapters[excel]

# With both
pip install ffai-workflow-adapters[all]
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
    # Create a default client (resolves from config/clients.yaml)
    from ffai_workflow_adapters import get_config
    config = get_config()
    client_cfg = config.clients.get_client_type(config.clients.default_client)
    client = AsyncFFLiteLLMClient(
        model_string=f"{client_cfg.provider_prefix}{client_cfg.default_model}",
        api_key=os.environ.get(client_cfg.api_key_env, ""),
    )
    ffai = FFAI(client)

    # Load workflow from Airtable
    base_id = os.environ["AIRTABLE_BASE_ID"]
    spec = load_workflow_airtable(base_id, "Workflow Steps", view="basic", name="my_workflow")

    # Execute
    result = await ffai.execute_workflow(spec)

    # Write results back to Airtable
    write_workflow_results(base_id, "_results", result)

asyncio.run(main())
```

## Adapters

| Adapter | Status | Documentation |
|---------|--------|---------------|
| Airtable | Available | [docs/airtable.md](airtable.md) |
| Excel | Available | [docs/excel.md](excel.md) |
| Google Sheets | Planned | — |

## Configuration

The config system uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) with YAML files and environment variable overrides, mirroring ffai's config pattern.

### Config Files

| File | Purpose |
|------|---------|
| `config/main.yaml` | Retry settings |
| `config/adapters.yaml` | Per-adapter settings, field maps, passthrough, extra output columns |
| `config/logging.yaml` | Logging configuration |
| `config/clients.yaml` | LiteLLM client definitions |

### Priority (highest to lowest)

1. Explicit constructor kwargs
2. Environment variables (nested delimiter `__`, e.g., `RETRY__MAX_ATTEMPTS=5`)
3. Merged YAML files from `config/`

### Clients

Define named clients in `config/clients.yaml` and reference them from your data source:

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

Reference by name in your data source's `client` column. Leave blank for the default.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MISTRAL_API_KEY` | Yes | Mistral API key (default model) |
| `OPENAI_API_KEY` | For GPT models | OpenAI API key |
| `AIRTABLE_API_KEY` | For Airtable | Airtable personal access token |
| `AIRTABLE_BASE_ID` | For Airtable | Airtable base ID |

## API Reference

### `load_workflow_airtable(base_id, table_name, ...)`

Load a workflow spec from an Airtable table.

### `write_workflow_results(base_id, table_name, result, ...)`

Write workflow execution results back to an Airtable table.

### `load_workflow_excel(path, ...)`

Load a workflow spec from an Excel (.xlsx) file.

### `write_workflow_results_excel(result, path=None, *, sheet=None, adapter=None, spec=None, run_id=None)`

Write workflow execution results to an Excel file. `path` and `sheet` default to `output_path`/`output_sheet` from config. Pass `spec=` to include passthrough columns. Pass `run_id=` for a custom run ID (auto-generated timestamp if omitted).

### `get_config()`

Get the global configuration singleton.

### `reload_config()`

Reload configuration from YAML files.

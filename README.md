# ffai-workflow-adapters

[![PyPI](https://img.shields.io/pypi/v/ffai-workflow-adapters.svg)](https://pypi.org/project/ffai-workflow-adapters/)
[![Docs](https://readthedocs.org/projects/ffai-workflow-adapters/badge/?version=latest)](https://ffai-workflow-adapters.readthedocs.io/en/latest/)
[![CI](https://github.com/antquinonez/ffai-workflow-adapters/actions/workflows/ci.yml/badge.svg)](https://github.com/antquinonez/ffai-workflow-adapters/actions/workflows/ci.yml)

External workflow adapters for [ffai](https://pypi.org/project/ffai/) — define and execute LLM workflows from Airtable, Excel, CSV, Google Sheets, ODS, and other tabular sources. Each row in a spreadsheet becomes a workflow step (name, prompt, model, temperature, etc.).

**Documentation**: https://ffai-workflow-adapters.readthedocs.io/en/latest/

## Installation

```bash
pip install ffai-workflow-adapters
```

With optional adapters:

```bash
pip install ffai-workflow-adapters[airtable]
pip install ffai-workflow-adapters[excel]
pip install ffai-workflow-adapters[google_sheets]
pip install ffai-workflow-adapters[ods]
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
from ffai_workflow_adapters import load_workflow_excel, write_workflow_results_excel

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

    spec = load_workflow_excel("workflow.xlsx", name="my_workflow")

    result = await ffai.execute_workflow(spec)

    write_workflow_results_excel(result, path="results.xlsx")


asyncio.run(main())
```

## How It Works

1. **Define** your workflow as rows in a spreadsheet — each row is a step with a name, prompt, model, and optional parameters
2. **Load** the table into a `WorkflowSpec` using the adapter for your data source
3. **Execute** with ffai — steps run sequentially, with `{{step.response}}` interpolation chaining outputs between steps
4. **Write back** results (response, tokens, cost, duration) to your data source

### Example Workflow Table

| name | prompt | client | history | temperature |
|------|--------|--------|---------|-------------|
| `topic` | `Name a famous scientific discovery and explain it in one sentence.` | `litellm-mistral-small` | | `0.7` |
| `explain` | `Given this discovery: {{topic.response}} — write a paragraph about its impact.` | `litellm-gpt-4o-mini` | `topic` | `0.5` |

## Adapters

| Adapter | Format | Install | Documentation |
|---------|--------|---------|---------------|
| Airtable | Cloud | `pip install ffai-workflow-adapters[airtable]` | [Airtable adapter guide](docs/airtable.md) |
| CSV | File | Included (stdlib `csv`) | [CSV adapter guide](docs/csv.md) |
| Excel | File | `pip install ffai-workflow-adapters[excel]` | [Excel adapter guide](docs/excel.md) |
| Google Sheets | Cloud | `pip install ffai-workflow-adapters[google_sheets]` | [Google Sheets adapter guide](docs/google-sheets.md) |
| ODS | File | `pip install ffai-workflow-adapters[ods]` | [ODS adapter guide](docs/ods.md) |

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

Cloud adapter operations (Airtable, Google Sheets) are protected by rate limiting, circuit breakers, and retries with exponential backoff. All settings are in `config/main.yaml` and tunable via environment variables:

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

| Variable | Adapter | Description |
|----------|---------|-------------|
| `MISTRAL_API_KEY` | — | Mistral API key (default model) |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `AIRTABLE_API_KEY` | Airtable | Airtable personal access token |
| `AIRTABLE_BASE_ID` | Airtable | Airtable base ID |
| `GOOGLE_SHEETS_CREDENTIALS` | Google Sheets | Path to service account JSON file |
| `GOOGLE_SHEETS_AUTHORIZED_USER` | Google Sheets | Path to authorized user JSON file (OAuth) |
| `GOOGLE_SHEETS_API_KEY` | Google Sheets | API key string (public sheets only) |
| `OBSERVABILITY__ENABLED` | — | Enable OpenTelemetry span emission (`true`/`false`, default `false`) |
| `OBSERVABILITY__OTEL__ENDPOINT` | — | OTLP gRPC endpoint (default `http://localhost:4317`) |

### Observability

Adapter operations emit OpenTelemetry spans when FFAI's observability is enabled. Set `OBSERVABILITY__ENABLED=true` to activate. Requires `pip install ffai[otel]`. When disabled (the default), spans are no-ops with zero overhead.

| Span | Operation |
|------|-----------|
| `ffai.adapters.airtable.load` | Load workflow from Airtable table |
| `ffai.adapters.airtable.write` | Write results to Airtable table |
| `ffai.adapters.excel.load` | Load workflow from Excel file |
| `ffai.adapters.excel.write` | Write results to Excel file |
| `ffai.adapters.csv.load` | Load workflow from CSV/TSV file |
| `ffai.adapters.csv.write` | Write results to CSV/TSV file |
| `ffai.adapters.ods.load` | Load workflow from ODS file |
| `ffai.adapters.ods.write` | Write results to ODS file |
| `ffai.adapters.google_sheets.load` | Load workflow from Google Sheets |
| `ffai.adapters.google_sheets.write` | Write results to Google Sheets |
| `ffai.adapters.resilience.call` | External API call (rate limited, retried) |
| `ffai.adapters.resilience.retry` | Retry attempt on transient failure |

## API Reference

### Airtable

#### `load_workflow_airtable(base_id, table_name, *, view=None, adapter=None, name="unnamed", ...)`

Load a workflow spec from an Airtable table. Supports `view`, `adapter` (named variant), `name`, `defaults`, `clients`, `tools`, and more.

#### `write_workflow_results(base_id, table_name, result, *, adapter=None, spec=None, run_id=None)`

Write workflow execution results back to an Airtable table. Creates one record per step.

### CSV / TSV

#### `load_workflow_csv(path, *, delimiter=",", adapter=None, name="unnamed", ...)`

Load a workflow spec from a CSV file. Use `delimiter="\t"` for TSV.

#### `load_workflow_tsv(path, *, adapter=None, name="unnamed", ...)`

Load a workflow spec from a TSV file. Equivalent to `load_workflow_csv` with tab delimiter.

#### `write_workflow_results_csv(result, path=None, *, delimiter=",", adapter=None, spec=None, run_id=None)`

Write results to a CSV file. Appends to existing files. Falls back to `output_path` from config.

#### `write_workflow_results_tsv(result, path=None, *, adapter=None, spec=None, run_id=None)`

Write results to a TSV file.

### Excel

#### `load_workflow_excel(path, *, sheet=None, adapter=None, name="unnamed", ...)`

Load a workflow spec from an Excel `.xlsx` file. Supports `sheet`, `adapter`, `name`, `defaults`, `clients`, `tools`.

#### `write_workflow_results_excel(result, path=None, *, sheet=None, adapter=None, spec=None, run_id=None)`

Write results to an Excel file. `path` and `sheet` default to values from `config/adapters.yaml`. Pass `spec=` to include passthrough columns. Pass `run_id=` for a custom run ID (auto-generated if omitted).

### Google Sheets

#### `load_workflow_google_sheets(spreadsheet_id, *, worksheet=None, auth_method=None, credentials_file=None, ...)`

Load a workflow spec from a Google Sheets spreadsheet. Supports three auth methods: `service_account` (default), `oauth`, and `api_key`. Includes rate limiting and retry.

#### `write_workflow_results_google_sheets(spreadsheet_id, result, *, worksheet=None, auth_method=None, ...)`

Write results to a Google Sheets worksheet. Creates the worksheet if it doesn't exist.

### ODS

#### `load_workflow_ods(path, *, sheet=None, adapter=None, name="unnamed", ...)`

Load a workflow spec from an OpenDocument `.ods` file.

#### `write_workflow_results_ods(result, path=None, *, sheet=None, adapter=None, spec=None, run_id=None)`

Write results to an ODS file. Always creates a new file.

### Configuration

#### `get_config()`

Get the global configuration singleton.

#### `reload_config()`

Reload configuration from YAML files.

## License

MIT

# Smartsheet Adapter

Load and execute ffai workflows from Smartsheet sheets, with write-back of results.

## Setup

### 1. Install with Smartsheet support

```bash
pip install ffai-workflow-adapters[smartsheet]
```

This installs [smartsheet-python-sdk](https://pypi.org/project/smartsheet-python-sdk/), the official Python SDK for the Smartsheet API.

### 2. Generate an access token

1. Log in to Smartsheet.
2. Go to **Account > Personal Settings > API Access**.
3. Click **Generate new access token**.
4. Copy the token value.

### 3. Set environment variable

```
SMARTSHEET_ACCESS_TOKEN=your_token_here
```

## Authentication

The Smartsheet adapter uses a single access token. Pass it directly or set the `SMARTSHEET_ACCESS_TOKEN` environment variable:

```python
from ffai_workflow_adapters import load_workflow_smartsheet

# Option A: Explicit token
spec = load_workflow_smartsheet(1234567890123456, access_token="your_token")

# Option B: From environment variable (default: SMARTSHEET_ACCESS_TOKEN)
spec = load_workflow_smartsheet(1234567890123456)
```

### Custom environment variable

To use a different env var name:

```python
spec = load_workflow_smartsheet(
    1234567890123456,
    access_token_env="MY_SMARTSHEET_TOKEN",
)
```

Or configure in `config/adapters.yaml`:

```yaml
adapters:
  smartsheet:
    access_token_env: MY_SMARTSHEET_TOKEN
```

## Loading Workflows

### `load_workflow_smartsheet(sheet_id, *, ...)`

```python
from ffai_workflow_adapters import load_workflow_smartsheet

spec = load_workflow_smartsheet(
    4563217890123456,            # sheet ID (integer from the URL)
    adapter="marketing",        # optional: named adapter from config
    access_token="...",         # optional: overrides env var
    access_token_env="MY_TOKEN", # optional: overrides config env var name
    name="my_workflow",
    defaults={"temperature": 0.5},
    clients={"reviewer": {"type": "litellm", "model": "gpt-4o"}},
)
```

The `sheet_id` is the numeric ID in the Smartsheet URL:

```
https://app.smartsheet.com/sheets/4563217890123456
```

### Sheet Format

The first row must be a header with column names. Each subsequent row is a workflow step.

#### Required Columns

| Column | Description |
|--------|-------------|
| `name` | Unique step identifier |
| `prompt` | Prompt text (supports `{{step.response}}` interpolation) |

#### Optional Columns

| Column | Description | Default |
|--------|-------------|---------|
| `client` | Client name from `config/clients.yaml` | System default |
| `model` | Direct model string override | Client default |
| `history` | Comma-separated step names for context | — |
| `temperature` | Sampling temperature (0-2) | Client default |
| `max_tokens` | Maximum tokens to generate | Client default |
| `system_instructions` | Per-step system prompt | — |
| `condition` | Skip step unless expression is true | — |
| `abort_condition` | Abort workflow if expression is true | — |

See [Airtable adapter docs](airtable.md#column-name-aliases) for the full list of column name aliases.

### Example Smartsheet Workflow

| name | prompt | client | history | temperature |
|------|--------|--------|---------|-------------|
| `topic` | `Name a famous scientific discovery.` | `litellm-mistral-small` | | `0.7` |
| `explain` | `Explain its impact: {{topic.response}}` | `litellm-gpt-4o-mini` | `topic` | `0.5` |

## Writing Results

### `write_workflow_results_smartsheet(sheet_id, result, *, ...)`

```python
from ffai_workflow_adapters import write_workflow_results_smartsheet

result = await ffai.execute_workflow(spec)

# Write to a results sheet
write_workflow_results_smartsheet(9876543210456789, result, spec=spec)

# With custom run ID
write_workflow_results_smartsheet(9876543210456789, result, spec=spec, run_id="batch-42")
```

If the results sheet is empty (no columns), the adapter creates columns matching the output field names. If it already has columns, the adapter maps output fields to existing column IDs and appends rows.

#### Output Columns

| Column | Description |
|--------|-------------|
| `workflow` | Workflow name |
| `step` | Step name |
| `status` | Execution status |
| `response` | AI response text |
| `model` | Model used |
| `input_tokens` | Prompt tokens |
| `output_tokens` | Completion tokens |
| `cost_usd` | Estimated cost |
| `duration_ms` | Execution time (ms) |
| `timestamp` | ISO 8601 timestamp |

Column names are remapped via `output_field_map` if configured.

## Field Mapping

Same system as other adapters. Configure in `config/adapters.yaml`:

```yaml
adapters:
  smartsheet:
    input_field_map:
      Task: name
      Instructions: prompt
      "AI Model": client
    output_field_map:
      step: Task
      response: Output
```

See [Airtable adapter - Field Mapping](airtable.md#field-mapping) for full details on mapping and inheritance rules.

## Passthrough Columns

Carry extra source columns (Comments, Priority, etc.) into the output. Configure in `config/adapters.yaml`:

```yaml
adapters:
  smartsheet:
    passthrough_columns:
      - Comments
      - Priority
      - Category
```

At load time, values are captured from the source sheet and stored as metadata on the spec. At write time, pass the spec to include them:

```python
spec = load_workflow_smartsheet(sheet_id)
result = await ffai.execute_workflow(spec)
write_workflow_results_smartsheet(results_sheet_id, result, spec=spec)
```

Passthrough columns appear in the output after the standard columns, with their original names (or remapped via `output_field_map` if configured). If a step has no value for a passthrough column, `None` is written.

## Extra Output Columns

Add derived columns to every output row. Configure in `config/adapters.yaml`:

```yaml
adapters:
  smartsheet:
    extra_output_columns:
      run_id: "{{run_id}}"
      run_date: "{{date}}"
      batch_id: "2026-Q2-run-01"
```

### Template Expressions

| Template | Resolves to |
|----------|------------|
| `{{run_id}}` | Timestamp-based run ID (e.g., `20260602-174021`) |
| `{{date}}` | Current UTC date (e.g., `2026-06-02`) |
| `{{timestamp}}` | Current UTC ISO timestamp |
| `{{now:FORMAT}}` | `strftime` format (e.g., `{{now:%Y-%m-%d %H:%M}}` → `2026-06-02 17:40`) |
| Any other string | Literal value |

All templates resolve **once per write call**. Pass `run_id="batch-42"` to use a custom ID instead of the auto-generated one.

## Schema Validation

At load time, the adapter validates your sheet before making any API calls:

1. **Required columns** — `name` and `prompt` must be present (after field mapping). Raises `TabularLoadError` with the list of missing columns and suggestions.
2. **Type checking** — `temperature` must be numeric, `max_tokens` must be numeric. Raises per-row errors.
3. **Unrecognized columns** — columns that don't match any canonical field, field map entry, or passthrough column trigger a warning log message.

### Canonical Field Names

| Field | Type | Required |
|-------|------|----------|
| `name` | string | Yes |
| `prompt` | string | Yes |
| `client` | string | No |
| `model` | string | No |
| `history` | string | No |
| `temperature` | float | No |
| `max_tokens` | int | No |
| `system_instructions` | string | No |
| `condition` | string | No |
| `abort_condition` | string | No |
| `response_format` | string | No |
| `response_model` | string | No |
| `strict` | bool | No |
| `tools` | string | No |
| `tool_choice` | string | No |

If your sheet uses different column names, configure `input_field_map` to map them.

## Resilience

All Smartsheet API calls are automatically protected by:

1. **Rate limiting** — A token-bucket limiter caps request throughput (default: 5 req/s, burst 10).
2. **Circuit breaker** — After repeated failures (default: 5), calls are blocked until a recovery timeout (default: 30s).
3. **Retry with backoff** — Failed requests with retryable status codes (429, 502, 503, 504) are retried with exponential backoff and jitter (default: 3 attempts).

Configure via `config/main.yaml`. See [Airtable adapter - Resilience](airtable.md#resilience) for full configuration details.

## Observability

Adapter operations emit OpenTelemetry spans when FFAI's observability is enabled. Spans cover Smartsheet load and write operations, including record counts, timing, and error details.

See [Airtable adapter - Observability](airtable.md#observability) for full details.

### Emitted Spans

| Span Name | Operation | Key Attributes |
|-----------|-----------|----------------|
| `ffai.adapters.smartsheet.load` | Load workflow from sheet | `adapter`, `sheet_id`, `rows.count`, `workflow.name` |
| `ffai.adapters.smartsheet.write` | Write results to sheet | `adapter`, `sheet_id`, `records.count`, `records.appended` |
| `ffai.adapters.resilience.call` | External API call (Smartsheet) | `call.success`, `circuit_breaker.failures` |

## Config Reference

```yaml
adapters:
  smartsheet:
    # Access token env var
    access_token_env: SMARTSHEET_ACCESS_TOKEN

    # Carry source columns to output
    passthrough_columns:
      - Comments
      - Priority

    # Add derived columns
    extra_output_columns:
      run_id: "{{run_id}}"
      run_date: "{{date}}"

    # Remap source column names to canonical fields
    input_field_map:
      Name: name
      Prompt: prompt

    # Remap output column names
    output_field_map:
      step: Step
      response: Response

    # Named variants (inherit/override base config)
    named:
      marketing:
        input_field_map:
          Campaign: name
          Brief: prompt
        output_field_map:
          step: Campaign
```

## Full Example

```python
import asyncio
from ffai import FFAI
from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient
from ffai_workflow_adapters import (
    load_workflow_smartsheet,
    write_workflow_results_smartsheet,
)

WORKFLOW_SHEET_ID = 4563217890123456
RESULTS_SHEET_ID = 9876543210456789

async def main():
    client = AsyncFFLiteLLMClient(model_string="mistral/mistral-small-latest", api_key="...")
    ffai = FFAI(client)

    spec = load_workflow_smartsheet(
        WORKFLOW_SHEET_ID,
        name="smartsheet_workflow",
    )
    result = await ffai.execute_workflow(spec)

    # Write results to a separate sheet with passthrough + extra columns
    write_workflow_results_smartsheet(RESULTS_SHEET_ID, result, spec=spec)

asyncio.run(main())
```

# Excel Adapter

Load and execute ffai workflows from Excel (.xlsx) files, with write-back of results.

## Setup

### 1. Install with Excel support

```bash
pip install ffai-workflow-adapters[excel]
```

### 2. No environment variables required

Excel files are read from the local filesystem. No API keys needed.

## Loading Workflows

### `load_workflow_excel(path, *, ...)`

```python
from ffai_workflow_adapters import load_workflow_excel

spec = load_workflow_excel(
    "workflows/my_workflow.xlsx",
    sheet="Steps",             # optional: sheet name or index (default: active sheet)
    adapter="marketing",       # optional: named adapter from config
    name="my_workflow",
    defaults={"temperature": 0.5},
    clients={"reviewer": {"type": "litellm", "model": "gpt-4o"}},
)
```

### Excel File Format

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

### Example Excel Workflow

| name | prompt | client | history | temperature |
|------|--------|--------|---------|-------------|
| `topic` | `Name a famous scientific discovery.` | `litellm-mistral-small` | | `0.7` |
| `explain` | `Explain its impact: {{topic.response}}` | `litellm-gpt-4o-mini` | `topic` | `0.5` |

## Writing Results

### `write_workflow_results_excel(result, path=None, *, sheet=None, adapter=None, spec=None)`

```python
from ffai_workflow_adapters import write_workflow_results_excel

result = await ffai.execute_workflow(spec)

# Write using config defaults (output_path, output_sheet from adapters.yaml)
write_workflow_results_excel(result)

# Override path and/or sheet
write_workflow_results_excel(result, path="output/run2.xlsx")
write_workflow_results_excel(result, sheet="Run 2")

# With passthrough columns — pass the spec returned by load_workflow_excel
write_workflow_results_excel(result, spec=spec)
```

`path` and `sheet` are optional — if omitted, they fall back to `output_path` and `output_sheet` from the resolved adapter config. Raises `ValueError` if neither is set.

If the file exists, results are appended to the sheet. If the sheet exists, rows are appended after existing data. Parent directories are created automatically.

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

Same system as the Airtable adapter. Configure in `config/adapters.yaml`:

```yaml
adapters:
  excel:
    input_field_map:
      Task: name
      Instructions: prompt
      "AI Model": client
    output_field_map:
      step: Task
      response: Output
    named:
      quarterly:
        input_field_map:
          Step: name
          Query: prompt
```

See [Airtable adapter - Field Mapping](airtable.md#field-mapping) for full details on mapping and inheritance rules.

## Passthrough Columns

Carry extra source columns (Comments, Priority, etc.) into the output. Configure in `config/adapters.yaml`:

```yaml
adapters:
  excel:
    passthrough_columns:
      - Comments
      - Priority
      - Category
```

At load time, values are captured from the source workbook and stored as metadata on the spec. At write time, pass the spec to include them:

```python
spec = load_workflow_excel("workflows/steps.xlsx")
result = await ffai.execute_workflow(spec)
write_workflow_results_excel(result, spec=spec)
```

Passthrough columns appear in the output after the standard columns, with their original names (or remapped via `output_field_map` if configured). If a step has no value for a passthrough column, `None` is written.

Named adapters inherit `passthrough_columns` from the base config and can override.

## Extra Output Columns

Add derived columns to every output row. Configure in `config/adapters.yaml`:

```yaml
adapters:
  excel:
    extra_output_columns:
      run_id: "{{run_id}}"
      run_date: "{{date}}"
      batch_id: "2026-Q2-run-01"
      run_time: "{{now:%H:%M:%S}}"
```

### Template Expressions

| Template | Resolves to |
|----------|------------|
| `{{run_id}}` | Timestamp-based run ID (e.g., `20260602-174021`) |
| `{{date}}` | Current UTC date (e.g., `2026-06-02`) |
| `{{timestamp}}` | Current UTC ISO timestamp |
| `{{now:FORMAT}}` | `strftime` format (e.g., `{{now:%Y-%m-%d %H:%M}}` → `2026-06-02 17:40`) |
| Any other string | Literal value |

All templates resolve **once per write call** — every row in the same run gets the same `run_id`, `date`, etc. Pass `run_id="batch-42"` to `write_workflow_results_excel()` to use a custom ID instead of the auto-generated one.

Extra columns appear in the output after passthrough columns. Named adapters inherit and can override.

## Schema Validation

At load time, the adapter validates your workbook before making any API calls:

1. **Required columns** — `name` and `prompt` must be present (after field mapping). Raises `TabularLoadError` with the list of missing columns and suggestions.
2. **Type checking** — `temperature` must be numeric, `max_tokens` must be numeric. Raises per-row errors.
3. **Unrecognized columns** — columns that don't match any canonical field, field map entry, or passthrough column trigger a warning log message. They're passed through to ffai (which ignores them).

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

If your workbook uses different column names, configure `input_field_map` to map them.

## Column Order in Output

Standard columns → passthrough columns → extra output columns.

## Observability

Adapter operations emit OpenTelemetry spans when FFAI's observability is enabled. Spans cover Excel load and write operations, including file paths, record counts, timing, and error details.

### Enabling

Same as Airtable adapter — see [Airtable adapter - Observability](airtable.md#observability).

### Emitted Spans

| Span Name | Operation | Key Attributes |
|-----------|-----------|----------------|
| `ffai.adapters.excel.load` | Load workflow from file | `adapter`, `path`, `sheet`, `columns.count`, `rows.count`, `workflow.name` |
| `ffai.adapters.excel.write` | Write results to file | `adapter`, `path`, `sheet`, `run_id`, `records.count` |

## Config Reference

```yaml
adapters:
  excel:
    # Output destination (used when path= is omitted)
    output_path: "output/results.xlsx"
    output_sheet: "Results"

    # Carry source columns to output
    passthrough_columns:
      - Comments
      - Priority

    # Add derived columns
    extra_output_columns:
      run_id: "{{run_id}}"
      run_date: "{{date}}"
      batch: "demo-run"

    # Remap source column names to canonical fields
    input_field_map:
      Name: name
      Prompt: prompt

    # Remap output column names
    output_field_map:
      step: Step
      response: Response

    # Named adapter overrides
    named:
      custom:
        output_path: "output/results_custom.xlsx"
        output_sheet: "Custom Results"
        input_field_map:
          Task: name
          Instructions: prompt
        output_field_map:
          step: Task
          response: Output
```

## Full Example

```python
import asyncio
from ffai import FFAI
from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient
from ffai_workflow_adapters import load_workflow_excel, write_workflow_results_excel

async def main():
    client = AsyncFFLiteLLMClient(model_string="mistral/mistral-small-latest", api_key="...")
    ffai = FFAI(client)

    spec = load_workflow_excel("workflows/steps.xlsx", name="excel_workflow")
    result = await ffai.execute_workflow(spec)

    # Writes to output/results.xlsx (from config) with passthrough + extra columns
    write_workflow_results_excel(result, spec=spec)

asyncio.run(main())
```

# ODS Adapter

Load and execute ffai workflows from OpenDocument Spreadsheet (.ods) files, with write-back of results.

## Setup

### 1. Install with ODS support

```bash
pip install ffai-workflow-adapters[ods]
```

This installs [odfpy](https://pypi.org/project/odfpy/), a pure-Python library for reading and writing ODS files.

### 2. No environment variables required

ODS files are read from the local filesystem. No API keys needed for the adapter itself (you still need LLM API keys for ffai).

## Loading Workflows

### `load_workflow_ods(path, *, ...)`

```python
from ffai_workflow_adapters import load_workflow_ods

spec = load_workflow_ods(
    "workflows/my_workflow.ods",
    sheet="Steps",             # optional: sheet name or index (default: first sheet)
    adapter="marketing",       # optional: named adapter from config
    name="my_workflow",
    defaults={"temperature": 0.5},
    clients={"reviewer": {"type": "litellm", "model": "gpt-4o"}},
)
```

### ODS File Format

The first row of the selected sheet must be a header with column names. Each subsequent row is a workflow step.

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

### Example ODS Workflow

| name | prompt | client | history | temperature |
|------|--------|--------|---------|-------------|
| `topic` | `Name a famous scientific discovery.` | `litellm-mistral-small` | | `0.7` |
| `explain` | `Explain its impact: {{topic.response}}` | `litellm-gpt-4o-mini` | `topic` | `0.5` |

### Sheet Selection

The `sheet` parameter accepts a sheet name (string) or index (integer):

```python
# By name
spec = load_workflow_ods("workflows/steps.ods", sheet="Workflow")

# By index (0-based)
spec = load_workflow_ods("workflows/steps.ods", sheet=1)

# Default: first sheet
spec = load_workflow_ods("workflows/steps.ods")
```

Raises `TabularLoadError` if the named sheet doesn't exist.

## Writing Results

### `write_workflow_results_ods(result, path=None, *, ...)`

```python
from ffai_workflow_adapters import write_workflow_results_ods

result = await ffai.execute_workflow(spec)

# Write using config defaults (output_path, output_sheet from adapters.yaml)
write_workflow_results_ods(result)

# Override path and/or sheet
write_workflow_results_ods(result, path="output/run2.ods")
write_workflow_results_ods(result, sheet="Run 2")

# With passthrough columns — pass the spec returned by load_workflow_ods
write_workflow_results_ods(result, spec=spec)
```

`path` and `sheet` are optional — if omitted, they fall back to `output_path` and `output_sheet` from the resolved adapter config. Raises `ValueError` if no output path is set.

**Note:** ODS write always creates a new file. Unlike CSV (which appends), calling `write_workflow_results_ods` overwrites any existing file at the path. This is a limitation of the ODS format — appending rows to an existing ODS document while preserving formatting is complex.

Parent directories are created automatically.

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
  ods:
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
  ods:
    passthrough_columns:
      - Comments
      - Priority
      - Category
```

At load time, values are captured from the source workbook and stored as metadata on the spec. At write time, pass the spec to include them:

```python
spec = load_workflow_ods("workflows/steps.ods")
result = await ffai.execute_workflow(spec)
write_workflow_results_ods(result, spec=spec)
```

Passthrough columns appear in the output after the standard columns, with their original names (or remapped via `output_field_map` if configured). If a step has no value for a passthrough column, `None` is written.

Named adapters inherit `passthrough_columns` from the base config and can override.

## Extra Output Columns

Add derived columns to every output row. Configure in `config/adapters.yaml`:

```yaml
adapters:
  ods:
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

All templates resolve **once per write call** — every row in the same run gets the same `run_id`, `date`, etc. Pass `run_id="batch-42"` to `write_workflow_results_ods()` to use a custom ID instead of the auto-generated one.

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

Adapter operations emit OpenTelemetry spans when FFAI's observability is enabled. Spans cover ODS load and write operations, including file paths, record counts, timing, and error details.

### Enabling

Same as Airtable adapter — see [Airtable adapter - Observability](airtable.md#observability).

### Emitted Spans

| Span Name | Operation | Key Attributes |
|-----------|-----------|----------------|
| `ffai.adapters.ods.load` | Load workflow from file | `adapter`, `path`, `sheet`, `columns.count`, `rows.count`, `workflow.name` |
| `ffai.adapters.ods.write` | Write results to file | `adapter`, `path`, `sheet`, `run_id`, `records.count` |

## Config Reference

```yaml
adapters:
  ods:
    # Output destination (used when path= is omitted)
    output_path: "output/results.ods"
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
```

## Full Example

```python
import asyncio
from ffai import FFAI
from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient
from ffai_workflow_adapters import load_workflow_ods, write_workflow_results_ods

async def main():
    client = AsyncFFLiteLLMClient(model_string="mistral/mistral-small-latest", api_key="...")
    ffai = FFAI(client)

    spec = load_workflow_ods("workflows/steps.ods", name="ods_workflow")
    result = await ffai.execute_workflow(spec)

    # Writes to output/results.ods (from config) with passthrough + extra columns
    write_workflow_results_ods(result, spec=spec)

asyncio.run(main())
```

# CSV/TSV Adapter

Load and execute ffai workflows from CSV and TSV files, with write-back of results.

## Setup

### 1. Install

```bash
pip install ffai-workflow-adapters[csv]
```

CSV/TSV support uses Python's built-in `csv` module — no extra dependencies required. The `[csv]` extra is empty but provided for consistency with other adapters.

### 2. No environment variables required

CSV and TSV files are read from the local filesystem. No API keys needed for the adapter itself (you still need LLM API keys for ffai).

## Loading Workflows

### `load_workflow_csv(path, *, ...)`

```python
from ffai_workflow_adapters import load_workflow_csv

spec = load_workflow_csv(
    "workflows/my_workflow.csv",
    delimiter=",",             # optional: field delimiter (default: ",")
    adapter="marketing",       # optional: named adapter from config
    name="my_workflow",
    defaults={"temperature": 0.5},
    clients={"reviewer": {"type": "litellm", "model": "gpt-4o"}},
)
```

### `load_workflow_tsv(path, *, ...)`

Thin wrapper around `load_workflow_csv` with `delimiter="\t"`. Same parameters except `delimiter`.

```python
from ffai_workflow_adapters import load_workflow_tsv

spec = load_workflow_tsv(
    "workflows/my_workflow.tsv",
    adapter="marketing",
    name="my_workflow",
)
```

### CSV/TSV File Format

The first row must be a header with column names. Each subsequent row is a workflow step. Files are read with UTF-8 encoding (with BOM support).

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

### Example CSV Workflow

```csv
name,prompt,client,history,temperature
topic,Name a famous scientific discovery.,litellm-mistral-small,,0.7
explain,Explain its impact: {{topic.response}},litellm-gpt-4o-mini,topic,0.5
```

### Example TSV Workflow

```tsv
name	prompt	client	history	temperature
topic	Name a famous scientific discovery.	litellm-mistral-small		0.7
explain	Explain its impact: {{topic.response}}	litellm-gpt-4o-mini	topic	0.5
```

## Writing Results

### `write_workflow_results_csv(result, path=None, *, ...)`

```python
from ffai_workflow_adapters import write_workflow_results_csv

result = await ffai.execute_workflow(spec)

# Write using config defaults (output_path from adapters.yaml)
write_workflow_results_csv(result)

# Override path
write_workflow_results_csv(result, path="output/run2.csv")

# With passthrough columns — pass the spec returned by load_workflow_csv
write_workflow_results_csv(result, spec=spec)
```

### `write_workflow_results_tsv(result, path=None, *, ...)`

Thin wrapper around `write_workflow_results_csv` with `delimiter="\t"`.

```python
from ffai_workflow_adapters import write_workflow_results_tsv

write_workflow_results_tsv(result, path="output/run2.tsv", spec=spec)
```

`path` is optional — if omitted, it falls back to `output_path` from the resolved adapter config. Raises `ValueError` if neither is set.

If the file exists, data rows are appended without duplicating the header. Parent directories are created automatically.

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
  csv_adapter:
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
  csv_adapter:
    passthrough_columns:
      - Comments
      - Priority
      - Category
```

At load time, values are captured from the source file and stored as metadata on the spec. At write time, pass the spec to include them:

```python
spec = load_workflow_csv("workflows/steps.csv")
result = await ffai.execute_workflow(spec)
write_workflow_results_csv(result, spec=spec)
```

Passthrough columns appear in the output after the standard columns, with their original names (or remapped via `output_field_map` if configured). If a step has no value for a passthrough column, `None` is written.

Named adapters inherit `passthrough_columns` from the base config and can override.

## Extra Output Columns

Add derived columns to every output row. Configure in `config/adapters.yaml`:

```yaml
adapters:
  csv_adapter:
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

All templates resolve **once per write call** — every row in the same run gets the same `run_id`, `date`, etc. Pass `run_id="batch-42"` to `write_workflow_results_csv()` to use a custom ID instead of the auto-generated one.

Extra columns appear in the output after passthrough columns. Named adapters inherit and can override.

## Schema Validation

At load time, the adapter validates your file before making any API calls:

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

If your file uses different column names, configure `input_field_map` to map them.

## Column Order in Output

Standard columns → passthrough columns → extra output columns.

## Observability

Adapter operations emit OpenTelemetry spans when FFAI's observability is enabled. Spans cover CSV load and write operations, including file paths, record counts, timing, and error details.

### Enabling

Same as Airtable adapter — see [Airtable adapter - Observability](airtable.md#observability).

### Emitted Spans

| Span Name | Operation | Key Attributes |
|-----------|-----------|----------------|
| `ffai.adapters.csv.load` | Load workflow from file | `adapter`, `path`, `delimiter`, `columns.count`, `rows.count`, `workflow.name` |
| `ffai.adapters.csv.write` | Write results to file | `adapter`, `path`, `delimiter`, `run_id`, `records.count` |

## Config Reference

```yaml
adapters:
  csv_adapter:
    # Output destination (used when path= is omitted)
    output_path: "output/results.csv"
    delimiter: ","

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
from ffai_workflow_adapters import load_workflow_csv, write_workflow_results_csv

async def main():
    client = AsyncFFLiteLLMClient(model_string="mistral/mistral-small-latest", api_key="...")
    ffai = FFAI(client)

    spec = load_workflow_csv("workflows/steps.csv", name="csv_workflow")
    result = await ffai.execute_workflow(spec)

    # Writes to output/results.csv (from config) with passthrough + extra columns
    write_workflow_results_csv(result, spec=spec)

asyncio.run(main())
```

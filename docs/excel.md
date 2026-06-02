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

### `write_workflow_results_excel(path, result, *, ...)`

```python
from ffai_workflow_adapters import write_workflow_results_excel

result = await ffai.execute_workflow(spec)
write_workflow_results_excel("output/results.xlsx", result)

# Append to a named sheet
write_workflow_results_excel("output/results.xlsx", result, sheet="Run 2")
```

Results are written to an Excel file with one row per workflow step. If the file exists, results are appended. If the sheet exists, rows are appended after existing data.

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

    write_workflow_results_excel("output/results.xlsx", result)

asyncio.run(main())
```

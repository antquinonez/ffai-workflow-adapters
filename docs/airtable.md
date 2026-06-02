# Airtable Adapter

Load and execute ffai workflows from Airtable tables, with write-back of results.

## Setup

### 1. Install with Airtable support

```bash
pip install ffai-workflow-adapters[airtable]
```

### 2. Create a personal access token

Go to [airtable.com/create/tokens](https://airtable.com/create/tokens) and create a token with:

- **Data access**: `data.records:read`, `data.records:write`
- **Access**: Add your specific base

### 3. Set environment variables

Add to your `.env`:

```
AIRTABLE_API_KEY=patXXXXXXXXXXXXXX.XXXXXXXXXXXXXX
AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX
MISTRAL_API_KEY=your-mistral-key
OPENAI_API_KEY=your-openai-key
```

### 4. Configure clients (optional)

Edit `config/clients.yaml` to define named models. See the main [README](README.md#clients).

## Workflow Table

Create an Airtable table with the following columns:

### Required Columns

| Column Name | Type | Description |
|-------------|------|-------------|
| `name` | Single line text | Unique step identifier |
| `prompt` | Long text | Prompt text (supports `{{step.response}}` interpolation) |

### Optional Columns

| Column Name | Type | Description | Default |
|-------------|------|-------------|---------|
| `client` | Single line text or Single Select | Client name from `config/clients.yaml` | System default |
| `model` | Single line text | Direct model string override | Client default |
| `history` | Single line text | Comma-separated step names to include as context | — |
| `temperature` | Number | Sampling temperature (0-2) | Client default |
| `max_tokens` | Number | Maximum tokens to generate | Client default |
| `system_instructions` | Long text | Per-step system prompt | — |
| `condition` | Single line text | Skip step unless expression is true | — |
| `abort_condition` | Single line text | Abort workflow if expression is true | — |
| `response_format` | Single line text | Response format (plain text or JSON) | — |
| `tools` | Single line text | Comma-separated tool names | — |
| `tool_choice` | Single line text | Tool choice strategy | — |
| `strict` | Checkbox | Enable strict mode | `false` |

### Column Name Aliases

The adapter normalizes column names automatically. These alternatives are recognized:

| Canonical | Aliases |
|-----------|---------|
| `name` | `step`, `step_name`, `step name` |
| `prompt` | `prompt_text`, `prompt text`, `question` |
| `client` | `client_name`, `client name` |
| `model` | `model_name`, `model name` |
| `history` | `depends_on`, `depends on`, `dependencies`, `deps` |
| `temperature` | `temp` |
| `max_tokens` | `max tokens`, `maxtokens`, `token_limit` |

### Example: Two-Step Workflow

| name | prompt | client | history | temperature |
|------|--------|--------|---------|-------------|
| `topic` | `Name a famous scientific discovery and explain it in one sentence.` | `litellm-mistral-small` | | `0.7` |
| `explain` | `Given this discovery: {{topic.response}} — write a paragraph about its impact.` | `litellm-gpt-4o-mini` | `topic` | `0.5` |

## Results Table

Create a table (e.g., `_results`) to receive execution output:

| Column Name | Type |
|-------------|------|
| `workflow` | Single line text |
| `step` | Single line text |
| `status` | Single line text |
| `response` | Long text |
| `model` | Single line text |
| `input_tokens` | Number |
| `output_tokens` | Number |
| `cost_usd` | Currency |
| `duration_ms` | Number |
| `timestamp` | Single line text |

## Per-Step Client Selection

Use a **Single Select** column named `client` to let users pick models per step. The option values must match keys in `config/clients.yaml`:

| Single Select Option | Resolves To |
|---------------------|-------------|
| `litellm-mistral-small` | Mistral Small via `MISTRAL_API_KEY` |
| `litellm-gpt-4o-mini` | GPT-4o-mini via `OPENAI_API_KEY` |

Leave the field blank to use the system default (`default_client` in `config/clients.yaml`).

## API

### `load_workflow_airtable(base_id, table_name, *, ...)`

Load a `WorkflowSpec` from an Airtable table.

```python
from ffai_workflow_adapters import load_workflow_airtable

spec = load_workflow_airtable(
    "appXXXXXXXXXXXXXX",
    "Workflow Steps",
    view="basic",              # optional: Airtable view name
    name="my_workflow",        # optional: workflow name
    description="...",         # optional: description
    api_key="pat...",          # optional: overrides AIRTABLE_API_KEY
    api_key_env="MY_KEY_VAR",  # optional: overrides config env var name
    defaults={"temperature": 0.5},
    clients={"reviewer": {"type": "litellm", "model": "gpt-4o"}},
    tools={"search": {...}},
)
```

### `write_workflow_results(base_id, table_name, result, *, ...)`

Write execution results to an Airtable table. Creates one record per workflow step.

```python
from ffai_workflow_adapters import write_workflow_results

result = await ffai.execute_workflow(spec)
created = write_workflow_results("appXXXXXXXXXXXXXX", "_results", result)
print(f"Wrote {len(created)} records")
```

## Views

Use Airtable views to define workflow variants without duplicating data:

```python
# Run only the "active" steps
spec = load_workflow_airtable(base_id, "Steps", view="active")

# Run a different variant
spec = load_workflow_airtable(base_id, "Steps", view="extended")
```

## Full Example

See [`examples/run_airtable_workflow.py`](../examples/run_airtable_workflow.py) for a complete working script.

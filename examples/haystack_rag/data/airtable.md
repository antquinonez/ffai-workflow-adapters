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
    adapter="marketing",      # optional: named adapter from config
    view="basic",             # optional: Airtable view name
    name="my_workflow",       # optional: workflow name
    description="...",        # optional: description
    api_key="pat...",         # optional: overrides AIRTABLE_API_KEY
    api_key_env="MY_KEY_VAR", # optional: overrides config env var name
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
created = write_workflow_results(
    "appXXXXXXXXXXXXXX",
    "_results",
    result,
    adapter="marketing",      # optional: named adapter from config
)
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

## Named Adapters

When working with multiple Airtable bases, define named adapter configs in `config/adapters.yaml`. Named configs **inherit** unset fields from the base airtable config.

### Configuration

```yaml
adapters:
  airtable:
    api_key_env: AIRTABLE_API_KEY          # inherited by all named configs
    base_id_env: AIRTABLE_BASE_ID
    named:
      marketing:
        base_id_env: AIRTABLE_MARKETING_BASE_ID
        input_field_map:
          Task: name
          Instructions: prompt
          "AI Model": client
        output_field_map:
          response: Output
          step: "Step Name"
      research:
        base_id_env: AIRTABLE_RESEARCH_BASE_ID
        default_view: "active"
```

### Usage

Pass the `adapter` parameter to load and write functions:

```python
# Uses the "marketing" named config (custom fields, different base)
spec = load_workflow_airtable(base_id, "Steps", adapter="marketing")
write_workflow_results(base_id, "_results", result, adapter="marketing")

# No adapter parameter = base config (default behavior)
spec = load_workflow_airtable(base_id, "Steps")
```

### Inheritance Rules

| Field Type | Behavior |
|-----------|----------|
| Scalars (e.g., `base_id_env`, `default_view`) | Named config overrides base; unset fields fall back to base |
| Dicts (e.g., `input_field_map`, `output_field_map`) | Merged — named config values override base, base values fill gaps |

If a named config doesn't exist, the base config is used as-is.

## Resilience

All Airtable API calls (`load_workflow_airtable` and `write_workflow_results`) are automatically protected by:

1. **Rate limiting** — A token-bucket limiter caps request throughput (default: 5 req/s, burst 10).
2. **Circuit breaker** — After repeated failures (default: 5), calls are blocked until a recovery timeout (default: 30s), then a limited number of probe requests are allowed before the circuit fully re-opens.
3. **Retry with backoff** — Failed requests with retryable status codes (429, 502, 503, 504) are retried with exponential backoff and jitter (default: 3 attempts).
4. **Batched concurrent writes** — `write_workflow_results` splits records into chunks (default: 10) and writes them concurrently (default: 3 threads).

These are internal — the public API is unchanged. Configure via `config/main.yaml`:

```yaml
retry:
  max_attempts: 3
  min_wait_seconds: 1.0
  max_wait_seconds: 60.0
  exponential_base: 2.0
  exponential_jitter: true
  retry_on_status_codes:
    - 429
    - 503
    - 502
    - 504

resilience:
  rate_limit:
    requests_per_second: 5.0
    burst: 10
  circuit_breaker:
    failure_threshold: 5
    recovery_timeout_seconds: 30.0
    half_open_max_calls: 3
  batch:
    chunk_size: 10
    max_concurrency: 3
```

Override any setting via environment variables using the `__` delimiter (e.g., `RESILIENCE__RATE_LIMIT__REQUESTS_PER_SECOND=10`).

## Field Mapping

If your Airtable columns use custom names, configure mappings in `config/adapters.yaml` instead of renaming your columns.

### Input Field Mapping

Map your Airtable column names to the canonical workflow field names:

```yaml
adapters:
  airtable:
    input_field_map:        # {your_column: canonical_name}
      Task: name
      Instructions: prompt
      "AI Model": client
      Context: history
      Temp: temperature
```

Unmapped columns pass through unchanged. The [column aliases](#column-name-aliases) still apply after mapping.

### Output Field Mapping

Map the canonical result field names to your results table columns:

```yaml
adapters:
  airtable:
    output_field_map:       # {canonical_name: your_column}
      step: "Step Name"
      response: Output
      model: "AI Model"
      input_tokens: "Tokens In"
      output_tokens: "Tokens Out"
```

Unmapped fields use their canonical names.

### Canonical Field Names

**Input fields** (your columns → these names):

| Canonical Name | Description |
|----------------|-------------|
| `name` | Step identifier |
| `prompt` | Prompt text |
| `client` | Client name from `config/clients.yaml` |
| `model` | Direct model string |
| `history` | Comma-separated context steps |
| `temperature` | Sampling temperature |
| `max_tokens` | Max tokens |
| `system_instructions` | System prompt |
| `condition` | Skip-unless expression |
| `abort_condition` | Abort-if expression |
| `response_format` | Response format |
| `tools` | Comma-separated tool names |
| `strict` | Strict mode (true/false) |

**Output fields** (these names → your columns):

| Canonical Name | Description |
|----------------|-------------|
| `workflow` | Workflow name |
| `step` | Step name |
| `status` | Execution status |
| `response` | AI response text |
| `model` | Model used |
| `input_tokens` | Prompt tokens |
| `output_tokens` | Completion tokens |
| `cost_usd` | Estimated cost |
| `duration_ms` | Execution time |
| `timestamp` | ISO 8601 timestamp |

## Observability

Adapter operations emit OpenTelemetry spans when FFAI's observability is enabled. Spans cover Airtable load and write operations, including record counts, timing, and error details.

### Enabling

Adapter spans use FFAI's TelemetryManager. Enable via environment variable:

```
OBSERVABILITY__ENABLED=true
OBSERVABILITY__OTEL__ENDPOINT=http://localhost:4317
```

Or in FFAI's `config/main.yaml`:

```yaml
observability:
  enabled: true
  otel:
    endpoint: "http://localhost:4317"
```

Requires `pip install ffai[otel]` for OpenTelemetry packages. When disabled (the default), spans are no-ops with zero overhead.

### Emitted Spans

| Span Name | Operation | Key Attributes |
|-----------|-----------|----------------|
| `ffai.adapters.airtable.load` | Load workflow from table | `adapter`, `base_id`, `table`, `view`, `records.raw_count`, `rows.count`, `workflow.name` |
| `ffai.adapters.airtable.write` | Write results to table | `adapter`, `base_id`, `table`, `run_id`, `records.count`, `batch.chunk_size`, `batch.max_concurrency`, `records.created` |
| `ffai.adapters.resilience.call` | External API call (Airtable) | `call.success`, `circuit_breaker.failures` |
| `ffai.adapters.resilience.retry` | Retry attempt | `attempt`, `max_attempts`, `wait_seconds` |

## Full Example

See [`examples/run_airtable_workflow.py`](../examples/run_airtable_workflow.py) for a complete working script.

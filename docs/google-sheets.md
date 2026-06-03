# Google Sheets Adapter

Load and execute ffai workflows from Google Sheets spreadsheets, with write-back of results.

## Setup

### 1. Install with Google Sheets support

```bash
pip install ffai-workflow-adapters[google_sheets]
```

This installs [gspread](https://pypi.org/project/gspread/), the Python library for the Google Sheets API.

### 2. Enable API access

Regardless of authentication method, you need a Google Cloud project with the Sheets and Drive APIs enabled:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or select an existing one).
3. Search for **Google Sheets API** and enable it.
4. Search for **Google Drive API** and enable it.

### 3. Choose an authentication method

The adapter supports three authentication methods. Choose based on your use case:

| Method | Best for | Access scope |
|--------|----------|-------------|
| **Service account** | Bots, automation, server-side | Any spreadsheet shared with the service account |
| **OAuth Client ID** | End-user apps, interactive use | The authenticated user's spreadsheets |
| **API key** | Public spreadsheets only | Only publicly shared spreadsheets |

## Authentication

### Service Account (default)

A service account is a bot account that accesses spreadsheets on its own behalf. You must share each spreadsheet with the service account's email address.

**Setup:**

1. Go to **IAM & Admin → Service Accounts** and create a service account.
2. Create a key (JSON format) and download it.
3. Share your spreadsheet with the service account's `client_email`.

**Environment variables:**

```
GOOGLE_SHEETS_CREDENTIALS=/path/to/service-account.json
```

**Usage (default — no extra parameters needed):**

```python
spec = load_workflow_google_sheets(
    "SPREADSHEET_ID",
    credentials_file="/path/to/service-account.json",  # or set GOOGLE_SHEETS_CREDENTIALS
)
```

Or pass an explicit path via `credentials_file`:

```python
spec = load_workflow_google_sheets(
    "SPREADSHEET_ID",
    credentials_file="/path/to/sa.json",
)
```

### OAuth Client ID

For applications that access spreadsheets on behalf of an end user. The first run opens a browser for the user to grant access. Subsequent runs reuse the stored credentials.

**Setup:**

1. Go to **APIs & Services → OAuth Consent Screen** and configure it.
2. Go to **APIs & Services → Credentials** and create an **OAuth client ID** (Desktop app).
3. Download the credentials JSON file.

**Environment variables:**

```
GOOGLE_SHEETS_CREDENTIALS=/path/to/credentials.json
GOOGLE_SHEETS_AUTHORIZED_USER=/path/to/authorized_user.json
```

The `authorized_user.json` is created automatically after the first browser login. Set `GOOGLE_SHEETS_AUTHORIZED_USER` to persist it across runs.

**Usage:**

```python
spec = load_workflow_google_sheets(
    "SPREADSHEET_ID",
    auth_method="oauth",
    credentials_file="/path/to/credentials.json",
    authorized_user_file="/path/to/authorized_user.json",  # optional on first run
)
```

Or configure in `config/adapters.yaml` to make OAuth the default:

```yaml
adapters:
  google_sheets:
    auth_method: oauth
    credentials_env: GOOGLE_SHEETS_CREDENTIALS
    authorized_user_env: GOOGLE_SHEETS_AUTHORIZED_USER
```

### API Key (public spreadsheets only)

For read-only access to publicly shared spreadsheets. No OAuth flow, no service account — just a simple API key.

**Setup:**

1. Go to **APIs & Services → Credentials** and create an **API key**.
2. Make sure your spreadsheet is shared publicly (Anyone with the link → Viewer).

**Environment variables:**

```
GOOGLE_SHEETS_API_KEY=AIzaSyD...
```

**Usage:**

```python
spec = load_workflow_google_sheets(
    "SPREADSHEET_ID",
    auth_method="api_key",
    api_key="AIzaSyD...",
)
```

**Limitations:** API key auth only works with `open_by_key` (which the adapter uses internally). The `gc.open()` method (searching by name) is not supported. Writing results requires a service account or OAuth — API key auth is read-only for most practical purposes.

### Choosing auth method at call time

You can override the configured auth method per call:

```python
# Config says service_account, but this call uses API key
spec = load_workflow_google_sheets(
    "SPREADSHEET_ID",
    auth_method="api_key",
    api_key="AIzaSyD...",
)
```

The `auth_method` parameter takes precedence over the config setting.

## Loading Workflows

### `load_workflow_google_sheets(spreadsheet_id, *, ...)`

```python
from ffai_workflow_adapters import load_workflow_google_sheets

spec = load_workflow_google_sheets(
    "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",  # spreadsheet ID from URL
    worksheet="Steps",          # optional: worksheet name or index (default: first worksheet)
    adapter="marketing",        # optional: named adapter from config
    auth_method="service_account",  # optional: "service_account" (default), "oauth", or "api_key"
    credentials_file="/path/to/sa.json",  # optional: overrides env var
    credentials_env="MY_CREDS_VAR",       # optional: overrides config env var name
    name="my_workflow",
    defaults={"temperature": 0.5},
    clients={"reviewer": {"type": "litellm", "model": "gpt-4o"}},
)
```

The `spreadsheet_id` is the long string in the Google Sheets URL:

```
https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
```

### Worksheet Format

The first row of the selected worksheet must be a header with column names. Each subsequent row is a workflow step.

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

### Example Google Sheets Workflow

| name | prompt | client | history | temperature |
|------|--------|--------|---------|-------------|
| `topic` | `Name a famous scientific discovery.` | `litellm-mistral-small` | | `0.7` |
| `explain` | `Explain its impact: {{topic.response}}` | `litellm-gpt-4o-mini` | `topic` | `0.5` |

### Worksheet Selection

The `worksheet` parameter accepts a sheet name (string) or index (integer):

```python
# By name
spec = load_workflow_google_sheets(spreadsheet_id, worksheet="Workflow")

# By index (0-based)
spec = load_workflow_google_sheets(spreadsheet_id, worksheet=1)

# Default: first worksheet
spec = load_workflow_google_sheets(spreadsheet_id)
```

## Writing Results

### `write_workflow_results_google_sheets(spreadsheet_id, result, *, ...)`

```python
from ffai_workflow_adapters import write_workflow_results_google_sheets

result = await ffai.execute_workflow(spec)

# Write to the default "Results" worksheet
write_workflow_results_google_sheets(spreadsheet_id, result)

# Specify a custom worksheet
write_workflow_results_google_sheets(spreadsheet_id, result, worksheet="Run 2")

# With passthrough columns — pass the spec returned by load_workflow_google_sheets
write_workflow_results_google_sheets(spreadsheet_id, result, spec=spec)
```

The `worksheet` parameter defaults to `output_worksheet` from the adapter config, or `"Results"` if not configured. If the worksheet doesn't exist, it is created with a header row followed by data rows. If it does exist, data rows are appended after existing data.

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
  google_sheets:
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
  google_sheets:
    passthrough_columns:
      - Comments
      - Priority
      - Category
```

At load time, values are captured from the source worksheet and stored as metadata on the spec. At write time, pass the spec to include them:

```python
spec = load_workflow_google_sheets(spreadsheet_id, worksheet="Steps")
result = await ffai.execute_workflow(spec)
write_workflow_results_google_sheets(spreadsheet_id, result, spec=spec)
```

Passthrough columns appear in the output after the standard columns, with their original names (or remapped via `output_field_map` if configured). If a step has no value for a passthrough column, `None` is written.

Named adapters inherit `passthrough_columns` from the base config and can override.

## Extra Output Columns

Add derived columns to every output row. Configure in `config/adapters.yaml`:

```yaml
adapters:
  google_sheets:
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

All templates resolve **once per write call** — every row in the same run gets the same `run_id`, `date`, etc. Pass `run_id="batch-42"` to `write_workflow_results_google_sheets()` to use a custom ID instead of the auto-generated one.

Extra columns appear in the output after passthrough columns. Named adapters inherit and can override.

## Schema Validation

At load time, the adapter validates your worksheet before making any API calls:

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

If your worksheet uses different column names, configure `input_field_map` to map them.

## Column Order in Output

Standard columns → passthrough columns → extra output columns.

## Resilience

All Google Sheets API calls are automatically protected by:

1. **Rate limiting** — A token-bucket limiter caps request throughput (default: 5 req/s, burst 10).
2. **Circuit breaker** — After repeated failures (default: 5), calls are blocked until a recovery timeout (default: 30s), then a limited number of probe requests are allowed before the circuit fully re-opens.
3. **Retry with backoff** — Failed requests with retryable status codes (429, 502, 503, 504) are retried with exponential backoff and jitter (default: 3 attempts).

These are internal — the public API is unchanged. Configure via `config/main.yaml`. See [Airtable adapter - Resilience](airtable.md#resilience) for full configuration details.

## Observability

Adapter operations emit OpenTelemetry spans when FFAI's observability is enabled. Spans cover Google Sheets load and write operations, including record counts, timing, and error details.

### Enabling

Same as Airtable adapter — see [Airtable adapter - Observability](airtable.md#observability).

### Emitted Spans

| Span Name | Operation | Key Attributes |
|-----------|-----------|----------------|
| `ffai.adapters.google_sheets.load` | Load workflow from spreadsheet | `adapter`, `spreadsheet_id`, `worksheet`, `rows.count`, `workflow.name` |
| `ffai.adapters.google_sheets.write` | Write results to spreadsheet | `adapter`, `spreadsheet_id`, `run_id`, `records.count`, `records.appended` |
| `ffai.adapters.resilience.call` | External API call (Google Sheets) | `call.success`, `circuit_breaker.failures` |
| `ffai.adapters.resilience.retry` | Retry attempt | `attempt`, `max_attempts`, `wait_seconds` |

## Config Reference

```yaml
adapters:
  google_sheets:
    # Authentication method: "service_account" (default), "oauth", or "api_key"
    auth_method: service_account

    # Service account / OAuth credentials env var (holds path to JSON file)
    credentials_env: GOOGLE_SHEETS_CREDENTIALS

    # OAuth authorized user env var (holds path to authorized_user.json)
    authorized_user_env: GOOGLE_SHEETS_AUTHORIZED_USER

    # API key env var (for api_key auth method)
    api_key_env: GOOGLE_SHEETS_API_KEY

    # Output worksheet name (used when worksheet= is omitted)
    output_worksheet: "Results"

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
from ffai_workflow_adapters import (
    load_workflow_google_sheets,
    write_workflow_results_google_sheets,
)

SPREADSHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"

async def main():
    client = AsyncFFLiteLLMClient(model_string="mistral/mistral-small-latest", api_key="...")
    ffai = FFAI(client)

    spec = load_workflow_google_sheets(
        SPREADSHEET_ID,
        worksheet="Steps",
        name="sheets_workflow",
    )
    result = await ffai.execute_workflow(spec)

    # Appends to "Results" worksheet with passthrough + extra columns
    write_workflow_results_google_sheets(SPREADSHEET_ID, result, spec=spec)

asyncio.run(main())
```

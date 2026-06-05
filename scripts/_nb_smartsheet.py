import nbformat as nbf

nb = nbf.v4.new_notebook()
nb.cells = []


def code(s):
    nb.cells.append(nbf.v4.new_code_cell(s))


def md(s):
    nb.cells.append(nbf.v4.new_markdown_cell(s))


md("""\
# Smartsheet Workflow Tutorial

This notebook demonstrates the full lifecycle of an ffai workflow using Smartsheet:

1. **Authenticate** with Smartsheet (access token)
2. **Populate** a sheet with workflow steps
3. **Load** the workflow into an ffai `WorkflowSpec`
4. **Execute** the workflow against an LLM
5. **Write** results back to another sheet

## Prerequisites

```bash
pip install ffai-workflow-adapters[smartsheet]
```

You also need:
- A Smartsheet account with API access
- An access token (generate at Account > Personal Settings > API Access)
- A sheet to use as the workflow source
""")

md("""\
---
<div class="page-break"></div>

## Section 1: Configuration

Enter your sheet ID and access token.
""")

code("""\
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path
_cwd = Path().resolve()
_project_root = _cwd
for _p in [_cwd, *list(_cwd.parents)]:
    if (_p / "pyproject.toml").is_file():
        _project_root = _p
        break
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()  # noqa: E402

# --- Your sheet ID (integer from the sheet URL) ---
# The sheet ID is the numeric value in the Smartsheet URL:
# https://app.smartsheet.com/sheets/<SHEET_ID>
SHEET_ID = int(os.environ.get(
    "SMARTSHEET_SHEET_ID",
    "0",
))

# --- Access token ---
# Set SMARTSHEET_ACCESS_TOKEN in your .env or environment
ACCESS_TOKEN = os.environ.get("SMARTSHEET_ACCESS_TOKEN", "")

if SHEET_ID == 0:
    print("WARNING: Set SMARTSHEET_SHEET_ID to your workflow sheet ID")
if not ACCESS_TOKEN:
    print("WARNING: Set SMARTSHEET_ACCESS_TOKEN in your environment")
else:
    print(f"Sheet ID: {SHEET_ID}")
    print("Access token: configured")
""")

md("""\
---
<div class="page-break"></div>

## Section 2: Populate the Workflow Sheet

Create workflow step definitions on the sheet. This uses the `smartsheet` SDK
directly to add columns and rows.
""")

code("""\
import smartsheet

# Connect to Smartsheet
smart = smartsheet.Smartsheet(access_token=ACCESS_TOKEN)

# Define workflow steps
# Each dict is a row. Keys are column headers.
workflow_steps = [
    {
        "name": "topic",
        "prompt": "Name a famous scientific discovery and describe it in one sentence.",
        "temperature": 0.7,
    },
    {
        "name": "explain",
        "prompt": "Given this discovery: {{topic.response}} -- write a paragraph about its historical impact.",
        "history": "topic",
        "temperature": 0.5,
    },
    {
        "name": "modern",
        "prompt": "Given this discovery: {{topic.response}} -- how is it applied in modern technology today?",
        "history": "topic",
        "temperature": 0.6,
    },
]

headers = ["name", "prompt", "temperature", "history"]

print(f"Workflow has {len(workflow_steps)} steps:")
for step in workflow_steps:
    print(f"  - {step['name']}: {step['prompt'][:60]}...")
""")

code("""\
# Add columns to the sheet
# First check what columns already exist
sheet = smart.Sheets.get_sheet(SHEET_ID)

existing_col_titles = [col.title for col in sheet.columns]
print(f"Existing columns: {existing_col_titles}")

# Create any missing columns
col_map = {col.title: col.id for col in sheet.columns}
for header in headers:
    if header not in existing_col_titles:
        new_col = smartsheet.models.Column({
            "title": header,
            "type": "TEXT_NUMBER",
            "primary": header == "name",
        })
        result = smart.Sheets.add_columns(SHEET_ID, [new_col])
        col_map[header] = result.data[0].id
        print(f"Added column: {header}")

# Refresh sheet to get updated column list
sheet = smart.Sheets.get_sheet(SHEET_ID)
col_map = {col.title: col.id for col in sheet.columns}
print(f"Column map: {col_map}")
""")

code("""\
# Add workflow step rows
rows_to_add = []
for step in workflow_steps:
    new_row = smartsheet.models.Row()
    new_row.cells = [
        smartsheet.models.Cell({
            "column_id": col_map[h],
            "value": step.get(h, ""),
        })
        for h in headers
    ]
    rows_to_add.append(new_row)

result = smart.Sheets.add_rows(SHEET_ID, rows_to_add)
print(f"Added {len(result.data)} rows to sheet")
""")

md("""\
Verify the sheet contents:
""")

code("""\
# Read back the sheet to confirm
sheet = smart.Sheets.get_sheet(SHEET_ID)

col_map = {col.id: col.title for col in sheet.columns}
for row in sheet.rows:
    record = {}
    for cell in row.cells:
        title = col_map.get(cell.column_id)
        if title is not None:
            record[title] = cell.value
    print("  ".join(f"{k}: {v}" for k, v in record.items()))
""")

md("""\
---
<div class="page-break"></div>

## Section 3: Load the Workflow

Use the adapter to load the sheet into an ffai `WorkflowSpec`.
""")

code("""\
from ffai_workflow_adapters import (
    load_workflow_smartsheet,
    write_workflow_results_smartsheet,
)

# Load the workflow from Smartsheet
spec = load_workflow_smartsheet(
    SHEET_ID,
    access_token=ACCESS_TOKEN,
    name="smartsheet_tutorial",
)

print(f"Workflow: {spec.name}")
print(f"Steps: {len(spec.prompts)}")
for p in spec.prompts:
    hist = f" [history: {p.history}]" if p.history else ""
    print(f"  - {p.name} (temp={p.temperature}){hist}")
    print(f"    {p.prompt[:80]}{'...' if len(p.prompt) > 80 else ''}")
""")

md("""\
---
<div class="page-break"></div>

## Section 4: Execute the Workflow

Run the workflow through ffai with your LLM client. Set `MISTRAL_API_KEY` or
`OPENAI_API_KEY` in your `.env` file.
""")

code("""\
import asyncio
import concurrent.futures
from ffai import FFAI
from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient

def run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()

# Create the LLM client
model_string = os.environ.get("FFAI_MODEL_STRING", "mistral/mistral-small-latest")
api_key_env = "MISTRAL_API_KEY" if "mistral" in model_string else "OPENAI_API_KEY"
api_key = os.environ.get(api_key_env, "")

if not api_key:
    print(f"WARNING: {api_key_env} not set. LLM calls will fail.")

client = AsyncFFLiteLLMClient(model_string=model_string, api_key=api_key)
ffai = FFAI(client)

print(f"LLM client: {model_string}")
print("Executing workflow...")
""")

code("""\
result = run_sync(ffai.execute_workflow(spec))

print(f"Completed: {result.success_count} succeeded, {result.failed_count} failed, {result.skipped_count} skipped")
print()

for step_name, step_result in result.results.items():
    print(f"=== {step_name} ===")
    print(f"Model: {step_result.model}")
    if step_result.usage:
        print(f"Tokens: {step_result.usage.input_tokens} in + {step_result.usage.output_tokens} out")
    if step_result.cost_usd:
        print(f"Cost: ${step_result.cost_usd:.6f}")
    print(f"Duration: {step_result.duration_ms:.0f}ms")
    resp_str = str(step_result.response)
    print(f"Response: {resp_str[:200]}{'...' if len(resp_str) > 200 else ''}")
    print()
""")

md("""\
---
<div class="page-break"></div>

## Section 5: Write Results to Another Sheet

Write the execution results to a results sheet. The adapter creates
columns if needed and appends rows.
""")

code("""\
# Use a separate sheet for results (or the same sheet ID)
RESULTS_SHEET_ID = int(os.environ.get(
    "SMARTSHEET_RESULTS_SHEET_ID",
    str(SHEET_ID),
))

rows = write_workflow_results_smartsheet(
    RESULTS_SHEET_ID,
    result,
    spec=spec,
    access_token=ACCESS_TOKEN,
)

print(f"Written {len(rows)} rows to results sheet")
print(f"Columns per row: {len(rows[0]) if rows else 0}")
""")

md("""\
Verify the results sheet:
""")

code("""\
# Read back the results sheet
results_sheet = smart.Sheets.get_sheet(RESULTS_SHEET_ID)

col_map = {col.id: col.title for col in results_sheet.columns}
print(f"Results: {results_sheet.total_row_count} rows")
print()

for row in results_sheet.rows:
    record = {}
    for cell in row.cells:
        title = col_map.get(cell.column_id)
        if title is not None:
            record[title] = cell.value
    headers = list(record.keys())
    print("  ".join(str(record.get(h, "")) for h in headers))
""")

md("""\
---
<div class="page-break"></div>

## Summary

What happened in this notebook:

| Step | Action | Output |
|------|--------|--------|
| Section 1 | Configured auth (access token) | Smartsheet client |
| Section 2 | Populated sheet with 3 workflow steps | Smartsheet rows |
| Section 3 | Loaded steps into an ffai `WorkflowSpec` | Workflow with 3 prompts |
| Section 4 | Executed the workflow against an LLM | `WorkflowResult` with responses |
| Section 5 | Wrote results to results sheet | Appended rows to Smartsheet |

### Smartsheet specifics

- **Single auth method** — just an access token (simpler than Google Sheets)
- **Sheet = entire spreadsheet** — no worksheet concept; each sheet has its own ID
- **Column IDs** — Smartsheet uses integer column IDs internally; the adapter handles translation
- **Rate limiting** — the adapter uses `ResilientCaller` for automatic retry and backoff

### Next steps

- Try adding **passthrough columns** (e.g. Comments, Priority) in `config/adapters.yaml`
- Configure **extra output columns** (e.g. `run_id`, `run_date`) for tracking
- Use **field mapping** if your sheet uses custom column names
- Set up **named adapters** for different workflows in the same account
""")

nb.metadata["language_info"] = {
    "codemirror_mode": {"name": "ipython", "version": 3},
    "file_extension": ".py",
    "mimetype": "text/x-python",
    "name": "python",
    "nbconvert_exporter": "python",
    "pygments_lexer": "ipython3",
    "version": "3.14.5",
}

with open("examples/smartsheet/smartsheet_workflow.ipynb", "w") as f:
    nbf.write(nb, f)

print("Created examples/smartsheet/smartsheet_workflow.ipynb")

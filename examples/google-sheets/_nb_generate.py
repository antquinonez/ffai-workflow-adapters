"""Generate the Google Sheets tutorial notebook.

Creates examples/google-sheets/google_sheets_workflow.ipynb which walks
through populating a Google Sheet with workflow steps, loading the workflow,
executing it, and writing results to another sheet.

Usage:
    python examples/google-sheets/_nb_generate.py
"""

from pathlib import Path

import nbformat as nbf

nb = nbf.v4.new_notebook()
nb.cells = []


def code(s):
    nb.cells.append(nbf.v4.new_code_cell(s))


def md(s):
    nb.cells.append(nbf.v4.new_markdown_cell(s))


md("""\
# Google Sheets Workflow Tutorial

This notebook demonstrates the full lifecycle of an ffai workflow using Google Sheets:

1. **Authenticate** with Google Sheets (service account, OAuth, or API key)
2. **Populate** a worksheet with workflow steps
3. **Load** the workflow into an ffai `WorkflowSpec`
4. **Execute** the workflow against an LLM
5. **Write** results back to another worksheet

## Prerequisites

```bash
pip install ffai-workflow-adapters[google_sheets]
```

You also need:
- A Google Cloud project with the **Google Sheets API** and **Google Drive API** enabled
- A spreadsheet to work with (the spreadsheet ID from its URL)
- Authentication credentials (see Section 1)
""")

md("""\
---
<div class="page-break"></div>

## Section 1: Configuration

Enter your spreadsheet ID and choose an authentication method.
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

# --- Your spreadsheet ID (from the URL) ---
SPREADSHEET_ID = os.environ.get(
    "GOOGLE_SHEETS_SPREADSHEET_ID",
    "PASTE_YOUR_SPREADSHEET_ID_HERE",
)

# --- Authentication method ---
# Options: "service_account", "oauth", "api_key"
# The adapter uses whichever credentials you provide.
AUTH_METHOD = os.environ.get("GOOGLE_SHEETS_AUTH_METHOD", "service_account")

print(f"Spreadsheet ID: {SPREADSHEET_ID}")
print(f"Auth method: {AUTH_METHOD}")
""")


md("""\
### Set up authentication

Choose **one** of the three methods below. Uncomment and fill in the one you want.
""")


code("""\
from ffai_workflow_adapters.google_sheets import (
    load_workflow_google_sheets,
    write_workflow_results_google_sheets,
)

# Build auth kwargs based on your chosen method.
# The adapter picks up credentials from environment variables by default,
# but you can override them here.

auth_kwargs = {}

if AUTH_METHOD == "service_account":
    # Option A: Service Account (default)
    # Set GOOGLE_SHEETS_CREDENTIALS env var to the path of your service account JSON,
    # or pass credentials_file directly:
    # auth_kwargs["credentials_file"] = "/path/to/service-account.json"
    auth_kwargs["auth_method"] = "service_account"
    print("Using service account auth")
    print(f"  Credentials file: {os.environ.get('GOOGLE_SHEETS_CREDENTIALS', '(not set)')}")

elif AUTH_METHOD == "oauth":
    # Option B: OAuth Client ID (end-user auth)
    # Set GOOGLE_SHEETS_CREDENTIALS to your OAuth credentials JSON path.
    # Optionally set GOOGLE_SHEETS_AUTHORIZED_USER for the stored token.
    # auth_kwargs["credentials_file"] = "/path/to/credentials.json"
    # auth_kwargs["authorized_user_file"] = "/path/to/authorized_user.json"
    auth_kwargs["auth_method"] = "oauth"
    print("Using OAuth auth")
    print(f"  Credentials file: {os.environ.get('GOOGLE_SHEETS_CREDENTIALS', '(not set)')}")
    print(f"  Authorized user: {os.environ.get('GOOGLE_SHEETS_AUTHORIZED_USER', '(not set)')}")

elif AUTH_METHOD == "api_key":
    # Option C: API Key (public spreadsheets only)
    # Set GOOGLE_SHEETS_API_KEY env var, or pass api_key directly:
    # auth_kwargs["api_key"] = "AIzaSyD..."
    auth_kwargs["auth_method"] = "api_key"
    print("Using API key auth")
    print(f"  API key env: {os.environ.get('GOOGLE_SHEETS_API_KEY', '(not set)')}")

else:
    raise ValueError(f"Unknown AUTH_METHOD: {AUTH_METHOD!r}")
""")


md("""\
---
<div class="page-break"></div>

## Section 2: Populate the Workflow Sheet

Create a worksheet named "Steps" with workflow step definitions. If the worksheet
already exists, it will be cleared and re-populated.
""")


code("""\
import gspread

# Connect to Google Sheets using the same auth helper the adapter uses
from ffai_workflow_adapters.google_sheets import _resolve_auth, _get_gc
from ffai_workflow_adapters.config import get_config

cfg = get_config()
auth = _resolve_auth(
    auth_method=auth_kwargs.get("auth_method"),
    credentials_file=auth_kwargs.get("credentials_file"),
    api_key=auth_kwargs.get("api_key"),
    cfg_auth_method=cfg.adapters.google_sheets.auth_method,
    cfg_credentials_env=cfg.adapters.google_sheets.credentials_env,
    cfg_authorized_user_env=cfg.adapters.google_sheets.authorized_user_env,
    cfg_api_key_env=cfg.adapters.google_sheets.api_key_env,
)

gc = _get_gc(gspread, auth)
spreadsheet = gc.open_by_key(SPREADSHEET_ID)

print(f"Connected to: {spreadsheet.title}")
print(f"Existing worksheets: {[ws.title for ws in spreadsheet.worksheets()]}")
""")


code("""\
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
# Create or replace the "Steps" worksheet
STEPS_WORKSHEET = "Steps"

existing_titles = [ws.title for ws in spreadsheet.worksheets()]

if STEPS_WORKSHEET in existing_titles:
    steps_ws = spreadsheet.worksheet(STEPS_WORKSHEET)
    steps_ws.clear()
    print(f"Cleared existing worksheet '{STEPS_WORKSHEET}'")
else:
    steps_ws = spreadsheet.add_worksheet(
        title=STEPS_WORKSHEET,
        rows=len(workflow_steps) + 1,
        cols=len(headers),
    )
    print(f"Created worksheet '{STEPS_WORKSHEET}'")

# Write header row
steps_ws.update(values=[headers], range_name="A1")

# Write data rows
rows_to_write = [[step.get(h, "") for h in headers] for step in workflow_steps]
steps_ws.update(values=rows_to_write, range_name="A2")

print(f"Written {len(rows_to_write)} rows to '{STEPS_WORKSHEET}'")
print(f"Columns: {headers}")
""")

md("""\
Verify the worksheet contents:
""")


code("""\
# Read back the worksheet to confirm
all_records = steps_ws.get_all_records()

for row in all_records:
    print("  ".join(f"{k}: {v}" for k, v in row.items()))
""")


md("""\
---
<div class="page-break"></div>

## Section 3: Load the Workflow

Use the adapter to load the worksheet into an ffai `WorkflowSpec`.
""")


code("""\
# Load the workflow from Google Sheets
# auth_kwargs were set up in Section 1
spec = load_workflow_google_sheets(
    SPREADSHEET_ID,
    worksheet=STEPS_WORKSHEET,
    name="sheets_tutorial",
    **auth_kwargs,
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
from dotenv import load_dotenv
from ffai import FFAI
from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient

load_dotenv()

# Helper to run async code in both Jupyter and plain Python
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
result = run_sync(ffai.workflow.execute_workflow(spec))

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

Write the execution results to a "Results" worksheet in the same spreadsheet.
The adapter creates the worksheet if it doesn't exist, or appends if it does.
""")


code("""\
RESULTS_WORKSHEET = "Results"

rows = write_workflow_results_google_sheets(
    SPREADSHEET_ID,
    result,
    worksheet=RESULTS_WORKSHEET,
    spec=spec,  # includes passthrough column data from load
    **auth_kwargs,
)

print(f"Written {len(rows)} rows to '{RESULTS_WORKSHEET}'")
print(f"Columns per row: {len(rows[0]) if rows else 0}")
""")


md("""\
Verify the results worksheet:
""")


code("""\
# Read back the results worksheet
results_ws = spreadsheet.worksheet(RESULTS_WORKSHEET)
results_records = results_ws.get_all_records()

print(f"Results: {len(results_records)} rows\\n")

if results_records:
    # Print header
    headers = list(results_records[0].keys())
    print("  ".join(headers))
    print("  ".join("-" * len(h) for h in headers))
    for row in results_records:
        print("  ".join(str(row.get(h, "")) for h in headers))
""")


md("""\
---
<div class="page-break"></div>

## Summary

What happened in this notebook:

| Step | Action | Output |
|------|--------|--------|
| Section 1 | Configured auth (service account / OAuth / API key) | Auth kwargs |
| Section 2 | Populated "Steps" worksheet with 3 workflow steps | Google Sheet rows |
| Section 3 | Loaded steps into an ffai `WorkflowSpec` | Workflow with 3 prompts |
| Section 4 | Executed the workflow against an LLM | `WorkflowResult` with responses |
| Section 5 | Wrote results to "Results" worksheet | Appended rows to Google Sheet |

### Next steps

- Try adding **passthrough columns** (e.g. Comments, Priority) in `config/adapters.yaml`
- Configure **extra output columns** (e.g. `run_id`, `run_date`) for tracking
- Use **field mapping** if your sheet uses custom column names
- Set up **named adapters** for different workflows in the same spreadsheet
- See the [Google Sheets adapter docs](../../docs/google-sheets.md) for full configuration options
""")


# Write the notebook
out_path = Path(__file__).resolve().parent / "google_sheets_workflow.ipynb"
with open(out_path, "w") as f:
    nbf.write(nb, f)

print(f"Created {out_path}")

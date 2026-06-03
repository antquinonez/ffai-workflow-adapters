"""Generate the ODS tutorial notebook.

Creates examples/ods/ods_workflow.ipynb — a workflow demonstrating
condition and abort_condition for conditional step execution using ODS files.

Usage:
    python examples/ods/_nb_generate.py
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
# ODS Workflow Tutorial — Conditional Steps

This notebook demonstrates an ffai workflow with **conditional execution** using
OpenDocument Spreadsheet (.ods) files:

- `condition` — skip a step unless the expression is true
- `abort_condition` — stop the entire workflow if the expression is true

The workflow is a research triage pipeline:

1. **topic** — Generate a research topic idea
2. **evaluate** — Rate the topic's viability (returns JSON)
3. **refine** — Improve the topic *(only runs if viability is low)*
4. **cost_check** — Estimate complexity *(aborts if too complex)*
5. **plan** — Create a research plan

## Prerequisites

```bash
pip install ffai-workflow-adapters[ods]
```

This installs [odfpy](https://pypi.org/project/odfpy/), a pure-Python ODS library.
""")


code("""\
import os
import sys
from pathlib import Path

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

from odf.opendocument import OpenDocumentSpreadsheet  # noqa: E402
from odf.table import Table, TableRow, TableCell  # noqa: E402
from odf.text import P  # noqa: E402
from ffai_workflow_adapters import load_workflow_ods, write_workflow_results_ods  # noqa: E402

print(f"Project root: {_project_root}")
""")


md("""\
---
<div class="page-break"></div>

## Section 1: Create the Workflow Workbook

Build an ODS file with 5 steps demonstrating `condition` and `abort_condition`.
""")


code("""\
def text_cell(text):
    cell = TableCell()
    p = P()
    p.addText(str(text))
    cell.addElement(p)
    return cell


ODS_DIR = Path(_project_root) / "examples" / "ods"
ODS_FILE = str(ODS_DIR / "tutorial_workflow.ods")
ODS_RESULTS = str(ODS_DIR / "tutorial_results.ods")

headers = ["name", "prompt", "condition", "abort_condition", "temperature"]

steps = [
    {
        "name": "topic",
        "prompt": "Suggest a specific, novel research topic in the field of quantum computing. One sentence only.",
        "condition": "",
        "abort_condition": "",
        "temperature": 0.8,
    },
    {
        "name": "evaluate",
        "prompt": (
            "Rate this research topic on viability and novelty. "
            'Respond with ONLY JSON: {"viable": true, "score": 7, "novelty": "high"} '
            "where viable is true if score >= 7.\\n\\nTopic: {{topic.response}}"
        ),
        "condition": "",
        "abort_condition": "",
        "temperature": 0.2,
    },
    {
        "name": "refine",
        "prompt": (
            "This research topic scored below 7 on viability. Suggest an improved, "
            "more feasible version of it.\\n\\n"
            "Original: {{topic.response}}\\n"
            "Evaluation: {{evaluate.response}}"
        ),
        "condition": 'json_get({{evaluate.response}}, "viable") == False',
        "abort_condition": "",
        "temperature": 0.7,
    },
    {
        "name": "cost_check",
        "prompt": (
            "Estimate how complex this research would be. "
            'Respond with ONLY JSON: {"complexity": "low"|"medium"|"high", '
            '"estimated_months": 6, "feasible": true} '
            "where feasible is false if estimated_months > 24.\\n\\n"
            "Topic: {{refine.response}}{{topic.response}}"
        ),
        "condition": "",
        "abort_condition": 'json_get({{cost_check.response}}, "feasible") == False',
        "temperature": 0.3,
    },
    {
        "name": "plan",
        "prompt": (
            "Create a brief 3-step research plan for this topic. "
            "Include methodology and expected timeline.\\n\\n"
            "Topic: {{refine.response}}{{topic.response}}\\n"
            "Evaluation: {{evaluate.response}}\\n"
            "Cost: {{cost_check.response}}"
        ),
        "condition": "",
        "abort_condition": "",
        "temperature": 0.5,
    },
]

# Build ODS file
doc = OpenDocumentSpreadsheet()
table = Table(name="Workflow")

header_row = TableRow()
for h in headers:
    header_row.addElement(text_cell(h))
table.addElement(header_row)

for step in steps:
    row = TableRow()
    for h in headers:
        row.addElement(text_cell(step.get(h, "")))
    table.addElement(row)

doc.spreadsheet.addElement(table)
doc.save(ODS_FILE)

print(f"Created {ODS_FILE}")
print(f"Steps: {len(steps)}")
print()
for step in steps:
    cond = f" [condition: {step['condition']}]" if step["condition"] else ""
    abort = f" [abort: {step['abort_condition']}]" if step["abort_condition"] else ""
    print(f"  {step['name']}{cond}{abort}")
""")


md("""\
---
<div class="page-break"></div>

## Section 2: Load the Workflow

Load the ODS file into an ffai `WorkflowSpec`.
""")


code("""\
spec = load_workflow_ods(ODS_FILE, sheet="Workflow", name="ods_conditional")

print(f"Workflow: {spec.name}")
print(f"Steps: {len(spec.prompts)}")
print()
for p in spec.prompts:
    cond = f" [condition: {p.condition}]" if p.condition else ""
    abort = f" [abort: {p.abort_condition}]" if p.abort_condition else ""
    print(f"  {p.name} (temp={p.temperature}){cond}{abort}")
    print(f"    {p.prompt[:90]}{'...' if len(p.prompt) > 90 else ''}")
""")


md("""\
---
<div class="page-break"></div>

## Section 3: Execute the Workflow

Run the workflow through ffai. The `refine` step will be **skipped** if the
topic scores 7+, and the workflow will **abort** if the cost check shows
it's too complex (> 24 months).
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

print(f"Completed: {result.success_count} succeeded, {result.failed_count} failed, {result.skipped_count} skipped, {result.aborted_count} aborted")
print(f"Aborted: {result.aborted}")
print()

for step_name, step_result in result.results.items():
    status_icon = {"success": "+", "failed": "X", "skipped": "-"}.get(step_result.status, "?")
    print(f"[{status_icon}] {step_name}: {step_result.status}")
    if step_result.status == "success":
        print(f"    Model: {step_result.model}")
        if step_result.usage:
            print(f"    Tokens: {step_result.usage.input_tokens} in + {step_result.usage.output_tokens} out")
        resp_str = str(step_result.response)
        print(f"    Response: {resp_str[:200]}{'...' if len(resp_str) > 200 else ''}")
    print()
""")


md("""\
---
<div class="page-break"></div>

## Section 4: Write Results

Save the execution results to an ODS file. Note: ODS write always creates a
new file (unlike CSV which appends).
""")


code("""\
saved = write_workflow_results_ods(result, path=ODS_RESULTS, sheet="Results", spec=spec)
print(f"Saved to {saved}")

# Read back and display
from ffai_workflow_adapters.ods import _cell_value  # noqa: E402

doc_results = __import__("odf.opendocument", fromlist=["load"]).load(saved)
tables = doc_results.spreadsheet.getElementsByType(Table)

from odf.table import TableRow as _TR  # noqa: E402

rows_el = tables[0].getElementsByType(_TR)
for i, row_el in enumerate(rows_el):
    cells = row_el.getElementsByType(TableCell)
    values = [str(_cell_value(c) or "") for c in cells]
    print("  ".join(values))
""")


md("""\
---
<div class="page-break"></div>

## How Conditions Work

### `condition` — Skip a step unless true

The `refine` step uses:
```
json_get({{evaluate.response}}, "viable") == False
```
The `evaluate` step returns JSON like `{"viable": true, "score": 7}`. The `json_get`
function extracts the `"viable"` field. If it's `False` (score < 7), `refine` runs.

### `abort_condition` — Stop the workflow if true

The `cost_check` step uses:
```
json_get({{cost_check.response}}, "feasible") == False
```
The `cost_check` step returns JSON like `{"feasible": true, "estimated_months": 12}`.
If `feasible` is `False`, the workflow **aborts**.

### Condition syntax reference

| Expression | Meaning |
|-----------|---------|
| `{{step.response}} contains "text"` | Response includes substring |
| `{{step.status}} == "success"` | Status check |
| `{{step.has_response}}` | Has a non-empty response |
| `len({{step.response}}) > 100` | Response length check |
| `{{a.status}} == "success" and {{b.status}} == "success"` | Boolean AND |
| `{{step.response}} matches "pattern"` | Regex match |

### ODS specifics

- ODS write always creates a **new file** (no append — ODS format limitation)
- Sheet selection via `sheet` parameter (name or 0-based index)
- Uses [odfpy](https://pypi.org/project/odfpy/) — pure Python, no system dependencies

### Next steps

- Try adjusting the viability threshold from 7 to a different value
- Add more conditional steps for different score ranges
- Configure **passthrough columns** and **extra output columns** in `config/adapters.yaml`
- See [ODS adapter docs](../../docs/ods.md) for full configuration options
""")


out_path = Path(__file__).resolve().parent / "ods_workflow.ipynb"
with open(out_path, "w") as f:
    nbf.write(nb, f)

print(f"Created {out_path}")

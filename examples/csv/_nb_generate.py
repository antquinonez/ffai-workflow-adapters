"""Generate the CSV/TSV tutorial notebook.

Creates examples/csv/csv_workflow.ipynb — a workflow demonstrating
condition and abort_condition for conditional step execution using CSV and TSV.

Usage:
    python examples/csv/_nb_generate.py
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
# CSV/TSV Workflow Tutorial — Conditional Steps

This notebook demonstrates an ffai workflow with **conditional execution** using CSV and TSV files:

- `condition` — skip a step unless the expression is true
- `abort_condition` — stop the entire workflow if the expression is true

The workflow is a product review analysis pipeline:

1. **extract** — Extract pros and cons from a product review (returns JSON)
2. **sentiment** — Classify overall sentiment (returns JSON)
3. **escalate** — Suggest manager escalation *(only runs if sentiment is negative)*
4. **flag** — Check for inappropriate content *(aborts workflow if flagged)*
5. **report** — Write a summary report

## Prerequisites

```bash
pip install ffai-workflow-adapters[csv]
```

No extra dependencies — CSV support uses Python's built-in `csv` module.
""")


code("""\
import csv
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

from ffai_workflow_adapters import (  # noqa: E402
    load_workflow_csv,
    load_workflow_tsv,
    write_workflow_results_csv,
    write_workflow_results_tsv,
)

print(f"Project root: {_project_root}")
""")


md("""\
---
<div class="page-break"></div>

## Section 1: Create the Workflow Files

Build both a CSV and a TSV file with the same 5-step conditional workflow.
""")


code("""\
CSV_DIR = Path(_project_root) / "examples" / "csv"
CSV_FILE = str(CSV_DIR / "tutorial_workflow.csv")
TSV_FILE = str(CSV_DIR / "tutorial_workflow.tsv")
CSV_RESULTS = str(CSV_DIR / "tutorial_results.csv")
TSV_RESULTS = str(CSV_DIR / "tutorial_results.tsv")

headers = ["name", "prompt", "condition", "abort_condition", "temperature"]

steps = [
    {
        "name": "extract",
        "prompt": (
            "Analyze this product review. Extract the pros and cons as a JSON object: "
            '{"pros": ["..."], "cons": ["..."]}\\n\\n'
            'Review: "The laptop is fast and lightweight, but the battery life is terrible '
            'and the keyboard feels cheap. The screen is gorgeous though."'
        ),
        "condition": "",
        "abort_condition": "",
        "temperature": 0.3,
    },
    {
        "name": "sentiment",
        "prompt": (
            "Classify the overall sentiment of this review as JSON: "
            '{"sentiment": "positive"|"negative"|"mixed", "confidence": 0.95}\\n\\n'
            "Review: {{extract.response}}"
        ),
        "condition": "",
        "abort_condition": "",
        "temperature": 0.2,
    },
    {
        "name": "escalate",
        "prompt": (
            "This review has negative sentiment. Write a brief escalation note for a product manager "
            "explaining why this review needs attention.\\n\\n"
            "Analysis: {{extract.response}}\\n"
            "Sentiment: {{sentiment.response}}"
        ),
        "condition": '{{sentiment.response}} contains "negative"',
        "abort_condition": "",
        "temperature": 0.5,
    },
    {
        "name": "flag",
        "prompt": (
            "Check this review analysis for any inappropriate or harmful content. "
            'Respond with JSON: {"safe": true, "flagged": false, "reason": ""}\\n\\n'
            "Analysis: {{extract.response}}"
        ),
        "condition": "",
        "abort_condition": 'json_get({{flag.response}}, "flagged") == True',
        "temperature": 0.1,
    },
    {
        "name": "report",
        "prompt": (
            "Write a one-paragraph summary report for this product review analysis. "
            "Include sentiment, key pros/cons, and whether escalation is needed.\\n\\n"
            "Extract: {{extract.response}}\\n"
            "Sentiment: {{sentiment.response}}\\n"
            "Escalation: {{escalate.response}}"
        ),
        "condition": "",
        "abort_condition": "",
        "temperature": 0.5,
    },
]

# Write CSV
with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f, delimiter=",")
    writer.writerow(headers)
    for step in steps:
        writer.writerow([step.get(h, "") for h in headers])

# Write TSV
with open(TSV_FILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f, delimiter="\\t")
    writer.writerow(headers)
    for step in steps:
        writer.writerow([step.get(h, "") for h in headers])

print(f"Created {CSV_FILE}")
print(f"Created {TSV_FILE}")
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

## Section 2: Load the Workflow (CSV)

Load the CSV file into an ffai `WorkflowSpec`.
""")


code("""\
spec = load_workflow_csv(CSV_FILE, name="csv_conditional")

print(f"Workflow: {spec.name}")
print(f"Steps: {len(spec.prompts)}")
print()
for p in spec.prompts:
    cond = f" [condition: {p.condition}]" if p.condition else ""
    abort = f" [abort: {p.abort_condition}]" if p.abort_condition else ""
    print(f"  {p.name} (temp={p.temperature}){cond}{abort}")
""")


md("""\
---
<div class="page-break"></div>

## Section 3: Load the Workflow (TSV)

Same workflow, but from a TSV file. The `load_workflow_tsv` function is a
thin wrapper around `load_workflow_csv` with `delimiter="\\t"`.
""")


code("""\
spec_tsv = load_workflow_tsv(TSV_FILE, name="tsv_conditional")

print(f"Workflow: {spec_tsv.name}")
print(f"Steps: {len(spec_tsv.prompts)}")
assert len(spec_tsv.prompts) == len(spec.prompts), "CSV and TSV should have same steps"
print("CSV and TSV load identically")
""")


md("""\
---
<div class="page-break"></div>

## Section 4: Execute the Workflow

Run the CSV workflow through ffai. The `escalate` step will be **skipped**
if sentiment is positive, and the workflow will **abort** if content is flagged.
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
print("Executing CSV workflow...")
""")


code("""\
result = run_sync(ffai.workflow.execute_workflow(spec))

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

## Section 5: Write Results (CSV and TSV)

Save results to both CSV and TSV formats.
""")


code("""\
csv_path = write_workflow_results_csv(result, path=CSV_RESULTS, spec=spec)
print(f"CSV saved to {csv_path}")

tsv_path = write_workflow_results_tsv(result, path=TSV_RESULTS, spec=spec)
print(f"TSV saved to {tsv_path}")
print()

# Display CSV contents
print("=== CSV Results ===")
with open(csv_path, encoding="utf-8") as f:
    for line in f:
        print(line.rstrip())
""")


md("""\
---
<div class="page-break"></div>

## How Conditions Work

### `condition` — Skip a step unless true

The `escalate` step uses:
```
{{sentiment.response}} contains "negative"
```
The `sentiment` step returns JSON like `{"sentiment": "positive", ...}`. The
`contains` operator checks the stringified response for the substring `"negative"`.
If sentiment is positive or mixed, `"negative"` is absent — `escalate` is **skipped**.

### `abort_condition` — Stop the workflow if true

The `flag` step uses:
```
json_get({{flag.response}}, "flagged") == True
```
The `flag` step returns JSON like `{"safe": true, "flagged": false}`. If `flagged`
is `True`, the workflow **aborts**. The `report` step never runs.

### Condition syntax reference

| Expression | Meaning |
|-----------|---------|
| `{{step.response}} contains "text"` | Response includes substring |
| `{{step.status}} == "success"` | Status check |
| `{{step.has_response}}` | Has a non-empty response |
| `len({{step.response}}) > 100` | Response length check |
| `{{a.status}} == "success" and {{b.status}} == "success"` | Boolean AND |
| `{{step.response}} matches "pattern"` | Regex match |

### CSV vs TSV

- `load_workflow_csv` / `write_workflow_results_csv` accept a `delimiter` parameter (default `","`)
- `load_workflow_tsv` / `write_workflow_results_tsv` are thin wrappers with `delimiter="\\t"`
- Use whichever format fits your pipeline

### Next steps

- Try changing the review text to see different condition outcomes
- Add `abort_condition` to other steps for early termination
- Configure **passthrough columns** and **extra output columns** in `config/adapters.yaml`
- See [CSV adapter docs](../../docs/csv.md) for full configuration options
""")


out_path = Path(__file__).resolve().parent / "csv_workflow.ipynb"
with open(out_path, "w") as f:
    nbf.write(nb, f)

print(f"Created {out_path}")

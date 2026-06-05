# Airtable Examples

Scripts and notebooks that use the Airtable adapter to load LLM workflows,
run RAG queries over file attachments, and write results back.

## Prerequisites

```bash
pip install ffai-workflow-adapters[airtable] litellm pandas
```

For RAG notebooks, also install:

```bash
pip install chromadb sentence-transformers "unstructured[md,docx,odt]" httpx
```

Create a `.env` file in the project root with:

```
AIRTABLE_API_KEY=pat...
AIRTABLE_BASE_ID=app...
MISTRAL_API_KEY=...
```

## Airtable Base Setup

The examples expect an Airtable base with the tables described below. Field names
must match exactly — the adapter config in `config/adapters.yaml` maps these
user-facing column names to canonical fields.

### Table: Workflow Steps

Standard workflow table used by `run_default.py`. Three records with chained
template variables (`{{topic.response}}`).

| Field | Type | Purpose |
|-------|------|---------|
| Name | singleLineText | Step name (mapped to canonical `name`) |
| Prompt | multilineText | Prompt text, supports `{{step.response}}` templates |
| Model | singleSelect | Client name — `litellm-mistral-small` or `litellm-gpt-4o-mini` |
| Temperature | number (precision 2) | Sampling temperature |
| Max Tokens | number (precision 0) | Max response tokens |
| History | singleLineText | Name of prior step whose response to include as context |

The **"basic" view** filters to non-empty records. Empty rows are skipped by the
adapter.

### Table: Custom Workflow

Same workflow structure with different column names, used by `run_named.py` to
demonstrate named adapter configs.

| Field | Type | Purpose |
|-------|------|---------|
| Task | singleLineText | Step name (mapped via named adapter's `input_field_map`) |
| Instructions | multilineText | Prompt text |
| AI Model | singleSelect | Client name |
| Temp | number | Temperature |
| Max Tokens | number | Max tokens |
| Context | singleLineText | Prior step context |

### Table: Rag Workflow

Five RAG-oriented steps with passthrough columns (Comments, Priority, Category).
Used by `rag_workflow.ipynb` to run each step per-document.

| Field | Type | Purpose |
|-------|------|---------|
| Name | singleLineText | Step name |
| Prompt | multilineText | Prompt, supports `{{summarize.response}}` templates |
| Model | singleSelect | `litellm-mistral-small` or `litellm-gpt-4o-mini` |
| Temperature | number | Sampling temperature |
| Max Tokens | number | Max response tokens |
| Comments | multilineText | Passthrough column — written to results |
| Priority | singleSelect: `High`, `Medium`, `Low` | Passthrough column |
| Category | singleSelect: `RAG` | Passthrough column |

The **"rag" view** filters to the 5 workflow steps.

Default step values:

| Name | Model | Temp | Priority | Prompt (first 80 chars) |
|------|-------|------|----------|------------------------|
| questions | litellm-mistral-small | 0.6 | Medium | Generate 5 insightful questions... |
| findings | litellm-mistral-small | 0.3 | High | What are the main findings... |
| summarize | litellm-mistral-small | 0.5 | High | Summarize the key topics... |
| detail | litellm-gpt-4o-mini | 0.7 | Medium | Based on the summary: {{summarize.response}}... |
| report | litellm-gpt-4o-mini | 0.5 | Low | Using the summary: {{summarize.response}} and... |

### Table: Documents

File attachments for RAG indexing. 13 records — mix of Markdown, plain text,
DOCX, and ODT files.

| Field | Type | Purpose |
|-------|------|---------|
| Name | singleLineText | Display name |
| Description | singleLineText | Short description |
| File | multipleAttachments | The document file |
| Status | singleSelect: `Todo`, `In progress`, `Done` | Processing status |

### Table: \_results

Output table for `run_default.py`. Created by the adapter's `write_workflow_results()`.

| Field | Type | Purpose |
|-------|------|---------|
| Workflow | singleLineText | Workflow name |
| Step | singleLineText | Step name |
| Status | singleLineText | `completed` |
| Response | multilineText | LLM response |
| Model | singleLineText | Model used |
| Input Tokens | number | Prompt tokens |
| Output Tokens | number | Completion tokens |
| Cost | currency ($, precision 7) | Cost in USD |
| Duration ms | number (precision 1) | Wall-clock time |
| Timestamp | singleLineText | ISO 8601 UTC |
| run_id | singleLineText | Run identifier (e.g. `20260604-153000`) |
| run_date | date | Run date |

### Table: \_results\_custom

Same structure as `_results` but with the named adapter's output field map.
`Step` becomes `Task`, `Response` becomes `Output`, `Model` becomes `AI Model`.

### Table: \_results\_rag

Output table for RAG notebooks. Same structure as `_results` plus passthrough
columns from `Rag Workflow`:

| Extra Field | Type | Notes |
|-------------|------|-------|
| Comments | multilineText | Passthrough from workflow step |
| Priority | singleSelect: `High`, `Medium`, `Low` | Must match Rag Workflow options |
| Category | singleSelect: `RAG` | Must match Rag Workflow options |

**Pitfall:** Priority and Category are `singleSelect` fields. Writing a value
that isn't a pre-configured option raises `INVALID_MULTIPLE_CHOICE_OPTIONS`. The
RAG notebooks handle this with a fallback that retries without passthrough columns.

## Scripts

### run_default.py

Loads 3 steps from "Workflow Steps" (basic view) using the default adapter
config, executes them via ffai, writes results to `_results`.

```bash
python examples/airtable/run_default.py
```

### run_named.py

Same flow but uses the `"custom"` named adapter, loading from "Custom Workflow"
with different column names (Task/Instructions/AI Model). Writes to `_results_custom`.

```bash
python examples/airtable/run_named.py
```

### helpers.py

Shared utilities used by both scripts — `create_default_client()`, `get_base_id()`,
and `run_workflow()`. Not run directly.

## Notebooks

### rag_workflow.ipynb

Full RAG pipeline — downloads all file attachments, extracts text, indexes into
ChromaDB (collection `airtable_rag`), loads 5 workflow steps from "Rag Workflow",
and runs each step **per-document** using `source=filename` filtering. Writes
results to `_results_rag`.

Generated by `_nb_rag_workflow.py`. Execute headlessly:

```bash
jupyter nbconvert --to notebook --execute \
    --ExecutePreprocessor.timeout=300 \
    examples/airtable/rag_workflow.ipynb --output rag_workflow.ipynb
```

### rag_search.ipynb

Three targeted RAG queries (architecture, people, adapters) across all 13
indexed documents. Uses a separate ChromaDB collection (`airtable_search`) and
`AttachmentSync`/`DocumentSync` for three-tier checksum dedup — repeat runs
skip unchanged documents with zero I/O.

Generated by `_nb_rag_search.py`. Execute headlessly:

```bash
jupyter nbconvert --to notebook --execute \
    --ExecutePreprocessor.timeout=600 \
    examples/airtable/rag_search.ipynb --output rag_search.ipynb
```

## Field Mapping Reference

The adapter config maps Airtable column names to canonical field names. This
decouples the user's spreadsheet from the library's internals.

**Input field map** (Airtable → canonical):

| Airtable Column | Canonical Field | Used By |
|----------------|-----------------|---------|
| Name | name | All adapters |
| Prompt | prompt | All adapters |
| Model | client | All adapters |
| History | history | All adapters |
| Temperature | temperature | All adapters |
| Max Tokens | max_tokens | All adapters |

The `"custom"` named adapter overrides to: Task→name, Instructions→prompt,
AI Model→client, Context→history, Temp→temperature. Dict fields (like
`input_field_map`) are **merged** into the base config, so columns not
overridden (e.g. Max Tokens) are still recognized.

**Output field map** (canonical → Airtable):

| Canonical Field | Airtable Column | Type |
|----------------|-----------------|------|
| workflow | Workflow | singleLineText |
| step | Step | singleLineText |
| status | Status | singleLineText |
| response | Response | multilineText |
| model | Model | singleLineText |
| input_tokens | Input Tokens | number |
| output_tokens | Output Tokens | number |
| cost_usd | Cost | currency |
| duration_ms | Duration ms | number |
| timestamp | Timestamp | singleLineText |

## Client Config

Models are referenced by client name in Airtable's `Model` column. The actual
model string is resolved from `config/clients.yaml`:

| Client Name | Provider | Model String |
|-------------|----------|-------------|
| litellm-mistral-small | Mistral | `mistral/mistral-small-latest` |
| litellm-gpt-4o-mini | OpenAI | `openai/gpt-4o-mini` |

The `Model` column in Airtable must contain one of these client names exactly
(as a singleSelect option). The adapter resolves the full model string and API
key from the config at runtime.

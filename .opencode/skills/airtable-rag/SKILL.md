---
name: airtable-rag
description: >
  Use when building notebooks or scripts that integrate Airtable file attachments
  with ffai RAG (Retrieval-Augmented Generation). Covers attachment downloading,
  text extraction, ChromaDB indexing, per-document RAG queries with source filtering,
  generate_fn with GenerationResult for token/cost tracking, and writing results
  back to Airtable. Load BEFORE creating or modifying any RAG+Airtable integration.
license: MIT
---

# Airtable + RAG Integration Guide

Patterns for combining the Airtable adapter with ffai's RAG pipeline. Each section
documents a pattern that required failed runs to discover — follow them to avoid
silent data loss, deadlocks, and write failures.

## Table of Contents

- [Architecture](#architecture)
- [Attachment Download](#attachment-download)
- [Text Extraction](#text-extraction)
- [RAG Pipeline Setup](#rag-pipeline-setup)
- [generate_fn Must Return GenerationResult](#generate_fn-must-return-generationresult)
- [Per-Document Execution with Source Filtering](#per-document-execution-with-source-filtering)
- [Async in Jupyter](#async-in-jupyter)
- [Writing Results to Airtable](#writing-results-to-airtable)
- [Dependencies](#dependencies)
- [Validation](#validation)

## Architecture

```
Airtable "Documents" table
  └─ File attachments (PDF, DOCX, TXT, MD, ODT)
       │
       ▼  download via pyairtable + httpx
Local files in ffai_data/
       │
       ▼  extract text via unstructured
Plain text strings
       │
       ▼  rag.aindex(text, source=filename)
ChromaDB vector store (persisted)
       │
       ▼  rag.aquery(prompt, generate_fn=..., source=filename)
QueryResult (answer, hits, sources, usage, cost_usd, duration_ms)
       │
       ▼  pyairtable batch_create
Airtable "_results_*" table
```

## Attachment Download

Airtable attachment URLs are **temporary** and expire. Download fresh each run.
Use the Airtable API key as a Bearer token.

### Using AttachmentSync (recommended)

```python
from ffai_workflow_adapters import AttachmentSync

att_sync = AttachmentSync(DATA_DIR, api_key)

# Classify records into unchanged vs needs-work (tier 1: size check)
unchanged, needs_work = att_sync.classify(docs_records)

# Download individual files
filepath = att_sync.download(url, filename)

# Record checksum metadata after extraction
att_sync.record(filename, airtable_size, checksum, text_len)

# Persist checksums.json
att_sync.save()
```

### Manual download (simple caching)

```python
from pyairtable.api import Api
import httpx

api = Api(api_key)
docs_table = api.table(base_id, "Documents")
docs_records = docs_table.all()

for rec in docs_records:
    attachments = rec["fields"].get("File", [])
    for att in attachments:
        filepath = DATA_DIR / att["filename"]
        if filepath.exists():
            continue  # cached
        resp = httpx.get(
            att["url"],
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        filepath.write_bytes(resp.content)
```

### Key details

- Attachment objects have keys: `filename`, `url`, `type`, `size`, `id`
- The `url` is a temporary signed URL — do not store for later use
- Cache files locally by filename to avoid re-downloading on re-runs

## Text Extraction

Use `unstructured` for multi-format support. The `partition()` function auto-detects
format from the file extension.

```python
from unstructured.partition.auto import partition

elements = partition(filename=str(filepath))
text = "\n\n".join(el.text for el in elements if el.text)
```

### Required extras

```bash
pip install "unstructured[md]"      # Markdown files
pip install "unstructured[docx]"    # DOCX files
pip install "unstructured[odt]"     # ODT files
# Or: pip install "unstructured[md,docx,odt]"
```

Without the right extras, `partition()` raises an error like:
`partition_md() is not available because one or more dependencies are not installed`

### Supported formats

PDF, DOCX, ODT, TXT, Markdown, PPTX, HTML, and more. See unstructured docs for
the full list and their required extras.

## RAG Pipeline Setup

Use local embeddings (`all-MiniLM-L6-v2`) to avoid needing additional API keys.
The first run downloads the model (~90 MB); subsequent runs use the cache.

```python
from ffai.rag import RAG
from ffai.rag.stores import get_store

CHROMA_DIR = DATA_DIR / "chroma"

rag = RAG(
    embed="local/all-MiniLM-L6-v2",
    store=get_store("chroma", collection_name="airtable_rag", dir=str(CHROMA_DIR)),
    chunker="recursive",
    chunk_size=1000,
    chunk_overlap=200,
)
```

### Indexing

Tag each document with its filename as `source` for filtering and deduplication:

```python
chunks = run_sync(rag.aindex(text, source=filename))
```

The `source` parameter is stored as metadata on each chunk in ChromaDB and can be
used to filter queries to a specific document.

## Three-Tier Dedup with DocumentSync

For repeat runs, use `DocumentSync` to skip unchanged documents entirely. It
combines `AttachmentSync` (tier 1: size check) with ChromaDB metadata (tier 2:
checksum check) and `aindex(checksum=...)` (tier 3: embedding dedup).

```python
from ffai_workflow_adapters import AttachmentSync, DocumentSync

att_sync = AttachmentSync(DATA_DIR, api_key)

def extract_text(filepath):
    from unstructured.partition.auto import partition
    elements = partition(filename=filepath)
    return "\n\n".join(el.text for el in elements if el.text)

doc_sync = DocumentSync(att_sync, extract_text)
result = doc_sync.process_records(docs_records, rag)

documents = result["documents"]       # list of {name, filename, text, checksum, text_len}
downloaded = result["downloaded"]      # files downloaded from Airtable
extracted = result["extracted"]        # files successfully extracted
fully_skipped = result["fully_skipped"]  # zero I/O (all 3 tiers matched)
```

| Tier | Check | Cost |
|------|-------|------|
| 1 | Airtable `size` matches stored `airtable_size` | API metadata only |
| 2 | Stored checksum matches ChromaDB `document_checksum` | Local DB query |
| 3 | `rag.aindex(checksum=...)` | Skips if tiers 1+2 pass |

## generate_fn Must Return GenerationResult

**This is the most critical pattern.** If `generate_fn` returns a plain string,
`rag.aquery()` silently sets usage=None, cost_usd=0.0, duration_ms=None. You lose
all token, cost, and duration data with no error or warning.

### Use the library utility

```python
from ffai_workflow_adapters import litellm_generate_fn

gen_fn = litellm_generate_fn("mistral/mistral-small-latest", api_key, temperature=0.5)
result = run_sync(rag.aquery(prompt, generate_fn=gen_fn, top_k=5))
```

`litellm_generate_fn` returns a `GenerationResult` with usage, cost_usd, and
duration_ms. It handles the litellm↔ffai token name mapping internally
(`prompt_tokens` → `input_tokens`, `completion_tokens` → `output_tokens`).

### What happens without it

```python
# Wrong — returns string, loses metrics
def generate(prompt):
    resp = litellm.completion(model="mistral/mistral-small-latest", ...)
    return resp.choices[0].message.content  # string → no metrics
```

### Why litellm.completion_cost()?

litellm tracks pricing internally. `completion_cost(resp)` returns the estimated
cost in USD for the request, covering both input and output tokens.

## Per-Document Execution with Source Filtering

**Do not query all documents at once.** When indexed documents are unrelated (e.g.,
a resume, an architecture doc, a letter), a global query returns a mashup of chunks
from different sources.

### Pattern: loop over documents, filter by source

```python
all_results = {}

for doc in documents:
    doc_name = doc["name"]
    doc_source = doc["filename"]
    step_results = {}  # per-document template state

    for step in spec.prompts:
        prompt = resolve_templates(step.prompt, step_results)
        gen_fn = litellm_generate_fn(model_string, api_key)

        result = run_sync(
            rag.aquery(prompt, generate_fn=gen_fn, top_k=5, source=doc_source)
        )

        step_results[step.name] = result.answer
        all_results[(doc_name, step.name)] = result
```

The `source=doc_source` kwarg filters the vector store search to only chunks tagged
with that filename during indexing. It passes through to ChromaDB's `where` clause.

### Template resolution between steps

`{{summarize.response}}` style references are resolved manually using a regex replacer
that looks up prior step results from the same document's run:

```python
import re

def resolve_templates(prompt, results):
    def replacer(match):
        ref = match.group(1)
        parts = ref.split(".")
        if len(parts) == 2 and parts[1] == "response" and parts[0] in results:
            return results[parts[0]]
        return match.group(0)
    return re.sub(r"\{\{([\w\.]+)\}\}", replacer, prompt)
```

Template state (`step_results`) is scoped per document — each document's chain of
steps is independent.

## Async in Jupyter

**Never call `asyncio.run()` directly in notebook code.** Jupyter runs inside an
active event loop, and `asyncio.run()` raises `RuntimeError`.

### The run_sync helper

```python
import asyncio
import concurrent.futures

def run_sync(coro):
    """Run an async coroutine from Jupyter or plain Python."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
```

Use this for all RAG async methods:

| Method | Usage |
|--------|-------|
| `rag.aindex(text, source=...)` | `run_sync(rag.aindex(...))` |
| `rag.asearch(query, top_k=5)` | `run_sync(rag.asearch(...))` |
| `rag.aquery(prompt, generate_fn=..., ...)` | `run_sync(rag.aquery(...))` |
| `rag.count()` | Call directly (sync, no event loop issue) |

### Why aquery, not query?

`rag.query()` is the sync wrapper, but it calls `asyncio.run()` internally which
deadlocks in Jupyter. `rag.aquery()` is the async native — use it with `run_sync()`.

## Writing Results to Airtable

Since `rag.aquery()` returns `QueryResult` (not ffai's `WorkflowResult`), you cannot
use `write_workflow_results()` directly. Build records manually using the adapter's
field mapping from config.

### Record construction

```python
output_field_map = airtable_cfg.output_field_map
passthrough_columns = airtable_cfg.passthrough_columns or []
extra_output_columns = airtable_cfg.extra_output_columns or {}

fields = {
    "workflow": f"{spec.name}/{doc_name}",
    "step": step.name,
    "status": "completed",
    "response": qr.answer,
    "model": model_name,
    "timestamp": timestamp_iso,
}

if qr.usage:
    fields["input_tokens"] = qr.usage.input_tokens
    fields["output_tokens"] = qr.usage.output_tokens
if qr.cost_usd is not None:
    fields["cost_usd"] = qr.cost_usd
if qr.duration_ms is not None:
    fields["duration_ms"] = round(qr.duration_ms, 1)

# Apply output field map (canonical → user column names)
if output_field_map:
    fields = {output_field_map.get(k, k): v for k, v in fields.items()}
```

### Passthrough column pitfall

If the results table has select-type fields for passthrough columns (Priority, Category),
the write fails with `INVALID_MULTIPLE_CHOICE_OPTIONS` when the values aren't
pre-configured as select options. Handle this with a fallback:

```python
try:
    created = res_table.batch_create(records)
except Exception:
    fallback = [
        {k: v for k, v in rec.items() if k not in passthrough_columns}
        for rec in records
    ]
    created = res_table.batch_create(fallback)
```

### Client config resolution

Resolve the model string and API key from the adapter's client config:

```python
client_config = config.clients
client_name = step.client.name  # e.g. "litellm-mistral-small"
client_cfg = client_config.get_client_type(client_name)
model_string = f"{client_cfg.provider_prefix}{client_cfg.default_model}"
# e.g. "mistral/mistral-small-latest"
api_key = os.environ.get(client_cfg.api_key_env, "")
```

## Dependencies

All required packages and their install commands:

```bash
pip install ffai-workflow-adapters[airtable]   # pyairtable + adapter
pip install chromadb                           # vector store backend
pip install sentence-transformers              # local embeddings
pip install "unstructured[md,docx,odt]"        # multi-format text extraction
pip install httpx                              # attachment downloads
pip install litellm                            # LLM calls in generate_fn
pip install pandas                             # results tables in notebooks
```

## Validation

After creating or modifying an Airtable+RAG notebook:

1. **Lint**: `ruff check examples/airtable/`
2. **Quick validation**: `python .opencode/skills/jupyter-notebook/nb_validate.py examples/airtable/rag_workflow.ipynb`
3. **Full execution**: `JUPYTER_CONFIG_DIR=/tmp/empty_jupyter_config jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=600 examples/airtable/rag_workflow.ipynb --output rag_workflow.ipynb`

The full execution makes real API calls (Airtable, LLM) and needs credentials in `.env`.

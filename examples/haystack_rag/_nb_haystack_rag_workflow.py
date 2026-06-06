"""Generate the Haystack RAG workflow notebook.

Creates examples/haystack_rag/haystack_rag_workflow.ipynb -- a notebook that
downloads file attachments from Airtable, indexes them with HaystackRAG, and
runs workflow steps as RAG queries.

Usage:
    python examples/haystack_rag/_nb_haystack_rag_workflow.py
    jupyter nbconvert --to notebook --execute \
        --ExecutePreprocessor.timeout=300 \
        examples/haystack_rag/haystack_rag_workflow.ipynb \
        --output haystack_rag_workflow.ipynb
"""

from __future__ import annotations

import nbformat as nbf

nb = nbf.v4.new_notebook()
nb.cells = []


def code(s):
    nb.cells.append(nbf.v4.new_code_cell(s))


def md(s):
    nb.cells.append(nbf.v4.new_markdown_cell(s))


md("""\
<style>
:root {
  --jp-content-font-size1: 11px;
  --jp-code-font-size: 10px;
  --jp-ui-font-size1: 10px;
}
body { font-size: 11px; line-height: 1.4; }
h1 { font-size: 20px !important; }
h2 { font-size: 16px !important; margin-top: 1.2em !important; }
h3 { font-size: 13px !important; }
table { font-size: 9px !important; table-layout: auto !important; }
th, td { font-size: 9px !important; padding: 2px 4px !important; }
.dataframe { width: 100%; }
.jp-Cell { page-break-inside: avoid; }
.page-break { page-break-before: always; }
.jp-OutputArea-output img { max-width: 100%; height: auto; }
pre { font-size: 9px !important; line-height: 1.3 !important; }
@page { margin: 0.6in 0.5in; }
</style>

# Haystack RAG Workflow Tutorial -- Document Q&A

This notebook demonstrates how to use **HaystackRAG** (from `ffai_workflow_adapters.rag`)
as a drop-in alternative to FFAI's built-in RAG, combined with the **Airtable adapter**:

1. Download file attachments from an Airtable "Documents" table
2. Extract text using `unstructured` (handles PDF, DOCX, ODT, TXT, Markdown, and more)
3. Index documents into an in-memory vector store with local sentence-transformer embeddings
4. Load workflow steps from an Airtable "Rag Workflow" table
5. Execute each step as a RAG query -- retrieving relevant chunks and generating answers
6. Write results back to the "_results_rag" table

### Key difference from the FFAI RAG notebook

This uses `HaystackRAG` from `ffai_workflow_adapters.rag` instead of `ffai.rag.RAG`.
The interface is identical (`aindex`, `asearch`, `aquery`, `count`) but backed by
Haystack pipelines. This gives you access to multiple vector-store backends,
hybrid retrieval, and optional re-ranking.

### Prerequisites

```bash
pip install "ffai-workflow-adapters[airtable,haystack]" unstructured httpx
```

Required `.env`:
- `AIRTABLE_API_KEY` -- Airtable personal access token
- `AIRTABLE_BASE_ID` -- Your base ID
- `MISTRAL_API_KEY` -- For LLM generation via LiteLLM
""")

code("""\
import os
import re
import sys
import time
import asyncio
import concurrent.futures
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

import httpx  # noqa: E402
from ffai_workflow_adapters import get_config  # noqa: E402
from ffai_workflow_adapters.rag import HaystackRAG  # noqa: E402

DATA_DIR = _project_root / "examples" / "haystack_rag" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


print(f"Project root: {_project_root}")
print(f"Data dir: {DATA_DIR}")
""")

md("""\
---

<div class="page-break"></div>

## Section 1: Connect to Airtable

Load the adapter config and resolve credentials from environment variables.
""")

code("""\
config = get_config()
airtable_cfg = config.adapters.airtable.resolve(None)

api_key = os.environ.get(airtable_cfg.api_key_env, "")
base_id = os.environ.get(airtable_cfg.base_id_env, "")

if not api_key:
    raise ValueError(f"Set {airtable_cfg.api_key_env} in .env")
if not base_id:
    raise ValueError(f"Set {airtable_cfg.base_id_env} in .env")

from pyairtable.api import Api  # noqa: E402
api = Api(api_key)

print(f"Base: {base_id}")
print(f"API key: {api_key[:8]}...")
print(f"Input field map: {airtable_cfg.input_field_map}")
print(f"Output field map: {airtable_cfg.output_field_map}")
""")

md("""\
---

<div class="page-break"></div>

## Section 2: Download Document Attachments

Fetch records from the **"Documents"** table and download each file attachment.
Airtable attachment URLs are temporary, so we download them fresh each time.
Files are cached locally -- re-running skips already-downloaded files.
""")

code("""\
DOCS_TABLE = "Documents"

docs_table = api.table(base_id, DOCS_TABLE)
docs_records = docs_table.all()

print(f"Found {len(docs_records)} document record(s)\\n")

downloaded = []
for rec in docs_records:
    fields = rec["fields"]
    name = fields.get("Name", "unnamed")
    attachments = fields.get("File", [])

    if not attachments:
        print(f"  {name}: no attachments, skipping")
        continue

    for att in attachments:
        filename = att["filename"]
        url = att["url"]
        filepath = DATA_DIR / filename

        if filepath.exists():
            print(f"  {name}: {filename} (cached)")
        else:
            print(f"  {name}: downloading {filename}...")
            resp = httpx.get(url, headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            filepath.write_bytes(resp.content)
            print(f"    saved ({len(resp.content):,} bytes)")

        downloaded.append({"name": name, "filename": filename, "path": filepath})

print(f"\\n{len(downloaded)} file(s) ready for indexing")
""")

md("""\
---

<div class="page-break"></div>

## Section 3: Extract Text from Documents

Use `unstructured` to parse each file into plain text.
Supports PDF, DOCX, ODT, TXT, Markdown, PPTX, HTML, and more.
""")

code("""\
from unstructured.partition.auto import partition

documents = []
for doc in downloaded:
    print(f"Extracting: {doc['filename']}...", end=" ")
    try:
        elements = partition(filename=str(doc["path"]))
        text = "\\n\\n".join(el.text for el in elements if el.text)
        documents.append({
            "name": doc["name"],
            "filename": doc["filename"],
            "text": text,
        })
        print(f"{len(text):,} chars, {len(elements)} elements")
    except Exception as e:
        print(f"ERROR: {e}")

total_chars = sum(len(d["text"]) for d in documents)
print(f"\\nExtracted {total_chars:,} total characters from {len(documents)} document(s)")
""")

md("""\
---

<div class="page-break"></div>

## Section 4: Initialize HaystackRAG Pipeline

Create a `HaystackRAG` instance with:
- **Embeddings**: `all-MiniLM-L6-v2` (local, via sentence-transformers -- no API key needed)
- **Vector store**: In-memory (fast for demos; switch to `"chroma"`, `"qdrant"`, etc. for persistence)
- **Chunker**: Recursive character-based (1000 chars, 200 overlap)

The first run will download the embedding model (~90 MB). Subsequent runs use the cache.

> **Tip**: To persist the index, change `store="chroma"` and set `store_dir="./chroma_db"`.
""")

code("""\
rag = HaystackRAG(
    embed="sentence-transformers/all-MiniLM-L6-v2",
    store="inmemory",
    chunk_size=1000,
    chunk_overlap=200,
)

print("HaystackRAG pipeline initialized")
print("  Embeddings: sentence-transformers/all-MiniLM-L6-v2")
print("  Store:      InMemoryDocumentStore")
print("  Chunker:    recursive (size=1000, overlap=200)")
""")

md("""\
---

<div class="page-break"></div>

## Section 5: Index Documents

Chunk each document's text, compute embeddings, and store in the vector store.
The `source` parameter tags chunks with their filename for filtering and deduplication.
""")

code("""\
total_chunks = 0
for doc in documents:
    chunks = run_sync(rag.aindex(doc["text"], source=doc["filename"]))
    total_chunks += chunks
    print(f"  {doc['name']} ({doc['filename']}): {chunks} chunks")

print(f"\\nTotal: {total_chunks} chunks indexed")
""")

md("""\
---

<div class="page-break"></div>

## Section 6: Verify the Index

Quick sanity check -- count chunks and run a test search to confirm retrieval works.
""")

code("""\
count = rag.count()
print(f"Total chunks in store: {count}")

test_hits = run_sync(rag.asearch("What is this document about?", top_k=3))
print("\\nTest search -- top 3 hits:")
for hit in test_hits:
    print(f"  [{hit.score:.3f}] {hit.source}")
    print(f"    {hit.content[:150]}{'...' if len(hit.content) > 150 else ''}")
""")

md("""\
---

<div class="page-break"></div>

## Section 7: Load Workflow Steps from Airtable

Load the RAG-oriented workflow steps from the **"Rag Workflow"** table using the
Airtable adapter's field mapping (Name -> name, Prompt -> prompt, Model -> client, etc.).
""")

code("""\
from ffai_workflow_adapters import load_workflow_airtable

WORKFLOW_TABLE = "Rag Workflow"
VIEW_NAME = "rag"

spec = load_workflow_airtable(
    base_id,
    WORKFLOW_TABLE,
    view=VIEW_NAME,
    name="haystack_rag_workflow",
)

print(f"Workflow: {spec.name}")
print(f"Steps: {len(spec.prompts)}")
for step in spec.prompts:
    client_info = f" [client: {step.client.name}]" if step.client else ""
    prompt_preview = step.prompt[:80] + ("..." if len(step.prompt) > 80 else "")
    print(f"  - {step.name}{client_info}: {prompt_preview}")
""")

md("""\
---

<div class="page-break"></div>

## Section 8: Execute Workflow with HaystackRAG (Per-Document)

Each workflow step runs **once per document**, using source filtering to restrict
the RAG query to only that document's chunks. This gives document-specific answers
instead of a mashup across all documents.

For each document:

1. **Filter** -- Restrict the vector store search to only that document's chunks
2. **Resolve templates** -- Replace `{{step_name.response}}` references with prior answers
3. **RAG query** -- Retrieve relevant chunks and generate an answer grounded in that document
""")

code("""\
from ffai_workflow_adapters import litellm_generate_fn


def resolve_templates(prompt, results):
    def replacer(match):
        ref = match.group(1)
        parts = ref.split(".")
        if len(parts) == 2 and parts[1] == "response" and parts[0] in results:
            return results[parts[0]]
        return match.group(0)
    return re.sub(r"\\{\\{([\\w\\.]+)\\}\\}", replacer, prompt)


client_config = config.clients
default_client_name = client_config.default_client
default_client_cfg = client_config.get_client_type(default_client_name)
default_model_string = f"{default_client_cfg.provider_prefix}{default_client_cfg.default_model}"
default_api_key = os.environ.get(default_client_cfg.api_key_env, "")

all_results = {}

for doc in documents:
    doc_name = doc["name"]
    doc_source = doc["filename"]
    print(f"{'=' * 60}")
    print(f"DOCUMENT: {doc_name} ({doc_source})")
    print(f"{'=' * 60}")

    step_results = {}

    for step in spec.prompts:
        prompt = resolve_templates(step.prompt, step_results)

        step_client_name = step.client.name if step.client else default_client_name
        step_client_cfg = client_config.get_client_type(step_client_name)

        if step_client_cfg:
            model_string = f"{step_client_cfg.provider_prefix}{step_client_cfg.default_model}"
            step_api_key = os.environ.get(step_client_cfg.api_key_env, "")
        else:
            model_string = default_model_string
            step_api_key = default_api_key

        gen_fn = litellm_generate_fn(model_string, step_api_key)

        print(f"  --- {step.name} [{model_string}] ---")

        result = run_sync(
            rag.aquery(prompt, generate_fn=gen_fn, top_k=5, source=doc_source)
        )

        step_results[step.name] = result.answer
        all_results[(doc_name, step.name)] = result

        print(f"  Answer ({len(result.answer)} chars):")
        preview = result.answer[:300] + ("..." if len(result.answer) > 300 else "")
        for line in preview.split("\\n"):
            print(f"    {line}")
        if result.usage:
            print(f"  Tokens: {result.usage.input_tokens} in + {result.usage.output_tokens} out")
        if result.cost_usd:
            print(f"  Cost: ${result.cost_usd:.6f}")
        print()

print(f"Completed: {len(all_results)} total queries ({len(documents)} docs x {len(spec.prompts)} steps)")
""")

md("""\
---

<div class="page-break"></div>

## Section 9: Review Results

Summary table of all per-document RAG queries.
""")

code("""\
import pandas as pd

rows = []
for doc in documents:
    for step in spec.prompts:
        qr = all_results.get((doc["name"], step.name))
        rows.append({
            "Document": doc["name"],
            "Step": step.name,
            "Model": step.client.name if step.client else default_client_name,
            "Hits": len(qr.hits) if qr else 0,
            "Answer Chars": len(qr.answer) if qr else 0,
            "In Tokens": qr.usage.input_tokens if qr and qr.usage else "",
            "Out Tokens": qr.usage.output_tokens if qr and qr.usage else "",
            "Cost": f"${qr.cost_usd:.6f}" if qr and qr.cost_usd else "",
        })

df = pd.DataFrame(rows)
print(df.to_string(index=False))

total_cost = sum(
    qr.cost_usd for qr in all_results.values() if qr and qr.cost_usd
)
print(f"\\nTotal cost: ${total_cost:.4f}")
""")

md("""\
---

<div class="page-break"></div>

## Section 10: Write Results to Airtable

Build output records using the adapter's field mapping and write to the **"_results_rag"** table.
Each record is tagged with its source document name.
""")

code("""\
RESULTS_TABLE = "_results_rag"
output_field_map = airtable_cfg.output_field_map
passthrough_columns = airtable_cfg.passthrough_columns or []
extra_output_columns = airtable_cfg.extra_output_columns or {}

source_metadata = getattr(spec, "_source_metadata", None) or {}

run_id = time.strftime("%Y%m%d-%H%M%S")
run_date = time.strftime("%Y-%m-%d")

records = []
for doc in documents:
    for step in spec.prompts:
        qr = all_results.get((doc["name"], step.name))
        if not qr:
            continue

        fields = {
            "workflow": f"{spec.name}/{doc['name']}",
            "step": step.name,
            "status": "completed",
            "response": qr.answer,
            "model": step.client.name if step.client else default_client_name,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        if qr.usage:
            fields["input_tokens"] = qr.usage.input_tokens
            fields["output_tokens"] = qr.usage.output_tokens
        if qr.cost_usd is not None:
            fields["cost_usd"] = qr.cost_usd
        if qr.duration_ms is not None:
            fields["duration_ms"] = round(qr.duration_ms, 1)

        step_meta = source_metadata.get(step.name, {})
        for col in passthrough_columns:
            if col in step_meta:
                fields[col] = step_meta[col]

        for key, template in extra_output_columns.items():
            fields[key] = (
                template.replace("{{run_id}}", run_id).replace("{{date}}", run_date)
            )

        if output_field_map:
            fields = {output_field_map.get(k, k): v for k, v in fields.items()}

        records.append(fields)

print(f"Writing {len(records)} record(s) to {RESULTS_TABLE}...")

res_table = api.table(base_id, RESULTS_TABLE)
try:
    created = res_table.batch_create(records)
    print(f"Wrote {len(created)} record(s) to {RESULTS_TABLE}")
except Exception as e:
    print(f"Full write failed ({e})")
    print("Retrying without passthrough columns...")
    fallback = []
    for rec in records:
        slim = {k: v for k, v in rec.items() if k not in passthrough_columns}
        fallback.append(slim)
    created = res_table.batch_create(fallback)
    print(f"Wrote {len(created)} record(s) to {RESULTS_TABLE} (without passthrough)")

for rec in created:
    step_name = rec["fields"].get(output_field_map.get("step", "step"), "?")
    workflow = rec["fields"].get(output_field_map.get("workflow", "workflow"), "?")
    status = rec["fields"].get(output_field_map.get("status", "status"), "?")
    print(f"  {workflow} / {step_name}: {status}")
""")

md("""\
---

## Summary

This notebook demonstrated the HaystackRAG + Airtable integration:

1. **Downloaded** file attachments from the "Documents" table
2. **Extracted** text using `unstructured` (multi-format: Markdown, TXT, DOCX, ODT)
3. **Indexed** documents with local `all-MiniLM-L6-v2` embeddings via HaystackRAG
4. **Loaded** workflow steps from the "Rag Workflow" table via the Airtable adapter
5. **Executed** each step per-document with `rag.aquery(source=...)` -- retrieving
   relevant chunks from that specific document and generating grounded answers
6. **Wrote** results back to the "_results_rag" table with full field mapping

### Switching backends

To switch from in-memory to persistent storage, change the constructor:

```python
# ChromaDB (persistent)
rag = HaystackRAG(store="chroma", collection_name="my_rag", store_dir="./chroma_db", ...)

# Qdrant
rag = HaystackRAG(store="qdrant", collection_name="my_rag", store_dir="./qdrant_db", ...)

# Pinecone (cloud)
rag = HaystackRAG(store="pinecone", collection_name="my_rag", ...)
```

### Enabling hybrid retrieval

```python
rag = HaystackRAG(
    ...,
    hybrid=True,
    join_mode="reciprocal_rank_fusion",
)
```

### Adding re-ranking

```python
rag = HaystackRAG(
    ...,
    reranker="cross-encoder/ms-marco-MiniLM-L-6-v2",
)
```
""")

nb.metadata["kernelspec"] = {
    "display_name": "Python 3",
    "language": "python",
    "name": "python3",
}
nb.metadata["language_info"] = {
    "name": "python",
    "version": "3.14.0",
}

output_path = "examples/haystack_rag/haystack_rag_workflow.ipynb"
with open(output_path, "w") as f:
    nbf.write(nb, f)

print(f"Created {output_path}")

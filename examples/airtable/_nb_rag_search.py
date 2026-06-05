"""Generate the Airtable RAG search notebook.

Creates examples/airtable/rag_search.ipynb — a notebook that downloads all
documents from Airtable, indexes them into ChromaDB with checksum-based
dedup, and runs 3 targeted RAG queries across the full corpus.

Usage:
    python examples/airtable/_nb_rag_search.py
    jupyter nbconvert --to notebook --execute \\
        --ExecutePreprocessor.timeout=600 \\
        examples/airtable/rag_search.ipynb --output rag_search.ipynb
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

# Airtable RAG Search — Checksum Dedup & Multi-Query

This notebook demonstrates **efficient RAG querying** across an Airtable document corpus:

1. **Download** all file attachments (with local caching)
2. **Checksum dedup** — skip re-indexing unchanged documents using SHA256
3. **3 targeted queries** across all indexed documents
4. **Quality review** — evaluate retrieved chunks and generated answers

### Prerequisites

```bash
pip install ffai-workflow-adapters[airtable] chromadb sentence-transformers \\
    "unstructured[md,docx,odt]" httpx litellm pandas
```

Required `.env`: `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `MISTRAL_API_KEY`
""")

code("""\
import os
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

from ffai.rag import RAG  # noqa: E402
from ffai.rag.stores import get_store  # noqa: E402
from ffai_workflow_adapters import (  # noqa: E402
    AttachmentSync, DocumentSync, litellm_generate_fn, get_config,
)

DATA_DIR = _project_root / "examples" / "airtable" / "ffai_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR = DATA_DIR / "chroma"


def run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


print(f"Project root: {_project_root}")
print(f"Data dir: {DATA_DIR}")
print(f"ChromaDB dir: {CHROMA_DIR}")
""")

md("""\
---

<div class="page-break"></div>

## Section 1: Connect to Airtable

Load adapter config and resolve credentials.
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
""")

md("""\
---

<div class="page-break"></div>

## Section 2: Smart Download & Extract

A local `checksums.json` persists Airtable attachment sizes and text checksums
from the previous run. On repeat runs, unchanged documents are detected via a
three-tier check — **no network I/O, no text extraction, no embedding computation**.

| Tier | Check | Cost |
|------|-------|------|
| 1 | Airtable `size` matches stored `airtable_size` | API metadata only |
| 2 | Stored checksum matches ChromaDB `document_checksum` | Local DB query |
| 3 | `rag.aindex(checksum=...)` | Skips if tiers 1+2 pass |

Only documents that fail tier 1 or 2 get downloaded, extracted, and re-indexed.
""")

code("""\
DOCS_TABLE = "Documents"

att_sync = AttachmentSync(DATA_DIR, api_key)

docs_table = api.table(base_id, DOCS_TABLE)
docs_records = docs_table.all()

print(f"Found {len(docs_records)} document record(s)")
print(f"Stored checksums: {len(att_sync.stored)} document(s) from prior run\\n")

unchanged, needs_work = att_sync.classify(docs_records)

print(f"Tier 1 result: {len(unchanged)} potentially unchanged, {len(needs_work)} need processing")
""")

code("""\
from unstructured.partition.auto import partition


def extract_text(filepath):
    elements = partition(filename=filepath)
    return "\\n\\n".join(el.text for el in elements if el.text)


rag = RAG(
    embed="local/all-MiniLM-L6-v2",
    store=get_store("chroma", collection_name="airtable_search", dir=str(CHROMA_DIR)),
    chunker="recursive", chunk_size=1000, chunk_overlap=200,
)

doc_sync = DocumentSync(att_sync, extract_text)
result = doc_sync.process_records(docs_records, rag)

documents = result["documents"]

total_chars = sum(d["text_len"] for d in documents)
full_skip = result["fully_skipped"]
print(f"\\n{len(documents)} document(s), {total_chars:,} total chars")
print(f"Fully skipped (0 I/O): {full_skip}")
print(f"Downloaded + extracted: {result['downloaded']}")
""")

md("""\
---

<div class="page-break"></div>

## Section 3: Index Documents

Each document is indexed with its checksum — if the document hasn't changed since
the last run, indexing is skipped entirely (returns 0 chunks).

Run this notebook a second time to see all documents skipped.
""")

code("""\
print(f"RAG pipeline ready — existing chunks: {rag.count()}")
print()

total_new = 0
total_skipped = 0
for doc in documents:
    if doc["text"] is None:
        print(f"  SKIP (no text needed): {doc['name']} → checksum={doc['checksum'][:12]}...")
        total_skipped += 1
        continue

    chunks = run_sync(
        rag.aindex(doc["text"], source=doc["filename"], checksum=doc["checksum"])
    )
    status = "SKIPPED (unchanged)" if chunks == 0 else "INDEXED"
    if chunks == 0:
        total_skipped += 1
    else:
        total_new += 1
    print(f"  {status}: {doc['name']} ({doc['filename'][:50]}) → {chunks} chunks")

print(f"\\nResult: {total_new} indexed, {total_skipped} skipped (unchanged)")
print(f"Total chunks in store: {rag.count()}")
""")

md("""\
---

<div class="page-break"></div>

## Section 4: Define Queries & Generate Function

Three queries targeting different aspects of the document corpus:

1. **Architecture** — AI system design patterns across the corpus
2. **People** — Professional qualifications, roles, and performance
3. **Adapters** — How the workflow adapters load and execute LLM workflows
""")

code("""\
QUERIES = [
    {
        "name": "architecture",
        "question": (
            "What are the key architectural patterns and design principles "
            "for AI systems described in these documents? Include specific "
            "mechanisms, frameworks, and structural approaches."
        ),
    },
    {
        "name": "people",
        "question": (
            "What people, professional roles, qualifications, and skills "
            "are mentioned across these documents? Include any performance "
            "evaluations, career history, or personal characteristics."
        ),
    },
    {
        "name": "adapters",
        "question": (
            "How do the workflow adapters load, validate, and execute LLM "
            "workflows from tabular data sources? Include details about field "
            "mapping, passthrough columns, and output handling."
        ),
    },
]


client_cfg = config.clients.get_client_type(config.clients.default_client)
model_string = f"{client_cfg.provider_prefix}{client_cfg.default_model}"
llm_api_key = os.environ.get(client_cfg.api_key_env, "")

print(f"Model: {model_string}")
print(f"Queries: {[q['name'] for q in QUERIES]}")
""")

md("""\
---

<div class="page-break"></div>

## Section 5: Execute RAG Queries

Run each query against the full indexed corpus. For each query we show:
- The top retrieved chunks (search hits)
- The generated answer (RAG-augmented)
- Token usage and cost
""")

code("""\
gen_fn = litellm_generate_fn(model_string, llm_api_key, temperature=0.3, max_tokens=2000)

results = {}
for q in QUERIES:
    print(f"{'=' * 60}")
    print(f"QUERY: {q['name']}")
    print(f"{'=' * 60}")
    print(f"Q: {q['question']}")
    print()

    hits = run_sync(rag.asearch(q["question"], top_k=8))
    print(f"Retrieved {len(hits)} chunks:")
    for h in hits:
        print(f"  [{h.score:.3f}] {h.source}: {h.content[:100]}{'...' if len(h.content) > 100 else ''}")
    print()

    result = run_sync(
        rag.aquery(q["question"], generate_fn=gen_fn, top_k=8)
    )
    results[q["name"]] = result

    print(f"ANSWER ({len(result.answer)} chars):")
    print(result.answer)
    print()
    print(f"Sources: {result.sources}")
    if result.usage:
        print(f"Tokens: {result.usage.input_tokens} in + {result.usage.output_tokens} out")
    if result.cost_usd:
        print(f"Cost: ${result.cost_usd:.6f}")
    if result.duration_ms:
        print(f"Duration: {result.duration_ms:.0f}ms")
    print()
""")

md("""\
---

<div class="page-break"></div>

## Section 6: Quality Review

Summary of all queries with retrieval and generation metrics.
""")

code("""\
import pandas as pd

rows = []
for q in QUERIES:
    r = results[q["name"]]
    rows.append({
        "Query": q["name"],
        "Hits": len(r.hits),
        "Sources": len(r.sources),
        "Answer Chars": len(r.answer),
        "In Tokens": r.usage.input_tokens if r.usage else "",
        "Out Tokens": r.usage.output_tokens if r.usage else "",
        "Cost": f"${r.cost_usd:.6f}" if r.cost_usd else "",
        "Duration": f"{r.duration_ms:.0f}ms" if r.duration_ms else "",
    })

df = pd.DataFrame(rows)
print(df.to_string(index=False))

total_cost = sum(r.cost_usd for r in results.values() if r.cost_usd)
print(f"\\nTotal cost: ${total_cost:.4f}")
""")

md("""\
---

<div class="page-break"></div>

## Section 7: Source Coverage

Which documents contributed to each query? This shows whether the retriever
is finding the right documents or missing relevant ones.
""")

code("""\
rows = []
all_sources = sorted(set(d["filename"] for d in documents))
for q in QUERIES:
    r = results[q["name"]]
    hit_sources = set(r.sources)
    for src in all_sources:
        short = src[:50]
        rows.append({
            "Query": q["name"],
            "Source": short,
            "Retrieved": "Y" if src in hit_sources else "-",
        })

df_cov = pd.DataFrame(rows)
print(df_cov.to_string(index=False))
print()
print(f"Documents indexed: {len(documents)}")
print(f"Documents contributing to at least one query: {len(set(s for r in results.values() for s in r.sources))}")
""")

md("""\
---

## Summary

This notebook demonstrated:

1. **Checksum dedup** — Documents are fingerprinted with SHA256. On repeat runs,
   unchanged documents are skipped entirely (`aindex` returns 0 chunks).
2. **3 targeted RAG queries** across the full corpus, each retrieving relevant
   chunks from different document clusters.
3. **Quality metrics** — token usage, cost, duration, source coverage, and
   retrieval scores for evaluating answer quality.

Re-run this notebook to see the indexing phase skip all documents (checksums match).
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

output_path = "examples/airtable/rag_search.ipynb"
with open(output_path, "w") as f:
    nbf.write(nb, f)

print(f"Created {output_path}")

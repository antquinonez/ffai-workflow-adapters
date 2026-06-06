"""Haystack-backed RAG — a drop-in alternative to ``ffai.rag.RAG``.

This subpackage provides ``HaystackRAG``, which offers the same
``aindex`` / ``asearch`` / ``aquery`` / ``count`` interface as
``ffai.rag.RAG`` but is powered by Haystack pipelines.  It adds support
for hybrid retrieval, re-ranking, and multiple vector-store backends.

Install the optional dependency with::

    pip install ffai-workflow-adapters[haystack]

Quick start::

    from ffai_workflow_adapters.rag import HaystackRAG

    rag = HaystackRAG(
        embed="sentence-transformers/all-MiniLM-L6-v2",
        store="chroma",
        collection_name="my_rag",
        store_dir="./chroma_db",
    )

    # Same interface as ffai.rag.RAG
    await rag.aindex(text, source="doc.txt")
    hits = await rag.asearch("What is X?", top_k=5)
    result = await rag.aquery("What is X?", generate_fn=my_fn, top_k=5)
    total = rag.count()
"""
from __future__ import annotations

from ._rag import HaystackRAG
from ._store import StoreAdapter
from ._types import GenerationResult, QueryResult, SearchHit

__all__ = [
    "HaystackRAG",
    "StoreAdapter",
    "SearchHit",
    "QueryResult",
    "GenerationResult",
]

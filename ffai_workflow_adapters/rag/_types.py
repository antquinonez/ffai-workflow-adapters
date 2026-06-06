"""Data types compatible with ffai.rag.types for Haystack-backed RAG.

These dataclasses mirror the ffai RAG result types so that code written
against ``ffai.rag.RAG`` works with ``HaystackRAG`` without changes.
They are standalone -- no ffai import required.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchHit:
    """A single retrieved chunk matching a query."""

    content: str
    score: float
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_content: str | None = None
    id: str = ""


@dataclass
class GenerationResult:
    """Result from an LLM generation call."""

    text: str
    usage: Any | None = None
    cost_usd: float = 0.0
    duration_ms: float | None = None


@dataclass
class QueryResult:
    """Result from a RAG query (retrieve + generate)."""

    answer: str
    hits: list[SearchHit] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    prompt: str = ""
    usage: Any | None = None
    cost_usd: float = 0.0
    duration_ms: float | None = None

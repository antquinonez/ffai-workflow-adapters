"""Tests for ffai_workflow_adapters.rag subpackage.

Tests use mocked Haystack components so that ``haystack-ai`` does not need
to be installed for the test suite to run.  This follows the project pattern
of mocking optional dependencies at the boundary.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ffai_workflow_adapters.rag._types import GenerationResult, QueryResult, SearchHit


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# _types.py
# ---------------------------------------------------------------------------


class TestSearchHit:
    def test_defaults(self) -> None:
        hit = SearchHit(content="hello", score=0.9)
        assert hit.content == "hello"
        assert hit.score == 0.9
        assert hit.source == ""
        assert hit.metadata == {}
        assert hit.parent_content is None
        assert hit.id == ""

    def test_full_construction(self) -> None:
        hit = SearchHit(
            content="chunk text",
            score=0.75,
            source="doc.pdf",
            metadata={"page": 1},
            parent_content="full doc",
            id="abc123",
        )
        assert hit.source == "doc.pdf"
        assert hit.metadata["page"] == 1


class TestGenerationResult:
    def test_defaults(self) -> None:
        r = GenerationResult(text="answer")
        assert r.text == "answer"
        assert r.usage is None
        assert r.cost_usd == 0.0
        assert r.duration_ms is None

    def test_with_usage(self) -> None:
        usage = SimpleNamespace(input_tokens=10, output_tokens=20)
        r = GenerationResult(
            text="response", usage=usage, cost_usd=0.003, duration_ms=150.0,
        )
        assert r.usage.input_tokens == 10
        assert r.cost_usd == 0.003


class TestQueryResult:
    def test_defaults(self) -> None:
        qr = QueryResult(answer="yes")
        assert qr.answer == "yes"
        assert qr.hits == []
        assert qr.sources == []
        assert qr.prompt == ""
        assert qr.usage is None
        assert qr.cost_usd == 0.0
        assert qr.duration_ms is None

    def test_with_hits_and_usage(self) -> None:
        hits = [SearchHit(content="x", score=0.5, source="a.txt")]
        usage = SimpleNamespace(input_tokens=5, output_tokens=15)
        qr = QueryResult(
            answer="no",
            hits=hits,
            sources=["a.txt"],
            usage=usage,
            cost_usd=0.001,
            duration_ms=200.0,
        )
        assert len(qr.hits) == 1
        assert qr.hits[0].source == "a.txt"
        assert qr.sources == ["a.txt"]


# ---------------------------------------------------------------------------
# _store.py — StoreAdapter
# ---------------------------------------------------------------------------


class TestStoreAdapter:
    def test_needs_reindex_first_time(self) -> None:
        mock_store = MagicMock()
        adapter = _make_store_adapter(mock_store)
        assert adapter.needs_reindex("file.txt", "abc123") is True

    def test_needs_reindex_after_recording(self) -> None:
        mock_store = MagicMock()
        adapter = _make_store_adapter(mock_store)
        adapter.record_checksum("file.txt", "abc123")
        assert adapter.needs_reindex("file.txt", "abc123") is False

    def test_needs_reindex_changed_checksum(self) -> None:
        mock_store = MagicMock()
        adapter = _make_store_adapter(mock_store)
        adapter.record_checksum("file.txt", "abc123")
        assert adapter.needs_reindex("file.txt", "def456") is True

    def test_needs_reindex_strategy_scoped(self) -> None:
        mock_store = MagicMock()
        adapter = _make_store_adapter(mock_store)
        adapter.record_checksum("file.txt", "abc", strategy="recursive")
        assert adapter.needs_reindex("file.txt", "abc", strategy="recursive") is False
        assert adapter.needs_reindex("file.txt", "abc", strategy="sentence") is True

    def test_count_delegates(self) -> None:
        mock_store = MagicMock()
        mock_store.count_documents.return_value = 42
        adapter = _make_store_adapter(mock_store)
        assert adapter.count() == 42

    def test_delete_by_source(self) -> None:
        mock_store = MagicMock()
        doc = MagicMock()
        doc.id = "doc1"
        doc.meta = {"source": "old.txt"}
        mock_store.filter_documents.return_value = [doc]
        adapter = _make_store_adapter(mock_store)
        adapter.record_checksum("old.txt", "abc")
        adapter.delete_by_source("old.txt")
        mock_store.delete_documents.assert_called_once_with(["doc1"])
        assert adapter.needs_reindex("old.txt", "abc") is True

    def test_persist_checksums(self, tmp_path: Path) -> None:
        mock_store = MagicMock()
        adapter = _make_store_adapter(mock_store, persist_dir=tmp_path)
        adapter.record_checksum("a.txt", "h1")
        adapter.record_checksum("b.txt", "h2")

        adapter2 = _make_store_adapter(MagicMock(), persist_dir=tmp_path)
        assert adapter2.needs_reindex("a.txt", "h1") is False
        assert adapter2.needs_reindex("b.txt", "h2") is False
        assert adapter2.needs_reindex("a.txt", "changed") is True

    def test_name_reflects_store_type(self) -> None:
        class FakeChromaStore:
            pass

        adapter = _make_store_adapter(FakeChromaStore())
        assert adapter.name == "FakeChromaStore"


def _make_store_adapter(
    store: MagicMock,
    persist_dir: Path | None = None,
) -> Any:
    from ffai_workflow_adapters.rag._store import StoreAdapter

    return StoreAdapter(
        document_store=store,
        persist_dir=persist_dir,
    )


# ---------------------------------------------------------------------------
# _rag.py — HaystackRAG (with mocked Haystack internals)
# ---------------------------------------------------------------------------


class TestHaystackRAG:
    """Test HaystackRAG with Haystack components mocked at the boundary."""

    @pytest.fixture(autouse=True)
    def _patch_haystack(self) -> None:
        """Mock all Haystack imports so tests run without haystack-ai."""
        mock_doc_store = MagicMock()
        mock_doc_store.count_documents.return_value = 0
        mock_doc_store.filter_documents.return_value = []
        mock_doc_store.write_documents.return_value = 0

        mock_text_embedder = MagicMock()
        mock_text_embedder.run.return_value = {
            "embedding": [0.1, 0.2, 0.3],
        }

        mock_doc_embedder = MagicMock()
        mock_doc_embedder.run.side_effect = lambda docs: {"documents": docs}

        self._mock_doc_store = mock_doc_store
        self._mock_text_emb = mock_text_embedder
        self._mock_doc_emb = mock_doc_embedder

        mock_haystack = MagicMock()

        def fake_document(content: str = "", meta: dict | None = None, id: str = "") -> Any:
            d = MagicMock()
            d.content = content
            d.meta = meta or {}
            d.id = id
            return d

        mock_haystack.Document = fake_document

        patches = [
            patch("ffai_workflow_adapters.rag._rag._require_haystack"),
            patch(
                "ffai_workflow_adapters.rag._rag._build_document_store",
                return_value=mock_doc_store,
            ),
            patch(
                "ffai_workflow_adapters.rag._rag._build_embedders",
                return_value=(mock_text_embedder, mock_doc_embedder),
            ),
            patch.dict("sys.modules", {"haystack": mock_haystack}),
        ]
        for p in patches:
            p.start()
        self._patches = patches

        from ffai_workflow_adapters.rag._rag import HaystackRAG

        self._rag = HaystackRAG(store="inmemory", store_dir=None)
        yield
        for p in self._patches:
            p.stop()

    def test_count_empty(self) -> None:
        assert self._rag.count() == 0

    def test_aindex_basic(self) -> None:
        n = _run(self._rag.aindex("Hello world document text", source="test.txt"))
        assert n > 0
        self._mock_doc_emb.run.assert_called_once()
        self._mock_doc_store.write_documents.assert_called_once()

    def test_aindex_empty_text(self) -> None:
        n = _run(self._rag.aindex("", source="empty.txt"))
        assert n == 0

    def test_aindex_dedup_by_checksum(self) -> None:
        _run(self._rag.aindex("text content", source="doc.txt", checksum="abc"))
        self._mock_doc_store.write_documents.reset_mock()
        n = _run(self._rag.aindex("text content", source="doc.txt", checksum="abc"))
        assert n == 0
        self._mock_doc_store.write_documents.assert_not_called()

    def test_aindex_changed_checksum_reindexes(self) -> None:
        _run(self._rag.aindex("text content", source="doc.txt", checksum="abc"))
        self._mock_doc_store.write_documents.reset_mock()
        n = _run(self._rag.aindex("new content", source="doc.txt", checksum="def"))
        assert n > 0
        self._mock_doc_store.write_documents.assert_called_once()

    def test_asearch_returns_search_hits(self) -> None:
        mock_doc = MagicMock()
        mock_doc.content = "relevant chunk"
        mock_doc.score = 0.92
        mock_doc.meta = {"source": "doc.txt"}
        mock_doc.id = "chunk1"

        self._mock_doc_store.__class__ = type("InMemoryDocumentStore", (), {})

        with patch.object(
            self._rag, "_retrieve", return_value=[mock_doc],
        ):
            hits = _run(self._rag.asearch("test query", top_k=5))

        assert len(hits) == 1
        assert hits[0].content == "relevant chunk"
        assert hits[0].score == 0.92
        assert hits[0].source == "doc.txt"

    def test_asearch_with_source_filter(self) -> None:
        mock_doc = MagicMock()
        mock_doc.content = "filtered"
        mock_doc.score = 0.8
        mock_doc.meta = {"source": "target.txt"}
        mock_doc.id = "c1"

        self._mock_doc_store.__class__ = type("InMemoryDocumentStore", (), {})

        with patch.object(
            self._rag, "_retrieve", return_value=[mock_doc],
        ) as mock_retrieve:
            hits = _run(self._rag.asearch("query", top_k=3, source="target.txt"))

        mock_retrieve.assert_called_once_with(
            "query", top_k=3, filters={"source": "target.txt"},
        )
        assert hits[0].source == "target.txt"

    def test_aquery_with_string_generate_fn(self) -> None:
        mock_doc = MagicMock()
        mock_doc.content = "context chunk"
        mock_doc.score = 0.7
        mock_doc.meta = {"source": "s.txt"}
        mock_doc.id = "c1"

        with patch.object(
            self._rag, "asearch",
            return_value=[SearchHit(content="context chunk", score=0.7, source="s.txt")],
        ):
            result = _run(
                self._rag.aquery(
                    "What is X?",
                    generate_fn=lambda prompt: "X is Y",
                    top_k=3,
                )
            )

        assert result.answer == "X is Y"
        assert len(result.hits) == 1
        assert result.sources == ["s.txt"]
        assert result.cost_usd == 0.0
        assert result.usage is None

    def test_aquery_with_generation_result(self) -> None:
        usage = SimpleNamespace(input_tokens=50, output_tokens=25)

        with patch.object(
            self._rag, "asearch",
            return_value=[SearchHit(content="ctx", score=0.8, source="f.txt")],
        ):
            result = _run(
                self._rag.aquery(
                    "question",
                    generate_fn=lambda p: GenerationResult(
                        text="the answer",
                        usage=usage,
                        cost_usd=0.002,
                        duration_ms=120.0,
                    ),
                    top_k=5,
                )
            )

        assert result.answer == "the answer"
        assert result.usage.input_tokens == 50
        assert result.cost_usd == 0.002
        assert result.duration_ms == 120.0

    def test_aquery_without_generate_fn(self) -> None:
        with patch.object(
            self._rag, "asearch",
            return_value=[SearchHit(content="c", score=0.5, source="d.txt")],
        ):
            result = _run(self._rag.aquery("question", top_k=3))

        assert result.answer == ""
        assert len(result.hits) == 1
        assert result.prompt != ""

    def test_aquery_custom_template(self) -> None:
        template = "Context: {context}\nQ: {question}\nA:"

        with patch.object(
            self._rag, "asearch",
            return_value=[SearchHit(content="data", score=0.9, source="s.txt")],
        ):
            result = _run(
                self._rag.aquery(
                    "hello",
                    generate_fn=lambda p: p,
                    prompt_template=template,
                    top_k=1,
                )
            )

        assert result.answer.startswith("Context:")
        assert "hello" in result.answer

    def test_store_property_is_adapter(self) -> None:
        from ffai_workflow_adapters.rag._store import StoreAdapter

        assert isinstance(self._rag._store, StoreAdapter)
        assert self._rag._store.needs_reindex("x", "y") is True

    def test_build_filters_none_when_empty(self) -> None:
        from ffai_workflow_adapters.rag._rag import HaystackRAG

        assert HaystackRAG._build_filters({}) is None

    def test_build_filters_single(self) -> None:
        from ffai_workflow_adapters.rag._rag import HaystackRAG

        result = HaystackRAG._build_filters({"source": "f.txt"})
        assert result == {
            "field": "meta.source",
            "operator": "==",
            "value": "f.txt",
        }

    def test_build_filters_multiple(self) -> None:
        from ffai_workflow_adapters.rag._rag import HaystackRAG

        result = HaystackRAG._build_filters({"source": "a.txt", "category": "news"})
        assert result["operator"] == "AND"
        assert len(result["conditions"]) == 2


# ---------------------------------------------------------------------------
# _rag.py — chunking helper
# ---------------------------------------------------------------------------


class TestChunking:
    def test_short_text_returns_single_chunk(self) -> None:
        from ffai_workflow_adapters.rag._rag import _chunk_text

        chunks = _chunk_text("short", chunk_size=100, chunk_overlap=20)
        assert chunks == ["short"]

    def test_long_text_splits(self) -> None:
        from ffai_workflow_adapters.rag._rag import _chunk_text

        text = "A" * 150
        chunks = _chunk_text(text, chunk_size=100, chunk_overlap=20)
        assert len(chunks) == 2
        assert len(chunks[0]) == 100

    def test_empty_text_returns_empty(self) -> None:
        from ffai_workflow_adapters.rag._rag import _chunk_text

        assert _chunk_text("", chunk_size=100, chunk_overlap=20) == []

    def test_whitespace_only_returns_empty(self) -> None:
        from ffai_workflow_adapters.rag._rag import _chunk_text

        assert _chunk_text("   \n\t  ", chunk_size=100, chunk_overlap=20) == []


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------


class TestImportGuard:
    def test_missing_haystack_raises(self) -> None:
        with patch.dict("sys.modules", {"haystack": None}):
            from ffai_workflow_adapters.rag._rag import _require_haystack

            with pytest.raises(ImportError, match="haystack-ai is required"):
                _require_haystack()

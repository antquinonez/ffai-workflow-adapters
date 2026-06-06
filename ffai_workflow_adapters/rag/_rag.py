"""Haystack-backed RAG with an interface compatible with ffai.rag.RAG.

Provides ``HaystackRAG`` — a drop-in alternative to ``ffai.rag.RAG`` powered
by Haystack pipelines.  Supports hybrid retrieval, optional re-ranking, and
multiple vector-store backends.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Callable

from ._store import StoreAdapter
from ._types import GenerationResult, QueryResult, SearchHit

logger = logging.getLogger(__name__)


def _require_haystack() -> Any:
    try:
        import haystack  # type: ignore[import-untyped]  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "haystack-ai is required for HaystackRAG. "
            "Install it with: pip install ffai-workflow-adapters[haystack]"
        ) from exc
    return haystack


def _build_document_store(
    backend: str,
    collection_name: str,
    store_dir: str | None,
    **kwargs: Any,
) -> Any:
    """Create a Haystack ``DocumentStore`` by backend name."""
    if backend == "inmemory":
        from haystack.document_stores.in_memory import InMemoryDocumentStore  # type: ignore[import-untyped]

        return InMemoryDocumentStore()

    if backend == "chroma":
        from haystack_integrations.document_stores.chroma import ChromaDocumentStore  # type: ignore[import-untyped]

        return ChromaDocumentStore(
            collection_name=collection_name,
            persist_path=store_dir or "./chroma_db",
        )

    if backend == "qdrant":
        from haystack_integrations.document_stores.qdrant import QdrantDocumentStore  # type: ignore[import-untyped]

        return QdrantDocumentStore(
            index=collection_name,
            path=store_dir or "./qdrant_db",
            **kwargs,
        )

    if backend == "pinecone":
        from haystack_integrations.document_stores.pinecone import PineconeDocumentStore  # type: ignore[import-untyped]

        return PineconeDocumentStore(
            index=collection_name,
            **kwargs,
        )

    if backend == "weaviate":
        from haystack_integrations.document_stores.weaviate import WeaviateDocumentStore  # type: ignore[import-untyped]

        return WeaviateDocumentStore(
            collection=collection_name,
            **kwargs,
        )

    raise ValueError(
        f"Unknown store backend '{backend}'. "
        f"Supported: inmemory, chroma, qdrant, pinecone, weaviate"
    )


def _build_embedders(embed_model: str, device: str | None = None) -> tuple[Any, Any]:
    """Build (text_embedder, document_embedder) pair for the given model."""
    from haystack.components.embedders import (  # type: ignore[import-untyped]
        SentenceTransformersDocumentEmbedder,
        SentenceTransformersTextEmbedder,
    )

    init_kwargs: dict[str, Any] = {}
    if device:
        from haystack.components.embedders import ComponentDevice  # type: ignore[import-untyped]

        init_kwargs["device"] = ComponentDevice.from_str(device)

    text_emb = SentenceTransformersTextEmbedder(model=embed_model, **init_kwargs)
    doc_emb = SentenceTransformersDocumentEmbedder(model=embed_model, **init_kwargs)
    text_emb.warm_up()
    doc_emb.warm_up()
    return text_emb, doc_emb


def _chunk_text(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Simple recursive character-based chunking."""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - chunk_overlap
    return chunks


class HaystackRAG:
    """Haystack-backed RAG with an interface compatible with ``ffai.rag.RAG``.

    Provides the same ``aindex``, ``asearch``, ``aquery``, and ``count``
    methods as ``ffai.rag.RAG`` but uses Haystack pipelines internally.
    Enhancements over the ffai built-in RAG include:

    - Multiple vector-store backends (ChromaDB, Qdrant, Pinecone, Weaviate,
      or in-memory).
    - Hybrid retrieval (BM25 + vector) via ``hybrid=True``.
    - Optional re-ranking with cross-encoder models.

    Args:
        embed: Sentence-transformers model name for embeddings.
        store: Vector-store backend name (``"inmemory"`` | ``"chroma"``
            | ``"qdrant"`` | ``"pinecone"`` | ``"weaviate"``).
        collection_name: Collection / index name inside the store.
        store_dir: Directory for persistent stores.  ``None`` uses defaults.
        chunk_size: Maximum characters per chunk.
        chunk_overlap: Overlap characters between adjacent chunks.
        hybrid: Enable BM25 + vector hybrid retrieval.
        reranker: Reranker model name (e.g.
            ``"cross-encoder/ms-marco-MiniLM-L-6-v2"``).  ``None`` disables
            re-ranking.
        join_mode: How to merge hybrid results (``"concatenate"``,
            ``"merge"``, ``"reciprocal_rank_fusion"``).
        embed_device: Device for the embedding model (``"cpu"``, ``"cuda"``).
        store_kwargs: Extra keyword arguments forwarded to the document store
            constructor.
    """

    def __init__(
        self,
        embed: str = "sentence-transformers/all-MiniLM-L6-v2",
        store: str = "chroma",
        collection_name: str = "haystack_rag",
        store_dir: str | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        hybrid: bool = False,
        reranker: str | None = None,
        join_mode: str = "reciprocal_rank_fusion",
        embed_device: str | None = None,
        store_kwargs: dict[str, Any] | None = None,
    ) -> None:
        _require_haystack()

        self._embed_model = embed
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._hybrid = hybrid
        self._reranker_model = reranker
        self._join_mode = join_mode

        self._document_store = _build_document_store(
            backend=store,
            collection_name=collection_name,
            store_dir=store_dir,
            **(store_kwargs or {}),
        )

        self._store_adapter = StoreAdapter(
            document_store=self._document_store,
            persist_dir=store_dir,
        )

        self._text_embedder, self._doc_embedder = _build_embedders(
            embed, embed_device,
        )

        if hybrid and store != "inmemory":
            logger.warning(
                "Hybrid BM25 retrieval works best with 'inmemory' or "
                "backends that support full-text search (Elasticsearch, "
                "Weaviate).  Store '%s' may not support BM25.", store,
            )

    @property
    def _store(self) -> StoreAdapter:
        """Compatibility shim for ``DocumentSync`` which accesses ``rag._store``."""
        return self._store_adapter

    def count(self) -> int:
        """Return the total number of documents in the store."""
        return self._store_adapter.count()

    async def aindex(
        self,
        text: str,
        source: str | None = None,
        checksum: str | None = None,
        **metadata: str,
    ) -> int:
        """Index *text* into the document store.

        Text is split into chunks of ``chunk_size`` characters, embedded,
        and written to the document store.  Each chunk carries ``source``
        and any extra ``metadata`` as Haystack ``Document.meta``.

        If *checksum* and *source* are both provided and the checksum
        matches what was previously recorded for that source, indexing is
        skipped (returns 0).

        Args:
            text: The document text to index.
            source: Source identifier stored as metadata on each chunk.
            checksum: Hash of the document content for dedup.
            **metadata: Additional string metadata attached to each chunk.

        Returns:
            Number of chunks created (0 if skipped).
        """
        if not text or not text.strip():
            return 0

        if source and checksum:
            if not self._store_adapter.needs_reindex(source, checksum):
                logger.debug("Skipping re-index for unchanged source: %s", source)
                return 0

        chunks = _chunk_text(text, self._chunk_size, self._chunk_overlap)
        if not chunks:
            return 0

        meta: dict[str, Any] = {**metadata}
        if source:
            meta["source"] = source
        if checksum:
            meta["checksum"] = checksum

        from haystack import Document  # type: ignore[import-untyped]

        documents: list[Document] = []
        for i, chunk in enumerate(chunks):
            doc_id = hashlib.sha256(
                f"{source or 'doc'}:{i}:{chunk}".encode()
            ).hexdigest()[:16]
            documents.append(
                Document(content=chunk, meta={**meta, "chunk_index": i}, id=doc_id)
            )

        embedded = await asyncio.to_thread(
            self._doc_embedder.run, documents,
        )
        embedded_docs = embedded["documents"]

        await asyncio.to_thread(
            self._document_store.write_documents, embedded_docs,
        )

        if source and checksum:
            self._store_adapter.record_checksum(source, checksum)

        logger.debug(
            "Indexed %d chunks for source '%s'", len(embedded_docs), source,
        )
        return len(embedded_docs)

    async def asearch(
        self,
        query: str,
        top_k: int = 5,
        **filters: str,
    ) -> list[SearchHit]:
        """Search the document store and return ranked ``SearchHit`` objects.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.
            **filters: Metadata filters passed to the retriever.  Use
                ``source="filename"`` to restrict to a single source.

        Returns:
            List of ``SearchHit`` objects sorted by relevance.
        """
        results = await self._retrieve(query, top_k=top_k, filters=filters)
        return [
            SearchHit(
                content=doc.content or "",
                score=doc.score or 0.0,
                source=doc.meta.get("source", ""),
                metadata={
                    k: v for k, v in doc.meta.items()
                    if k not in ("source", "chunk_index")
                },
                id=doc.id,
            )
            for doc in results
        ]

    async def aquery(
        self,
        question: str,
        generate_fn: Callable[[str], str | GenerationResult] | None = None,
        top_k: int = 5,
        prompt_template: str | None = None,
        **filters: str,
    ) -> QueryResult:
        """Retrieve relevant documents and generate an answer.

        Performs retrieval, builds a RAG prompt from the retrieved context,
        calls *generate_fn* to produce an answer, and returns a
        ``QueryResult``.

        If *generate_fn* returns a ``GenerationResult``, usage/cost/duration
        are captured.  If it returns a plain string, those fields default to
        ``None`` / ``0.0``.

        Args:
            question: The question to answer.
            generate_fn: A callable ``(prompt: str) -> str | GenerationResult``.
            top_k: Number of documents to retrieve.
            prompt_template: Optional Jinja-style template with
                ``{{documents}}`` and ``{{question}}`` placeholders.
            **filters: Metadata filters (e.g. ``source="file.pdf"``).

        Returns:
            A ``QueryResult`` with the answer, hits, and usage metadata.
        """
        hits = await self.asearch(question, top_k=top_k, **filters)

        if prompt_template is None:
            prompt_template = (
                "Given the following documents, answer the question.\n\n"
                "Documents:\n"
                "{context}\n\n"
                "Question: {question}\n\n"
                "Answer:"
            )

        context_parts = []
        for hit in hits:
            label = f"[{hit.source}]" if hit.source else ""
            context_parts.append(f"{label} {hit.content}")
        context = "\n\n".join(context_parts)

        prompt = prompt_template.format(context=context, question=question)

        if generate_fn is None:
            return QueryResult(
                answer="",
                hits=hits,
                sources=list({h.source for h in hits if h.source}),
                prompt=prompt,
            )

        gen_result = await asyncio.to_thread(generate_fn, prompt)

        if isinstance(gen_result, GenerationResult):
            return QueryResult(
                answer=gen_result.text,
                hits=hits,
                sources=list({h.source for h in hits if h.source}),
                prompt=prompt,
                usage=gen_result.usage,
                cost_usd=gen_result.cost_usd,
                duration_ms=gen_result.duration_ms,
            )

        return QueryResult(
            answer=str(gen_result),
            hits=hits,
            sources=list({h.source for h in hits if h.source}),
            prompt=prompt,
        )

    async def _retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[Any]:
        """Core retrieval logic shared by ``asearch`` and ``aquery``."""
        filter_dict = self._build_filters(filters or {})

        embedding_result = await asyncio.to_thread(
            self._text_embedder.run, query,
        )
        query_embedding = embedding_result["embedding"]

        if self._hybrid:
            return await self._hybrid_retrieve(
                query, query_embedding, top_k, filter_dict,
            )

        return await self._embedding_retrieve(
            query_embedding, top_k, filter_dict,
        )

    async def _embedding_retrieve(
        self,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, Any] | None,
    ) -> list[Any]:
        """Single-mode embedding retrieval."""
        from haystack.document_stores.in_memory import InMemoryDocumentStore  # type: ignore[import-untyped]

        if isinstance(self._document_store, InMemoryDocumentStore):
            from haystack.components.retrievers.in_memory import (  # type: ignore[import-untyped]
                InMemoryEmbeddingRetriever,
            )

            retriever = InMemoryEmbeddingRetriever(
                document_store=self._document_store,
                top_k=top_k,
                filters=filters,
            )
        else:
            retriever = self._build_embedding_retriever(top_k, filters)

        result = await asyncio.to_thread(
            retriever.run, query_embedding=query_embedding,
        )
        docs = result["documents"]

        if self._reranker_model:
            docs = await self._rerank("", docs, top_k)

        return docs

    async def _hybrid_retrieve(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int,
        filters: dict[str, Any] | None,
    ) -> list[Any]:
        """Hybrid BM25 + embedding retrieval with join."""
        from haystack.components.joiners import DocumentJoiner  # type: ignore[import-untyped]
        from haystack.components.retrievers.in_memory import (  # type: ignore[import-untyped]
            InMemoryBM25Retriever,
            InMemoryEmbeddingRetriever,
        )
        from haystack.document_stores.in_memory import InMemoryDocumentStore  # type: ignore[import-untyped]

        if not isinstance(self._document_store, InMemoryDocumentStore):
            logger.warning(
                "Hybrid retrieval falling back to embedding-only; "
                "BM25 requires InMemoryDocumentStore"
            )
            return await self._embedding_retrieve(
                query_embedding, top_k, filters,
            )

        bm25 = InMemoryBM25Retriever(
            document_store=self._document_store,
            top_k=top_k,
            filters=filters,
        )
        emb = InMemoryEmbeddingRetriever(
            document_store=self._document_store,
            top_k=top_k,
            filters=filters,
        )
        joiner = DocumentJoiner(join_mode=self._join_mode)

        bm25_result = await asyncio.to_thread(bm25.run, query=query)
        emb_result = await asyncio.to_thread(
            emb.run, query_embedding=query_embedding,
        )

        joined = joiner.run(
            documents=[
                bm25_result["documents"],
                emb_result["documents"],
            ],
        )

        docs = joined["documents"][:top_k]

        if self._reranker_model:
            docs = await self._rerank(query, docs, top_k)

        return docs

    async def _rerank(
        self,
        query: str,
        documents: list[Any],
        top_k: int,
    ) -> list[Any]:
        """Re-rank documents using a cross-encoder model."""
        if not self._reranker_model or not documents:
            return documents

        from haystack.components.rankers import (  # type: ignore[import-untyped]
            SentenceTransformersSimilarityRanker,
        )

        ranker = SentenceTransformersSimilarityRanker(
            model=self._reranker_model,
            top_k=top_k,
        )
        ranker.warm_up()

        result = await asyncio.to_thread(
            ranker.run, query=query, documents=documents,
        )
        return result["documents"]

    def _build_embedding_retriever(
        self,
        top_k: int,
        filters: dict[str, Any] | None,
    ) -> Any:
        """Build an embedding retriever for non-InMemory stores."""
        store = self._document_store
        store_type = type(store).__name__

        if "Chroma" in store_type:
            from haystack_integrations.components.retrievers.chroma import (  # type: ignore[import-untyped]
                ChromaEmbeddingRetriever,
            )

            return ChromaEmbeddingRetriever(
                document_store=store, top_k=top_k,
            )
        if "Qdrant" in store_type:
            from haystack_integrations.components.retrievers.qdrant import (  # type: ignore[import-untyped]
                QdrantEmbeddingRetriever,
            )

            return QdrantEmbeddingRetriever(
                document_store=store, top_k=top_k,
                filters=filters,
            )
        if "Pinecone" in store_type:
            from haystack_integrations.components.retrievers.pinecone import (  # type: ignore[import-untyped]
                PineconeEmbeddingRetriever,
            )

            return PineconeEmbeddingRetriever(
                document_store=store, top_k=top_k,
                filters=filters,
            )
        if "Weaviate" in store_type:
            from haystack_integrations.components.retrievers.weaviate import (  # type: ignore[import-untyped]
                WeaviateEmbeddingRetriever,
            )

            return WeaviateEmbeddingRetriever(
                document_store=store, top_k=top_k,
                filters=filters,
            )

        raise ValueError(
            f"No embedding retriever available for store type '{store_type}'"
        )

    @staticmethod
    def _build_filters(
        filters: dict[str, str],
    ) -> dict[str, Any] | None:
        """Convert simple ``{key: value}`` filters to Haystack filter format."""
        if not filters:
            return None

        conditions = [
            {"field": f"meta.{k}", "operator": "==", "value": v}
            for k, v in filters.items()
        ]
        if len(conditions) == 1:
            return conditions[0]
        return {"operator": "AND", "conditions": conditions}

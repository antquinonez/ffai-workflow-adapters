"""Three-tier document deduplication for RAG indexing."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class DocumentSync:
    """Coordinate download, extraction, and indexing of documents for RAG.

    Implements a three-tier dedup strategy:

    1. **Size check** — Compare Airtable attachment size with stored size.
    2. **ChromaDB check** — Compare stored checksum against vector store metadata.
    3. **Index check** — ``rag.aindex(checksum=...)`` skips if checksum matches.

    Tier 1 avoids network I/O. Tier 2 avoids text extraction. Tier 3 avoids
    embedding computation. An unchanged document on a repeat run touches
    zero I/O across all tiers.

    Args:
        attachment_sync: An ``AttachmentSync`` instance for file management.
        extract_fn: Callable ``(filepath) -> str`` that extracts text from a file.
    """

    def __init__(
        self,
        attachment_sync: Any,
        extract_fn: Any,
    ) -> None:
        self._sync = attachment_sync
        self._extract_fn = extract_fn

    def process_records(
        self,
        records: list[dict[str, Any]],
        rag: Any,
        file_field: str = "File",
    ) -> dict[str, Any]:
        """Process all Airtable records through the dedup pipeline.

        Args:
            records: Airtable record dicts (from ``table.all()``).
            rag: An ``ffai.rag.RAG`` instance.
            file_field: Name of the attachment field.

        Returns:
            Dict with keys ``documents``, ``downloaded``, ``extracted``,
            ``fully_skipped``, ``indexed``, ``skipped``.
        """
        from ffai_workflow_adapters._airtable_attachments import sha256_of_text

        unchanged, needs_work = self._sync.classify(records, file_field)

        documents: list[dict[str, Any]] = []
        downloaded = 0
        extracted = 0

        for doc in needs_work:
            filepath = self._sync.download(doc["url"], doc["filename"])
            downloaded += 1

            try:
                text = self._extract_fn(str(filepath))
            except Exception as e:
                logger.warning("Extraction failed for %s: %s", doc["filename"], e)
                continue

            checksum = sha256_of_text(text)
            extracted += 1
            documents.append({
                "name": doc["name"],
                "filename": doc["filename"],
                "text": text,
                "checksum": checksum,
                "text_len": len(text),
            })
            self._sync.record(doc["filename"], doc["airtable_size"], checksum, len(text))

        fully_skipped = 0
        for doc in unchanged:
            store = rag._store if hasattr(rag, "_store") else None
            if store is not None and hasattr(store, "needs_reindex"):
                needs = store.needs_reindex(doc["filename"], doc["checksum"], strategy="recursive")
                if not needs:
                    documents.append({
                        "name": doc["name"],
                        "filename": doc["filename"],
                        "text": None,
                        "checksum": doc["checksum"],
                        "text_len": doc.get("text_len", 0),
                    })
                    fully_skipped += 1
                    continue

            filepath = self._sync.download(doc["url"], doc["filename"])
            downloaded += 1
            try:
                text = self._extract_fn(str(filepath))
            except Exception as e:
                logger.warning("Re-extraction failed for %s: %s", doc["filename"], e)
                continue

            checksum = sha256_of_text(text)
            extracted += 1
            documents.append({
                "name": doc["name"],
                "filename": doc["filename"],
                "text": text,
                "checksum": checksum,
                "text_len": len(text),
            })
            self._sync.record(doc["filename"], doc["airtable_size"], checksum, len(text))

        self._sync.save()

        return {
            "documents": documents,
            "downloaded": downloaded,
            "extracted": extracted,
            "fully_skipped": fully_skipped,
        }

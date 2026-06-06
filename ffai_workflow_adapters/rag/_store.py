"""Store adapter wrapping a Haystack DocumentStore with dedup support.

Provides the ``needs_reindex()`` interface that ``DocumentSync`` relies on
(via ``rag._store``), plus a checksum sidecar for tracking indexed documents.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CHECKSUMS_FILE = "haystack_checksums.json"


class StoreAdapter:
    """Wraps a Haystack ``DocumentStore`` with source/checksum tracking.

    This adapter bridges the gap between Haystack's ``DocumentStore`` API
    and the ``needs_reindex(source, checksum, strategy)`` protocol used by
    ``DocumentSync``.  It maintains a JSON sidecar file mapping
    ``(source, strategy)`` to checksums so that unchanged documents can be
    skipped on repeat runs.

    Args:
        document_store: A Haystack ``DocumentStore`` instance.
        persist_dir: Directory for the checksum sidecar file.  If ``None``,
            checksums are only kept in memory (lost between runs).
    """

    def __init__(
        self,
        document_store: Any,
        persist_dir: str | Path | None = None,
    ) -> None:
        self._store = document_store
        self._persist_dir = Path(persist_dir) if persist_dir else None
        self._checksums: dict[str, dict[str, str]] = {}
        if self._persist_dir:
            self._load_checksums()

    @property
    def name(self) -> str:
        return type(self._store).__name__

    def count(self) -> int:
        return self._store.count_documents()

    def needs_reindex(
        self,
        source: str,
        checksum: str,
        strategy: str = "default",
    ) -> bool:
        """Return ``True`` if *source* must be re-indexed.

        Compares the stored checksum for ``(source, strategy)`` against the
        provided *checksum*.  If they match, returns ``False`` (no re-index
        needed).
        """
        stored = self._checksums.get(source, {}).get(strategy)
        if stored is None:
            return True
        return stored != checksum

    def record_checksum(
        self,
        source: str,
        checksum: str,
        strategy: str = "default",
    ) -> None:
        """Record that *source* has been indexed with *checksum*."""
        if source not in self._checksums:
            self._checksums[source] = {}
        self._checksums[source][strategy] = checksum
        self._save_checksums()

    def delete_by_source(self, source: str) -> None:
        """Remove all documents with ``meta.source == source``."""
        filters = {
            "operator": "AND",
            "conditions": [
                {"field": "meta.source", "operator": "==", "value": source},
            ],
        }
        docs = self._store.filter_documents(filters=filters)
        if docs:
            self._store.delete_documents([d.id for d in docs])
        self._checksums.pop(source, None)
        self._save_checksums()

    def _checksums_path(self) -> Path | None:
        if self._persist_dir is None:
            return None
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        return self._persist_dir / _CHECKSUMS_FILE

    def _load_checksums(self) -> None:
        path = self._checksums_path()
        if path is None or not path.exists():
            return
        try:
            self._checksums = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load checksums from %s: %s", path, exc)
            self._checksums = {}

    def _save_checksums(self) -> None:
        path = self._checksums_path()
        if path is None:
            return
        try:
            path.write_text(
                json.dumps(self._checksums, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to save checksums to %s: %s", path, exc)

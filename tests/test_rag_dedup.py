"""Tests for _rag_dedup.py DocumentSync."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ffai_workflow_adapters._airtable_attachments import AttachmentSync
from ffai_workflow_adapters._rag_dedup import DocumentSync


def _make_rag(needs_reindex_return: bool = True) -> MagicMock:
    store = MagicMock()
    store.needs_reindex.return_value = needs_reindex_return
    rag = MagicMock()
    rag._store = store
    return rag


def _make_records() -> list[dict[str, Any]]:
    return [
        {"fields": {"Name": "Doc A", "File": [
            {"filename": "a.txt", "url": "https://x/a", "size": 100},
        ]}},
        {"fields": {"Name": "Doc B", "File": [
            {"filename": "b.txt", "url": "https://x/b", "size": 200},
        ]}},
    ]


class TestDocumentSync:
    def test_first_run_indexes_all(self, tmp_path: Path) -> None:
        sync = AttachmentSync(tmp_path, api_key="k")
        extract_calls = []

        def extract(path):
            text = Path(path).stem + " content"
            extract_calls.append(path)
            return text

        rag = _make_rag()
        doc_sync = DocumentSync(sync, extract)

        with pytest.MonkeyPatch.context() as mp:
            import httpx
            mock_resp = type("R", (), {
                "content": b"data",
                "raise_for_status": lambda self: None,
            })()
            mp.setattr(httpx, "get", lambda url, headers=None: mock_resp)

            result = doc_sync.process_records(_make_records(), rag)

        assert result["downloaded"] == 2
        assert result["extracted"] == 2
        assert result["fully_skipped"] == 0
        assert len(result["documents"]) == 2
        assert all(d["text"] is not None for d in result["documents"])

    def test_second_run_skips_all(self, tmp_path: Path) -> None:
        sync = AttachmentSync(tmp_path, api_key="k")

        def extract(path):
            return Path(path).stem + " content"

        rag_first = _make_rag(needs_reindex_return=True)
        doc_sync = DocumentSync(sync, extract)

        records = _make_records()

        with pytest.MonkeyPatch.context() as mp:
            import httpx
            mock_resp = type("R", (), {
                "content": b"data",
                "raise_for_status": lambda self: None,
            })()
            mp.setattr(httpx, "get", lambda url, headers=None: mock_resp)

            doc_sync.process_records(records, rag_first)

        rag_second = _make_rag(needs_reindex_return=False)
        result = doc_sync.process_records(records, rag_second)

        assert result["downloaded"] == 0
        assert result["extracted"] == 0
        assert result["fully_skipped"] == 2
        assert all(d["text"] is None for d in result["documents"])

    def test_changed_doc_reindexed(self, tmp_path: Path) -> None:
        sync = AttachmentSync(tmp_path, api_key="k")

        def extract(path):
            return "content"

        doc_sync = DocumentSync(sync, extract)
        mock_resp = type("R", (), {
            "content": b"data",
            "raise_for_status": lambda self: None,
        })()

        with pytest.MonkeyPatch.context() as mp:
            import httpx
            mp.setattr(httpx, "get", lambda url, headers=None: mock_resp)

            rag_first = _make_rag(needs_reindex_return=True)
            doc_sync.process_records(_make_records(), rag_first)

        changed_records = [
            {"fields": {"Name": "Doc A", "File": [
                {"filename": "a.txt", "url": "https://x/a", "size": 999},
            ]}},
            {"fields": {"Name": "Doc B", "File": [
                {"filename": "b.txt", "url": "https://x/b", "size": 200},
            ]}},
        ]

        with pytest.MonkeyPatch.context() as mp:
            import httpx
            mp.setattr(httpx, "get", lambda url, headers=None: mock_resp)

            rag_second = _make_rag(needs_reindex_return=False)
            result = doc_sync.process_records(changed_records, rag_second)

        assert result["downloaded"] == 1
        assert result["extracted"] == 1
        assert result["fully_skipped"] == 1

    def test_extraction_failure_skipped(self, tmp_path: Path) -> None:
        sync = AttachmentSync(tmp_path, api_key="k")

        def bad_extract(path):
            raise RuntimeError("parse error")

        doc_sync = DocumentSync(sync, bad_extract)

        with pytest.MonkeyPatch.context() as mp:
            import httpx
            mock_resp = type("R", (), {
                "content": b"data",
                "raise_for_status": lambda self: None,
            })()
            mp.setattr(httpx, "get", lambda url, headers=None: mock_resp)

            rag = _make_rag()
            result = doc_sync.process_records(_make_records(), rag)

        assert result["downloaded"] == 2
        assert result["extracted"] == 0
        assert len(result["documents"]) == 0

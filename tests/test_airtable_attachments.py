"""Tests for _airtable_attachments.py AttachmentSync."""
from __future__ import annotations

from pathlib import Path

import pytest

from ffai_workflow_adapters._airtable_attachments import AttachmentSync, sha256_of_text


class TestSha256OfText:
    def test_returns_hex_digest(self) -> None:
        result = sha256_of_text("hello")
        assert isinstance(result, str)
        assert len(result) == 64

    def test_deterministic(self) -> None:
        assert sha256_of_text("test") == sha256_of_text("test")

    def test_different_inputs_different_hashes(self) -> None:
        assert sha256_of_text("a") != sha256_of_text("b")


class TestAttachmentSync:
    def test_creates_data_dir(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "new_dir"
        AttachmentSync(data_dir, api_key="k")
        assert data_dir.exists()

    def test_stored_empty_on_first_run(self, tmp_path: Path) -> None:
        sync = AttachmentSync(tmp_path, api_key="k")
        assert sync.stored == {}

    def test_save_and_reload(self, tmp_path: Path) -> None:
        sync = AttachmentSync(tmp_path, api_key="k")
        sync.record("file.txt", airtable_size=100, checksum="abc", text_len=50)
        sync.save()

        sync2 = AttachmentSync(tmp_path, api_key="k")
        assert sync2.stored["file.txt"]["airtable_size"] == 100
        assert sync2.stored["file.txt"]["checksum"] == "abc"

    def test_classify_splits_records(self, tmp_path: Path) -> None:
        sync = AttachmentSync(tmp_path, api_key="k")
        sync.record("old.txt", airtable_size=100, checksum="abc123", text_len=50)
        sync.save()

        records = [
            {"fields": {"Name": "Old Doc", "File": [
                {"filename": "old.txt", "url": "https://example.com/old", "size": 100},
            ]}},
            {"fields": {"Name": "New Doc", "File": [
                {"filename": "new.txt", "url": "https://example.com/new", "size": 200},
            ]}},
        ]

        unchanged, needs_work = sync.classify(records)

        assert len(unchanged) == 1
        assert unchanged[0]["filename"] == "old.txt"
        assert unchanged[0]["checksum"] == "abc123"

        assert len(needs_work) == 1
        assert needs_work[0]["filename"] == "new.txt"

    def test_classify_skips_no_attachment_records(self, tmp_path: Path) -> None:
        sync = AttachmentSync(tmp_path, api_key="k")
        records = [
            {"fields": {"Name": "No File"}},
            {"fields": {"Name": "Empty File", "File": []}},
        ]
        unchanged, needs_work = sync.classify(records)
        assert len(unchanged) == 0
        assert len(needs_work) == 0

    def test_classify_size_mismatch_means_needs_work(self, tmp_path: Path) -> None:
        sync = AttachmentSync(tmp_path, api_key="k")
        sync.record("doc.txt", airtable_size=100, checksum="abc", text_len=50)

        records = [
            {"fields": {"Name": "Doc", "File": [
                {"filename": "doc.txt", "url": "https://x", "size": 999},
            ]}},
        ]

        unchanged, needs_work = sync.classify(records)
        assert len(unchanged) == 0
        assert len(needs_work) == 1

    def test_download_writes_file(self, tmp_path: Path) -> None:
        sync = AttachmentSync(tmp_path, api_key="test-key")

        with pytest.MonkeyPatch.context() as mp:
            import httpx
            mock_resp = type("R", (), {
                "content": b"file content",
                "raise_for_status": lambda self: None,
            })()
            mp.setattr(httpx, "get", lambda url, headers=None: mock_resp)

            filepath = sync.download("https://example.com/f", "test.txt")

        assert filepath.exists()
        assert filepath.read_bytes() == b"file content"

"""Airtable attachment download, caching, and checksum tracking."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def sha256_of_text(text: str) -> str:
    """Return the SHA-256 hex digest of a string."""
    return hashlib.sha256(text.encode()).hexdigest()


class AttachmentSync:
    """Download Airtable attachments with local caching and checksum tracking.

    Maintains a ``checksums.json`` sidecar file that records Airtable
    attachment sizes and extracted-text checksums from the previous run.
    On repeat runs, attachments whose Airtable size has not changed are
    skipped entirely (no network I/O, no text extraction).

    Args:
        data_dir: Directory for downloaded files and ``checksums.json``.
        api_key: Airtable API key (used as Bearer token for downloads).
    """

    def __init__(self, data_dir: str | Path, api_key: str) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key
        self.checksums_file = self.data_dir / "checksums.json"
        self._stored: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.checksums_file.exists():
            self._stored = json.loads(self.checksums_file.read_text())

    def save(self) -> None:
        self.checksums_file.write_text(json.dumps(self._stored, indent=2))

    @property
    def stored(self) -> dict[str, dict[str, Any]]:
        return self._stored

    def classify(
        self, records: list[dict[str, Any]], file_field: str = "File"
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split records into unchanged (skip) and needs-work lists.

        Compares Airtable attachment ``size`` against stored
        ``airtable_size``. Matching sizes are assumed unchanged.

        Args:
            records: Airtable record dicts (from ``table.all()``).
            file_field: Name of the attachment field. Defaults to ``"File"``.

        Returns:
            ``(unchanged, needs_work)`` tuples of flattened attachment dicts.
        """
        unchanged: list[dict[str, Any]] = []
        needs_work: list[dict[str, Any]] = []

        for rec in records:
            fields = rec["fields"]
            name = fields.get("Name", "unnamed")
            attachments = fields.get(file_field, [])

            for att in attachments:
                filename = att["filename"]
                airtable_size = att.get("size", 0)
                prev = self._stored.get(filename, {})

                entry = {
                    "name": name,
                    "filename": filename,
                    "url": att["url"],
                    "airtable_size": airtable_size,
                }

                if prev.get("airtable_size") == airtable_size and prev.get("checksum"):
                    unchanged.append({**entry, "checksum": prev["checksum"],
                                      "text_len": prev.get("text_len", 0)})
                else:
                    needs_work.append(entry)

        return unchanged, needs_work

    def download(self, url: str, filename: str) -> Path:
        """Download an attachment to the data directory.

        Args:
            url: Temporary Airtable attachment URL.
            filename: Local filename to save as.

        Returns:
            Path to the downloaded file.
        """
        filepath = self.data_dir / filename
        resp = httpx.get(url, headers={"Authorization": f"Bearer {self.api_key}"})
        resp.raise_for_status()
        filepath.write_bytes(resp.content)
        return filepath

    def record(
        self,
        filename: str,
        airtable_size: int,
        checksum: str,
        text_len: int,
    ) -> None:
        """Store checksum metadata for a processed file."""
        self._stored[filename] = {
            "airtable_size": airtable_size,
            "checksum": checksum,
            "text_len": text_len,
        }

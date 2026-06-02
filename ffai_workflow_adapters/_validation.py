"""Shared schema validation for tabular workflow data."""
from __future__ import annotations

from typing import Any

from ffai.workflow.tabular import TabularLoadError

REQUIRED_FIELDS = frozenset({"name", "prompt"})


def validate_schema(rows: list[dict[str, Any]], source_label: str) -> None:
    all_keys: set[str] = set()
    for row in rows:
        all_keys.update(row.keys())

    missing = REQUIRED_FIELDS - all_keys
    if missing:
        raise TabularLoadError(
            f"'{source_label}' is missing required columns: {sorted(missing)}. "
            f"Found columns: {sorted(all_keys)}. "
            f"Use input_field_map in config to map your column names."
        )

    if "temperature" in all_keys:
        for i, row in enumerate(rows):
            t = row.get("temperature")
            if t is not None:
                try:
                    float(t)
                except (ValueError, TypeError):
                    raise TabularLoadError(
                        f"Row {i} ('{row.get('name', '?')}'): temperature must be a number, got '{t}'"
                    )

    if "max_tokens" in all_keys:
        for i, row in enumerate(rows):
            mt = row.get("max_tokens")
            if mt is not None:
                try:
                    int(float(mt))
                except (ValueError, TypeError):
                    raise TabularLoadError(
                        f"Row {i} ('{row.get('name', '?')}'): max_tokens must be a number, got '{mt}'"
                    )

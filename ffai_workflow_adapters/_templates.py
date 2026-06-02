"""Template variable resolution for extra output columns."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _generate_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _resolve_extra_value(template: str, run_id: str) -> Any:
    if template == "{{run_id}}":
        return run_id
    if template.startswith("{{now:") and template.endswith("}}"):
        fmt = template[6:-2]
        return datetime.now(timezone.utc).strftime(fmt)
    if template == "{{date}}":
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if template == "{{timestamp}}":
        return datetime.now(timezone.utc).isoformat()
    return template

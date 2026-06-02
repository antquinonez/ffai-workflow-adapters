"""Example: Named adapter with custom field mapping.

Uses the "custom" named adapter from config/adapters.yaml, which maps
different column names (Task, Instructions, AI Model) to the canonical
workflow fields. Named configs inherit unset fields from the base config.

Usage:
    python examples/airtable/run_named.py

Required .env:
    AIRTABLE_API_KEY, AIRTABLE_BASE_ID, MISTRAL_API_KEY
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import get_base_id, run_workflow

ADAPTER = "custom"
TABLE_NAME = "Custom Workflow"
RESULTS_TABLE = "_results_custom"


async def main() -> None:
    base_id = get_base_id(adapter=ADAPTER)
    await run_workflow(
        base_id,
        TABLE_NAME,
        RESULTS_TABLE,
        adapter=ADAPTER,
        workflow_name="named_custom",
    )


if __name__ == "__main__":
    asyncio.run(main())

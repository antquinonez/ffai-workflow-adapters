"""Example: Default adapter with input/output field mapping.

Uses the base airtable config from config/adapters.yaml, which maps
user-friendly column names (Name, Prompt, Model) to the canonical
workflow fields (name, prompt, client).

Usage:
    python examples/airtable/run_default.py

Required .env:
    AIRTABLE_API_KEY, AIRTABLE_BASE_ID, MISTRAL_API_KEY
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import get_base_id, run_workflow

TABLE_NAME = "Workflow Steps"
VIEW_NAME = "basic"
RESULTS_TABLE = "_results"


async def main() -> None:
    base_id = get_base_id()
    await run_workflow(
        base_id,
        TABLE_NAME,
        RESULTS_TABLE,
        view=VIEW_NAME,
        workflow_name="default_adapter",
    )


if __name__ == "__main__":
    asyncio.run(main())

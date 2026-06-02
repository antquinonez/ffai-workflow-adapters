"""Example: Named adapter with custom field mapping.

Uses the "custom" named adapter from config/adapters.yaml, which maps
different column names (Task, Instructions, AI Model) to the canonical
workflow fields. Named configs inherit unset fields from the base config.

Usage:
    python examples/excel/run_named.py

Required .env:
    MISTRAL_API_KEY (or OPENAI_API_KEY for GPT steps)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import run_workflow

ADAPTER = "custom"
WORKBOOK = str(Path(__file__).resolve().parent / "workflow_custom.xlsx")
RESULTS = str(Path(__file__).resolve().parent / "results_custom.xlsx")


async def main() -> None:
    await run_workflow(
        WORKBOOK,
        RESULTS,
        adapter=ADAPTER,
        sheet="Steps",
        results_sheet="Custom Results",
        workflow_name="excel_custom",
    )


if __name__ == "__main__":
    asyncio.run(main())

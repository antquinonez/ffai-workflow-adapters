"""Example: Default adapter with input/output field mapping.

Uses the base excel config from config/adapters.yaml, which maps
user-friendly column names (Name, Prompt, Model) to the canonical
workflow fields (name, prompt, client).

Usage:
    python examples/excel/run_default.py

Required .env:
    MISTRAL_API_KEY (or OPENAI_API_KEY for GPT steps)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import run_workflow

WORKBOOK = str(Path(__file__).resolve().parent / "workflow_default.xlsx")
RESULTS = str(Path(__file__).resolve().parent / "results_default.xlsx")


async def main() -> None:
    await run_workflow(
        WORKBOOK,
        RESULTS,
        sheet="Workflow",
        workflow_name="excel_default",
    )


if __name__ == "__main__":
    asyncio.run(main())

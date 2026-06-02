"""Example: Default adapter with input/output field mapping.

Uses the base airtable config from config/adapters.yaml, which maps
user-friendly column names (Name, Prompt, Model) to the canonical
workflow fields (name, prompt, client).

Usage:
    python -m examples.run_default_adapter

Required .env:
    AIRTABLE_API_KEY, AIRTABLE_BASE_ID, MISTRAL_API_KEY

Your "Workflow Steps" table should use these column names
(as configured in config/adapters.yaml input_field_map):

    Name         - Single line text (maps to "name")
    Prompt       - Long text (maps to "prompt")
    Model        - Single Select (maps to "client")
    History      - Single line text (maps to "history")
    Temperature  - Number (maps to "temperature")
    Max Tokens   - Number (maps to "max_tokens")

Your "_results" table should use these column names
(as configured in config/adapters.yaml output_field_map):

    Workflow, Step, Status, Response, Model,
    Input Tokens, Output Tokens, Cost, Duration ms, Timestamp
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from airtable_helpers import get_base_id, run_workflow

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

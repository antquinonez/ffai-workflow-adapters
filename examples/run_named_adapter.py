"""Example: Named adapter with custom field mapping.

Uses the "custom" named adapter from config/adapters.yaml, which maps
different column names (Task, Instructions, AI Model) to the canonical
workflow fields. Named configs inherit unset fields from the base config.

Usage:
    python -m examples.run_named_adapter

Required .env:
    AIRTABLE_API_KEY, AIRTABLE_BASE_ID, MISTRAL_API_KEY

Create a "Custom Workflow" table in the same base with these columns
(as configured in config/adapters.yaml -> airtable.named.custom.input_field_map):

    Task          - Single line text (maps to "name")
    Instructions  - Long text (maps to "prompt")
    AI Model      - Single Select (maps to "client")
                   Options: litellm-mistral-small, litellm-gpt-4o-mini
    Context       - Single line text (maps to "history")
    Temp          - Number (maps to "temperature")

Example rows:
    Task    | Instructions                                    | AI Model              | Context
    ------- | ----------------------------------------------- | --------------------- | -------
    topic   | Name a famous scientific discovery.             | litellm-mistral-small |
    explain | Explain its impact: {{topic.response}}          | litellm-gpt-4o-mini   | topic

Your "_results" table columns are remapped by the named adapter's output_field_map:
    Task (from "step"), Output (from "response"), AI Model (from "model"),
    plus inherited Workflow, Status, Input Tokens, Output Tokens, Cost,
    Duration ms, Timestamp
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from airtable_helpers import get_base_id, run_workflow

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

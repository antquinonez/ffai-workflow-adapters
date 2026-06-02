"""Example: Load a workflow from Airtable and execute it.

Usage:
    python examples/run_airtable_workflow.py

Required .env variables:
    AIRTABLE_API_KEY    - Your Airtable personal access token
    AIRTABLE_BASE_ID    - Your Airtable base ID (e.g. appXXXXXXXXXXXXXX)
    MISTRAL_API_KEY     - Your Mistral API key (default model)
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from ffai import FFAI
from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient

from ffai_workflow_adapters import load_workflow_airtable, get_config

load_dotenv()

TABLE_NAME = "Workflow Steps"
VIEW_NAME = "basic"


async def main() -> None:
    config = get_config()
    base_id = os.environ.get(config.adapters.airtable.base_id_env, "")
    if not base_id:
        raise ValueError(
            f"Set {config.adapters.airtable.base_id_env} in your .env file"
        )

    api_key = os.environ.get("MISTRAL_API_KEY", "")
    client = AsyncFFLiteLLMClient(
        model_string="mistral/mistral-small-latest",
        api_key=api_key,
    )
    ffai = FFAI(client)

    print(f"Loading workflow from Airtable: {TABLE_NAME} (view: {VIEW_NAME})...\n")
    spec = load_workflow_airtable(
        base_id,
        TABLE_NAME,
        view=VIEW_NAME,
        name="airtable_basic",
        description="Basic 2-step workflow from Airtable",
    )

    print(f"Workflow: {spec.name}")
    print(f"Steps: {len(spec.prompts)}")
    for step in spec.prompts:
        print(f"  - {step.name}: {step.prompt[:80]}{'...' if len(step.prompt) > 80 else ''}")
    print()

    print("Executing workflow...\n")
    result = await ffai.execute_workflow(spec)

    print(f"Completed: {result.success_count} succeeded, {result.failed_count} failed, {result.skipped_count} skipped")
    print()
    for step_name, step_result in result.results.items():
        print(f"=== {step_name} ===")
        print(f"Model: {step_result.model}")
        if step_result.usage:
            print(f"Tokens: {step_result.usage.input_tokens} input + {step_result.usage.output_tokens} output")
        print(f"Response:\n{step_result.response}")
        print()


if __name__ == "__main__":
    asyncio.run(main())

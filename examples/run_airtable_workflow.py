"""Example: Load a workflow from Airtable, execute it, and write results back.

Usage:
    python examples/run_airtable_workflow.py

Required .env variables:
    AIRTABLE_API_KEY    - Your Airtable personal access token
    AIRTABLE_BASE_ID    - Your Airtable base ID (e.g. appXXXXXXXXXXXXXX)
    MISTRAL_API_KEY     - Your Mistral API key (default client)
    OPENAI_API_KEY      - Your OpenAI API key (if using gpt-4o-mini steps)

The script reads steps from the "Workflow Steps" table (view: basic),
executes them, then writes results to the "_results" table in the same base.

Per-step client resolution:
    - Add a "client" column to Airtable with values like "litellm-mistral-small"
      or "litellm-gpt-4o-mini". These resolve from config/clients.yaml.
    - If the column is blank, the system default client is used.

Named adapters:
    - Define per-base overrides in config/adapters.yaml under airtable.named
    - Pass adapter="name" to load_workflow_airtable / write_workflow_results
    - Named configs inherit unset fields from the base airtable config

Create the "_results" table with these columns:
    workflow      - Single line text
    step          - Single line text
    status        - Single line text
    response      - Long text
    model         - Single line text
    input_tokens  - Number
    output_tokens - Number
    cost_usd      - Currency
    duration_ms   - Number
    timestamp     - Single line text (ISO 8601)
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from ffai import FFAI
from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient

from ffai_workflow_adapters import get_config, load_workflow_airtable, write_workflow_results

load_dotenv()

TABLE_NAME = "Workflow Steps"
VIEW_NAME = "basic"
RESULTS_TABLE = "_results"
ADAPTER_NAME = None  # Set to a named adapter from config/adapters.yaml, e.g. "marketing"


def _create_default_client() -> AsyncFFLiteLLMClient:
    config = get_config()
    default_name = config.clients.default_client
    client_cfg = config.clients.get_client_type(default_name)

    if client_cfg:
        model_string = f"{client_cfg.provider_prefix}{client_cfg.default_model}"
        api_key = os.environ.get(client_cfg.api_key_env, "")
    else:
        model_string = "mistral/mistral-small-latest"
        api_key = os.environ.get("MISTRAL_API_KEY", "")

    return AsyncFFLiteLLMClient(model_string=model_string, api_key=api_key)


async def main() -> None:
    config = get_config()
    airtable_cfg = config.adapters.airtable.resolve(ADAPTER_NAME)
    base_id = os.environ.get(airtable_cfg.base_id_env, "")
    if not base_id:
        raise ValueError(f"Set {airtable_cfg.base_id_env} in your .env file")

    default_client = _create_default_client()
    ffai = FFAI(default_client)

    adapter_info = f" (adapter: {ADAPTER_NAME})" if ADAPTER_NAME else ""
    print(f"Default client: {config.clients.default_client}")
    print(f"Loading workflow from Airtable{adapter_info}: {TABLE_NAME} (view: {VIEW_NAME})...\n")
    spec = load_workflow_airtable(
        base_id,
        TABLE_NAME,
        adapter=ADAPTER_NAME,
        view=VIEW_NAME,
        name="airtable_basic",
        description="Basic 2-step workflow from Airtable",
    )

    print(f"Workflow: {spec.name}")
    print(f"Steps: {len(spec.prompts)}")
    for step in spec.prompts:
        client_info = f" [client: {step.client.name}]" if step.client else ""
        print(f"  - {step.name}{client_info}: {step.prompt[:80]}{'...' if len(step.prompt) > 80 else ''}")
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

    print(f"Writing results to Airtable: {RESULTS_TABLE}...")
    created = write_workflow_results(base_id, RESULTS_TABLE, result, adapter=ADAPTER_NAME)
    print(f"Wrote {len(created)} record(s) to {RESULTS_TABLE}")


if __name__ == "__main__":
    asyncio.run(main())

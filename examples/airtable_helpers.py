"""Shared helpers for Airtable example scripts."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from ffai import FFAI
from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient

from ffai_workflow_adapters import get_config, load_workflow_airtable, write_workflow_results

load_dotenv()


def create_default_client() -> AsyncFFLiteLLMClient:
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


def get_base_id(adapter: str | None = None) -> str:
    config = get_config()
    airtable_cfg = config.adapters.airtable.resolve(adapter)
    base_id = os.environ.get(airtable_cfg.base_id_env, "")
    if not base_id:
        raise ValueError(f"Set {airtable_cfg.base_id_env} in your .env file")
    return base_id


async def run_workflow(
    base_id: str,
    table_name: str,
    results_table: str,
    *,
    adapter: str | None = None,
    view: str | None = None,
    workflow_name: str = "workflow",
) -> None:
    config = get_config()
    airtable_cfg = config.adapters.airtable.resolve(adapter)

    default_client = create_default_client()
    ffai = FFAI(default_client)

    adapter_info = f" (adapter: {adapter})" if adapter else ""
    field_map_info = f", input_field_map: {airtable_cfg.input_field_map}" if airtable_cfg.input_field_map else ""
    print(f"Default client: {config.clients.default_client}")
    print(f"Loading from {table_name}{adapter_info} (view: {view}){field_map_info}...\n")

    spec = load_workflow_airtable(
        base_id,
        table_name,
        adapter=adapter,
        view=view,
        name=workflow_name,
    )

    print(f"Workflow: {spec.name}")
    print(f"Steps: {len(spec.prompts)}")
    for step in spec.prompts:
        client_info = f" [client: {step.client.name}]" if step.client else ""
        print(f"  - {step.name}{client_info}: {step.prompt[:80]}{'...' if len(step.prompt) > 80 else ''}")
    print()

    print("Executing...\n")
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

    output_map_info = f" (output_field_map: {airtable_cfg.output_field_map})" if airtable_cfg.output_field_map else ""
    print(f"Writing to {results_table}{output_map_info}...")
    created = write_workflow_results(base_id, results_table, result, adapter=adapter)
    print(f"Wrote {len(created)} record(s) to {results_table}")

"""Shared helpers for Excel example scripts."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from ffai import FFAI
from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient

from ffai_workflow_adapters import get_config, load_workflow_excel, write_workflow_results_excel

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


async def run_workflow(
    workbook_path: str,
    results_path: str,
    *,
    adapter: str | None = None,
    sheet: str | int | None = None,
    results_sheet: str = "Results",
    workflow_name: str = "workflow",
) -> None:
    config = get_config()
    excel_cfg = config.adapters.excel.resolve(adapter)

    default_client = create_default_client()
    ffai = FFAI(default_client)

    adapter_info = f" (adapter: {adapter})" if adapter else ""
    sheet_info = f" sheet={sheet}" if sheet else ""
    field_map_info = f", input_field_map: {excel_cfg.input_field_map}" if excel_cfg.input_field_map else ""
    print(f"Default client: {config.clients.default_client}")
    print(f"Loading from {workbook_path}{adapter_info}{sheet_info}{field_map_info}...\n")

    spec = load_workflow_excel(
        workbook_path,
        adapter=adapter,
        sheet=sheet,
        name=workflow_name,
    )

    print(f"Workflow: {spec.name}")
    print(f"Steps: {len(spec.prompts)}")
    for step in spec.prompts:
        client_info = f" [client: {step.client.name}]" if step.client else ""
        print(f"  - {step.name}{client_info}: {step.prompt[:80]}{'...' if len(step.prompt) > 80 else ''}")
    print()

    print("Executing...\n")
    result = await ffai.workflow.execute_workflow(spec)

    print(f"Completed: {result.success_count} succeeded, {result.failed_count} failed, {result.skipped_count} skipped")
    print()
    for step_name, step_result in result.results.items():
        print(f"=== {step_name} ===")
        print(f"Model: {step_result.model}")
        if step_result.usage:
            print(f"Tokens: {step_result.usage.input_tokens} input + {step_result.usage.output_tokens} output")
        print(f"Response:\n{step_result.response}")
        print()

    pt_info = f", passthrough: {excel_cfg.passthrough_columns}" if excel_cfg.passthrough_columns else ""
    extra_info = f", extra: {list(excel_cfg.extra_output_columns.keys())}" if excel_cfg.extra_output_columns else ""
    output_map_info = f" (output_field_map: {excel_cfg.output_field_map})" if excel_cfg.output_field_map else ""
    print(f"Writing to {results_path} [{results_sheet}]{output_map_info}{pt_info}{extra_info}...")
    saved = write_workflow_results_excel(result, path=results_path, sheet=results_sheet, adapter=adapter, spec=spec)
    print(f"Saved to {saved}")

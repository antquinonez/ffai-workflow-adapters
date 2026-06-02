"""Airtable integration tests — real API calls to Airtable.

Run with: pytest tests/integration/test_airtable_integration.py -m airtable

Requires: AIRTABLE_API_KEY, AIRTABLE_BASE_ID, MISTRAL_API_KEY in .env
"""

from __future__ import annotations

import asyncio
import os

import pytest

from dotenv import load_dotenv

load_dotenv()


def _get_base_id() -> str:
    base_id = os.environ.get("AIRTABLE_BASE_ID", "")
    if not base_id:
        pytest.skip("AIRTABLE_BASE_ID not set")
    return base_id


def _create_client():
    from ffai import FFAI
    from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient
    from ffai_workflow_adapters.config import get_config

    config = get_config()
    default_name = config.clients.default_client
    client_cfg = config.clients.get_client_type(default_name)

    model_string = f"{client_cfg.provider_prefix}{client_cfg.default_model}"
    api_key = os.environ.get(client_cfg.api_key_env, "")

    return FFAI(AsyncFFLiteLLMClient(model_string=model_string, api_key=api_key))


@pytest.mark.integration
@pytest.mark.airtable
class TestAirtableIntegration:
    def test_load_and_execute_default_adapter(self):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        base_id = _get_base_id()
        from ffai_workflow_adapters import load_workflow_airtable

        spec = load_workflow_airtable(
            base_id,
            "Workflow Steps",
            view="basic",
            name="airtable_integration",
        )
        assert spec.name == "airtable_integration"
        assert len(spec.prompts) >= 1

        ffai = _create_client()
        result = asyncio.run(ffai.execute_workflow(spec))
        assert result.success_count >= 1
        assert result.failed_count == 0

        for step_name, step_result in result.results.items():
            assert step_result.status == "success"
            assert step_result.response

    def test_load_and_execute_named_adapter(self):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        base_id = _get_base_id()
        from ffai_workflow_adapters import load_workflow_airtable

        spec = load_workflow_airtable(
            base_id,
            "Custom Workflow",
            adapter="custom",
            name="airtable_custom_integration",
        )
        assert spec.name == "airtable_custom_integration"
        assert len(spec.prompts) >= 1

        ffai = _create_client()
        result = asyncio.run(ffai.execute_workflow(spec))
        assert result.success_count >= 1

    def test_write_results_to_airtable(self):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        base_id = _get_base_id()
        from ffai_workflow_adapters import load_workflow_airtable, write_workflow_results

        spec = load_workflow_airtable(
            base_id,
            "Workflow Steps",
            view="basic",
            name="write_integration",
        )

        ffai = _create_client()
        result = asyncio.run(ffai.execute_workflow(spec))

        created = write_workflow_results(base_id, "_results", result)
        assert len(created) == result.success_count

    def test_write_results_with_named_adapter(self):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        base_id = _get_base_id()
        from ffai_workflow_adapters import load_workflow_airtable, write_workflow_results

        spec = load_workflow_airtable(
            base_id,
            "Custom Workflow",
            adapter="custom",
            name="write_custom_integration",
        )

        ffai = _create_client()
        result = asyncio.run(ffai.execute_workflow(spec))

        created = write_workflow_results(base_id, "_results_custom", result, adapter="custom")
        assert len(created) == result.success_count

    def test_field_mapping_applied(self):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        base_id = _get_base_id()
        from ffai_workflow_adapters import load_workflow_airtable

        spec = load_workflow_airtable(
            base_id,
            "Workflow Steps",
            view="basic",
            name="field_map_check",
        )

        for step in spec.prompts:
            assert step.name is not None
            assert step.prompt is not None
            assert step.client is not None

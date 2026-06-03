"""CSV/TSV integration tests — real files, real workflow execution, real write.

Run with: pytest tests/integration/test_csv_integration.py -m csv

Requires: MISTRAL_API_KEY (and OPENAI_API_KEY for GPT steps)
"""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path

import pytest

from ffai_workflow_adapters.csv_adapter import (
    load_workflow_csv,
    load_workflow_tsv,
    write_workflow_results_csv,
    write_workflow_results_tsv,
)


def _create_client():
    import os

    from dotenv import load_dotenv
    from ffai import FFAI
    from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient

    load_dotenv()

    from ffai_workflow_adapters.config import get_config

    config = get_config()
    default_name = config.clients.default_client
    client_cfg = config.clients.get_client_type(default_name)
    assert client_cfg is not None

    model_string = f"{client_cfg.provider_prefix}{client_cfg.default_model}"
    api_key = os.environ.get(client_cfg.api_key_env, "")

    return FFAI(AsyncFFLiteLLMClient(model_string=model_string, api_key=api_key))


def _create_workflow_csv(
    path: Path, rows: list[list[str | int | float]], headers: list[str] | None = None, delimiter: str = ","
) -> None:
    if headers is None:
        headers = ["name", "prompt", "client", "history", "temperature", "max_tokens", "Comments", "Priority"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([str(v) if v is not None else "" for v in row])


@pytest.mark.integration
@pytest.mark.csv
class TestCsvIntegration:
    def test_load_execute_write_roundtrip(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        workflow = tmp_path / "workflow.csv"
        results = tmp_path / "results.csv"
        _create_workflow_csv(workflow, [
            ["topic", "Name a famous scientific discovery in one sentence.", "litellm-mistral-small", "", 0.7, 256, "Generate topic", "High"],
            ["explain", "Briefly explain the impact of: {{topic.response}}", "litellm-mistral-small", "topic", 0.5, 256, "Expand on it", "Medium"],
        ])

        spec = load_workflow_csv(workflow, name="csv_integration")
        assert spec.name == "csv_integration"
        assert len(spec.prompts) == 2
        assert spec.prompts[0].name == "topic"
        assert spec.prompts[1].history == ["topic"]

        ffai = _create_client()
        result = asyncio.run(ffai.execute_workflow(spec))

        assert result.success_count == 2
        assert result.failed_count == 0
        assert result.results["topic"].response
        assert result.results["explain"].response

        path = write_workflow_results_csv(result, path=results, spec=spec)
        assert Path(path).exists()

        with results.open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 3

        header = rows[0]
        assert "run_id" in header
        assert "run_date" in header

        run_id_col = header.index("run_id")
        assert rows[1][run_id_col] == rows[2][run_id_col]

    def test_append_second_run(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        workflow = tmp_path / "workflow.csv"
        results = tmp_path / "results.csv"
        _create_workflow_csv(workflow, [
            ["topic", "Name a famous scientific discovery in one sentence.", "litellm-mistral-small", "", 0.7, 256, "Generate topic", "High"],
            ["explain", "Briefly explain the impact of: {{topic.response}}", "litellm-mistral-small", "topic", 0.5, 256, "Expand on it", "Medium"],
        ])

        spec = load_workflow_csv(workflow, name="csv_append")
        ffai = _create_client()

        result1 = asyncio.run(ffai.execute_workflow(spec))
        write_workflow_results_csv(result1, path=results, spec=spec)

        result2 = asyncio.run(ffai.execute_workflow(spec))
        write_workflow_results_csv(result2, path=results, spec=spec)

        with results.open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 5

        run_id_col = rows[0].index("run_id")
        assert rows[1][run_id_col] != rows[3][run_id_col]

    def test_custom_run_id(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        workflow = tmp_path / "workflow.csv"
        results = tmp_path / "results.csv"
        _create_workflow_csv(workflow, [
            ["topic", "Name a famous scientific discovery in one sentence.", "litellm-mistral-small", "", 0.7, 256, "", ""],
        ])

        spec = load_workflow_csv(workflow, name="csv_run_id")
        ffai = _create_client()
        result = asyncio.run(ffai.execute_workflow(spec))

        write_workflow_results_csv(result, path=results, spec=spec, run_id="batch-42")

        with results.open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        run_id_col = rows[0].index("run_id")
        assert rows[1][run_id_col] == "batch-42"

    def test_prompt_with_commas_and_quotes(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        workflow = tmp_path / "workflow.csv"
        results = tmp_path / "results.csv"
        _create_workflow_csv(workflow, [
            ["topic", 'Name a discovery. Include details: "who", "when", "where".', "litellm-mistral-small", "", 0.7, 256, "Has commas, quotes", "High"],
        ])

        spec = load_workflow_csv(workflow, name="csv_quoting")
        assert spec.prompts[0].prompt == 'Name a discovery. Include details: "who", "when", "where".'

        ffai = _create_client()
        result = asyncio.run(ffai.execute_workflow(spec))
        assert result.success_count == 1

        write_workflow_results_csv(result, path=results, spec=spec)

        with results.open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 2

        comments_col = rows[0].index("Comments")
        assert rows[1][comments_col] == "Has commas, quotes"

    def test_passthrough_columns_in_output(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        workflow = tmp_path / "workflow.csv"
        results = tmp_path / "results.csv"
        _create_workflow_csv(workflow, [
            ["topic", "Name a famous invention in one sentence.", "litellm-mistral-small", "", 0.7, 256, "Invention step", "High"],
        ])

        spec = load_workflow_csv(workflow, name="csv_passthrough")
        ffai = _create_client()
        result = asyncio.run(ffai.execute_workflow(spec))

        write_workflow_results_csv(result, path=results, spec=spec)

        with results.open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        header = rows[0]

        comments_col = header.index("Comments")
        assert rows[1][comments_col] == "Invention step"

        priority_col = header.index("Priority")
        assert rows[1][priority_col] == "High"


@pytest.mark.integration
@pytest.mark.csv
class TestTsvIntegration:
    def test_load_execute_write_roundtrip(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        workflow = tmp_path / "workflow.tsv"
        results = tmp_path / "results.tsv"
        _create_workflow_csv(workflow, [
            ["topic", "Name a famous scientific discovery in one sentence.", "litellm-mistral-small", "", 0.7, 256, "Generate topic", "High"],
            ["explain", "Briefly explain the impact of: {{topic.response}}", "litellm-mistral-small", "topic", 0.5, 256, "Expand on it", "Medium"],
        ], delimiter="\t")

        spec = load_workflow_tsv(workflow, name="tsv_integration")
        assert spec.name == "tsv_integration"
        assert len(spec.prompts) == 2

        ffai = _create_client()
        result = asyncio.run(ffai.execute_workflow(spec))

        assert result.success_count == 2
        assert result.results["topic"].response
        assert result.results["explain"].response

        path = write_workflow_results_tsv(result, path=results, spec=spec)
        assert Path(path).exists()

        with results.open(encoding="utf-8") as f:
            rows = list(csv.reader(f, delimiter="\t"))
        assert len(rows) == 3

        header = rows[0]
        assert "run_id" in header

        run_id_col = header.index("run_id")
        assert rows[1][run_id_col] == rows[2][run_id_col]

    def test_prompt_with_tabs_and_quotes(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        workflow = tmp_path / "workflow.tsv"
        results = tmp_path / "results.tsv"

        prompt = 'List the following: "alpha", "beta", "gamma".'
        _create_workflow_csv(workflow, [
            ["topic", prompt, "litellm-mistral-small", "", 0.7, 256, "", ""],
        ], delimiter="\t")

        spec = load_workflow_tsv(workflow, name="tsv_quoting")
        assert spec.prompts[0].prompt == prompt

        ffai = _create_client()
        result = asyncio.run(ffai.execute_workflow(spec))
        assert result.success_count == 1

        write_workflow_results_tsv(result, path=results, spec=spec)

        with results.open(encoding="utf-8") as f:
            rows = list(csv.reader(f, delimiter="\t"))
        assert len(rows) == 2

        response_col = rows[0].index("Response")
        assert rows[1][response_col]

"""ODS integration tests — real files, real workflow execution, real write.

Run with: pytest tests/integration/test_ods_integration.py -m ods

Requires: MISTRAL_API_KEY (and OPENAI_API_KEY for GPT steps)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from ffai_workflow_adapters.ods import load_workflow_ods, write_workflow_results_ods


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


def _create_ods(path: Path, headers: list[str], rows: list[list[str | int | float | None]], sheet: str = "Sheet1") -> None:
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow
    from odf.text import P

    doc = OpenDocumentSpreadsheet()
    table: Any = Table(name=sheet)

    def _text_cell(text: str) -> Any:
        cell = TableCell()
        p = P()
        p.addText(str(text) if text is not None else "")
        cell.addElement(p)
        return cell

    header_row = TableRow()
    for h in headers:
        header_row.addElement(_text_cell(h))
    table.addElement(header_row)

    for row_data in rows:
        row = TableRow()
        for val in row_data:
            if val is not None:
                row.addElement(_text_cell(str(val)))
            else:
                row.addElement(TableCell())
        table.addElement(row)

    doc.spreadsheet.addElement(table)  # type: ignore[union-attr]
    doc.save(str(path))


def _read_ods(path: Path, sheet: str | None = None) -> tuple[list[str], list[list[str | None]]]:
    from odf.opendocument import load as odf_load
    from odf.table import Table as OdsTable
    from odf.table import TableCell as OdsTableCell
    from odf.table import TableRow as OdsTableRow
    from odf.text import P

    doc = odf_load(str(path))
    tables = doc.spreadsheet.getElementsByType(OdsTable)  # type: ignore[union-attr]
    if sheet:
        table = next((t for t in tables if t.getAttribute("name") == sheet), tables[0])
    else:
        table = tables[0]

    rows_el = table.getElementsByType(OdsTableRow)

    def _cell_str(cell: Any) -> str | None:
        ps = cell.getElementsByType(P)
        if not ps:
            return None
        parts = [str(p.firstChild) for p in ps if p.firstChild is not None]
        return "".join(parts).strip() or None

    all_rows = []
    for row_el in rows_el:
        cells = row_el.getElementsByType(OdsTableCell)
        all_rows.append([_cell_str(c) for c in cells])

    return all_rows[0], all_rows[1:]


@pytest.mark.integration
@pytest.mark.ods
class TestOdsIntegration:
    def test_load_execute_write_roundtrip(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        workflow = tmp_path / "workflow.ods"
        results = tmp_path / "results.ods"
        _create_ods(workflow, ["name", "prompt", "client", "history", "temperature", "max_tokens", "Comments", "Priority"], [
            ["topic", "Name a famous scientific discovery in one sentence.", "litellm-mistral-small", "", 0.7, 256, "Generate topic", "High"],
            ["explain", "Briefly explain the impact of: {{topic.response}}", "litellm-mistral-small", "topic", 0.5, 256, "Expand on it", "Medium"],
        ], sheet="Workflow")

        spec = load_workflow_ods(workflow, sheet="Workflow", name="ods_integration")
        assert spec.name == "ods_integration"
        assert len(spec.prompts) == 2
        assert spec.prompts[0].name == "topic"
        assert spec.prompts[1].history == ["topic"]

        ffai = _create_client()
        result = asyncio.run(ffai.workflow.execute_workflow(spec))

        assert result.success_count == 2
        assert result.failed_count == 0
        assert result.results["topic"].response
        assert result.results["explain"].response

        path = write_workflow_results_ods(result, path=results, spec=spec)
        assert Path(path).exists()

        header, data = _read_ods(results)
        assert len(data) == 2

        assert "run_id" in header
        assert "run_date" in header

        run_id_col = header.index("run_id")
        assert data[0][run_id_col] == data[1][run_id_col]

    def test_custom_run_id(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        workflow = tmp_path / "workflow.ods"
        results = tmp_path / "results.ods"
        _create_ods(workflow, ["name", "prompt", "client", "temperature"], [
            ["topic", "Name a famous invention in one sentence.", "litellm-mistral-small", 0.7],
        ], sheet="Steps")

        spec = load_workflow_ods(workflow, sheet="Steps", name="ods_run_id")
        ffai = _create_client()
        result = asyncio.run(ffai.workflow.execute_workflow(spec))

        write_workflow_results_ods(result, path=results, run_id="ods-batch-7")

        header, data = _read_ods(results)
        run_id_col = header.index("run_id")
        assert data[0][run_id_col] == "ods-batch-7"

    def test_passthrough_columns_in_output(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        workflow = tmp_path / "workflow.ods"
        results = tmp_path / "results.ods"
        _create_ods(workflow, ["name", "prompt", "client", "temperature", "Comments", "Priority"], [
            ["topic", "Name a famous invention in one sentence.", "litellm-mistral-small", 0.7, "Invention step", "High"],
        ])

        spec = load_workflow_ods(workflow, name="ods_passthrough")
        ffai = _create_client()
        result = asyncio.run(ffai.workflow.execute_workflow(spec))

        write_workflow_results_ods(result, path=results, spec=spec)

        header, data = _read_ods(results)

        comments_col = header.index("Comments")
        assert data[0][comments_col] == "Invention step"

        priority_col = header.index("Priority")
        assert data[0][priority_col] == "High"

    def test_first_sheet_used_by_default(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        workflow = tmp_path / "workflow.ods"
        _create_ods(workflow, ["name", "prompt", "temperature"], [
            ["topic", "Name a discovery.", 0.7],
        ], sheet="FirstSheet")

        spec = load_workflow_ods(workflow, name="ods_default_sheet")
        assert spec.prompts[0].name == "topic"

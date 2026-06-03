from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ffai.workflow.tabular import TabularLoadError
from ffai_workflow_adapters.ods import load_workflow_ods, write_workflow_results_ods


def _create_ods(path: Path, headers: list[str], rows: list[list], sheet_name: str | None = None) -> None:
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableCell, TableRow
    from odf.text import P

    doc = OpenDocumentSpreadsheet()
    table = Table(name=sheet_name or "Sheet1")

    def _text_cell(text: str) -> Any:
        cell = TableCell()
        p = P()
        p.addText(text)
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

    doc.spreadsheet.addElement(table)
    doc.save(str(path))


def _get_table_cls():
    from odf.table import Table
    return Table


def _text_cell(text: str) -> Any:
    from odf.table import TableCell
    from odf.text import P
    cell = TableCell()
    p = P()
    p.addText(text)
    cell.addElement(p)
    return cell


def _make_result():
    from dataclasses import dataclass, field

    from ffai.core.response_result import ResponseResult
    from ffai.core.usage import TokenUsage

    @dataclass
    class FakeWorkflowResult:
        results: dict = field(default_factory=dict)
        success_count: int = 0
        failed_count: int = 0
        skipped_count: int = 0
        aborted: bool = False
        aborted_count: int = 0
        spec_name: str = "test_workflow"

    return FakeWorkflowResult(
        success_count=2,
        results={
            "topic": ResponseResult(
                response="DNA discovered.",
                model="mistral-small-latest",
                status="success",
                usage=TokenUsage(input_tokens=41, output_tokens=40, total_tokens=81),
                duration_ms=1234.5,
            ),
            "explain": ResponseResult(
                response="It changed everything.",
                model="gpt-4o-mini",
                status="success",
                usage=TokenUsage(input_tokens=84, output_tokens=161, total_tokens=245),
                cost_usd=0.002,
                duration_ms=2345.6,
            ),
        },
    )


class TestLoadWorkflowOds:
    def test_basic_load(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        filepath = tmp_path / "workflow.ods"
        _create_ods(filepath, ["name", "prompt", "history"], [
            ["topic", "Name a discovery.", ""],
            ["explain", "Explain {{topic.response}}.", "topic"],
        ])

        spec = load_workflow_ods(filepath, name="test")
        assert spec.name == "test"
        assert len(spec.prompts) == 2
        assert spec.prompts[0].name == "topic"
        assert spec.prompts[1].history == ["topic"]

    def test_sheet_by_name(self, tmp_path: Path):
        from odf.opendocument import OpenDocumentSpreadsheet
        from odf.table import TableRow

        from ffai_workflow_adapters.config import reload_config

        reload_config()

        filepath = tmp_path / "multi.ods"
        doc = OpenDocumentSpreadsheet()

        other = _get_table_cls()(name="Other")
        row = TableRow()
        for v in ["x", "y"]:
            row.addElement(_text_cell(v))
        other.addElement(row)
        doc.spreadsheet.addElement(other)

        steps = _get_table_cls()(name="Steps")
        row = TableRow()
        for v in ["name", "prompt"]:
            row.addElement(_text_cell(v))
        steps.addElement(row)
        row2 = TableRow()
        for v in ["topic", "Go"]:
            row2.addElement(_text_cell(v))
        steps.addElement(row2)
        doc.spreadsheet.addElement(steps)

        doc.save(str(filepath))

        spec = load_workflow_ods(filepath, sheet="Steps", name="sheet_test")
        assert len(spec.prompts) == 1
        assert spec.prompts[0].name == "topic"

    def test_sheet_by_index(self, tmp_path: Path):
        from odf.opendocument import OpenDocumentSpreadsheet
        from odf.table import TableRow

        from ffai_workflow_adapters.config import reload_config

        reload_config()

        filepath = tmp_path / "multi.ods"
        doc = OpenDocumentSpreadsheet()

        skip = _get_table_cls()(name="Skip")
        row = TableRow()
        row.addElement(_text_cell("x"))
        skip.addElement(row)
        doc.spreadsheet.addElement(skip)

        steps = _get_table_cls()(name="Steps")
        row = TableRow()
        for v in ["name", "prompt"]:
            row.addElement(_text_cell(v))
        steps.addElement(row)
        row2 = TableRow()
        for v in ["topic", "Go"]:
            row2.addElement(_text_cell(v))
        steps.addElement(row2)
        doc.spreadsheet.addElement(steps)

        doc.save(str(filepath))

        spec = load_workflow_ods(filepath, sheet=1, name="index_test")
        assert len(spec.prompts) == 1

    def test_defaults_to_first_sheet(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        filepath = tmp_path / "workflow.ods"
        _create_ods(filepath, ["name", "prompt"], [["topic", "Go"]])

        spec = load_workflow_ods(filepath, name="default_sheet")
        assert spec.prompts[0].name == "topic"

    def test_input_field_mapping(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.ods.input_field_map = {"Task": "name", "Instructions": "prompt"}
        try:
            filepath = tmp_path / "workflow.ods"
            _create_ods(filepath, ["Task", "Instructions"], [["topic", "Go"]])

            spec = load_workflow_ods(filepath, name="mapped")
            assert spec.prompts[0].name == "topic"
            assert spec.prompts[0].prompt == "Go"
        finally:
            cfg.adapters.ods.input_field_map = {}

    def test_passthrough_columns(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.ods.input_field_map = {}
        cfg.adapters.ods.passthrough_columns = ["Comments"]
        try:
            filepath = tmp_path / "workflow.ods"
            _create_ods(filepath, ["name", "prompt", "Comments"], [
                ["topic", "Go", "Check refs"],
            ])

            spec = load_workflow_ods(filepath, name="pt_test")
            meta = getattr(spec, "_source_metadata", None)
            assert meta is not None
            assert meta["topic"]["Comments"] == "Check refs"
        finally:
            cfg.adapters.ods.input_field_map = {}
            cfg.adapters.ods.passthrough_columns = []

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(TabularLoadError, match="not found"):
            load_workflow_ods(tmp_path / "nonexistent.ods")

    def test_empty_file_raises(self, tmp_path: Path):
        filepath = tmp_path / "empty.ods"
        _create_ods(filepath, ["name", "prompt"], [])

        with pytest.raises(TabularLoadError, match="no data rows"):
            load_workflow_ods(filepath)

    def test_missing_required_columns_raises(self, tmp_path: Path):
        filepath = tmp_path / "bad.ods"
        _create_ods(filepath, ["name_only", "other"], [["step1", "value"]])

        with pytest.raises(TabularLoadError, match="missing required columns"):
            load_workflow_ods(filepath)

    def test_missing_odfpy_raises(self, tmp_path: Path):
        filepath = tmp_path / "workflow.ods"
        _create_ods(filepath, ["name", "prompt"], [["topic", "Go"]])

        with patch.dict("sys.modules", {"odf": None, "odf.opendocument": None}):
            with pytest.raises(TabularLoadError, match="odfpy is required"):
                load_workflow_ods(filepath)

    def test_warns_on_unrecognized_columns(self, tmp_path: Path, caplog):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.ods.input_field_map = {}
        cfg.adapters.ods.passthrough_columns = []
        try:
            filepath = tmp_path / "warn.ods"
            _create_ods(filepath, ["name", "prompt", "WackyColumn"], [["step1", "Go", "x"]])

            with caplog.at_level(logging.WARNING):
                spec = load_workflow_ods(filepath, name="warn_test")
            assert spec.prompts[0].name == "step1"
            assert "Unrecognized columns" in caplog.text
        finally:
            pass


class TestWriteWorkflowResultsOds:
    def test_write_new_file(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.ods.output_field_map)
        cfg.adapters.ods.output_field_map = {}
        try:
            filepath = tmp_path / "results.ods"
            result = _make_result()

            path = write_workflow_results_ods(result, path=filepath)
            assert Path(path).exists()
        finally:
            cfg.adapters.ods.output_field_map = saved

    def test_output_field_mapping(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.ods.output_field_map = {"step": "Task", "response": "Output"}
        try:
            filepath = tmp_path / "results.ods"
            result = _make_result()

            write_workflow_results_ods(result, path=filepath)

            doc = __import__("odf.opendocument", fromlist=["load"]).load(str(filepath))
            rows = doc.spreadsheet.getElementsByType(_get_table_cls())[0].getElementsByType(
                __import__("odf.table", fromlist=["TableRow"]).TableRow
            )
            header_cells = rows[0].getElementsByType(
                __import__("odf.table", fromlist=["TableCell"]).TableCell
            )
            from odf.text import P
            header = [str(c.getElementsByType(P)[0].firstChild.data) for c in header_cells if c.getElementsByType(P)]
            assert "Task" in header
            assert "Output" in header
            assert "step" not in header
        finally:
            cfg.adapters.ods.output_field_map = {}

    def test_no_path_raises(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved_path = cfg.adapters.ods.output_path
        cfg.adapters.ods.output_path = ""
        try:
            result = _make_result()
            with pytest.raises(ValueError, match="No output path"):
                write_workflow_results_ods(result)
        finally:
            cfg.adapters.ods.output_path = saved_path

    def test_missing_odfpy_raises(self, tmp_path: Path):
        result = _make_result()
        filepath = tmp_path / "results.ods"

        with patch.dict("sys.modules", {"odf": None, "odf.opendocument": None}):
            with pytest.raises(TabularLoadError, match="odfpy is required"):
                write_workflow_results_ods(result, path=filepath)

    def test_extra_output_columns(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved_map = dict(cfg.adapters.ods.output_field_map)
        saved_extra = dict(cfg.adapters.ods.extra_output_columns)
        cfg.adapters.ods.output_field_map = {}
        cfg.adapters.ods.extra_output_columns = {"batch": "test-run-01"}
        try:
            filepath = tmp_path / "results.ods"
            result = _make_result()

            write_workflow_results_ods(result, path=filepath)
            assert filepath.exists()
        finally:
            cfg.adapters.ods.output_field_map = saved_map
            cfg.adapters.ods.extra_output_columns = saved_extra


class TestOdsSpans:
    def test_load_emits_span(self, tmp_path: Path):
        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span

        filepath = tmp_path / "workflow.ods"
        _create_ods(filepath, ["name", "prompt"], [["topic", "hello"]])

        recorder = SpanRecorder()
        with adapter_span("test_parent", _recorder=recorder):
            load_workflow_ods(filepath, name="ods_test")

        load_spans = [s for s in recorder.spans if s.name == "ffai.adapters.ods.load"]
        assert len(load_spans) == 1
        span = load_spans[0]
        assert span.attributes["adapter"] == "default"
        assert str(filepath) in span.attributes["path"]
        assert span.attributes["columns.count"] == 2
        assert span.attributes["rows.count"] == 1
        assert span.attributes["workflow.name"] == "ods_test"

    def test_write_emits_span(self, tmp_path: Path):
        from dataclasses import dataclass, field

        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span

        @dataclass
        class FakeUsage:
            input_tokens: int = 10
            output_tokens: int = 20

        @dataclass
        class FakeStepResult:
            response: str = "ok"
            model: str = "m"
            status: str = "success"
            usage: Any = field(default_factory=FakeUsage)
            cost_usd: float = 0.001
            duration_ms: float = 100.0

        @dataclass
        class FakeWorkflowResult:
            results: dict = field(default_factory=lambda: {"step1": FakeStepResult()})
            spec_name: str = "test_wf"

        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.ods.output_field_map)
        cfg.adapters.ods.output_field_map = {}
        try:
            filepath = tmp_path / "results.ods"
            result = FakeWorkflowResult()

            recorder = SpanRecorder()
            with adapter_span("test_parent", _recorder=recorder):
                write_workflow_results_ods(result, path=filepath)

            write_spans = [s for s in recorder.spans if s.name == "ffai.adapters.ods.write"]
            assert len(write_spans) == 1
            span = write_spans[0]
            assert span.attributes["adapter"] == "default"
            assert str(filepath) in span.attributes["path"]
            assert span.attributes["records.count"] == 1
        finally:
            cfg.adapters.ods.output_field_map = saved

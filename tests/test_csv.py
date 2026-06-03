from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from ffai.workflow.tabular import TabularLoadError
from ffai_workflow_adapters.csv_adapter import (
    load_workflow_csv,
    load_workflow_tsv,
    write_workflow_results_csv,
    write_workflow_results_tsv,
)


def _create_csv(path: Path, headers: list[str], rows: list[list], delimiter: str = ",") -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)


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


class TestLoadWorkflowCsv:
    def test_basic_load(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        filepath = tmp_path / "workflow.csv"
        _create_csv(filepath, ["name", "prompt", "history"], [
            ["topic", "Name a discovery."],
            ["explain", "Explain {{topic.response}}.", "topic"],
        ])

        spec = load_workflow_csv(filepath, name="test")
        assert spec.name == "test"
        assert len(spec.prompts) == 2
        assert spec.prompts[0].name == "topic"
        assert spec.prompts[1].history == ["topic"]

    def test_tsv_load(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        filepath = tmp_path / "workflow.tsv"
        _create_csv(filepath, ["name", "prompt"], [["topic", "Go"]], delimiter="\t")

        spec = load_workflow_tsv(filepath, name="tsv_test")
        assert spec.prompts[0].name == "topic"

    def test_tsv_equals_csv_with_tab(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        filepath = tmp_path / "workflow.tsv"
        _create_csv(filepath, ["name", "prompt"], [["step1", "Go"]], delimiter="\t")

        spec_tsv = load_workflow_tsv(filepath, name="a")
        spec_csv = load_workflow_csv(filepath, delimiter="\t", name="b")

        assert len(spec_tsv.prompts) == len(spec_csv.prompts)
        assert spec_tsv.prompts[0].name == spec_csv.prompts[0].name

    def test_with_defaults(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        filepath = tmp_path / "workflow.csv"
        _create_csv(filepath, ["name", "prompt"], [["step1", "Go"]])

        spec = load_workflow_csv(filepath, defaults={"temperature": 0.5, "max_tokens": 200})
        assert spec.defaults.temperature == 0.5

    def test_input_field_mapping(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.csv_adapter.input_field_map = {"Task": "name", "Instructions": "prompt"}
        try:
            filepath = tmp_path / "workflow.csv"
            _create_csv(filepath, ["Task", "Instructions"], [["topic", "Go"]])

            spec = load_workflow_csv(filepath, name="mapped")
            assert spec.prompts[0].name == "topic"
            assert spec.prompts[0].prompt == "Go"
        finally:
            cfg.adapters.csv_adapter.input_field_map = {}

    def test_passthrough_columns(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.csv_adapter.input_field_map = {}
        cfg.adapters.csv_adapter.passthrough_columns = ["Comments", "Priority"]
        try:
            filepath = tmp_path / "workflow.csv"
            _create_csv(filepath, ["name", "prompt", "Comments", "Priority"], [
                ["topic", "Go", "Check refs", "High"],
            ])

            spec = load_workflow_csv(filepath, name="pt_test")
            meta = getattr(spec, "_source_metadata", None)
            assert meta is not None
            assert meta["topic"]["Comments"] == "Check refs"
            assert meta["topic"]["Priority"] == "High"
        finally:
            cfg.adapters.csv_adapter.input_field_map = {}
            cfg.adapters.csv_adapter.passthrough_columns = []

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(TabularLoadError, match="not found"):
            load_workflow_csv(tmp_path / "nonexistent.csv")

    def test_empty_file_raises(self, tmp_path: Path):
        filepath = tmp_path / "empty.csv"
        _create_csv(filepath, ["name", "prompt"], [])

        with pytest.raises(TabularLoadError, match="no data rows"):
            load_workflow_csv(filepath)

    def test_missing_required_columns_raises(self, tmp_path: Path):
        filepath = tmp_path / "bad.csv"
        _create_csv(filepath, ["name_only", "other"], [["step1", "value"]])

        with pytest.raises(TabularLoadError, match="missing required columns"):
            load_workflow_csv(filepath)

    def test_invalid_temperature_raises(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        filepath = tmp_path / "bad.csv"
        _create_csv(filepath, ["name", "prompt", "temperature"], [["step1", "Go", "hot"]])

        with pytest.raises(TabularLoadError, match="temperature must be a number"):
            load_workflow_csv(filepath)

    def test_warns_on_unrecognized_columns(self, tmp_path: Path, caplog):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.csv_adapter.input_field_map = {}
        cfg.adapters.csv_adapter.passthrough_columns = []
        try:
            filepath = tmp_path / "warn.csv"
            _create_csv(filepath, ["name", "prompt", "WackyColumn"], [["step1", "Go", "x"]])

            with caplog.at_level(logging.WARNING):
                spec = load_workflow_csv(filepath, name="warn_test")
            assert spec.prompts[0].name == "step1"
            assert "Unrecognized columns" in caplog.text
            assert "WackyColumn" in caplog.text
        finally:
            pass


class TestWriteWorkflowResultsCsv:
    def test_write_new_file(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.csv_adapter.output_field_map)
        cfg.adapters.csv_adapter.output_field_map = {}
        try:
            filepath = tmp_path / "results.csv"
            result = _make_result()

            path = write_workflow_results_csv(result, path=filepath)
            assert Path(path).exists()

            with filepath.open(encoding="utf-8") as f:
                rows = list(csv.reader(f))
            assert rows[0][0] == "workflow"
            assert rows[0][1] == "step"
            assert len(rows) == 3
            assert rows[1][1] == "topic"
            assert rows[2][1] == "explain"
        finally:
            cfg.adapters.csv_adapter.output_field_map = saved

    def test_append_to_existing_file(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.csv_adapter.output_field_map)
        cfg.adapters.csv_adapter.output_field_map = {}
        try:
            filepath = tmp_path / "results.csv"
            result = _make_result()

            write_workflow_results_csv(result, path=filepath)
            write_workflow_results_csv(result, path=filepath)

            with filepath.open(encoding="utf-8") as f:
                rows = list(csv.reader(f))
            assert len(rows) == 5
            assert rows[0][1] == "step"
            assert rows[3][1] == "topic"
        finally:
            cfg.adapters.csv_adapter.output_field_map = saved

    def test_output_field_mapping(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.csv_adapter.output_field_map = {"step": "Task", "response": "Output"}
        try:
            filepath = tmp_path / "results.csv"
            result = _make_result()

            write_workflow_results_csv(result, path=filepath)

            with filepath.open(encoding="utf-8") as f:
                rows = list(csv.reader(f))
            header = rows[0]
            assert "Task" in header
            assert "Output" in header
            assert "step" not in header
        finally:
            cfg.adapters.csv_adapter.output_field_map = {}

    def test_config_output_path(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved_map = dict(cfg.adapters.csv_adapter.output_field_map)
        saved_path = cfg.adapters.csv_adapter.output_path
        cfg.adapters.csv_adapter.output_field_map = {}
        cfg.adapters.csv_adapter.output_path = str(tmp_path / "config_results.csv")
        try:
            result = _make_result()
            path = write_workflow_results_csv(result)
            assert Path(path).exists()
        finally:
            cfg.adapters.csv_adapter.output_field_map = saved_map
            cfg.adapters.csv_adapter.output_path = saved_path

    def test_no_path_raises(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved_path = cfg.adapters.csv_adapter.output_path
        cfg.adapters.csv_adapter.output_path = ""
        try:
            result = _make_result()
            with pytest.raises(ValueError, match="No output path"):
                write_workflow_results_csv(result)
        finally:
            cfg.adapters.csv_adapter.output_path = saved_path

    def test_write_tsv(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.csv_adapter.output_field_map)
        cfg.adapters.csv_adapter.output_field_map = {}
        try:
            filepath = tmp_path / "results.tsv"
            result = _make_result()

            path = write_workflow_results_tsv(result, path=filepath)
            assert Path(path).exists()

            with filepath.open(encoding="utf-8") as f:
                rows = list(csv.reader(f, delimiter="\t"))
            assert rows[0][1] == "step"
            assert len(rows) == 3
        finally:
            cfg.adapters.csv_adapter.output_field_map = saved

    def test_extra_output_columns(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved_map = dict(cfg.adapters.csv_adapter.output_field_map)
        saved_extra = dict(cfg.adapters.csv_adapter.extra_output_columns)
        cfg.adapters.csv_adapter.output_field_map = {}
        cfg.adapters.csv_adapter.extra_output_columns = {"batch": "test-run-01"}
        try:
            filepath = tmp_path / "results.csv"
            result = _make_result()

            write_workflow_results_csv(result, path=filepath)

            with filepath.open(encoding="utf-8") as f:
                rows = list(csv.reader(f))
            header = rows[0]
            assert "batch" in header
            batch_col = header.index("batch")
            assert rows[1][batch_col] == "test-run-01"
        finally:
            cfg.adapters.csv_adapter.output_field_map = saved_map
            cfg.adapters.csv_adapter.extra_output_columns = saved_extra

    def test_passthrough_columns(self, tmp_path: Path):
        from ffai_workflow_adapters.config import reload_config
        from ffai.workflow.tabular import load_workflow_rows

        cfg = reload_config()
        saved_map = dict(cfg.adapters.csv_adapter.output_field_map)
        saved_pt = list(cfg.adapters.csv_adapter.passthrough_columns)
        cfg.adapters.csv_adapter.output_field_map = {}
        cfg.adapters.csv_adapter.passthrough_columns = ["Notes"]
        try:
            filepath = tmp_path / "results.csv"
            result = _make_result()

            spec = load_workflow_rows([{"name": "topic", "prompt": "Go"}], name="test")
            object.__setattr__(spec, "_source_metadata", {"topic": {"Notes": "see above"}})

            write_workflow_results_csv(result, path=filepath, spec=spec)

            with filepath.open(encoding="utf-8") as f:
                rows = list(csv.reader(f))
            header = rows[0]
            assert "Notes" in header
            notes_col = header.index("Notes")
            assert rows[1][notes_col] == "see above"
        finally:
            cfg.adapters.csv_adapter.output_field_map = saved_map
            cfg.adapters.csv_adapter.passthrough_columns = saved_pt

    def test_run_id_auto_generated(self, tmp_path: Path):
        import re
        from ffai_workflow_adapters.config import reload_config

        cfg = reload_config()
        saved_map = dict(cfg.adapters.csv_adapter.output_field_map)
        saved_extra = dict(cfg.adapters.csv_adapter.extra_output_columns)
        cfg.adapters.csv_adapter.output_field_map = {}
        cfg.adapters.csv_adapter.extra_output_columns = {"run_id": "{{run_id}}"}
        try:
            filepath = tmp_path / "results.csv"
            result = _make_result()

            write_workflow_results_csv(result, path=filepath)

            with filepath.open(encoding="utf-8") as f:
                rows = list(csv.reader(f))
            header = rows[0]
            run_id_col = header.index("run_id")
            assert rows[1][run_id_col] == rows[2][run_id_col]
            assert re.match(r"\d{8}-\d{6}", str(rows[1][run_id_col]))
        finally:
            cfg.adapters.csv_adapter.output_field_map = saved_map
            cfg.adapters.csv_adapter.extra_output_columns = saved_extra


class TestCsvSpans:
    def test_load_emits_span(self, tmp_path: Path):
        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span

        filepath = tmp_path / "workflow.csv"
        _create_csv(filepath, ["name", "prompt"], [["topic", "hello"]])

        recorder = SpanRecorder()
        with adapter_span("test_parent", _recorder=recorder):
            spec = load_workflow_csv(filepath, name="csv_test")

        load_spans = [s for s in recorder.spans if s.name == "ffai.adapters.csv.load"]
        assert len(load_spans) == 1
        span = load_spans[0]
        assert span.attributes["adapter"] == "default"
        assert str(filepath) in span.attributes["path"]
        assert span.attributes["delimiter"] == ","
        assert span.attributes["columns.count"] == 2
        assert span.attributes["rows.count"] == 1
        assert span.attributes["workflow.name"] == "csv_test"

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
        saved = dict(cfg.adapters.csv_adapter.output_field_map)
        cfg.adapters.csv_adapter.output_field_map = {}
        try:
            filepath = tmp_path / "results.csv"
            result = FakeWorkflowResult()

            recorder = SpanRecorder()
            with adapter_span("test_parent", _recorder=recorder):
                out = write_workflow_results_csv(result, path=filepath)

            write_spans = [s for s in recorder.spans if s.name == "ffai.adapters.csv.write"]
            assert len(write_spans) == 1
            span = write_spans[0]
            assert span.attributes["adapter"] == "default"
            assert str(filepath) in span.attributes["path"]
            assert span.attributes["records.count"] == 1
        finally:
            cfg.adapters.csv_adapter.output_field_map = saved

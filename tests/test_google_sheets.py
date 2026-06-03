from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ffai.workflow.tabular import TabularLoadError
from ffai_workflow_adapters.google_sheets import (
    _reset_caller,
    load_workflow_google_sheets,
    write_workflow_results_google_sheets,
)


def _make_result():
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


def _mock_gspread(raw_records=None):
    mock_gspread = MagicMock()
    mock_gc = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_ws = MagicMock()
    mock_ws.get_all_records.return_value = raw_records or []
    mock_ws.title = "Results"
    mock_spreadsheet.sheet1 = mock_ws
    mock_spreadsheet.worksheet.return_value = mock_ws
    mock_spreadsheet.get_worksheet.return_value = mock_ws
    mock_spreadsheet.worksheets.return_value = [mock_ws]
    mock_spreadsheet.add_worksheet.return_value = mock_ws
    mock_gc.open_by_key.return_value = mock_spreadsheet
    mock_gspread.service_account.return_value = mock_gc
    return mock_gspread, mock_gc, mock_spreadsheet, mock_ws


class TestLoadWorkflowGoogleSheets:
    def setup_method(self):
        from ffai_workflow_adapters.config import reload_config
        reload_config()
        _reset_caller()

    def test_basic_load(self, tmp_path):
        import json
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"type": "service_account"}))

        mock_gs, _, _, _ = _mock_gspread([
            {"name": "topic", "prompt": "Go"},
            {"name": "explain", "prompt": "Explain.", "history": "topic"},
        ])

        with patch.dict("sys.modules", {"gspread": mock_gs}):
            spec = load_workflow_google_sheets(
                "ssid123",
                credentials_file=str(creds),
                name="gs_test",
            )

        assert spec.name == "gs_test"
        assert len(spec.prompts) == 2
        assert spec.prompts[0].name == "topic"
        assert spec.prompts[1].history == ["topic"]

    def test_worksheet_by_name(self, tmp_path):
        import json
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"type": "service_account"}))

        mock_gs, _, _, mock_ws = _mock_gspread([
            {"name": "topic", "prompt": "Go"},
        ])

        with patch.dict("sys.modules", {"gspread": mock_gs}):
            spec = load_workflow_google_sheets(
                "ssid123",
                worksheet="Steps",
                credentials_file=str(creds),
                name="ws_test",
            )

        assert len(spec.prompts) == 1

    def test_worksheet_by_index(self, tmp_path):
        import json
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"type": "service_account"}))

        mock_gs, _, _, _ = _mock_gspread([
            {"name": "topic", "prompt": "Go"},
        ])

        with patch.dict("sys.modules", {"gspread": mock_gs}):
            spec = load_workflow_google_sheets(
                "ssid123",
                worksheet=0,
                credentials_file=str(creds),
            )

        assert spec.prompts[0].name == "topic"

    def test_defaults_to_first_worksheet(self, tmp_path):
        import json
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"type": "service_account"}))

        mock_gs, _, _, mock_ws = _mock_gspread([
            {"name": "topic", "prompt": "Go"},
        ])

        with patch.dict("sys.modules", {"gspread": mock_gs}):
            spec = load_workflow_google_sheets(
                "ssid123",
                credentials_file=str(creds),
            )

        assert spec.prompts[0].name == "topic"

    def test_input_field_mapping(self, tmp_path):
        import json
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.google_sheets.input_field_map = {"Task": "name", "Instructions": "prompt"}
        try:
            creds = tmp_path / "creds.json"
            creds.write_text(json.dumps({"type": "service_account"}))

            mock_gs, _, _, _ = _mock_gspread([
                {"Task": "topic", "Instructions": "Go"},
            ])

            with patch.dict("sys.modules", {"gspread": mock_gs}):
                spec = load_workflow_google_sheets(
                    "ssid123",
                    credentials_file=str(creds),
                    name="mapped",
                )

            assert spec.prompts[0].name == "topic"
            assert spec.prompts[0].prompt == "Go"
        finally:
            cfg.adapters.google_sheets.input_field_map = {}

    def test_passthrough_columns(self, tmp_path):
        import json
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.google_sheets.input_field_map = {}
        cfg.adapters.google_sheets.passthrough_columns = ["Comments"]
        try:
            creds = tmp_path / "creds.json"
            creds.write_text(json.dumps({"type": "service_account"}))

            mock_gs, _, _, _ = _mock_gspread([
                {"name": "topic", "prompt": "Go", "Comments": "Check refs"},
            ])

            with patch.dict("sys.modules", {"gspread": mock_gs}):
                spec = load_workflow_google_sheets(
                    "ssid123",
                    credentials_file=str(creds),
                )

            meta = getattr(spec, "_source_metadata", None)
            assert meta is not None
            assert meta["topic"]["Comments"] == "Check refs"
        finally:
            cfg.adapters.google_sheets.input_field_map = {}
            cfg.adapters.google_sheets.passthrough_columns = []

    def test_missing_gspread_raises(self, tmp_path):
        import json
        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"type": "service_account"}))

        with patch.dict("sys.modules", {"gspread": None}):
            with pytest.raises(TabularLoadError, match="gspread is required"):
                load_workflow_google_sheets(
                    "ssid123",
                    credentials_file=str(creds),
                )

    def test_missing_credentials_raises(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = cfg.adapters.google_sheets.credentials_env
        cfg.adapters.google_sheets.credentials_env = "NONEXISTENT_VAR_12345"
        try:
            mock_gs, _, _, _ = _mock_gspread()
            with patch.dict("sys.modules", {"gspread": mock_gs}):
                with pytest.raises(TabularLoadError, match="credentials not provided"):
                    load_workflow_google_sheets("ssid123")
        finally:
            cfg.adapters.google_sheets.credentials_env = saved

    def test_empty_spreadsheet_raises(self, tmp_path):
        import json
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"type": "service_account"}))

        mock_gs, _, _, _ = _mock_gspread([])

        with patch.dict("sys.modules", {"gspread": mock_gs}):
            with pytest.raises(TabularLoadError, match="no records"):
                load_workflow_google_sheets(
                    "ssid123",
                    credentials_file=str(creds),
                )

    def test_missing_required_columns_raises(self, tmp_path):
        import json
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"type": "service_account"}))

        mock_gs, _, _, _ = _mock_gspread([
            {"name_only": "topic", "other": "val"},
        ])

        with patch.dict("sys.modules", {"gspread": mock_gs}):
            with pytest.raises(TabularLoadError, match="missing required columns"):
                load_workflow_google_sheets(
                    "ssid123",
                    credentials_file=str(creds),
                )

    def test_load_emits_span(self, tmp_path):
        import json
        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        creds = tmp_path / "creds.json"
        creds.write_text(json.dumps({"type": "service_account"}))

        mock_gs, _, _, _ = _mock_gspread([
            {"name": "topic", "prompt": "Go"},
        ])

        recorder = SpanRecorder()
        with patch.dict("sys.modules", {"gspread": mock_gs}):
            with adapter_span("test_parent", _recorder=recorder):
                load_workflow_google_sheets(
                    "ssid123",
                    credentials_file=str(creds),
                    name="span_test",
                )

        load_spans = [s for s in recorder.spans if s.name == "ffai.adapters.google_sheets.load"]
        assert len(load_spans) == 1
        span = load_spans[0]
        assert span.attributes["adapter"] == "default"
        assert span.attributes["spreadsheet_id"] == "ssid123"
        assert span.attributes["rows.count"] == 1
        assert span.attributes["workflow.name"] == "span_test"


class TestWriteWorkflowResultsGoogleSheets:
    def setup_method(self):
        from ffai_workflow_adapters.config import reload_config
        reload_config()
        _reset_caller()

    def test_write_appends_rows(self, tmp_path):
        import json
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.google_sheets.output_field_map)
        cfg.adapters.google_sheets.output_field_map = {}
        try:
            creds = tmp_path / "creds.json"
            creds.write_text(json.dumps({"type": "service_account"}))

            mock_gs, _, mock_ss, mock_ws = _mock_gspread()
            result = _make_result()

            with patch.dict("sys.modules", {"gspread": mock_gs}):
                rows = write_workflow_results_google_sheets(
                    "ssid123",
                    result,
                    credentials_file=str(creds),
                )

            assert len(rows) == 2
            mock_ws.append_rows.assert_called_once()
        finally:
            cfg.adapters.google_sheets.output_field_map = saved

    def test_creates_worksheet_if_not_exists(self, tmp_path):
        import json
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.google_sheets.output_field_map)
        cfg.adapters.google_sheets.output_field_map = {}
        try:
            creds = tmp_path / "creds.json"
            creds.write_text(json.dumps({"type": "service_account"}))

            mock_gs, _, mock_ss, mock_ws = _mock_gspread()
            mock_ss.worksheets.return_value = []
            new_ws = MagicMock()
            new_ws.title = "Results"
            mock_ss.add_worksheet.return_value = new_ws

            result = _make_result()

            with patch.dict("sys.modules", {"gspread": mock_gs}):
                write_workflow_results_google_sheets(
                    "ssid123",
                    result,
                    credentials_file=str(creds),
                )

            mock_ss.add_worksheet.assert_called_once()
        finally:
            cfg.adapters.google_sheets.output_field_map = saved

    def test_applies_output_field_map(self, tmp_path):
        import json
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.google_sheets.output_field_map = {"step": "Task", "response": "Output"}
        try:
            creds = tmp_path / "creds.json"
            creds.write_text(json.dumps({"type": "service_account"}))

            mock_gs, _, _, mock_ws = _mock_gspread()

            @dataclass
            class FakeStepResult:
                response: str = "ok"
                model: str = "m"
                status: str = "success"
                usage: Any = None
                cost_usd: float | None = None
                duration_ms: float | None = None

            @dataclass
            class FakeResult:
                results: dict = field(default_factory=lambda: {"s1": FakeStepResult()})
                spec_name: str = "t"

            result = FakeResult()

            with patch.dict("sys.modules", {"gspread": mock_gs}):
                write_workflow_results_google_sheets(
                    "ssid123",
                    result,
                    credentials_file=str(creds),
                )

            call_args = mock_ws.append_rows.call_args
            appended = call_args[0][0]
            assert len(appended) == 1
            assert appended[0][0] == "t"
            assert appended[0][1] == "s1"
        finally:
            cfg.adapters.google_sheets.output_field_map = {}

    def test_write_emits_span(self, tmp_path):
        import json
        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.google_sheets.output_field_map)
        cfg.adapters.google_sheets.output_field_map = {}
        try:
            creds = tmp_path / "creds.json"
            creds.write_text(json.dumps({"type": "service_account"}))

            mock_gs, _, _, mock_ws = _mock_gspread()

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

            result = FakeWorkflowResult()

            recorder = SpanRecorder()
            with patch.dict("sys.modules", {"gspread": mock_gs}):
                with adapter_span("test_parent", _recorder=recorder):
                    write_workflow_results_google_sheets(
                        "ssid123",
                        result,
                        credentials_file=str(creds),
                    )

            write_spans = [s for s in recorder.spans if s.name == "ffai.adapters.google_sheets.write"]
            assert len(write_spans) == 1
            span = write_spans[0]
            assert span.attributes["adapter"] == "default"
            assert span.attributes["records.count"] == 1
        finally:
            cfg.adapters.google_sheets.output_field_map = saved

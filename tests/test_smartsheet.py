from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ffai.workflow.tabular import TabularLoadError
from ffai_workflow_adapters.smartsheet import (
    _reset_caller,
    _resolve_access_token,
    _rows_to_records,
    load_workflow_smartsheet,
    write_workflow_results_smartsheet,
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


def _mock_smartsheet(raw_records=None):
    mock_smart_module = MagicMock()
    mock_sheet = MagicMock()

    if raw_records:
        col_titles = list(dict.fromkeys(k for r in raw_records for k in r))
    else:
        col_titles = ["name", "prompt"]

    mock_columns = []
    col_id_map = {}
    for i, title in enumerate(col_titles):
        col = MagicMock()
        col.id = 100 + i
        col.title = title
        mock_columns.append(col)
        col_id_map[title] = col.id

    mock_sheet.columns = mock_columns
    mock_sheet.total_row_count = len(raw_records) if raw_records else 0

    mock_rows = []
    for record in raw_records or []:
        mock_row = MagicMock()
        mock_cells = []
        for title, value in record.items():
            cell = MagicMock()
            cell.column_id = col_id_map.get(title, 0)
            cell.value = value
            mock_cells.append(cell)
        mock_row.cells = mock_cells
        mock_rows.append(mock_row)

    mock_sheet.rows = mock_rows

    mock_instance = MagicMock()
    mock_instance.Sheets.get_sheet.return_value = mock_sheet
    mock_instance.Sheets.add_rows.return_value = MagicMock(data=[])
    mock_instance.Sheets.add_columns.return_value = MagicMock(data=[])
    mock_smart_module.Smartsheet.return_value = mock_instance
    mock_smart_module.models.Row.return_value = MagicMock(cells=[])
    mock_smart_module.models.Cell.return_value = MagicMock()
    mock_smart_module.models.Column.return_value = MagicMock()

    return mock_smart_module, mock_sheet, mock_instance


class TestResolveAccessToken:
    def test_explicit_token(self):
        token = _resolve_access_token(access_token="tok123")
        assert token == "tok123"

    def test_env_var_token(self):
        with patch.dict("os.environ", {"SMARTSHEET_ACCESS_TOKEN": "env_tok"}):
            token = _resolve_access_token()
        assert token == "env_tok"

    def test_custom_env_var(self):
        with patch.dict("os.environ", {"MY_TOKEN": "custom_tok"}):
            token = _resolve_access_token(access_token_env="MY_TOKEN")
        assert token == "custom_tok"

    def test_missing_token_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(TabularLoadError, match="access token not provided"):
                _resolve_access_token(cfg_access_token_env="NONEXISTENT_VAR_999")


class TestRowsToRecords:
    def test_basic_translation(self):
        mock_sheet = MagicMock()
        col_a = MagicMock(id=100, title="name")
        col_b = MagicMock(id=101, title="prompt")
        mock_sheet.columns = [col_a, col_b]

        row = MagicMock()
        cell_a = MagicMock(column_id=100, value="step1")
        cell_b = MagicMock(column_id=101, value="Go")
        row.cells = [cell_a, cell_b]
        mock_sheet.rows = [row]

        records = _rows_to_records(mock_sheet)
        assert len(records) == 1
        assert records[0] == {"name": "step1", "prompt": "Go"}

    def test_skips_all_none_rows(self):
        mock_sheet = MagicMock()
        col_a = MagicMock(id=100, title="name")
        mock_sheet.columns = [col_a]

        row = MagicMock()
        cell = MagicMock(column_id=100, value=None)
        row.cells = [cell]
        mock_sheet.rows = [row]

        records = _rows_to_records(mock_sheet)
        assert len(records) == 0

    def test_empty_sheet(self):
        mock_sheet = MagicMock()
        mock_sheet.columns = []
        mock_sheet.rows = []
        records = _rows_to_records(mock_sheet)
        assert records == []

    def test_missing_column_id(self):
        mock_sheet = MagicMock()
        col_a = MagicMock(id=100, title="name")
        mock_sheet.columns = [col_a]

        row = MagicMock()
        cell = MagicMock(column_id=999, value="orphan")
        row.cells = [cell]
        mock_sheet.rows = [row]

        records = _rows_to_records(mock_sheet)
        assert len(records) == 0


class TestLoadWorkflowSmartsheet:
    def setup_method(self):
        from ffai_workflow_adapters.config import reload_config
        reload_config()
        _reset_caller()

    def test_basic_load(self):
        mock_mod, _, _ = _mock_smartsheet([
            {"name": "topic", "prompt": "Go"},
            {"name": "explain", "prompt": "Explain.", "history": "topic"},
        ])

        with patch.dict("sys.modules", {"smartsheet": mock_mod}):
            spec = load_workflow_smartsheet(
                12345,
                access_token="tok",
                name="ss_test",
            )

        assert spec.name == "ss_test"
        assert len(spec.prompts) == 2
        assert spec.prompts[0].name == "topic"
        assert spec.prompts[1].history == ["topic"]

    def test_input_field_mapping(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.smartsheet.input_field_map = {"Task": "name", "Instructions": "prompt"}
        try:
            mock_mod, _, _ = _mock_smartsheet([
                {"Task": "topic", "Instructions": "Go"},
            ])

            with patch.dict("sys.modules", {"smartsheet": mock_mod}):
                spec = load_workflow_smartsheet(
                    12345,
                    access_token="tok",
                    name="mapped",
                )

            assert spec.prompts[0].name == "topic"
            assert spec.prompts[0].prompt == "Go"
        finally:
            cfg.adapters.smartsheet.input_field_map = {}

    def test_passthrough_columns(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.smartsheet.input_field_map = {}
        cfg.adapters.smartsheet.passthrough_columns = ["Comments"]
        try:
            mock_mod, _, _ = _mock_smartsheet([
                {"name": "topic", "prompt": "Go", "Comments": "Check refs"},
            ])

            with patch.dict("sys.modules", {"smartsheet": mock_mod}):
                spec = load_workflow_smartsheet(
                    12345,
                    access_token="tok",
                )

            meta = getattr(spec, "_source_metadata", None)
            assert meta is not None
            assert meta["topic"]["Comments"] == "Check refs"
        finally:
            cfg.adapters.smartsheet.input_field_map = {}
            cfg.adapters.smartsheet.passthrough_columns = []

    def test_missing_sdk_raises(self):
        with patch.dict("sys.modules", {"smartsheet": None}):
            with pytest.raises(TabularLoadError, match="smartsheet-python-sdk is required"):
                load_workflow_smartsheet(12345, access_token="tok")

    def test_missing_access_token_raises(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = cfg.adapters.smartsheet.access_token_env
        cfg.adapters.smartsheet.access_token_env = "NONEXISTENT_VAR_12345"
        try:
            mock_mod, _, _ = _mock_smartsheet()
            with patch.dict("sys.modules", {"smartsheet": mock_mod}):
                with pytest.raises(TabularLoadError, match="access token not provided"):
                    load_workflow_smartsheet(12345)
        finally:
            cfg.adapters.smartsheet.access_token_env = saved

    def test_empty_sheet_raises(self):
        mock_mod, _, _ = _mock_smartsheet([])

        with patch.dict("sys.modules", {"smartsheet": mock_mod}):
            with pytest.raises(TabularLoadError, match="no records"):
                load_workflow_smartsheet(12345, access_token="tok")

    def test_missing_required_columns_raises(self):
        mock_mod, _, _ = _mock_smartsheet([
            {"name_only": "topic", "other": "val"},
        ])

        with patch.dict("sys.modules", {"smartsheet": mock_mod}):
            with pytest.raises(TabularLoadError, match="missing required columns"):
                load_workflow_smartsheet(12345, access_token="tok")

    def test_load_emits_span(self):
        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span
        from ffai_workflow_adapters.config import reload_config
        reload_config()

        mock_mod, _, _ = _mock_smartsheet([
            {"name": "topic", "prompt": "Go"},
        ])

        recorder = SpanRecorder()
        with patch.dict("sys.modules", {"smartsheet": mock_mod}):
            with adapter_span("test_parent", _recorder=recorder):
                load_workflow_smartsheet(
                    12345,
                    access_token="tok",
                    name="span_test",
                )

        load_spans = [s for s in recorder.spans if s.name == "ffai.adapters.smartsheet.load"]
        assert len(load_spans) == 1
        span = load_spans[0]
        assert span.attributes["adapter"] == "default"
        assert span.attributes["sheet_id"] == "12345"
        assert span.attributes["rows.count"] == 1
        assert span.attributes["workflow.name"] == "span_test"


class TestWriteWorkflowResultsSmartsheet:
    def setup_method(self):
        from ffai_workflow_adapters.config import reload_config
        reload_config()
        _reset_caller()

    def test_basic_write(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.smartsheet.output_field_map)
        cfg.adapters.smartsheet.output_field_map = {}
        try:
            mock_mod, _, mock_instance = _mock_smartsheet()
            result = _make_result()

            with patch.dict("sys.modules", {"smartsheet": mock_mod}):
                rows = write_workflow_results_smartsheet(
                    99999,
                    result,
                    access_token="tok",
                )

            assert len(rows) == 2
            mock_instance.Sheets.add_rows.assert_called_once()
        finally:
            cfg.adapters.smartsheet.output_field_map = saved

    def test_creates_columns_for_empty_sheet(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.smartsheet.output_field_map)
        cfg.adapters.smartsheet.output_field_map = {}
        try:
            mock_mod, _, mock_instance = _mock_smartsheet()
            empty_sheet = MagicMock()
            empty_sheet.columns = []
            empty_sheet.rows = []
            mock_instance.Sheets.get_sheet.return_value = empty_sheet

            populated_sheet = MagicMock()
            col_wf = MagicMock(id=200, title="workflow")
            col_step = MagicMock(id=201, title="step")
            populated_sheet.columns = [col_wf, col_step]
            mock_instance.Sheets.add_columns.return_value = MagicMock(data=[])

            def get_sheet_side_effect(sid):
                if mock_instance.Sheets.add_columns.called:
                    return populated_sheet
                return empty_sheet

            mock_instance.Sheets.get_sheet.side_effect = get_sheet_side_effect
            result = _make_result()

            with patch.dict("sys.modules", {"smartsheet": mock_mod}):
                rows = write_workflow_results_smartsheet(
                    99999,
                    result,
                    access_token="tok",
                )

            mock_instance.Sheets.add_columns.assert_called_once()
            assert len(rows) == 2
        finally:
            cfg.adapters.smartsheet.output_field_map = saved

    def test_applies_output_field_map(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.smartsheet.output_field_map = {"step": "Task", "response": "Output"}
        try:
            mock_mod, _, _ = _mock_smartsheet()

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

            with patch.dict("sys.modules", {"smartsheet": mock_mod}):
                rows = write_workflow_results_smartsheet(
                    99999,
                    result,
                    access_token="tok",
                )

            assert len(rows) == 1
        finally:
            cfg.adapters.smartsheet.output_field_map = {}

    def test_write_without_spec(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.smartsheet.output_field_map)
        cfg.adapters.smartsheet.output_field_map = {}
        try:
            mock_mod, _, _ = _mock_smartsheet()
            result = _make_result()

            with patch.dict("sys.modules", {"smartsheet": mock_mod}):
                rows = write_workflow_results_smartsheet(
                    99999,
                    result,
                    access_token="tok",
                    spec=None,
                )

            assert len(rows) == 2
        finally:
            cfg.adapters.smartsheet.output_field_map = saved

    def test_missing_sdk_raises(self):
        with patch.dict("sys.modules", {"smartsheet": None}):
            with pytest.raises(TabularLoadError, match="smartsheet-python-sdk is required"):
                write_workflow_results_smartsheet(99999, _make_result(), access_token="tok")

    def test_missing_access_token_raises(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = cfg.adapters.smartsheet.access_token_env
        cfg.adapters.smartsheet.access_token_env = "NONEXISTENT_VAR_54321"
        try:
            mock_mod, _, _ = _mock_smartsheet()
            with patch.dict("sys.modules", {"smartsheet": mock_mod}):
                with pytest.raises(TabularLoadError, match="access token not provided"):
                    write_workflow_results_smartsheet(99999, _make_result())
        finally:
            cfg.adapters.smartsheet.access_token_env = saved

    def test_write_emits_span(self):
        from ffai_workflow_adapters._spans import SpanRecorder, adapter_span
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.smartsheet.output_field_map)
        cfg.adapters.smartsheet.output_field_map = {}
        try:
            mock_mod, _, _ = _mock_smartsheet()

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
            with patch.dict("sys.modules", {"smartsheet": mock_mod}):
                with adapter_span("test_parent", _recorder=recorder):
                    write_workflow_results_smartsheet(
                        99999,
                        result,
                        access_token="tok",
                    )

            write_spans = [s for s in recorder.spans if s.name == "ffai.adapters.smartsheet.write"]
            assert len(write_spans) == 1
            span = write_spans[0]
            assert span.attributes["adapter"] == "default"
            assert span.attributes["records.count"] == 1
        finally:
            cfg.adapters.smartsheet.output_field_map = saved

    def test_run_id_auto_generated(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.smartsheet.output_field_map)
        cfg.adapters.smartsheet.output_field_map = {}
        try:
            mock_mod, _, _ = _mock_smartsheet()
            result = _make_result()

            with patch.dict("sys.modules", {"smartsheet": mock_mod}):
                rows = write_workflow_results_smartsheet(
                    99999,
                    result,
                    access_token="tok",
                )

            assert len(rows) == 2
        finally:
            cfg.adapters.smartsheet.output_field_map = saved

    def test_run_id_custom(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        saved = dict(cfg.adapters.smartsheet.output_field_map)
        cfg.adapters.smartsheet.output_field_map = {}
        try:
            mock_mod, _, _ = _mock_smartsheet()
            result = _make_result()

            with patch.dict("sys.modules", {"smartsheet": mock_mod}):
                rows = write_workflow_results_smartsheet(
                    99999,
                    result,
                    access_token="tok",
                    run_id="custom-run-42",
                )

            assert len(rows) == 2
        finally:
            cfg.adapters.smartsheet.output_field_map = saved

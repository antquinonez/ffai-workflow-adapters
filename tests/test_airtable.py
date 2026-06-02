from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from ffai.workflow.tabular import TabularLoadError
from ffai_workflow_adapters.airtable import (
    _get_api_key,
    _records_to_rows,
    load_workflow_airtable,
    write_workflow_results,
)


class TestGetApiKey:
    def test_explicit_key(self):
        assert _get_api_key("my_key") == "my_key"

    def test_from_env(self):
        with patch.dict(os.environ, {"AIRTABLE_API_KEY": "env_key"}):
            assert _get_api_key(None) == "env_key"

    def test_custom_env_var(self):
        with patch.dict(os.environ, {"MY_KEY": "custom_key"}):
            assert _get_api_key(None, env_var="MY_KEY") == "custom_key"

    def test_missing_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(TabularLoadError, match="AIRTABLE_API_KEY"):
                _get_api_key(None)

    def test_explicit_overrides_env(self):
        with patch.dict(os.environ, {"AIRTABLE_API_KEY": "env_key"}):
            assert _get_api_key("explicit") == "explicit"


class TestRecordsToRows:
    def test_basic_records(self):
        records = [
            {"id": "rec1", "fields": {"name": "a", "prompt": "Hello"}},
            {"id": "rec2", "fields": {"name": "b", "prompt": "World"}},
        ]
        rows = _records_to_rows(records)
        assert len(rows) == 2
        assert rows[0] == {"name": "a", "prompt": "Hello"}
        assert rows[1] == {"name": "b", "prompt": "World"}

    def test_empty_fields_skipped(self):
        records = [
            {"id": "rec1", "fields": {"name": "a", "prompt": "Hello"}},
            {"id": "rec2", "fields": {}},
            {"id": "rec3", "fields": {"name": "c", "prompt": "Go"}},
        ]
        rows = _records_to_rows(records)
        assert len(rows) == 2
        assert rows[1]["name"] == "c"

    def test_missing_fields_key(self):
        records = [{"id": "rec1"}, {"id": "rec2", "fields": {"name": "a", "prompt": "Go"}}]
        rows = _records_to_rows(records)
        assert len(rows) == 1
        assert rows[0]["name"] == "a"

    def test_with_field_map(self):
        records = [
            {"id": "rec1", "fields": {"Task": "topic", "Instructions": "Go"}},
            {"id": "rec2", "fields": {"Task": "explain", "Instructions": "Explain.", "Model": "gpt-4o"}},
        ]
        field_map = {"Task": "name", "Instructions": "prompt", "Model": "client"}
        rows = _records_to_rows(records, field_map=field_map)
        assert len(rows) == 2
        assert rows[0] == {"name": "topic", "prompt": "Go"}
        assert rows[1] == {"name": "explain", "prompt": "Explain.", "client": "gpt-4o"}

    def test_unmapped_columns_pass_through(self):
        records = [{"id": "rec1", "fields": {"name": "a", "prompt": "Go", "extra": "data"}}]
        field_map = {"extra": "client"}
        rows = _records_to_rows(records, field_map=field_map)
        assert rows[0]["name"] == "a"
        assert rows[0]["prompt"] == "Go"
        assert rows[0]["client"] == "data"


class TestLoadWorkflowAirtable:
    def setup_method(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        self._saved_input_map = cfg.adapters.airtable.input_field_map
        self._saved_output_map = cfg.adapters.airtable.output_field_map
        cfg.adapters.airtable.input_field_map = {}
        cfg.adapters.airtable.output_field_map = {}

    def teardown_method(self):
        from ffai_workflow_adapters.config import get_config
        cfg = get_config()
        cfg.adapters.airtable.input_field_map = self._saved_input_map
        cfg.adapters.airtable.output_field_map = self._saved_output_map

    @patch("pyairtable.api.Api")
    def test_basic_load(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.all.return_value = [
            {"id": "rec1", "fields": {"name": "topic", "prompt": "Name a discovery."}},
            {
                "id": "rec2",
                "fields": {
                    "name": "explain",
                    "prompt": "Explain {{topic.response}}.",
                    "history": "topic",
                },
            },
        ]
        mock_api_cls.return_value.table.return_value = mock_table

        spec = load_workflow_airtable(
            "appTestBase",
            "Workflow Steps",
            api_key="test_key",
            name="research",
        )

        mock_api_cls.assert_called_once_with("test_key")
        mock_api_cls.return_value.table.assert_called_once_with(
            "appTestBase", "Workflow Steps"
        )
        assert spec.name == "research"
        assert len(spec.prompts) == 2
        assert spec.prompts[0].name == "topic"
        assert spec.prompts[1].history == ["topic"]

    @patch("pyairtable.api.Api")
    def test_with_view(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.all.return_value = [
            {"id": "rec1", "fields": {"name": "a", "prompt": "Go"}},
        ]
        mock_api_cls.return_value.table.return_value = mock_table

        load_workflow_airtable(
            "appBase", "Steps", api_key="key", view="Active steps"
        )

        mock_table.all.assert_called_once_with(view="Active steps")

    @patch("pyairtable.api.Api")
    def test_without_view(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.all.return_value = [
            {"id": "rec1", "fields": {"name": "a", "prompt": "Go"}},
        ]
        mock_api_cls.return_value.table.return_value = mock_table

        load_workflow_airtable("appBase", "Steps", api_key="key")
        mock_table.all.assert_called_once_with()

    @patch("pyairtable.api.Api")
    def test_with_clients(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.all.return_value = [
            {"id": "rec1", "fields": {"name": "a", "prompt": "Go", "client": "reviewer"}},
        ]
        mock_api_cls.return_value.table.return_value = mock_table

        spec = load_workflow_airtable(
            "appBase",
            "Steps",
            api_key="key",
            clients={"reviewer": {"type": "litellm", "model": "gpt-4o"}},
        )
        assert "reviewer" in spec.clients
        assert spec.prompts[0].client is not None
        assert spec.prompts[0].client.name == "reviewer"

    @patch("pyairtable.api.Api")
    def test_with_defaults(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.all.return_value = [
            {"id": "rec1", "fields": {"name": "a", "prompt": "Go"}},
        ]
        mock_api_cls.return_value.table.return_value = mock_table

        spec = load_workflow_airtable(
            "appBase",
            "Steps",
            api_key="key",
            defaults={"temperature": 0.5, "max_tokens": 200},
        )
        assert spec.defaults.temperature == 0.5
        assert spec.defaults.max_tokens == 200

    @patch("pyairtable.api.Api")
    def test_empty_table_raises(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.all.return_value = []
        mock_api_cls.return_value.table.return_value = mock_table

        with pytest.raises(TabularLoadError, match="contains no records"):
            load_workflow_airtable("appBase", "Empty", api_key="key")

    @patch("pyairtable.api.Api")
    def test_description(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.all.return_value = [
            {"id": "rec1", "fields": {"name": "a", "prompt": "Go"}},
        ]
        mock_api_cls.return_value.table.return_value = mock_table

        spec = load_workflow_airtable(
            "appBase", "Steps", api_key="key", description="From Airtable"
        )
        assert spec.description == "From Airtable"

    def test_missing_api_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.dict("sys.modules", {"pyairtable.api": MagicMock(), "pyairtable": MagicMock()}):
                with pytest.raises(TabularLoadError, match="AIRTABLE_API_KEY"):
                    load_workflow_airtable("appBase", "Steps")

    def test_missing_pyairtable_raises(self):
        with patch.dict("sys.modules", {"pyairtable.api": None, "pyairtable": None}):
            with pytest.raises(TabularLoadError, match="pyairtable is required"):
                load_workflow_airtable("appBase", "Steps", api_key="key")


class TestWriteWorkflowResults:
    def setup_method(self):
        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        self._saved_output_map = cfg.adapters.airtable.output_field_map
        self._saved_input_map = cfg.adapters.airtable.input_field_map
        cfg.adapters.airtable.output_field_map = {}
        cfg.adapters.airtable.input_field_map = {}

    def teardown_method(self):
        from ffai_workflow_adapters.config import get_config
        cfg = get_config()
        cfg.adapters.airtable.output_field_map = self._saved_output_map
        cfg.adapters.airtable.input_field_map = self._saved_input_map

    def _make_result(self):
        from ffai.core.response_result import ResponseResult
        from ffai.core.usage import TokenUsage
        from dataclasses import dataclass, field

        @dataclass
        class FakeWorkflowResult:
            results: dict = field(default_factory=dict)
            success_count: int = 0
            failed_count: int = 0
            skipped_count: int = 0
            aborted: bool = False
            aborted_count: int = 0
            spec_name: str = "test_workflow"

        result = FakeWorkflowResult(
            success_count=2,
            results={
                "topic": ResponseResult(
                    response="Penicillin was discovered.",
                    model="mistral-small-latest",
                    status="success",
                    usage=TokenUsage(input_tokens=41, output_tokens=40, total_tokens=81),
                    duration_ms=1234.5,
                ),
                "explain": ResponseResult(
                    response="It changed the world.",
                    model="mistral-small-latest",
                    status="success",
                    usage=TokenUsage(input_tokens=84, output_tokens=161, total_tokens=245),
                    cost_usd=0.002,
                    duration_ms=2345.6,
                ),
            },
        )
        return result

    @patch("pyairtable.api.Api")
    def test_write_basic(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.batch_create.return_value = [
            {"id": "rec1"}, {"id": "rec2"}
        ]
        mock_api_cls.return_value.table.return_value = mock_table

        result = self._make_result()
        created = write_workflow_results(
            "appBase", "+results", result, api_key="key"
        )

        mock_api_cls.assert_called_once_with("key")
        mock_api_cls.return_value.table.assert_called_once_with("appBase", "+results")
        assert len(created) == 2

        call_args = mock_table.batch_create.call_args
        records = call_args[0][0]
        assert call_args[1] == {"typecast": True}
        assert records[0]["step"] == "topic"
        assert records[0]["workflow"] == "test_workflow"
        assert records[0]["status"] == "success"
        assert records[0]["input_tokens"] == 41
        assert records[0]["output_tokens"] == 40
        assert records[0]["duration_ms"] == 1234.5
        assert records[1]["step"] == "explain"
        assert records[1]["cost_usd"] == 0.002

    @patch("pyairtable.api.Api")
    def test_write_without_usage(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.batch_create.return_value = [{"id": "rec1"}]
        mock_api_cls.return_value.table.return_value = mock_table

        from ffai.core.response_result import ResponseResult

        result = self._make_result()
        result.results = {
            "step1": ResponseResult(response="ok", model="m", status="success"),
        }

        created = write_workflow_results(
            "appBase", "+results", result, api_key="key"
        )
        assert len(created) == 1

        records = mock_table.batch_create.call_args[0][0]
        assert "input_tokens" not in records[0]
        assert "output_tokens" not in records[0]

    def test_missing_pyairtable_raises(self):
        with patch.dict("sys.modules", {"pyairtable.api": None, "pyairtable": None}):
            with pytest.raises(TabularLoadError, match="pyairtable is required"):
                write_workflow_results(
                    "appBase", "+results", self._make_result(), api_key="key"
                )


class TestInputFieldMapping:
    @patch("pyairtable.api.Api")
    def test_custom_column_names_mapped(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.all.return_value = [
            {"id": "rec1", "fields": {"Task": "topic", "Instructions": "Name a discovery."}},
            {"id": "rec2", "fields": {"Task": "explain", "Instructions": "Explain it.", "AI Model": "gpt-4o"}},
        ]
        mock_api_cls.return_value.table.return_value = mock_table

        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.airtable.input_field_map = {"Task": "name", "Instructions": "prompt", "AI Model": "client"}

        spec = load_workflow_airtable("appBase", "Steps", api_key="key")
        assert len(spec.prompts) == 2
        assert spec.prompts[0].name == "topic"
        assert spec.prompts[0].prompt == "Name a discovery."
        assert spec.prompts[1].name == "explain"
        assert spec.prompts[1].client is not None
        assert spec.prompts[1].client.name == "gpt-4o"

        cfg.adapters.airtable.input_field_map = {}


class TestOutputFieldMapping:
    def _make_result(self):
        from ffai.core.response_result import ResponseResult
        from ffai.core.usage import TokenUsage
        from dataclasses import dataclass, field

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
            success_count=1,
            results={
                "topic": ResponseResult(
                    response="Penicillin.",
                    model="mistral-small-latest",
                    status="success",
                    usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
                ),
            },
        )

    @patch("pyairtable.api.Api")
    def test_output_fields_remapped(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.batch_create.return_value = [{"id": "rec1"}]
        mock_api_cls.return_value.table.return_value = mock_table

        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.airtable.output_field_map = {
            "step": "Step Name",
            "response": "Output",
            "model": "AI Model",
        }

        result = self._make_result()
        write_workflow_results("appBase", "Out", result, api_key="key")

        records = mock_table.batch_create.call_args[0][0]
        rec = records[0]
        assert "Step Name" in rec
        assert "Output" in rec
        assert "AI Model" in rec
        assert "step" not in rec
        assert "response" not in rec
        assert rec["Step Name"] == "topic"
        assert rec["Output"] == "Penicillin."

        cfg.adapters.airtable.output_field_map = {}


class TestNamedAdapterIntegration:
    @patch("pyairtable.api.Api")
    def test_load_with_named_adapter(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.all.return_value = [
            {"id": "rec1", "fields": {"Task": "topic", "Instructions": "Go"}},
        ]
        mock_api_cls.return_value.table.return_value = mock_table

        from ffai_workflow_adapters.config import reload_config
        cfg = reload_config()
        cfg.adapters.airtable.named = {
            "marketing": {
                "base_id_env": "AIRTABLE_MARKETING_BASE_ID",
                "input_field_map": {"Task": "name", "Instructions": "prompt"},
            },
        }

        spec = load_workflow_airtable("appBase", "Steps", adapter="marketing", api_key="key")
        assert spec.prompts[0].name == "topic"
        assert spec.prompts[0].prompt == "Go"

        cfg.adapters.airtable.named = {}

    @patch("pyairtable.api.Api")
    def test_write_with_named_adapter(self, mock_api_cls):
        mock_table = MagicMock()
        mock_table.batch_create.return_value = [{"id": "rec1"}]
        mock_api_cls.return_value.table.return_value = mock_table

        from ffai_workflow_adapters.config import reload_config

        cfg = reload_config()
        cfg.adapters.airtable.named = {
            "custom": {
                "output_field_map": {"response": "Output", "step": "StepName"},
            },
        }

        result = self._make_result()
        write_workflow_results("appBase", "Out", result, adapter="custom", api_key="key")

        rec = mock_table.batch_create.call_args[0][0][0]
        assert "StepName" in rec
        assert "Output" in rec
        assert rec["StepName"] == "topic"
        assert rec["Output"] == "Penicillin."

        cfg.adapters.airtable.named = {}

    def _make_result(self):
        from ffai.core.response_result import ResponseResult
        from ffai.core.usage import TokenUsage
        from dataclasses import dataclass, field

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
            success_count=1,
            results={
                "topic": ResponseResult(
                    response="Penicillin.",
                    model="mistral-small-latest",
                    status="success",
                    usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
                ),
            },
        )

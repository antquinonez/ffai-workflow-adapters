"""Google Sheets integration tests — real API calls to Google Sheets.

Run with: pytest tests/integration/test_google_sheets_integration.py -m google_sheets

Requires: GOOGLE_SHEETS_CREDENTIALS (or GOOGLE_SHEETS_API_KEY), and a test spreadsheet.
          Also requires MISTRAL_API_KEY for workflow execution.
          Set GOOGLE_SHEETS_TEST_SPREADSHEET_ID env var to the spreadsheet to test against.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from dotenv import load_dotenv

load_dotenv()


def _get_spreadsheet_id() -> str:
    sid = os.environ.get("GOOGLE_SHEETS_TEST_SPREADSHEET_ID", "")
    if not sid:
        pytest.skip("GOOGLE_SHEETS_TEST_SPREADSHEET_ID not set")
    return sid


def _create_client():
    from ffai import FFAI
    from ffai.Clients.AsyncFFLiteLLMClient import AsyncFFLiteLLMClient
    from ffai_workflow_adapters.config import get_config

    config = get_config()
    default_name = config.clients.default_client
    client_cfg = config.clients.get_client_type(default_name)
    assert client_cfg is not None

    model_string = f"{client_cfg.provider_prefix}{client_cfg.default_model}"
    api_key = os.environ.get(client_cfg.api_key_env, "")

    return FFAI(AsyncFFLiteLLMClient(model_string=model_string, api_key=api_key))


def _get_gspread():
    try:
        import gspread
        return gspread
    except ImportError:
        pytest.skip("gspread not installed")


def _get_gc():
    gspread = _get_gspread()
    from ffai_workflow_adapters.google_sheets import _resolve_auth
    from ffai_workflow_adapters.config import get_config

    cfg = get_config()
    auth = _resolve_auth(
        cfg_auth_method=cfg.adapters.google_sheets.auth_method,
        cfg_credentials_env=cfg.adapters.google_sheets.credentials_env,
        cfg_authorized_user_env=cfg.adapters.google_sheets.authorized_user_env,
        cfg_api_key_env=cfg.adapters.google_sheets.api_key_env,
    )

    if auth["method"] == "api_key":
        return gspread.api_key(auth["api_key"])
    if auth["method"] == "oauth":
        return gspread.oauth(
            credentials_filename=auth["credentials_filename"],
            authorized_user_filename=auth.get("authorized_user_filename"),  # type: ignore[arg-type]
        )
    return gspread.service_account(filename=auth["filename"])


def _ensure_worksheet(ss_id: str, title: str, headers: list[str], rows: list[list]) -> None:
    gc = _get_gc()
    ss = gc.open_by_key(ss_id)
    existing = [w.title for w in ss.worksheets()]
    if title in existing:
        ws = ss.worksheet(title)
        ws.clear()
    else:
        ws = ss.add_worksheet(title=title, rows=1 + len(rows), cols=len(headers))

    all_rows = [headers, *rows]
    ws.update(all_rows, value_input_option="USER_ENTERED")  # type: ignore[arg-type]


def _delete_worksheet(ss_id: str, title: str) -> None:
    gc = _get_gc()
    ss = gc.open_by_key(ss_id)
    existing = [w.title for w in ss.worksheets()]
    if title in existing:
        ws = ss.worksheet(title)
        ss.del_worksheet(ws)


def _read_worksheet(ss_id: str, title: str) -> list[list]:
    gc = _get_gc()
    ss = gc.open_by_key(ss_id)
    ws = ss.worksheet(title)
    return ws.get_all_values()


@pytest.mark.integration
@pytest.mark.google_sheets
class TestGoogleSheetsIntegration:
    def test_load_and_execute(self):
        from ffai_workflow_adapters.config import reload_config
        from ffai_workflow_adapters.google_sheets import load_workflow_google_sheets

        reload_config()

        ss_id = _get_spreadsheet_id()
        _ensure_worksheet(ss_id, "TestWorkflow", ["name", "prompt", "client", "temperature"], [
            ["topic", "Name a famous scientific discovery in one sentence.", "litellm-mistral-small", 0.7],
        ])

        spec = load_workflow_google_sheets(ss_id, worksheet="TestWorkflow", name="gsheets_integration")
        assert spec.name == "gsheets_integration"
        assert len(spec.prompts) == 1
        assert spec.prompts[0].name == "topic"

        ffai = _create_client()
        result = asyncio.run(ffai.workflow.execute_workflow(spec))
        assert result.success_count == 1
        assert result.results["topic"].response

    def test_load_execute_write_roundtrip(self):
        from ffai_workflow_adapters.config import reload_config
        from ffai_workflow_adapters.google_sheets import (
            load_workflow_google_sheets,
            write_workflow_results_google_sheets,
        )

        reload_config()

        ss_id = _get_spreadsheet_id()
        _ensure_worksheet(ss_id, "TestWorkflowRW", ["name", "prompt", "client", "temperature", "Comments"], [
            ["topic", "Name a famous invention in one sentence.", "litellm-mistral-small", 0.7, "Invention step"],
        ])

        spec = load_workflow_google_sheets(ss_id, worksheet="TestWorkflowRW", name="gsheets_rw")
        ffai = _create_client()
        result = asyncio.run(ffai.workflow.execute_workflow(spec))
        assert result.success_count == 1

        output_ws = "TestResults"
        _delete_worksheet(ss_id, output_ws)

        rows = write_workflow_results_google_sheets(
            ss_id, result, worksheet=output_ws, spec=spec, run_id="gs-test-1"
        )
        assert len(rows) == 1

        written = _read_worksheet(ss_id, output_ws)
        header = written[0]
        assert "run_id" in header
        assert "Comments" in header

        run_id_col = header.index("run_id")
        assert written[1][run_id_col] == "gs-test-1"

        comments_col = header.index("Comments")
        assert written[1][comments_col] == "Invention step"

    def test_multi_step_with_history(self):
        from ffai_workflow_adapters.config import reload_config
        from ffai_workflow_adapters.google_sheets import (
            load_workflow_google_sheets,
            write_workflow_results_google_sheets,
        )

        reload_config()

        ss_id = _get_spreadsheet_id()
        _ensure_worksheet(ss_id, "TestMultiStep", ["name", "prompt", "client", "history", "temperature"], [
            ["topic", "Name a scientific discovery.", "litellm-mistral-small", "", 0.7],
            ["explain", "Explain the impact of: {{topic.response}}", "litellm-mistral-small", "topic", 0.5],
        ])

        spec = load_workflow_google_sheets(ss_id, worksheet="TestMultiStep", name="gsheets_multi")
        assert len(spec.prompts) == 2
        assert spec.prompts[1].history == ["topic"]

        ffai = _create_client()
        result = asyncio.run(ffai.workflow.execute_workflow(spec))
        assert result.success_count == 2

        output_ws = "TestMultiResults"
        _delete_worksheet(ss_id, output_ws)

        write_workflow_results_google_sheets(ss_id, result, worksheet=output_ws)

        written = _read_worksheet(ss_id, output_ws)
        assert len(written) == 3
        assert written[0][0] == "Workflow"

        step_col = written[0].index("Step")
        assert written[1][step_col] == "topic"
        assert written[2][step_col] == "explain"

        run_id_col = written[0].index("run_id")
        assert written[1][run_id_col] == written[2][run_id_col]

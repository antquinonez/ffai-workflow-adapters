"""Google Sheets load/write adapter for ffai workflow execution."""
from __future__ import annotations

import logging
import os
from typing import Any

from ffai.workflow.tabular import TabularLoadError, load_workflow_rows

from ffai_workflow_adapters._resilience import CircuitBreaker, ResilientCaller, TokenBucket
from ffai_workflow_adapters._spans import adapter_span
from ffai_workflow_adapters._tabular_helpers import build_output_records, process_tabular_rows
from ffai_workflow_adapters._validation import validate_schema
from ffai_workflow_adapters.config import get_config

logger = logging.getLogger(__name__)


def _get_credentials_file(
    credentials_file: str | None = None,
    credentials_env: str | None = None,
    cfg_credentials_env: str | None = None,
) -> str:
    if credentials_file:
        return credentials_file
    env_var = credentials_env or cfg_credentials_env or "GOOGLE_SHEETS_CREDENTIALS"
    path = os.environ.get(env_var)
    if not path:
        raise TabularLoadError(
            f"Google Sheets credentials not provided. Pass credentials_file "
            f"parameter or set {env_var} environment variable."
        )
    return path


_last_config_id: int = 0
_caller: ResilientCaller | None = None


def _make_caller() -> ResilientCaller:
    global _caller, _last_config_id
    cfg = get_config()
    cfg_id = id(cfg)
    if _caller is not None and cfg_id == _last_config_id:
        return _caller
    rl = cfg.resilience.rate_limit
    cb = cfg.resilience.circuit_breaker
    retry = cfg.retry
    _caller = ResilientCaller(
        bucket=TokenBucket(rate=rl.requests_per_second, burst=rl.burst),
        breaker=CircuitBreaker(
            failure_threshold=cb.failure_threshold,
            recovery_timeout_seconds=cb.recovery_timeout_seconds,
            half_open_max_calls=cb.half_open_max_calls,
        ),
        retry_max_attempts=retry.max_attempts,
        retry_min_wait=retry.min_wait_seconds,
        retry_max_wait=retry.max_wait_seconds,
        retry_exponential_base=retry.exponential_base,
        retry_jitter=retry.exponential_jitter,
        retry_on_status_codes=retry.retry_on_status_codes,
        acquire_timeout=30.0,
    )
    _last_config_id = cfg_id
    return _caller


def _reset_caller() -> None:
    global _caller, _last_config_id
    _caller = None
    _last_config_id = 0


def load_workflow_google_sheets(
    spreadsheet_id: str,
    *,
    worksheet: str | int | None = None,
    adapter: str | None = None,
    credentials_file: str | None = None,
    credentials_env: str | None = None,
    name: str = "unnamed",
    description: str = "",
    defaults: dict[str, Any] | None = None,
    clients: dict[str, dict[str, Any] | str] | None = None,
    tools: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Load a workflow from a Google Sheets spreadsheet into a ffai WorkflowSpec.

    Reads all records from the specified worksheet, applies field mapping
    from the resolved adapter config, validates required columns, and
    delegates to ffai's load_workflow_rows. Includes rate limiting, circuit
    breaking, and retry with exponential backoff.

    Args:
        spreadsheet_id: Google Sheets spreadsheet ID (from the URL).
        worksheet: Worksheet name or index. Defaults to the first worksheet.
        adapter: Named adapter variant from config/adapters.yaml.
        credentials_file: Path to service account JSON file.
        credentials_env: Environment variable name holding the credentials
            file path. Defaults to ``GOOGLE_SHEETS_CREDENTIALS``.
        name: Workflow name assigned to the resulting WorkflowSpec.
        description: Workflow description for the resulting WorkflowSpec.
        defaults: Default values merged into each row.
        clients: Client definitions passed through to ffai.
        tools: Tool definitions passed through to ffai.

    Returns:
        A ffai WorkflowSpec ready for execution.

    Raises:
        TabularLoadError: If gspread is not installed, credentials are
            missing, the worksheet is empty, or required columns are absent.
    """
    try:
        import gspread  # pyright: ignore[reportMissingImports]
    except ImportError as e:
        raise TabularLoadError(
            "gspread is required for Google Sheets. "
            "Install with: pip install ffai-workflow-adapters[google_sheets]"
        ) from e

    cfg = get_config().adapters.google_sheets.resolve(adapter)
    field_map = cfg.input_field_map or None
    passthrough = cfg.passthrough_columns or []
    creds_file = _get_credentials_file(
        credentials_file, credentials_env, cfg_credentials_env=cfg.credentials_env,
    )

    with adapter_span(
        "google_sheets.load",
        adapter=adapter or "default",
        spreadsheet_id=spreadsheet_id,
        worksheet=str(worksheet) if worksheet else "first",
    ) as span:
        gc = gspread.service_account(filename=creds_file)
        spreadsheet = gc.open_by_key(spreadsheet_id)

        if worksheet is None:
            ws = spreadsheet.sheet1
        elif isinstance(worksheet, int):
            ws = spreadsheet.get_worksheet(worksheet)
        else:
            ws = spreadsheet.worksheet(worksheet)

        caller = _make_caller()
        raw_records = caller.call(ws.get_all_records)

        rows, source_metadata = process_tabular_rows(
            raw_records, field_map=field_map, passthrough_columns=passthrough
        )

        if not rows:
            raise TabularLoadError(
                f"Google Sheets spreadsheet '{spreadsheet_id}' contains no records"
            )

        source_label = f"Google Sheets '{spreadsheet_id}'"
        validate_schema(rows, source_label)

        spec = load_workflow_rows(
            rows,
            name=name,
            description=description,
            defaults=defaults,
            clients=clients,
            tools=tools,
        )

        span.set_attribute("rows.count", len(rows))
        span.set_attribute("workflow.name", name)

        if source_metadata:
            object.__setattr__(spec, "_source_metadata", source_metadata)

        return spec


def write_workflow_results_google_sheets(
    spreadsheet_id: str,
    result: Any,
    *,
    worksheet: str | None = None,
    adapter: str | None = None,
    credentials_file: str | None = None,
    credentials_env: str | None = None,
    spec: Any | None = None,
    run_id: str | None = None,
) -> list[list[Any]]:
    """Write workflow execution results to a Google Sheets spreadsheet.

    Appends one row per workflow step to the specified worksheet. Creates
    the worksheet if it doesn't exist. Supports passthrough columns from
    the source spec and extra output columns with template resolution.

    Args:
        spreadsheet_id: Google Sheets spreadsheet ID (from the URL).
        result: A ffai WorkflowResult containing step results.
        worksheet: Worksheet name for results. Defaults to the adapter
            config's ``output_worksheet`` or "Results".
        adapter: Named adapter variant for output field mapping.
        credentials_file: Path to service account JSON file.
        credentials_env: Environment variable name holding the credentials
            file path.
        spec: The original WorkflowSpec (used for passthrough column data).
        run_id: Unique run identifier. Auto-generated if not provided.

    Returns:
        List of row lists that were appended.

    Raises:
        TabularLoadError: If gspread is not installed or credentials are
            missing.
    """
    try:
        import gspread  # pyright: ignore[reportMissingImports]
    except ImportError as e:
        raise TabularLoadError(
            "gspread is required for Google Sheets. "
            "Install with: pip install ffai-workflow-adapters[google_sheets]"
        ) from e

    cfg = get_config().adapters.google_sheets.resolve(adapter)
    creds_file = _get_credentials_file(
        credentials_file, credentials_env, cfg_credentials_env=cfg.credentials_env,
    )

    source_metadata = getattr(spec, "_source_metadata", None) if spec else None

    with adapter_span(
        "google_sheets.write",
        adapter=adapter or "default",
        spreadsheet_id=spreadsheet_id,
    ) as span:
        gc = gspread.service_account(filename=creds_file)
        spreadsheet = gc.open_by_key(spreadsheet_id)
        ws_name = worksheet or cfg.output_worksheet or "Results"

        existing_titles = [w.title for w in spreadsheet.worksheets()]
        if ws_name in existing_titles:
            ws = spreadsheet.worksheet(ws_name)
        else:
            ws = spreadsheet.add_worksheet(title=ws_name, rows=1, cols=1)

        records, column_names, resolved_run_id = build_output_records(
            result,
            output_field_map=cfg.output_field_map or None,
            passthrough_columns=cfg.passthrough_columns or None,
            extra_output_columns=cfg.extra_output_columns or None,
            source_metadata=source_metadata,
            run_id=run_id,
        )

        span.set_attribute("records.count", len(records))

        caller = _make_caller()
        rows_to_append = [[rec.get(col) for col in column_names] for rec in records]

        caller.call(
            ws.append_rows, rows_to_append, value_input_option="USER_ENTERED"
        )

        span.set_attribute("records.appended", len(rows_to_append))

        return rows_to_append

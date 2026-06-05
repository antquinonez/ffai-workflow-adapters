"""Smartsheet load/write adapter for ffai workflow execution."""
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


def _resolve_access_token(
    *,
    access_token: str | None = None,
    access_token_env: str | None = None,
    cfg_access_token_env: str = "SMARTSHEET_ACCESS_TOKEN",
) -> str:
    token = access_token or os.environ.get(access_token_env or cfg_access_token_env)
    if not token:
        env_var = access_token_env or cfg_access_token_env
        raise TabularLoadError(
            f"Smartsheet access token not provided. Pass access_token "
            f"parameter or set {env_var} environment variable."
        )
    return token


def _rows_to_records(sheet: Any) -> list[dict[str, Any]]:
    col_map = {col.id: col.title for col in sheet.columns}
    records: list[dict[str, Any]] = []
    for row in sheet.rows:
        record: dict[str, Any] = {}
        for cell in row.cells:
            title = col_map.get(cell.column_id)
            if title is not None:
                record[title] = cell.value
        if any(v is not None for v in record.values()):
            records.append(record)
    return records


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


def load_workflow_smartsheet(
    sheet_id: int,
    *,
    adapter: str | None = None,
    access_token: str | None = None,
    access_token_env: str | None = None,
    name: str = "unnamed",
    description: str = "",
    defaults: dict[str, Any] | None = None,
    clients: dict[str, dict[str, Any] | str] | None = None,
    tools: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Load a workflow from a Smartsheet sheet into a ffai WorkflowSpec.

    Reads all rows from the specified sheet, applies field mapping from the
    resolved adapter config, validates required columns, and delegates to
    ffai's ``load_workflow_rows``. Includes rate limiting, circuit breaking,
    and retry with exponential backoff.

    Args:
        sheet_id: Smartsheet sheet ID (integer).
        adapter: Named adapter variant from config/adapters.yaml.
        access_token: Smartsheet API access token.
        access_token_env: Environment variable name holding the access token.
        name: Workflow name assigned to the resulting WorkflowSpec.
        description: Workflow description for the resulting WorkflowSpec.
        defaults: Default values merged into each row.
        clients: Client definitions passed through to ffai.
        tools: Tool definitions passed through to ffai.

    Returns:
        A ffai WorkflowSpec ready for execution.

    Raises:
        TabularLoadError: If smartsheet-python-sdk is not installed,
            access token is missing, the sheet is empty, or required
            columns are absent.
    """
    try:
        import smartsheet  # pyright: ignore[reportMissingImports]
    except ImportError as e:
        raise TabularLoadError(
            "smartsheet-python-sdk is required for Smartsheet. "
            "Install with: pip install ffai-workflow-adapters[smartsheet]"
        ) from e

    cfg = get_config().adapters.smartsheet.resolve(adapter)
    field_map = cfg.input_field_map or None
    passthrough = cfg.passthrough_columns or []

    token = _resolve_access_token(
        access_token=access_token,
        access_token_env=access_token_env,
        cfg_access_token_env=cfg.access_token_env,
    )

    with adapter_span(
        "smartsheet.load",
        adapter=adapter or "default",
        sheet_id=str(sheet_id),
    ) as span:
        smart = smartsheet.Smartsheet(access_token=token)  # pyright: ignore[reportAttributeAccessIssue]
        caller = _make_caller()
        sheet = caller.call(smart.Sheets.get_sheet, sheet_id)

        raw_records = _rows_to_records(sheet)

        rows, source_metadata = process_tabular_rows(
            raw_records, field_map=field_map, passthrough_columns=passthrough
        )

        if not rows:
            raise TabularLoadError(
                f"Smartsheet sheet '{sheet_id}' contains no records"
            )

        source_label = f"Smartsheet '{sheet_id}'"
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


def write_workflow_results_smartsheet(
    sheet_id: int,
    result: Any,
    *,
    adapter: str | None = None,
    access_token: str | None = None,
    access_token_env: str | None = None,
    spec: Any | None = None,
    run_id: str | None = None,
) -> list[list[Any]]:
    """Write workflow execution results to a Smartsheet sheet.

    Appends one row per workflow step to the specified sheet. Creates columns
    if the sheet is empty. Supports passthrough columns from the source spec
    and extra output columns with template resolution.

    Args:
        sheet_id: Smartsheet sheet ID (integer) for results.
        result: A ffai WorkflowResult containing step results.
        adapter: Named adapter variant for output field mapping.
        access_token: Smartsheet API access token.
        access_token_env: Environment variable name holding the access token.
        spec: The original WorkflowSpec (used for passthrough column data).
        run_id: Unique run identifier. Auto-generated if not provided.

    Returns:
        List of row value lists that were added.

    Raises:
        TabularLoadError: If smartsheet-python-sdk is not installed or
            access token is missing.
    """
    try:
        import smartsheet  # pyright: ignore[reportMissingImports]
    except ImportError as e:
        raise TabularLoadError(
            "smartsheet-python-sdk is required for Smartsheet. "
            "Install with: pip install ffai-workflow-adapters[smartsheet]"
        ) from e

    cfg = get_config().adapters.smartsheet.resolve(adapter)

    token = _resolve_access_token(
        access_token=access_token,
        access_token_env=access_token_env,
        cfg_access_token_env=cfg.access_token_env,
    )

    source_metadata = getattr(spec, "_source_metadata", None) if spec else None

    with adapter_span(
        "smartsheet.write",
        adapter=adapter or "default",
        sheet_id=str(sheet_id),
    ) as span:
        smart = smartsheet.Smartsheet(access_token=token)  # pyright: ignore[reportAttributeAccessIssue]

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
        sheet = caller.call(smart.Sheets.get_sheet, sheet_id)

        existing_col_map = {col.title: col.id for col in sheet.columns}

        if not existing_col_map:
            new_columns = []
            for i, col_name in enumerate(column_names):
                col = smartsheet.models.Column({  # pyright: ignore[reportAttributeAccessIssue]
                    "title": col_name,
                    "type": "TEXT_NUMBER",
                    "primary": i == 0,
                })
                new_columns.append(col)
            caller.call(smart.Sheets.add_columns, sheet_id, new_columns)
            sheet = caller.call(smart.Sheets.get_sheet, sheet_id)
            existing_col_map = {col.title: col.id for col in sheet.columns}

        rows_to_add = []
        for rec in records:
            new_row = smartsheet.models.Row()  # pyright: ignore[reportAttributeAccessIssue]
            new_row.cells = []
            for col_name in column_names:
                col_id = existing_col_map.get(col_name)
                if col_id is not None:
                    new_row.cells.append(
                        smartsheet.models.Cell({  # pyright: ignore[reportAttributeAccessIssue]
                            "column_id": col_id,
                            "value": rec.get(col_name),
                        })
                    )
            rows_to_add.append(new_row)

        caller.call(smart.Sheets.add_rows, sheet_id, rows_to_add)

        rows_data = [
            [rec.get(col) for col in column_names]
            for rec in records
        ]

        span.set_attribute("records.appended", len(rows_to_add))

        return rows_data

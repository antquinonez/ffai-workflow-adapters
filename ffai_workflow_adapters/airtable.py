from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from ffai.workflow.tabular import TabularLoadError, load_workflow_rows

from ffai_workflow_adapters._validation import validate_schema
from ffai_workflow_adapters.config import get_config


def _get_api_key(api_key: str | None = None, env_var: str | None = None) -> str:
    if api_key:
        return api_key

    key_env = env_var or get_config().adapters.airtable.api_key_env

    key = os.environ.get(key_env)
    if not key:
        raise TabularLoadError(
            f"Airtable API key not provided. Pass api_key parameter or set {key_env} environment variable."
        )
    return key


def _records_to_rows(records: Any, field_map: dict[str, str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        fields = record.get("fields", {})
        if not fields:
            continue
        if field_map:
            mapped: dict[str, Any] = {}
            for col, val in fields.items():
                canonical = field_map.get(col, col)
                if canonical is not None:
                    mapped[canonical] = val
            rows.append(mapped)
        else:
            rows.append(dict(fields))
    return rows


def load_workflow_airtable(
    base_id: str,
    table_name: str,
    *,
    adapter: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
    view: str | None = None,
    name: str = "unnamed",
    description: str = "",
    defaults: dict[str, Any] | None = None,
    clients: dict[str, dict[str, Any] | str] | None = None,
    tools: dict[str, dict[str, Any]] | None = None,
) -> Any:
    try:
        from pyairtable.api import Api
    except ImportError as e:
        raise TabularLoadError(
            "pyairtable is required for Airtable loading. Install with: pip install ffai-workflow-adapters[airtable]"
        ) from e

    cfg = get_config().adapters.airtable.resolve(adapter)

    if not view:
        view = cfg.default_view or None

    field_map = cfg.input_field_map or None

    key = _get_api_key(api_key, api_key_env)
    api = Api(key)
    table = api.table(base_id, table_name)

    kwargs: dict[str, Any] = {}
    if view:
        kwargs["view"] = view

    records = table.all(**kwargs)
    rows = _records_to_rows(records, field_map=field_map)

    if not rows:
        raise TabularLoadError(
            f"Airtable table '{table_name}' in base '{base_id}' contains no records"
        )

    validate_schema(rows, f"Airtable table '{table_name}' in base '{base_id}'")

    return load_workflow_rows(
        rows,
        name=name,
        description=description,
        defaults=defaults,
        clients=clients,
        tools=tools,
    )


def write_workflow_results(
    base_id: str,
    table_name: str,
    result: Any,
    *,
    adapter: str | None = None,
    api_key: str | None = None,
    api_key_env: str | None = None,
) -> list[dict[str, Any]]:
    try:
        from pyairtable.api import Api
    except ImportError as e:
        raise TabularLoadError(
            "pyairtable is required for Airtable output. Install with: pip install ffai-workflow-adapters[airtable]"
        ) from e

    cfg = get_config().adapters.airtable.resolve(adapter)
    output_map = cfg.output_field_map

    key = _get_api_key(api_key, api_key_env)
    api = Api(key)
    table = api.table(base_id, table_name)

    timestamp = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []

    for step_name, step_result in result.results.items():
        fields: dict[str, Any] = {
            "workflow": result.spec_name or "",
            "step": step_name,
            "status": step_result.status,
            "response": step_result.response or "",
            "model": step_result.model or "",
            "timestamp": timestamp,
        }
        if step_result.usage:
            fields["input_tokens"] = step_result.usage.input_tokens
            fields["output_tokens"] = step_result.usage.output_tokens
        if step_result.cost_usd:
            fields["cost_usd"] = step_result.cost_usd
        if step_result.duration_ms:
            fields["duration_ms"] = round(step_result.duration_ms, 1)

        if output_map:
            fields = {output_map.get(k, k): v for k, v in fields.items()}

        records.append(fields)

    return [dict(r) for r in table.batch_create(records, typecast=True)]

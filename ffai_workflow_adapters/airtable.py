from __future__ import annotations

import os
from typing import Any

from ffai.workflow.tabular import TabularLoadError, load_workflow_rows

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


def _records_to_rows(records: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        fields = record.get("fields", {})
        if fields:
            rows.append(dict(fields))
    return rows


def load_workflow_airtable(
    base_id: str,
    table_name: str,
    *,
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

    if not view:
        view = get_config().adapters.airtable.default_view or None

    key = _get_api_key(api_key, api_key_env)
    api = Api(key)
    table = api.table(base_id, table_name)

    kwargs: dict[str, Any] = {}
    if view:
        kwargs["view"] = view

    records = table.all(**kwargs)
    rows = _records_to_rows(records)

    if not rows:
        raise TabularLoadError(
            f"Airtable table '{table_name}' in base '{base_id}' contains no records"
        )

    return load_workflow_rows(
        rows,
        name=name,
        description=description,
        defaults=defaults,
        clients=clients,
        tools=tools,
    )

"""Configuration loading from YAML files, environment variables, and constructor kwargs."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


def _find_config_dir() -> Path:
    candidates = [
        Path.cwd() / "config",
        Path(__file__).parent.parent / "config",
        Path.cwd().parent / "config",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return Path("config")


def _load_yaml_file(filename: str) -> dict[str, Any]:
    config_dir = _find_config_dir()
    filepath = config_dir / filename
    if not filepath.exists():
        return {}
    with open(filepath, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_all_configs() -> dict[str, Any]:
    main_yaml = _load_yaml_file("main.yaml")
    return {
        "logging": _load_yaml_file("logging.yaml").get("logging", {}),
        "retry": main_yaml.get("retry", {}),
        "resilience": main_yaml.get("resilience", {}),
        "adapters": _load_yaml_file("adapters.yaml").get("adapters", {}),
        "clients": _load_yaml_file("clients.yaml"),
    }


class YamlConfigSource(PydanticBaseSettingsSource):
    """Pydantic settings source that reads values from a YAML dict."""

    def __init__(self, settings_cls: type[BaseSettings], yaml_data: dict[str, Any]):
        super().__init__(settings_cls)
        self._yaml_data = yaml_data

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        field_value = self._yaml_data.get(field_name)
        return field_value, field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._yaml_data


class LoggingRotationConfig(BaseSettings):
    """Log file rotation schedule settings."""

    when: str = "midnight"
    interval: int = 1
    backup_count: int = 10


class LoggingConfig(BaseSettings):
    """Logging output configuration (directory, level, format, rotation)."""
    directory: str = "logs"
    filename: str = "workflow_adapters.log"
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    rotation: LoggingRotationConfig = Field(default_factory=LoggingRotationConfig)


class RetryConfig(BaseSettings):
    """Retry behavior for transient API failures.

    Attributes:
        max_attempts: Maximum retry attempts per call.
        min_wait_seconds: Minimum wait between retries.
        max_wait_seconds: Maximum wait between retries.
        exponential_base: Base for exponential backoff calculation.
        exponential_jitter: If True, randomize wait time by +/- 50%.
        retry_on_status_codes: HTTP status codes that trigger retry.
    """
    max_attempts: int = 3
    min_wait_seconds: float = 1.0
    max_wait_seconds: float = 60.0
    exponential_base: float = 2.0
    exponential_jitter: bool = True
    retry_on_status_codes: list[int] = Field(default_factory=lambda: [429, 503, 502, 504])


class RateLimitConfig(BaseSettings):
    """Token bucket rate limiting settings.

    Attributes:
        requests_per_second: Token refill rate.
        burst: Maximum tokens (also initial count).
    """
    requests_per_second: float = 5.0
    burst: int = 10


class CircuitBreakerConfig(BaseSettings):
    """Circuit breaker failure protection settings.

    Attributes:
        failure_threshold: Consecutive failures before opening.
        recovery_timeout_seconds: Seconds in open state before half-open.
        half_open_max_calls: Probe calls allowed in half-open state.
    """
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0
    half_open_max_calls: int = 3


class BatchConfig(BaseSettings):
    """Batch write concurrency settings.

    Attributes:
        chunk_size: Records per batch write call.
        max_concurrency: Maximum concurrent write threads.
    """
    chunk_size: int = 10
    max_concurrency: int = 3


class ResilienceConfig(BaseSettings):
    """Combined resilience settings: rate limiting, circuit breaking, and batching."""
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    batch: BatchConfig = Field(default_factory=BatchConfig)


class _FieldMappedAdapterConfig(BaseSettings):
    input_field_map: dict[str, str] = Field(default_factory=dict)
    output_field_map: dict[str, str] = Field(default_factory=dict)
    passthrough_columns: list[str] = Field(default_factory=list)
    extra_output_columns: dict[str, str] = Field(default_factory=dict)
    named: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def resolve(self, name: str | None = None) -> Any:
        if not name:
            return self
        child_data = self.named.get(name)
        if not child_data:
            return self
        return self._inherit(child_data)

    def _inherit(self, child_data: dict[str, Any]) -> Any:
        data: dict[str, Any] = {}
        for field_name in self.__class__.model_fields:
            if field_name == "named":
                continue
            child_val = child_data.get(field_name)
            base_val = getattr(self, field_name, None)
            if isinstance(child_val, dict) and child_val:
                if isinstance(base_val, dict):
                    data[field_name] = {**base_val, **child_val}
                else:
                    data[field_name] = child_val
            elif child_val not in (None, "", [], {}):
                data[field_name] = child_val
            else:
                data[field_name] = base_val
        return self.__class__(**data)


class AirtableAdapterConfig(_FieldMappedAdapterConfig):
    """Airtable adapter settings including field maps and API key resolution.

    Attributes:
        api_key_env: Environment variable name for the Airtable API key.
        base_id_env: Environment variable name for the Airtable base ID.
        default_view: Default Airtable view to filter records.
    """
    api_key_env: str = "AIRTABLE_API_KEY"
    base_id_env: str = "AIRTABLE_BASE_ID"
    default_view: str = ""


class OdsAdapterConfig(_FieldMappedAdapterConfig):
    """ODS adapter settings."""
    output_path: str | None = None
    output_sheet: str = "Results"


class CsvAdapterConfig(_FieldMappedAdapterConfig):
    """CSV/TSV adapter settings."""
    output_path: str | None = None
    delimiter: str = ","


class ExcelAdapterConfig(_FieldMappedAdapterConfig):
    """Excel adapter settings including output path and sheet name.

    Attributes:
        output_path: Default output file path for write operations.
        output_sheet: Default sheet name for write results.
    """
    output_path: str | None = None
    output_sheet: str = "Results"


class GoogleSheetsAdapterConfig(_FieldMappedAdapterConfig):
    """Google Sheets adapter settings including credentials and worksheet."""
    credentials_env: str = "GOOGLE_SHEETS_CREDENTIALS"
    output_worksheet: str = "Results"


class AdaptersConfig(BaseSettings):
    """Per-adapter configuration grouped by adapter type."""
    model_config = SettingsConfigDict(extra="allow")

    airtable: AirtableAdapterConfig = Field(default_factory=AirtableAdapterConfig)
    csv_adapter: CsvAdapterConfig = Field(default_factory=CsvAdapterConfig)
    excel: ExcelAdapterConfig = Field(default_factory=ExcelAdapterConfig)
    google_sheets: GoogleSheetsAdapterConfig = Field(default_factory=GoogleSheetsAdapterConfig)
    ods: OdsAdapterConfig = Field(default_factory=OdsAdapterConfig)


class ClientTypeConfig(BaseSettings):
    """Definition of a single LLM client type.

    Attributes:
        client_class: Python class name for the client.
        type: Provider type ("native" or "litellm").
        api_key_env: Environment variable name for the API key.
        provider_prefix: LiteLLM model string prefix.
        default_model: Default model identifier.
        fallbacks: Ordered list of fallback model identifiers.
    """
    client_class: str = ""
    type: Literal["native", "litellm"] = "litellm"
    api_key_env: str = ""
    provider_prefix: str = ""
    default_model: str = ""
    fallbacks: list[str] = Field(default_factory=list)


class ClientsConfig(BaseSettings):
    """LLM client definitions and default client selection.

    Attributes:
        default_client: Name of the default client type.
        client_types: Map of client type name to ClientTypeConfig.
    """
    model_config = SettingsConfigDict(extra="allow")

    default_client: str = "litellm-mistral-small"
    client_types: dict[str, ClientTypeConfig] = Field(default_factory=dict)

    def get_client_type(self, name: str) -> ClientTypeConfig | None:
        """Look up a client type configuration by name."""
        return self.client_types.get(name)

    def get_available_client_types(self) -> list[str]:
        """Return the names of all configured client types."""

        return list(self.client_types.keys())


class Config(BaseSettings):
    """Root configuration model loaded from YAML, env vars, and kwargs.

    Priority order: constructor kwargs > environment variables (``__``
    delimiter) > YAML files in ``config/``.

    Attributes:
        logging: Logging output configuration.
        retry: Retry behavior for transient failures.
        resilience: Rate limiting, circuit breaking, and batch settings.
        adapters: Per-adapter field maps and settings.
        clients: LLM client type definitions.
    """
    model_config = SettingsConfigDict(
        extra="ignore",
        validate_default=True,
        env_nested_delimiter="__",
    )

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    resilience: ResilienceConfig = Field(default_factory=ResilienceConfig)
    adapters: AdaptersConfig = Field(default_factory=AdaptersConfig)
    clients: ClientsConfig = Field(default_factory=ClientsConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_data = _load_all_configs()
        yaml_source = YamlConfigSource(settings_cls, yaml_data)
        return (init_settings, env_settings, yaml_source)

    def get_client_type_config(self, name: str) -> ClientTypeConfig | None:
        """Look up a client type configuration by name."""

        return self.clients.get_client_type(name)

    def get_default_client_type(self) -> str:
        """Return the name of the default client type."""

        return self.clients.default_client

    def get_available_client_types(self) -> list[str]:
        """Return the names of all configured client types."""

        return self.clients.get_available_client_types()

    def get_adapter_api_key(self, adapter_name: str) -> str | None:
        """Resolve the API key for an adapter from its environment variable.

        Args:
            adapter_name: Adapter name (e.g. "airtable", "excel").

        Returns:
            The API key string, or None if the adapter or env var is not
            configured.
        """
        import os

        adapter: BaseSettings | None = getattr(self.adapters, adapter_name, None)
        if adapter is None:
            return None
        env_var = getattr(adapter, "api_key_env", None)
        if not env_var:
            return None
        return os.environ.get(env_var)


_config: Config | None = None


def get_config() -> Config:
    """Return the singleton Config instance, creating it on first call.

    The Config is loaded from YAML files, environment variables (using
    ``__`` as nested delimiter), and constructor defaults. Subsequent
    calls return the same instance until ``reload_config`` is called.
    """
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """Discard the cached Config and reload from all sources.

    Re-reads YAML files and environment variables. Use after changing
    config files or env vars at runtime.

    Returns:
        The freshly loaded Config instance.
    """
    global _config
    _config = Config()
    return _config

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
    def __init__(self, settings_cls: type[BaseSettings], yaml_data: dict[str, Any]):
        super().__init__(settings_cls)
        self._yaml_data = yaml_data

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        field_value = self._yaml_data.get(field_name)
        return field_value, field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._yaml_data


class LoggingRotationConfig(BaseSettings):
    when: str = "midnight"
    interval: int = 1
    backup_count: int = 10


class LoggingConfig(BaseSettings):
    directory: str = "logs"
    filename: str = "workflow_adapters.log"
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    rotation: LoggingRotationConfig = Field(default_factory=LoggingRotationConfig)


class RetryConfig(BaseSettings):
    max_attempts: int = 3
    min_wait_seconds: float = 1.0
    max_wait_seconds: float = 60.0
    exponential_base: float = 2.0
    exponential_jitter: bool = True
    retry_on_status_codes: list[int] = Field(default_factory=lambda: [429, 503, 502, 504])


class RateLimitConfig(BaseSettings):
    requests_per_second: float = 5.0
    burst: int = 10


class CircuitBreakerConfig(BaseSettings):
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0
    half_open_max_calls: int = 3


class BatchConfig(BaseSettings):
    chunk_size: int = 10
    max_concurrency: int = 3


class ResilienceConfig(BaseSettings):
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
    api_key_env: str = "AIRTABLE_API_KEY"
    base_id_env: str = "AIRTABLE_BASE_ID"
    default_view: str = ""


class ExcelAdapterConfig(_FieldMappedAdapterConfig):
    output_path: str | None = None
    output_sheet: str = "Results"


class GoogleSheetsAdapterConfig(BaseSettings):
    api_key_env: str = "GOOGLE_SHEETS_API_KEY"


class AdaptersConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="allow")

    airtable: AirtableAdapterConfig = Field(default_factory=AirtableAdapterConfig)
    excel: ExcelAdapterConfig = Field(default_factory=ExcelAdapterConfig)
    google_sheets: GoogleSheetsAdapterConfig = Field(default_factory=GoogleSheetsAdapterConfig)


class ClientTypeConfig(BaseSettings):
    client_class: str = ""
    type: Literal["native", "litellm"] = "litellm"
    api_key_env: str = ""
    provider_prefix: str = ""
    default_model: str = ""
    fallbacks: list[str] = Field(default_factory=list)


class ClientsConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="allow")

    default_client: str = "litellm-mistral-small"
    client_types: dict[str, ClientTypeConfig] = Field(default_factory=dict)

    def get_client_type(self, name: str) -> ClientTypeConfig | None:
        return self.client_types.get(name)

    def get_available_client_types(self) -> list[str]:
        return list(self.client_types.keys())


class Config(BaseSettings):
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
        return self.clients.get_client_type(name)

    def get_default_client_type(self) -> str:
        return self.clients.default_client

    def get_available_client_types(self) -> list[str]:
        return self.clients.get_available_client_types()

    def get_adapter_api_key(self, adapter_name: str) -> str | None:
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
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    global _config
    _config = Config()
    return _config

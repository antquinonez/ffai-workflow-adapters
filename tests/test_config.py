from __future__ import annotations

import os
from unittest.mock import patch

from ffai_workflow_adapters.config import (
    AdaptersConfig,
    AirtableAdapterConfig,
    BatchConfig,
    CircuitBreakerConfig,
    ClientsConfig,
    Config,
    LoggingConfig,
    LoggingRotationConfig,
    RateLimitConfig,
    ResilienceConfig,
    RetryConfig,
    _load_all_configs,
    _load_yaml_file,
    get_config,
    reload_config,
)


class TestYamlLoading:
    def test_load_main_yaml(self):
        data = _load_yaml_file("main.yaml")
        assert "retry" in data
        assert data["retry"]["max_attempts"] == 3

    def test_load_adapters_yaml(self):
        data = _load_yaml_file("adapters.yaml")
        assert "adapters" in data
        assert "airtable" in data["adapters"]
        assert data["adapters"]["airtable"]["api_key_env"] == "AIRTABLE_API_KEY"

    def test_load_logging_yaml(self):
        data = _load_yaml_file("logging.yaml")
        assert "logging" in data
        assert data["logging"]["level"] == "INFO"

    def test_load_clients_yaml(self):
        data = _load_yaml_file("clients.yaml")
        assert "client_types" in data
        assert "litellm-mistral-small" in data["client_types"]
        assert "litellm-gpt-4o-mini" in data["client_types"]

    def test_load_missing_file(self):
        data = _load_yaml_file("nonexistent.yaml")
        assert data == {}

    def test_load_all_configs(self):
        data = _load_all_configs()
        assert "retry" in data
        assert "logging" in data
        assert "resilience" in data
        assert "adapters" in data
        assert "clients" in data


class TestRetryConfig:
    def test_defaults(self):
        cfg = RetryConfig()
        assert cfg.max_attempts == 3
        assert cfg.min_wait_seconds == 1.0
        assert cfg.max_wait_seconds == 60.0
        assert cfg.exponential_base == 2.0
        assert cfg.exponential_jitter is True
        assert 429 in cfg.retry_on_status_codes

    def test_from_yaml(self):
        data = _load_all_configs()
        cfg = RetryConfig(**data["retry"])
        assert cfg.max_attempts == 3
        assert cfg.exponential_jitter is True


class TestLoggingConfig:
    def test_defaults(self):
        cfg = LoggingConfig()
        assert cfg.level == "INFO"
        assert cfg.directory == "logs"
        assert isinstance(cfg.rotation, LoggingRotationConfig)

    def test_rotation_defaults(self):
        cfg = LoggingRotationConfig()
        assert cfg.when == "midnight"
        assert cfg.backup_count == 10


class TestAdaptersConfig:
    def test_defaults(self):
        cfg = AdaptersConfig()
        assert isinstance(cfg.airtable, AirtableAdapterConfig)
        assert cfg.airtable.api_key_env == "AIRTABLE_API_KEY"

    def test_from_yaml(self):
        data = _load_all_configs()
        cfg = AdaptersConfig(**data["adapters"])
        assert cfg.airtable.api_key_env == "AIRTABLE_API_KEY"
        assert cfg.google_sheets.api_key_env == "GOOGLE_SHEETS_API_KEY"


class TestClientsConfig:
    def test_defaults(self):
        cfg = ClientsConfig()
        assert cfg.default_client == "litellm-mistral-small"

    def test_from_yaml(self):
        data = _load_all_configs()
        cfg = ClientsConfig(**data["clients"])
        assert "litellm-mistral-small" in cfg.client_types
        assert "litellm-gpt-4o-mini" in cfg.client_types

        mistral = cfg.get_client_type("litellm-mistral-small")
        assert mistral is not None
        assert mistral.type == "litellm"
        assert mistral.provider_prefix == "mistral/"
        assert mistral.default_model == "mistral-small-latest"
        assert mistral.api_key_env == "MISTRAL_API_KEY"

        gpt = cfg.get_client_type("litellm-gpt-4o-mini")
        assert gpt is not None
        assert gpt.default_model == "gpt-4o-mini"
        assert gpt.api_key_env == "OPENAI_API_KEY"
        assert gpt.fallbacks == ["mistral/mistral-small-latest"]

    def test_get_available_client_types(self):
        data = _load_all_configs()
        cfg = ClientsConfig(**data["clients"])
        available = cfg.get_available_client_types()
        assert "litellm-mistral-small" in available
        assert "litellm-gpt-4o-mini" in available

    def test_get_missing_client_type(self):
        cfg = ClientsConfig()
        assert cfg.get_client_type("nonexistent") is None


class TestConfig:
    def test_full_config_from_yaml(self):
        cfg = Config()
        assert cfg.retry.max_attempts == 3
        assert cfg.logging.level == "INFO"
        assert cfg.adapters.airtable.api_key_env == "AIRTABLE_API_KEY"
        assert "litellm-mistral-small" in cfg.clients.client_types

    def test_env_override(self):
        with patch.dict(os.environ, {"RETRY__MAX_ATTEMPTS": "5"}):
            cfg = Config()
            assert cfg.retry.max_attempts == 5

    def test_nested_env_override(self):
        with patch.dict(os.environ, {"ADAPTERS__AIRTABLE__API_KEY_ENV": "MY_CUSTOM_KEY"}):
            cfg = Config()
            assert cfg.adapters.airtable.api_key_env == "MY_CUSTOM_KEY"

    def test_init_kwargs_override(self):
        cfg = Config(retry=RetryConfig(max_attempts=10))
        assert cfg.retry.max_attempts == 10

    def test_get_client_type_config(self):
        cfg = Config()
        mistral = cfg.get_client_type_config("litellm-mistral-small")
        assert mistral is not None
        assert mistral.type == "litellm"

    def test_get_default_client_type(self):
        cfg = Config()
        assert cfg.get_default_client_type() == "litellm-mistral-small"

    def test_get_adapter_api_key(self):
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "test_key_123"}, clear=True):
            cfg = Config()
            assert cfg.get_adapter_api_key("airtable") is None

        with patch.dict(os.environ, {"AIRTABLE_API_KEY": "airtable_key"}, clear=True):
            cfg = Config()
            assert cfg.get_adapter_api_key("airtable") == "airtable_key"

    def test_get_adapter_api_key_nonexistent(self):
        cfg = Config()
        assert cfg.get_adapter_api_key("nonexistent") is None

    def test_get_adapter_api_key_no_env_attr(self):
        cfg = Config()
        assert cfg.get_adapter_api_key("excel") is None

    def test_get_available_client_types(self):
        cfg = Config()
        available = cfg.get_available_client_types()
        assert "litellm-mistral-small" in available
        assert "litellm-gpt-4o-mini" in available


class TestNamedAdapterResolution:
    def test_resolve_no_name_returns_base(self):
        cfg = AirtableAdapterConfig(
            api_key_env="AIRTABLE_API_KEY",
            base_id_env="AIRTABLE_BASE_ID",
        )
        resolved = cfg.resolve(None)
        assert resolved.api_key_env == "AIRTABLE_API_KEY"
        assert resolved.base_id_env == "AIRTABLE_BASE_ID"

    def test_resolve_empty_name_returns_base(self):
        cfg = AirtableAdapterConfig()
        resolved = cfg.resolve("")
        assert resolved is cfg

    def test_resolve_unknown_name_returns_base(self):
        cfg = AirtableAdapterConfig()
        resolved = cfg.resolve("nonexistent")
        assert resolved is cfg

    def test_resolve_named_overrides_scalar(self):
        cfg = AirtableAdapterConfig(
            api_key_env="AIRTABLE_API_KEY",
            base_id_env="AIRTABLE_BASE_ID",
            named={
                "marketing": {"base_id_env": "AIRTABLE_MARKETING_BASE_ID"},
            },
        )
        resolved = cfg.resolve("marketing")
        assert resolved.base_id_env == "AIRTABLE_MARKETING_BASE_ID"
        assert resolved.api_key_env == "AIRTABLE_API_KEY"

    def test_resolve_named_inherits_base(self):
        cfg = AirtableAdapterConfig(
            api_key_env="AIRTABLE_API_KEY",
            base_id_env="AIRTABLE_BASE_ID",
            default_view="active",
            named={
                "research": {"base_id_env": "AIRTABLE_RESEARCH_BASE_ID"},
            },
        )
        resolved = cfg.resolve("research")
        assert resolved.base_id_env == "AIRTABLE_RESEARCH_BASE_ID"
        assert resolved.api_key_env == "AIRTABLE_API_KEY"
        assert resolved.default_view == "active"

    def test_resolve_named_merges_dicts(self):
        cfg = AirtableAdapterConfig(
            input_field_map={"Name": "name"},
            named={
                "marketing": {
                    "input_field_map": {"Task": "name", "Instructions": "prompt"},
                },
            },
        )
        resolved = cfg.resolve("marketing")
        assert resolved.input_field_map == {"Name": "name", "Task": "name", "Instructions": "prompt"}

    def test_resolve_named_output_map(self):
        cfg = AirtableAdapterConfig(
            output_field_map={"step": "Step"},
            named={
                "custom": {
                    "output_field_map": {"response": "Output", "step": "StepName"},
                },
            },
        )
        resolved = cfg.resolve("custom")
        assert resolved.output_field_map == {"step": "StepName", "response": "Output"}

    def test_resolve_named_dict_field_without_base_dict(self):
        cfg = AirtableAdapterConfig(
            input_field_map={"Name": "name"},
            named={
                "custom": {
                    "input_field_map": {"Task": "name", "Instructions": "prompt"},
                    "extra_output_columns": {"batch": "run-01"},
                },
            },
        )
        resolved = cfg.resolve("custom")
        assert resolved.input_field_map == {"Name": "name", "Task": "name", "Instructions": "prompt"}
        assert resolved.extra_output_columns == {"batch": "run-01"}

    def test_resolve_named_does_not_mutate_base(self):
        cfg = AirtableAdapterConfig(
            base_id_env="AIRTABLE_BASE_ID",
            named={
                "marketing": {"base_id_env": "AIRTABLE_MARKETING_BASE_ID"},
            },
        )
        cfg.resolve("marketing")
        assert cfg.base_id_env == "AIRTABLE_BASE_ID"


class TestResilienceConfig:
    def test_defaults(self):
        cfg = ResilienceConfig()
        assert cfg.rate_limit.requests_per_second == 5.0
        assert cfg.rate_limit.burst == 10
        assert cfg.circuit_breaker.failure_threshold == 5
        assert cfg.circuit_breaker.recovery_timeout_seconds == 30.0
        assert cfg.circuit_breaker.half_open_max_calls == 3
        assert cfg.batch.chunk_size == 10
        assert cfg.batch.max_concurrency == 3

    def test_from_yaml(self):
        data = _load_all_configs()
        assert "resilience" in data
        cfg = ResilienceConfig(**data["resilience"])
        assert cfg.rate_limit.requests_per_second == 5.0
        assert cfg.batch.chunk_size == 10

    def test_constructor_override(self):
        cfg = ResilienceConfig(rate_limit=RateLimitConfig(requests_per_second=100))
        assert cfg.rate_limit.requests_per_second == 100

    def test_env_override(self):
        with patch.dict(os.environ, {"RESILIENCE__RATE_LIMIT__REQUESTS_PER_SECOND": "100"}):
            cfg = Config()
            assert cfg.resilience.rate_limit.requests_per_second == 100.0

    def test_sub_model_defaults(self):
        assert RateLimitConfig().requests_per_second == 5.0
        assert CircuitBreakerConfig().failure_threshold == 5
        assert BatchConfig().chunk_size == 10


class TestSingleton:
    def setup_method(self):
        reload_config()

    def test_get_config_returns_same_instance(self):
        a = get_config()
        b = get_config()
        assert a is b

    def test_reload_config_returns_new_instance(self):
        a = get_config()
        b = reload_config()
        assert a is not b
        assert isinstance(b, Config)

    def test_reload_then_get(self):
        a = reload_config()
        b = get_config()
        assert a is b

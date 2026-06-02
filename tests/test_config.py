from __future__ import annotations

import os
from unittest.mock import patch

from ffai_workflow_adapters.config import (
    AdaptersConfig,
    AirtableAdapterConfig,
    ClientsConfig,
    Config,
    LoggingConfig,
    LoggingRotationConfig,
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
        assert gpt.fallbacks == ["litellm-mistral-small"]

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
        with patch.dict(os.environ, {"MISTRAL_API_KEY": "test_key_123"}):
            cfg = Config()
            # airtable uses AIRTABLE_API_KEY, not MISTRAL_API_KEY
            assert cfg.get_adapter_api_key("airtable") is None

        with patch.dict(os.environ, {"AIRTABLE_API_KEY": "airtable_key"}):
            cfg = Config()
            assert cfg.get_adapter_api_key("airtable") == "airtable_key"

    def test_get_adapter_api_key_nonexistent(self):
        cfg = Config()
        assert cfg.get_adapter_api_key("nonexistent") is None


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

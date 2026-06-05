"""Tests for _generate.py litellm_generate_fn factory."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestLitellmGenerateFn:
    def test_returns_generation_result_with_metrics(self) -> None:
        from ffai_workflow_adapters._generate import litellm_generate_fn

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "hello world"
        mock_resp.usage.prompt_tokens = 50
        mock_resp.usage.completion_tokens = 10

        with patch("litellm.completion", return_value=mock_resp) as mock_comp, \
             patch("litellm.completion_cost", return_value=0.001):
            fn = litellm_generate_fn(
                model="mistral/mistral-small-latest",
                api_key="test-key",
                temperature=0.7,
                max_tokens=512,
            )
            result = fn("test prompt")

        mock_comp.assert_called_once_with(
            model="mistral/mistral-small-latest",
            messages=[{"role": "user", "content": "test prompt"}],
            api_key="test-key",
            temperature=0.7,
            max_tokens=512,
        )

        assert result.text == "hello world"
        assert result.usage.input_tokens == 50
        assert result.usage.output_tokens == 10
        assert result.cost_usd == 0.001
        assert result.duration_ms > 0

    def test_handles_empty_response(self) -> None:
        from ffai_workflow_adapters._generate import litellm_generate_fn

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = None
        mock_resp.usage.prompt_tokens = 20
        mock_resp.usage.completion_tokens = 0

        with patch("litellm.completion", return_value=mock_resp), \
             patch("litellm.completion_cost", return_value=0.0):
            fn = litellm_generate_fn(model="test/model", api_key="k")
            result = fn("prompt")

        assert result.text == ""
        assert result.cost_usd == 0.0

    def test_handles_none_cost(self) -> None:
        from ffai_workflow_adapters._generate import litellm_generate_fn

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "ok"
        mock_resp.usage.prompt_tokens = 10
        mock_resp.usage.completion_tokens = 5

        with patch("litellm.completion", return_value=mock_resp), \
             patch("litellm.completion_cost", return_value=None):
            fn = litellm_generate_fn(model="test/model", api_key="k")
            result = fn("prompt")

        assert result.cost_usd == 0.0

    def test_is_callable(self) -> None:
        from ffai_workflow_adapters._generate import litellm_generate_fn

        fn = litellm_generate_fn(model="m", api_key="k")
        assert callable(fn)

    def test_default_parameters(self) -> None:
        from ffai_workflow_adapters._generate import litellm_generate_fn

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "x"
        mock_resp.usage.prompt_tokens = 1
        mock_resp.usage.completion_tokens = 1

        with patch("litellm.completion", return_value=mock_resp) as mock_comp, \
             patch("litellm.completion_cost", return_value=0.0):
            fn = litellm_generate_fn(model="m", api_key="k")
            fn("prompt")

        _, kwargs = mock_comp.call_args
        assert kwargs["temperature"] == 0.5
        assert kwargs["max_tokens"] == 1024

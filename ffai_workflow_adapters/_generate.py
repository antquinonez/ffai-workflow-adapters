"""Generate function factory for ffai RAG aquery() backed by litellm."""
from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Callable


def litellm_generate_fn(
    model: str,
    api_key: str,
    temperature: float = 0.5,
    max_tokens: int = 1024,
) -> Callable[[str], Any]:
    """Create a sync generate_fn for ``RAG.aquery()`` backed by litellm.

    Returns a callable that calls ``litellm.completion()`` and wraps the
    response in a ``GenerationResult`` with usage, cost, and timing metadata.
    This is required because returning a plain string from ``generate_fn``
    causes ``aquery()`` to silently set usage, cost_usd, and duration_ms to
    ``None`` / ``0.0``.

    Args:
        model: LiteLLM model string (e.g. ``"mistral/mistral-small-latest"``).
        api_key: API key for the model provider.
        temperature: Sampling temperature. Defaults to 0.5.
        max_tokens: Maximum tokens in the response. Defaults to 1024.

    Returns:
        A sync callable ``(prompt: str) -> GenerationResult`` suitable for
        passing to ``rag.aquery(prompt, generate_fn=...)``.
    """
    import litellm
    from ffai.rag.types import GenerationResult

    def generate(prompt: str) -> GenerationResult:
        t0 = time.perf_counter()
        resp = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        cost = litellm.completion_cost(resp) or 0.0
        usage = SimpleNamespace(
            input_tokens=resp.get("usage", {}).get("prompt_tokens", 0) if isinstance(resp, dict) else resp.usage.prompt_tokens,  # type: ignore[union-attr]
            output_tokens=resp.get("usage", {}).get("completion_tokens", 0) if isinstance(resp, dict) else resp.usage.completion_tokens,  # type: ignore[union-attr]
        )
        choices = resp.get("choices", []) if isinstance(resp, dict) else resp.choices  # type: ignore[union-attr]
        text = choices[0].message.content or ""  # type: ignore[union-attr]
        return GenerationResult(
            text=text,
            usage=usage,
            cost_usd=cost,
            duration_ms=elapsed_ms,
        )

    return generate

"""Unified LLM call helper — supports OpenAI-compatible endpoints and Ollama.

Usage:
    from agno_plus.adapters.llm import call_llm

    text = call_llm(
        "Describe this column: qty",
        backend="openai",
        model="gpt-4o-mini",
        api_key="sk-...",
    )

    json_str = call_llm(
        "Extract fields as JSON",
        backend="ollama",
        model="llama3.2",
        base_url="http://localhost:11434",
        json_response=True,
    )
"""

from __future__ import annotations


def call_llm(
    prompt: str,
    *,
    backend: str,
    model: str,
    api_key: str = "",
    base_url: str = "",
    json_response: bool = False,
    max_tokens: int = 0,
    temperature: float = 0.0,
) -> str:
    """Call an LLM and return the assistant's text response.

    Args:
        prompt: The user message to send.
        backend: "openai" or "ollama".
        model: Model identifier (e.g. "gpt-4o-mini", "llama3.2").
        api_key: API key (required for "openai").
        base_url: Base URL (required for "ollama", e.g. "http://localhost:11434").
        json_response: Request JSON output mode (structured extraction).
        max_tokens: Maximum tokens in the response (0 = provider default).
        temperature: Sampling temperature (0 = deterministic).

    Returns:
        Raw text content of the assistant's reply.

    Raises:
        ValueError: If backend is unsupported.
        RuntimeError: If the LLM call fails.
    """
    if backend == "openai":
        return _call_openai(prompt, model=model, api_key=api_key,
                            json_response=json_response, max_tokens=max_tokens,
                            temperature=temperature)
    if backend == "ollama":
        return _call_ollama(prompt, model=model, base_url=base_url,
                            json_response=json_response, max_tokens=max_tokens,
                            temperature=temperature)
    raise ValueError(f"Unsupported LLM backend: {backend!r}. Use 'openai' or 'ollama'.")


def _call_openai(
    prompt: str,
    *,
    model: str,
    api_key: str,
    json_response: bool,
    max_tokens: int,
    temperature: float,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if json_response:
        kwargs["response_format"] = {"type": "json_object"}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens

    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _call_ollama(
    prompt: str,
    *,
    model: str,
    base_url: str,
    json_response: bool,
    max_tokens: int,
    temperature: float,
) -> str:
    import httpx

    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": temperature},
    }
    if json_response:
        payload["format"] = "json"
    if max_tokens:
        payload["options"]["num_predict"] = max_tokens

    resp = httpx.post(
        f"{base_url.rstrip('/')}/api/chat",
        json=payload,
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]

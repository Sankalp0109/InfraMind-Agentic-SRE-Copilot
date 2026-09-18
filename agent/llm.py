"""Provider-agnostic call_llm(messages, tools) -> response, via litellm.

This is the one piece of the stack that intentionally isn't hand-rolled —
MCP and the RAG pipeline are the protocol/retrieval work worth doing from
scratch; calling an LLM provider is incidental plumbing. Tries a list of
free-tier models in order, falling through to the next on a rate limit (or
similar transient failure) from the current one — Groq's free tier turned
out to have a very tight 8,000 TPM cap that a multi-tool ReAct loop burns
through fast, so a single-provider setup wasn't resilient enough for
comfortable use. Swapping/reordering providers means editing MODEL_CHAIN,
not rewriting the agent loop — that's the actual point of going through
litellm instead of a provider SDK directly.
"""

import os
import sys
import time

import litellm
import openai
from opentelemetry.trace import Status, StatusCode

from tracing import get_tracer

# Tried in order; falls through to the next model on a rate limit, missing
# model, or transient provider error from the current one. Override via
# INFRAMIND_LLM_MODELS (comma-separated) — e.g. to add Cerebras once a key
# is available, or to reorder.
MODEL_CHAIN = [
    m.strip()
    for m in os.environ.get(
        "INFRAMIND_LLM_MODELS",
        "groq/openai/gpt-oss-20b,gemini/gemini-3.6-flash",
    ).split(",")
    if m.strip()
]

# Groq's free-tier TPM rate limit reserves capacity for the request's full
# max_tokens up front (not just what's actually generated) — leaving
# max_tokens unset lets litellm/the provider default to the model's max
# output (large, for a reasoning model like gpt-oss), which alone can blow
# a tight free-tier per-minute budget before a single token is generated.
# Capped explicitly for every model in the chain; override via env var if a
# bigger budget is available (e.g. a paid tier). 1024 was tried first and
# was too tight for gpt-oss-20b specifically: it's a reasoning model that
# burns hundreds of tokens on internal chain-of-thought before emitting a
# tool call (observed 306/318 completion tokens as "reasoning" on a trivial
# request), so a low cap truncates it mid-tool-call and Groq's parser
# rejects the incomplete JSON with a 400 rather than a rate-limit error.
MAX_TOKENS = int(os.environ.get("INFRAMIND_LLM_MAX_TOKENS", "2048"))

_PROVIDER_KEY_ENV = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

# Free-tier limits are per-minute — retrying the whole chain after a short
# wait recovers from "every configured model got rate-limited within this
# minute" (observed in practice: Groq's TPM limit and Gemini's 5 RPM limit
# for gemini-3.6-flash both get exhausted within a single multi-turn ReAct
# investigation), rather than giving up after one pass through the chain.
CHAIN_RETRIES = int(os.environ.get("INFRAMIND_LLM_CHAIN_RETRIES", "3"))
CHAIN_RETRY_BACKOFF_SECONDS = int(os.environ.get("INFRAMIND_LLM_RETRY_BACKOFF", "20"))


def _configured_models() -> list[str]:
    """MODEL_CHAIN entries whose required API key is actually set — skipped
    silently rather than attempted-and-failed, so an unconfigured fallback
    provider doesn't burn a request just to hit a predictable auth error."""
    configured = []
    for model in MODEL_CHAIN:
        provider = model.split("/", 1)[0]
        env_var = _PROVIDER_KEY_ENV.get(provider)
        if env_var and not os.environ.get(env_var):
            continue
        configured.append(model)
    return configured


def mcp_tools_to_llm_tools(mcp_tools: list[dict]) -> list[dict]:
    """Convert MCP's tools/list shape ({name, description, inputSchema}) into
    the OpenAI-compatible function-calling shape litellm expects across
    providers."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["inputSchema"],
            },
        }
        for tool in mcp_tools
    ]


def _try_chain(models: list[str], kwargs: dict):
    """One pass through the fallback chain. Returns the response from the
    first model that succeeds, or the last exception raised if every model
    in this pass failed."""
    tracer = get_tracer()
    last_exc: Exception | None = None
    for model in models:
        with tracer.start_as_current_span("agent.llm_call") as span:
            span.set_attribute("llm.model", model)
            try:
                response = litellm.completion(model=model, **kwargs)
                span.set_attribute("llm.usage.total_tokens", response.usage.total_tokens)
                return response
            except openai.APIError as exc:
                # The true common base for every litellm-mapped provider error
                # (rate limits, bad requests, timeouts, service errors, ...).
                # litellm.APIError is NOT this base — it's one specific sibling
                # exception type among many, despite the generic-sounding name;
                # catching it alone silently misses most real failures (found by
                # hitting exactly that gap: a BadRequestError from a truncated
                # tool call propagated uncaught instead of falling through).
                span.set_status(Status(StatusCode.ERROR))
                span.set_attribute("llm.error", exc.__class__.__name__)
                print(f"[llm] {model} failed ({exc.__class__.__name__}), trying next model...", file=sys.stderr)
                last_exc = exc
    return last_exc


def call_llm(messages: list[dict], tools: list[dict] | None = None):
    """One LLM call, tried against each configured model in MODEL_CHAIN in
    order until one succeeds, retrying the whole chain with backoff if every
    model fails (free-tier limits are per-minute and recover quickly).
    Returns litellm's ModelResponse (OpenAI-compatible shape) — the caller
    reads response.choices[0].message, whose `.tool_calls` (if any) each
    have `.id`, `.function.name`, `.function.arguments` (a JSON string)."""
    models = _configured_models()
    if not models:
        configured_vars = ", ".join(_PROVIDER_KEY_ENV[m.split("/", 1)[0]] for m in MODEL_CHAIN)
        raise RuntimeError(
            f"No API key set for any model in INFRAMIND_LLM_MODELS ({MODEL_CHAIN}). "
            f"Set one of: {configured_vars}"
        )

    kwargs: dict = {"messages": messages, "max_tokens": MAX_TOKENS}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    last_exc: Exception | None = None
    for attempt in range(CHAIN_RETRIES):
        result = _try_chain(models, kwargs)
        if not isinstance(result, Exception):
            return result
        last_exc = result
        if attempt < CHAIN_RETRIES - 1:
            print(
                f"[llm] all models failed (attempt {attempt + 1}/{CHAIN_RETRIES}), "
                f"waiting {CHAIN_RETRY_BACKOFF_SECONDS}s before retrying the chain...",
                file=sys.stderr,
            )
            time.sleep(CHAIN_RETRY_BACKOFF_SECONDS)

    raise RuntimeError(
        f"All configured LLM models failed after {CHAIN_RETRIES} attempts: {models}. Last error: {last_exc}"
    ) from last_exc

"""ReAct orchestrator: alert -> reason -> call tools -> synthesize diagnosis.

Ties together mcp_client (real MCP tool access, not an in-process shortcut),
llm (provider-agnostic call_llm), guardrails (read_only/mutating gating),
and prompts (system prompt).
"""

import json

from guardrails import needs_approval, request_approval
from llm import call_llm, mcp_tools_to_llm_tools
from mcp_client import McpClient
from prompts import SYSTEM_PROMPT
from tracing import get_tracer

MAX_TURNS = 15  # safety cap on ReAct iterations, in case the model loops without converging


def _assistant_message_dict(message) -> dict:
    """Build the plain-dict form of an assistant turn with tool calls, for
    appending back into message history. Built explicitly rather than via
    message.model_dump() so this doesn't depend on litellm's exact pydantic
    field set matching what providers expect back on the next turn."""
    return {
        "role": "assistant",
        "content": message.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in message.tool_calls
        ],
    }


def run_investigation(
    alert_message: str,
    approval_callback=None,
    mcp_client: McpClient | None = None,
    on_event=None,
) -> dict:
    """Run one investigation to completion.

    approval_callback(tool_name, arguments) -> bool defaults to an
    interactive CLI prompt (guardrails.request_approval); the eval harness
    (Phase 5) should pass its own non-interactive callback, since a batch of
    scenarios can't block on stdin.

    mcp_client lets a caller (tests, the eval harness) reuse one already-running
    client instead of spawning a fresh subprocess per investigation; defaults
    to spawning and closing one for this call only.

    on_event(event: dict), if given, is called synchronously the moment each
    trace step happens — this is what lets a CLI stream the investigation
    live instead of only seeing the full trace after the fact. The full
    trace is still built and returned regardless, for logging/eval.

    Returns {"trace": [...], "diagnosis": str} — trace is the full
    thought/action/observation sequence, for logging and eval.
    """
    approval_callback = approval_callback or request_approval
    owns_client = mcp_client is None
    client = mcp_client or McpClient()

    trace: list[dict] = []

    def emit(event: dict) -> None:
        trace.append(event)
        if on_event:
            on_event(event)

    tracer = get_tracer()
    try:
        with tracer.start_as_current_span("agent.investigation") as inv_span:
            inv_span.set_attribute("agent.alert_message", alert_message)

            tools = client.list_tools()
            llm_tools = mcp_tools_to_llm_tools(tools)

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": alert_message},
            ]

            for turn in range(MAX_TURNS):
                response = call_llm(messages, tools=llm_tools)
                message = response.choices[0].message

                if not message.tool_calls:
                    # An empty content with no tool calls is not a real "nothing
                    # more to do" answer — observed in practice after several
                    # consecutive tool failures: the model spent its whole
                    # max_tokens budget reasoning about the failures and never
                    # completed a response. Treat that honestly rather than
                    # silently reporting an empty diagnosis as if it were valid.
                    diagnosis = message.content or (
                        "The model produced no tool call and no answer "
                        f"(finish_reason={response.choices[0].finish_reason!r}) — likely ran out of "
                        "its token budget reasoning about repeated tool failures. Try raising "
                        "INFRAMIND_LLM_MAX_TOKENS, or investigate manually."
                    )
                    inv_span.set_attribute("agent.turns", turn + 1)
                    inv_span.set_attribute("agent.diagnosis", diagnosis)
                    emit({"type": "diagnosis", "content": diagnosis})
                    return {"trace": trace, "diagnosis": diagnosis}

                messages.append(_assistant_message_dict(message))

                for tool_call in message.tool_calls:
                    name = tool_call.function.name
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                    emit({"type": "thought", "tool": name, "arguments": arguments})

                    if needs_approval(name) and not approval_callback(name, arguments):
                        content = [{"type": "text", "text": f"Denied by human approver: {name} was not run."}]
                        is_error = True
                        emit({"type": "action", "tool": name, "approved": False})
                    else:
                        content, is_error = client.call_tool(name, arguments)
                        emit({"type": "action", "tool": name, "approved": True})

                    observation_text = "\n".join(c.get("text", "") for c in content)
                    emit(
                        {"type": "observation", "tool": name, "text": observation_text, "is_error": is_error}
                    )

                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": observation_text})

            final = "Investigation did not converge within the turn limit."
            inv_span.set_attribute("agent.turns", MAX_TURNS)
            inv_span.set_attribute("agent.diagnosis", final)
            emit({"type": "diagnosis", "content": final})
            return {"trace": trace, "diagnosis": final}
    finally:
        if owns_client:
            client.close()

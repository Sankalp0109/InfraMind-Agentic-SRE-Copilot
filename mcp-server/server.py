"""InfraMind MCP server: JSON-RPC 2.0, hand-rolled (no MCP SDK).

Primarily speaks MCP protocol revision 2026-07-28 (see protocol.py) — the
current, stateless-per-request model. Also accepts a legacy `initialize`
handshake (2025-11-25) as a compatibility shim for today's tooling; see the
comment on LEGACY_PROTOCOL_VERSION in protocol.py for why.

`dispatch()` is the transport-agnostic protocol core: given a parsed
JSON-RPC message, it returns the response dict (or None for a notification).
Two transports sit on top of it:
  - stdio (this file's `main()`): one JSON-RPC message per line on
    stdin/stdout, per
    https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio
  - Streamable HTTP (http_transport.py): a single POST endpoint.

The legacy `initialize` shim is stdio-only. Streamable HTTP in this spec
revision has no session concept at all (removed relative to earlier
revisions) — a global "has this process seen initialize" flag, which is
correct for a stdio child process scoped to one caller, would leak legacy
state across unrelated HTTP clients. http_transport.py calls
`dispatch(message, allow_legacy=False)` accordingly.
"""

import json
import sys

from protocol import (
    LEGACY_PROTOCOL_VERSION,
    META_PROTOCOL_VERSION,
    META_SERVER_INFO,
    PROTOCOL_VERSION,
    SERVER_INFO,
    ProtocolError,
    check_protocol_version,
)
from resources import runbooks
from tools import TOOL_HANDLERS, TOOLS

CAPABILITIES = {"tools": {"listChanged": False}, "resources": {}}


class _LegacySession:
    """Tracks whether a legacy `initialize` handshake has completed.

    Scoped to this stdio process, per the legacy transport's session model —
    exactly the kind of connection state the modern protocol doesn't need,
    since modern requests are self-contained. Not used by the HTTP transport;
    see the module docstring.
    """

    initialized = False


_legacy = _LegacySession()


def _result(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code: int, message: str, data: dict | None = None) -> dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": error}


def handle_server_discover(params: dict) -> dict:
    return {
        "resultType": "complete",
        "supportedVersions": [PROTOCOL_VERSION],
        "capabilities": CAPABILITIES,
        "_meta": {META_SERVER_INFO: SERVER_INFO},
        "instructions": (
            "InfraMind observability tools for the OpenTelemetry Demo: "
            "metrics, traces, logs, alerts, and incident actions."
        ),
    }


def handle_tools_list(params: dict) -> dict:
    return {"resultType": "complete", "tools": TOOLS}


def handle_tools_call(params: dict) -> dict:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise ProtocolError(-32602, f"Unknown tool: {name}")

    try:
        content, is_error = handler(**arguments)
    except TypeError as exc:
        # Bad/missing arguments for the tool's signature — a protocol-level
        # error, not a tool execution error, since the call itself is malformed.
        raise ProtocolError(-32602, f"Invalid arguments for tool '{name}': {exc}") from exc

    return {"resultType": "complete", "content": content, "isError": is_error}


def handle_resources_list(params: dict) -> dict:
    return {"resultType": "complete", "resources": runbooks.list_resources()}


def handle_resources_read(params: dict) -> dict:
    uri = params.get("uri")
    contents = runbooks.read_resource(uri)  # raises ProtocolError if not found
    return {"resultType": "complete", "contents": contents}


def handle_initialize(params: dict) -> dict:
    """Legacy handshake entry point (2025-11-25 and earlier, stdio only). See
    LEGACY_PROTOCOL_VERSION in protocol.py for why this exists."""
    _legacy.initialized = True
    return {
        "protocolVersion": LEGACY_PROTOCOL_VERSION,
        "capabilities": CAPABILITIES,
        "serverInfo": SERVER_INFO,
    }


def handle_initialized_notification(params: dict) -> dict:
    return {}  # legacy session confirmed by the client; nothing to do


METHODS = {
    "server/discover": handle_server_discover,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "resources/list": handle_resources_list,
    "resources/read": handle_resources_read,
    "initialize": handle_initialize,
    "notifications/initialized": handle_initialized_notification,
}


def dispatch(message: dict, allow_legacy: bool = True) -> dict | None:
    """Transport-agnostic protocol core. Returns the JSON-RPC response dict,
    or None if the message was a notification (no response expected) or not
    a request/notification we understand at all."""
    is_notification = "id" not in message
    id_ = message.get("id")
    method = message.get("method")

    if method is None:
        return None

    params = message.get("params") or {}

    try:
        meta = params.get("_meta") or {}
        # A modern request declares its version explicitly and is checked
        # regardless of any legacy session — the two eras are independent.
        # `initialize` itself, and any request once a legacy session is
        # established, carries no _meta and is exempt from this check.
        in_legacy_session = allow_legacy and (method == "initialize" or _legacy.initialized)
        if meta.get(META_PROTOCOL_VERSION) or not in_legacy_session:
            check_protocol_version(meta)

        handler = METHODS.get(method)
        if handler is None:
            raise ProtocolError(-32601, f"Method not found: {method}")

        result = handler(params)
        return None if is_notification else _result(id_, result)
    except ProtocolError as exc:
        return None if is_notification else _error(id_, exc.code, exc.message, exc.data)
    except Exception as exc:  # noqa: BLE001 - last-resort protocol error, never crash the loop
        return None if is_notification else _error(id_, -32603, f"Internal error: {exc}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = _error(None, -32700, "Parse error")
        else:
            response = dispatch(message)

        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

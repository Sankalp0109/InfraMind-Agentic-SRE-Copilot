"""InfraMind MCP server: JSON-RPC 2.0 over stdio, hand-rolled (no MCP SDK).

Primarily speaks MCP protocol revision 2026-07-28 (see protocol.py) — the
current, stateless-per-request model. Also accepts a legacy `initialize`
handshake (2025-11-25) as a compatibility shim for today's tooling; see the
comment on LEGACY_PROTOCOL_VERSION in protocol.py for why. Both eras dispatch
to the same tool registry below.

One JSON-RPC message per line on stdin/stdout, per the stdio transport spec:
https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio
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
from tools import TOOL_HANDLERS, TOOLS

CAPABILITIES = {"tools": {"listChanged": False}}


class _LegacySession:
    """Tracks whether a legacy `initialize` handshake has completed.

    Scoped to this stdio process, per the legacy transport's session model —
    exactly the kind of connection state the modern protocol above doesn't
    need, since modern requests are self-contained.
    """

    initialized = False


_legacy = _LegacySession()


def _write(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _send_result(id_, result: dict) -> None:
    _write({"jsonrpc": "2.0", "id": id_, "result": result})


def _send_error(id_, code: int, message: str, data: dict | None = None) -> None:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    _write({"jsonrpc": "2.0", "id": id_, "error": error})


def handle_server_discover(id_, params: dict) -> None:
    _send_result(
        id_,
        {
            "resultType": "complete",
            "supportedVersions": [PROTOCOL_VERSION],
            "capabilities": CAPABILITIES,
            "_meta": {META_SERVER_INFO: SERVER_INFO},
            "instructions": (
                "InfraMind observability tools for the OpenTelemetry Demo: "
                "metrics, traces, logs, alerts, and incident actions."
            ),
        },
    )


def handle_tools_list(id_, params: dict) -> None:
    _send_result(id_, {"resultType": "complete", "tools": TOOLS})


def handle_tools_call(id_, params: dict) -> None:
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

    _send_result(id_, {"resultType": "complete", "content": content, "isError": is_error})


def handle_initialize(id_, params: dict) -> None:
    """Legacy handshake entry point (2025-11-25 and earlier). See
    LEGACY_PROTOCOL_VERSION in protocol.py for why this exists."""
    _legacy.initialized = True
    _send_result(
        id_,
        {
            "protocolVersion": LEGACY_PROTOCOL_VERSION,
            "capabilities": CAPABILITIES,
            "serverInfo": SERVER_INFO,
        },
    )


def handle_initialized_notification(id_, params: dict) -> None:
    pass  # legacy session confirmed by the client; nothing to do


METHODS = {
    "server/discover": handle_server_discover,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "initialize": handle_initialize,
    "notifications/initialized": handle_initialized_notification,
}


def _handle_message(message: dict) -> None:
    is_notification = "id" not in message
    id_ = message.get("id")
    method = message.get("method")

    if method is None:
        # Not a request/notification we understand (e.g. a response echoed
        # back to us, which a well-behaved client should never send on stdio).
        return

    params = message.get("params") or {}

    try:
        meta = params.get("_meta") or {}
        # A modern request declares its version explicitly and is checked
        # regardless of any legacy session — the two eras are independent.
        # `initialize` itself, and any request once a legacy session is
        # established, carries no _meta and is exempt from this check.
        if meta.get(META_PROTOCOL_VERSION) or not (method == "initialize" or _legacy.initialized):
            check_protocol_version(meta)

        handler = METHODS.get(method)
        if handler is None:
            raise ProtocolError(-32601, f"Method not found: {method}")

        handler(id_, params)
    except ProtocolError as exc:
        if not is_notification:
            _send_error(id_, exc.code, exc.message, exc.data)
    except Exception as exc:  # noqa: BLE001 - last-resort protocol error, never crash the loop
        if not is_notification:
            _send_error(id_, -32603, f"Internal error: {exc}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _send_error(None, -32700, "Parse error")
            continue
        _handle_message(message)


if __name__ == "__main__":
    main()

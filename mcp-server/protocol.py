"""MCP protocol revision 2026-07-28: constants and _meta helpers.

This revision replaced the old stateful `initialize` handshake with a
stateless model — every request carries its protocol version (and optional
client identity/capabilities) in `_meta`, and the server accepts or rejects
each request independently. See:
https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning
"""

PROTOCOL_VERSION = "2026-07-28"

# Legacy (initialize-handshake) revision this server also accepts, purely as
# a compatibility shim: as of this writing the official MCP Inspector CLI
# (@modelcontextprotocol/inspector 2.6.0) always opens a stdio connection
# with a legacy `initialize` request rather than probing `server/discover`
# first, despite the spec's own recommendation for dual-era clients. Without
# this, the reference tool used to verify this server can't talk to it at
# all. This server is still modern-first/primary — this is the minimum
# needed to make real verification tooling work today.
LEGACY_PROTOCOL_VERSION = "2025-11-25"

META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

SERVER_INFO = {"name": "inframind-mcp-server", "version": "0.1.0"}


class ProtocolError(Exception):
    """A JSON-RPC-level error: maps directly to a JSON-RPC `error` object."""

    def __init__(self, code: int, message: str, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class UnsupportedProtocolVersionError(ProtocolError):
    def __init__(self, requested: str | None, supported: list[str]):
        super().__init__(
            code=-32022,
            message="Unsupported protocol version",
            data={"supported": supported, "requested": requested},
        )


def check_protocol_version(meta: dict) -> None:
    """Validate _meta.protocolVersion on an incoming request.

    Raises UnsupportedProtocolVersionError if missing or not exactly the
    one version this server implements.
    """
    requested = (meta or {}).get(META_PROTOCOL_VERSION)
    if requested != PROTOCOL_VERSION:
        raise UnsupportedProtocolVersionError(requested, [PROTOCOL_VERSION])

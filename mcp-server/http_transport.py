"""Streamable HTTP transport (MCP spec 2026-07-28), a thin adapter over
server.dispatch(). Single POST endpoint, stateless — no legacy `initialize`
fallback here; see server.py's module docstring for why that's stdio-only.

Implements enough of this revision's transport requirements to be a real,
correct server for this project's own tool set: Origin validation (DNS
rebinding protection), localhost-only binding, bearer-token auth, and the
MCP-Protocol-Version / Mcp-Method / Mcp-Name header-vs-body validation this
revision requires. Deliberately does not implement SSE streaming responses
(a server may always choose the plain JSON response instead — legal per
spec), subscriptions/listen, or x-mcp-header parameter mirroring: none of
InfraMind's tools need progress notifications, long-lived subscriptions, or
header-mirrored parameters, so building that machinery now would be
speculative.
"""

import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from protocol import META_PROTOCOL_VERSION
from server import dispatch

AUTH_TOKEN = os.environ.get("MCP_BEARER_TOKEN")
_DEFAULT_ORIGINS = "http://localhost,http://127.0.0.1"
ALLOWED_ORIGINS = {o.strip() for o in os.environ.get("MCP_ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()}

_NAME_BEARING_METHODS = {
    "tools/call": "name",
    "resources/read": "uri",
    "prompts/get": "name",
}


def _rpc_error(code: int, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}}, status_code=status_code)


async def mcp_endpoint(request: Request) -> Response:
    # Origin validation — required by spec to prevent DNS rebinding attacks.
    # Absent Origin (curl, server-to-server) is fine; only a present-but-not-
    # allowed value is rejected.
    origin = request.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        return JSONResponse({"error": "Forbidden origin"}, status_code=403)

    # Bearer auth — only enforced if a token is actually configured, so local
    # dev without MCP_BEARER_TOKEN set still works out of the box. This is
    # what the build plan's "bearer-token check in the transport layer" step
    # means in practice: it belongs here, not on stdio, where the transport
    # itself (a subprocess the client spawned) already is the trust boundary.
    if AUTH_TOKEN:
        if request.headers.get("authorization") != f"Bearer {AUTH_TOKEN}":
            return JSONResponse({"error": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})

    try:
        message = await request.json()
    except Exception:
        return _rpc_error(-32700, "Parse error", 400)

    if not isinstance(message, dict) or "method" not in message:
        return _rpc_error(-32600, "Invalid Request: body must be a single JSON-RPC request or notification", 400)

    method = message["method"]
    params = message.get("params") or {}
    meta = params.get("_meta") or {}

    # Server Validation: required headers must be present and match the body.
    proto_header = request.headers.get("mcp-protocol-version")
    if not proto_header:
        return _rpc_error(-32020, "Missing required MCP-Protocol-Version header", 400)
    if proto_header != meta.get(META_PROTOCOL_VERSION):
        return _rpc_error(-32020, f"MCP-Protocol-Version header '{proto_header}' does not match body _meta value", 400)

    if request.headers.get("mcp-method") != method:
        return _rpc_error(-32020, f"Mcp-Method header does not match body method '{method}'", 400)

    name_field = _NAME_BEARING_METHODS.get(method)
    if name_field is not None:
        expected = params.get(name_field)
        if request.headers.get("mcp-name") != expected:
            return _rpc_error(-32020, f"Mcp-Name header does not match body params.{name_field}", 400)

    is_notification = "id" not in message
    response = dispatch(message, allow_legacy=False)

    if is_notification:
        # dispatch() already ran the handler for its side effect; per spec a
        # notification the server accepts gets 202 with no body.
        return Response(status_code=202)

    return JSONResponse(response)


app = Starlette(routes=[Route("/mcp", mcp_endpoint, methods=["POST"])])


if __name__ == "__main__":
    import uvicorn

    # Bind to localhost only, per the spec's own recommendation for locally-run servers.
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MCP_HTTP_PORT", "8765")))

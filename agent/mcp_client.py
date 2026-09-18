"""Minimal MCP client: spawns the InfraMind MCP server as a stdio subprocess
and speaks the same JSON-RPC 2.0 protocol (2026-07-28) the server
implements — hand-rolled to match, for the same reason the server itself is
hand-rolled rather than using an SDK: MCP is the centerpiece skill of this
project, on both ends of the wire, not just the server side. The agent
talks to the server as a real MCP client, not by importing its tool
registry directly in-process — that separation is the actual point of
building MCP at all.

One subprocess is spawned per McpClient and kept alive for the whole agent
run rather than respawned per call — search_past_incidents pays a real
one-time cost loading its embedding/cross-encoder models (observed tens of
seconds on this host under load), and paying that on every tool call would
make the agent unusably slow.
"""

import json
import subprocess
import sys
from pathlib import Path

from opentelemetry.trace import Status, StatusCode

from tracing import get_tracer

PROTOCOL_VERSION = "2026-07-28"
META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"

_SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp-server" / "server.py"


class McpClient:
    def __init__(self, python_executable: str | None = None):
        python_executable = python_executable or sys.executable
        self._proc = subprocess.Popen(
            [python_executable, str(_SERVER_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # let the server's stderr (model-load progress, warnings) pass through
            text=True,
            bufsize=1,  # line-buffered, needed for synchronous request/response over pipes
        )
        self._next_id = 1

    def _request(self, method: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        params["_meta"] = {META_PROTOCOL_VERSION: PROTOCOL_VERSION}
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        self._next_id += 1

        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(json.dumps(message) + "\n")
        self._proc.stdin.flush()

        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed its output unexpectedly (check its stderr)")

        response = json.loads(line)
        if "error" in response:
            err = response["error"]
            raise RuntimeError(f"MCP error {err['code']}: {err['message']}")
        return response["result"]

    def list_tools(self) -> list[dict]:
        return self._request("tools/list")["tools"]

    def call_tool(self, name: str, arguments: dict) -> tuple[list[dict], bool]:
        tracer = get_tracer()
        with tracer.start_as_current_span("mcp.tool_call") as span:
            span.set_attribute("mcp.tool.name", name)
            span.set_attribute("mcp.tool.arguments", json.dumps(arguments))
            result = self._request("tools/call", {"name": name, "arguments": arguments})
            is_error = result["isError"]
            span.set_attribute("mcp.tool.is_error", is_error)
            if is_error:
                span.set_status(Status(StatusCode.ERROR))
            return result["content"], is_error

    def close(self) -> None:
        if self._proc.stdin:
            self._proc.stdin.close()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()

    def __enter__(self) -> "McpClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

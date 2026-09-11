# InfraMind

An agentic SRE copilot that investigates production incidents by combining live observability tools (through a hand-built MCP server) with historical postmortems (through a hybrid RAG pipeline), running against the real [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo).

See [`InfraMind_Final_Plan.md`](./InfraMind_Final_Plan.md) for the full build plan.

## Environment

The OpenTelemetry Demo lives in `otel-demo/` as a git submodule, pinned to release `3.0.0`.

```
git submodule update --init --recursive
cd otel-demo
DEMO_VERSION=3.0.0 docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml up --detach
```

`DEMO_VERSION=3.0.0` overrides the submodule's own `.env` default of `latest` — as of this writing, the `latest`-tagged `payment` image on `ghcr.io/open-telemetry/demo` is broken (crashes on boot with `Cannot find module '@opentelemetry/auto-instrumentations-node/register'`), so images are pinned explicitly to the `3.0.0` release tag to match the checked-out submodule commit.

Once running:

| Service | URL |
|---|---|
| Web store | http://localhost:8080/ |
| Feature flags (flagd UI) | http://localhost:8080/feature |
| Grafana | http://localhost:8080/grafana/ |
| Jaeger UI | http://localhost:8080/jaeger/ui/ |
| Prometheus | http://localhost:9090/ |

Grafana and Jaeger are published to random ephemeral host ports in the upstream compose file (bare `"${GRAFANA_PORT}"`/`"${JAEGER_UI_PORT}"` entries, not `host:container` pairs), so they're not reliably reachable on `:3000`/`:16686` directly — access them through the `frontend-proxy` at `:8080` instead, which routes `/grafana/` and `/jaeger/` by path (see `src/frontend-proxy/envoy.tmpl.yaml`). Prometheus is the one service published with a fixed host port.

See [`NOTES.md`](./NOTES.md) for the Prometheus/Jaeger query APIs and log access patterns the MCP server's tools wrap.

To stop everything:
```
cd otel-demo
DEMO_VERSION=3.0.0 docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml down
```

## Python environment

```
/opt/anaconda3/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -r mcp-server/requirements.txt
```

## MCP server

Hand-rolled JSON-RPC 2.0 server (no MCP SDK), speaking the current MCP spec (`2026-07-28`) with a legacy `initialize` compatibility shim on stdio. See [`IMPLEMENTATION_DETAILS.md`](./IMPLEMENTATION_DETAILS.md) for the design decisions behind all of this.

**stdio** (what most MCP clients, including the official Inspector, use):
```
.venv/bin/python mcp-server/server.py
```

**Streamable HTTP** (stateless, single `/mcp` endpoint):
```
.venv/bin/python mcp-server/http_transport.py
```
Binds to `127.0.0.1:8765` by default (`MCP_HTTP_PORT` to override). Set `MCP_BEARER_TOKEN` to require `Authorization: Bearer <token>` on every request — unset, auth is not enforced (fine for local dev, not for anything network-reachable). Every request must carry `MCP-Protocol-Version`, `Mcp-Method`, and (for `tools/call`/`resources/read`) `Mcp-Name` headers matching the request body, per spec.

Verify either transport with the official inspector:
```
npx @modelcontextprotocol/inspector --cli .venv/bin/python mcp-server/server.py --method tools/list
```

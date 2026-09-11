# InfraMind

An agentic SRE copilot that investigates production incidents by combining live observability tools (through a hand-built MCP server) with historical postmortems (through a hybrid RAG pipeline), running against the real [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo).

See [`InfraMind_Final_Plan.md`](./InfraMind_Final_Plan.md) for the full build plan.

## Environment

The OpenTelemetry Demo lives in `otel-demo/` as a git submodule, pinned to release `3.0.0`.

```
git submodule update --init --recursive
cd otel-demo
docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml up --detach
```

Once running:

| Service | URL |
|---|---|
| Web store | http://localhost:8080/ |
| Feature flags (flagd UI) | http://localhost:8080/feature |
| Grafana | http://localhost:3000/ |
| Jaeger UI | http://localhost:16686/ |
| Prometheus | http://localhost:9090/ |

See [`NOTES.md`](./NOTES.md) for the Prometheus/Jaeger query APIs and log access patterns the MCP server's tools wrap.

To stop everything:
```
cd otel-demo
docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml down
```

## Python environment

```
/opt/anaconda3/bin/python3.13 -m venv .venv
source .venv/bin/activate
```

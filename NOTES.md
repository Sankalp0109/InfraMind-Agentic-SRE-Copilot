# Phase 0 notes — APIs for Phase 1's MCP tools

Captured by poking at the running `3.0.0` stack directly (`DEMO_VERSION=3.0.0`), not guessed in advance. All access is through the `frontend-proxy` at `:8080` except Prometheus, which is the one service published on a fixed host port.

## Prometheus (`get_metrics`)

Base URL: `http://localhost:9090/api/v1/`

Standard PromQL HTTP API — the two endpoints that matter:
- `GET /api/v1/query?query=<promql>` — instant query
- `GET /api/v1/query_range?query=<promql>&start=<ts>&end=<ts>&step=<s>` — range query, needed for "over the last N minutes" style questions

Example:
```
curl -s "http://localhost:9090/api/v1/query" --data-urlencode 'query=sum(demo_payment_transactions_total)'
```

**Metric names actually present** (not all services emit the same set — checked via `/api/v1/label/__name__/values`):
- `demo_payment_transactions_total` — custom app metric, labeled `service_name=payment`, `demo_payment_currency`. Only increments on *successful* charges, so it goes flat (not error-labeled) during a payment failure — useful as a symptom signal, not a root-cause signal on its own.
- `rpc_server_duration_milliseconds_count` / `_bucket` / `_sum` — gRPC server call duration, labeled by `service_name`, `rpc_grpc_status_code`, `rpc_method`, `rpc_service`. **Not every service emits this** — e.g. `ad` did early on, `payment` did not appear even after real traffic, likely a difference in gRPC instrumentation between services. `get_metrics` should not assume this metric exists uniformly; check `/api/v1/query?query=<metric>{service_name="X"}` returns a non-empty result before relying on it.
- `rpc_server_call_duration_seconds_*` — an alternate/older-convention duration histogram, also present for some services.
- Full list of custom demo metrics is defined in `otel-demo/telemetry-schema/metrics/` per service (Weaver registry) — worth generating `get_metrics`' known-metric list from there rather than hardcoding, since it's the source of truth and versioned with the submodule.

## Jaeger (`get_traces`)

Base URL: `http://localhost:8080/jaeger/ui/` — **not** `/jaeger/api/...` (that 404s). This is Jaeger v2 (`quay.io/jaegertracing/jaeger:2.19.0`), configured via `otel-demo/src/jaeger/config.yml` with `jaeger_query.base_path: /jaeger/ui`, so both the UI and its API live under that prefix.

- `GET /jaeger/ui/api/services` — list of service names Jaeger knows about
- `GET /jaeger/ui/api/traces?service=<name>&tags={"error":"true"}&limit=<n>` — traces for a service, filtered by tag (URL-encode the `tags` JSON)
- `GET /jaeger/ui/api/traces/<traceID>` — single trace by ID

A trace's `data[].spans[]` array carries `tags` (key/value list, not a dict — needs zipping) and `logs[].fields` (for exception details: `event=exception`, `exception.message`, `exception.stacktrace`, `exception.type`). `processes` maps `processID` → `serviceName` so you can filter spans belonging to one service within a multi-service trace.

Verified end-to-end: flipping `paymentFailure` to `100%` produced a trace with a `payment` service span (`oteldemo.PaymentService/Charge`), `error: true`, `otel.status_description: "Payment request failed. Invalid token. demo.user_context.loyalty_level=gold"`, and a full JS stack trace in the span's exception log pointing at `charge.js:46`.

## Logs (`get_logs`)

`docker logs <container-name> --tail <n>` to start, per the build plan. Container names match the compose service names (`payment`, `cart`, `checkout`, etc. — see `docker ps` for the full list of 27 services in the full+observability stack).

## Flipping flags programmatically (useful for the eval harness, not just manual QA)

`flagd` reads its config from a bind-mounted file (`otel-demo/src/flagd/demo.flagd.json` → `/etc/flagd/demo.flagd.json` in the container) with a file-watcher (`file/filepath_sync.go`) that hot-reloads on write — confirmed via `docker logs flagd`. This means flags can be flipped without a browser: edit `flags.<flagName>.defaultVariant` in that JSON file directly (same effect as using the flagd UI, since the UI writes to the same file), no container restart needed. **This is exactly what Phase 5's eval harness should do** to drive scenarios programmatically instead of scripting browser clicks — just remember to revert the file to its committed state afterward (`git checkout -- src/flagd/demo.flagd.json`) so the submodule stays clean against the pinned `3.0.0` release.

## Known gotchas hit during Phase 0

- **`DEMO_VERSION` must be pinned to `3.0.0`.** The submodule's own `.env` defaults it to `latest`, and at the time of this build the `latest`-tagged `ghcr.io/open-telemetry/demo:latest-payment` image was broken (`Cannot find module '@opentelemetry/auto-instrumentations-node/register'`, crash-loops on boot). Always pass `DEMO_VERSION=3.0.0` explicitly.
- **Grafana and Jaeger aren't on fixed host ports.** The upstream compose file publishes them with a bare port number (`"${GRAFANA_PORT}"`), which Docker Compose maps to a random ephemeral host port, not `:3000`/`:16686`. Reach them through `frontend-proxy` at `:8080/grafana/` and `:8080/jaeger/ui/` instead — Prometheus is the only one published on a fixed host port (`:9090`).

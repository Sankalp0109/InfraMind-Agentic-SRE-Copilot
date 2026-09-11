# InfraMind — Implementation Details

A running log of design decisions made while building this project, smallest to largest, with the reasoning behind each. Updated as the build progresses — see `InfraMind_Final_Plan.md` for the overall phase plan and `NOTES.md` for API-level reference notes.

---

## Phase 0 — Environment

### Container runtime: Docker Desktop (not Colima/Podman)
Nothing was installed on this machine. Chose Docker Desktop over Colima for maximum compatibility with the OTel Demo's own tooling/docs, at the cost of it being a heavier GUI app. Installed via `brew install --cask docker`.

### Python: 3.13 via Anaconda's interpreter, project-local `.venv`
System `python3` was 3.9.6 (too old for modern ML/embedding libraries needed in later phases). Anaconda's `python3.13` was already present on the machine, so `.venv` is built from `/opt/anaconda3/bin/python3.13` rather than installing yet another Python via pyenv.

### `otel-demo` pinned to release tag `3.0.0`, not tracking `main`
The whole point of using a real demo environment is that it's independently verifiable — pinning to a release (verified to exist both as a GitHub release and a real git tag) keeps the environment reproducible for anyone who checks the project out later, rather than drifting with upstream `main`.

### `DEMO_VERSION=3.0.0` must be set explicitly
The submodule's own `.env` defaults `DEMO_VERSION=latest`. At the time of this build, `ghcr.io/open-telemetry/demo:latest-payment` was broken (`Cannot find module '@opentelemetry/auto-instrumentations-node/register'`, crash-loops on boot) — a real bug in the currently-published `latest` tag, unrelated to anything in this project. Pinning `DEMO_VERSION=3.0.0` to match the checked-out release fixed it. Documented in the README's bring-up command.

### Grafana and Jaeger reached via `frontend-proxy` (`:8080/grafana/`, `:8080/jaeger/ui/`), not `:3000`/`:16686`
The upstream compose file publishes Grafana/Jaeger with a bare port number (`"${GRAFANA_PORT}"`), which Docker Compose maps to a **random ephemeral host port**, not a fixed one — only Prometheus uses the `host:container` form and is reliably on `:9090`. Confirmed via `docker port` and by reading `src/frontend-proxy/envoy.tmpl.yaml`, which routes `/grafana/` and `/jaeger/` to the respective containers by service name on the internal Docker network.

### Alert rules live in Grafana's unified alerting, not Prometheus rule files
`GET /api/v1/rules` on Prometheus returns zero groups in this stack — there are no Prometheus-native alerting rules configured at all. The doc's referenced `CartAddItemHighLatency` alert is real, but it's a **Grafana-provisioned alert rule** (`GET /api/v1/provisioning/alert-rules` on Grafana, default creds `admin:admin`), with firing instances read from Grafana's Alertmanager-compatible API (`/api/alertmanager/grafana/api/v2/alerts`). This is why `get_active_alerts` (Phase 1) queries Grafana, not Prometheus.

### Flags can be flipped programmatically, no browser needed
`flagd` reads `src/flagd/demo.flagd.json` via a bind mount (`./src/flagd:/etc/flagd`) with a file-watcher that hot-reloads on write. Editing `flags.<name>.defaultVariant` in that file has the same effect as using the flagd UI — useful for Phase 5's eval harness later. Always `git checkout -- src/flagd/demo.flagd.json` afterward so the submodule stays clean against the pinned release.

---

## Phase 1 — MCP server

### Protocol era: modern (2026-07-28) as primary, with a legacy `initialize` shim
The MCP spec revision current as of this build (`2026-07-28`, published ~6 weeks prior) replaced the old stateful `initialize` handshake with a **stateless per-request model**: every request carries its protocol version in `_meta`, and there's a new mandatory `server/discover` RPC instead of a handshake sequence. The old model (`2025-11-25` and earlier) is now officially "legacy."

Chose to build against the **current spec** as the primary/documented behavior — this is a portfolio project about understanding the real protocol, and building against a spec that was already legacy at time of writing would undercut that.

**However:** the actual official MCP Inspector (npm `@modelcontextprotocol/inspector@2.6.0`, the tool this plan uses to verify every tool) does not implement the spec's own recommended dual-era probing (`server/discover`-first) — it unconditionally opens stdio connections with a legacy `initialize` request. Confirmed by tracing raw stdin messages reaching the server. Without a legacy fallback, the reference verification tool literally cannot talk to a spec-correct modern-only server.

**Resolution:** the server answers *both* — modern requests (any request carrying `_meta.io.modelcontextprotocol/protocolVersion`) are handled statelessly per the current spec; a bare `initialize` request (no `_meta`) is treated as a legacy handshake, after which subsequent requests in that same stdio session (also with no `_meta`) are served under legacy semantics. Both eras dispatch into the exact same tool registry — there is no duplicated tool logic, only two thin entry paths gated in `server.py`'s `_handle_message`. See the comment on `LEGACY_PROTOCOL_VERSION` in `protocol.py` for the specifics.

This is a real, load-bearing example of "don't trust either the doc or the spec's own aspirational claims blindly — verify against what the actual tooling does."

### No MCP SDK, stdlib only (not even `requests`)
Consistent with the project's stated goal (MCP is the centerpiece skill to build by hand). Went one step further than "no MCP SDK" and used `urllib.request` instead of adding `requests` as a dependency, since the HTTP calls involved (GET with basic auth, JSON body) are simple enough that stdlib is sufficient — keeps the entire `mcp-server/` component dependency-free for now. Will add real dependencies (for RAG, embeddings, etc.) only when something genuinely needs them, per the "don't add dependencies before they're needed" principle already applied in Phase 0.

### Tool registry pattern
Each tool is a module under `mcp-server/tools/` exposing `NAME`, `DESCRIPTION`, `INPUT_SCHEMA`, `READ_ONLY` (bool — groundwork for Phase 3's guardrails, costs nothing to tag now), and a `call(**kwargs) -> tuple[list[content], bool]` function. `tools/__init__.py` aggregates these into `TOOLS` (for `tools/list`) and `TOOL_HANDLERS` (for `tools/call` dispatch) so `server.py` never needs to know about individual tools — adding a tool means adding a module and one line in `_MODULES`.

### Shared config via environment variables with verified defaults
`mcp-server/config.py` centralizes the observability backend URLs (`PROMETHEUS_URL`, `JAEGER_URL`, `GRAFANA_URL` + creds), defaulting to what Phase 0 actually verified works (`:8080/grafana/`, `:8080/jaeger/ui/`, `:9090`), overridable via env vars for a different stack.

### Error handling: protocol errors vs. tool execution errors
Following the modern spec's own distinction: malformed calls (unknown tool, bad arguments) raise `ProtocolError` → a real JSON-RPC `error` object, since the model can't fix a structurally broken request. Runtime failures a tool encounters while doing its job (backend unreachable, timeout) are returned as a normal `tools/call` **result** with `isError: true` and a text explanation, since that's the channel a model can actually read and react to (e.g. retry, report to the user).

### `get_active_alerts`'s network calls must not crash on timeout
Found via live testing (inspector `tools/call` hung, then crashed) that in this Python version, a socket timeout mid-response raises a bare `TimeoutError`, which is **not** a subclass caught by `urllib.error.URLError` the way older assumptions about urllib expect. Broadened the except clause to `(urllib.error.URLError, TimeoutError, OSError)` so a slow/unreachable backend degrades to a graceful `isError: true` tool result instead of crashing the handler. This matters in practice: this project's dev host (a MacBook Air) genuinely struggles under the full 27-container otel-demo stack — Grafana's SQLite backend has been observed taking 30-70s per request under load (`database is locked`, `context deadline exceeded` in its own logs), driven by host CPU load averages of 13-14. Every tool that calls out to a live backend needs to handle this kind of slowness as a normal case, not an edge case. Adopted the same broadened except clause in `get_metrics` from the start rather than waiting to hit the same bug twice.

### `get_metrics` summarizes rather than dumping raw samples
Prometheus's `query_range` can return dozens of points per label combination (e.g. `demo_payment_transactions_total` is split by currency). Returning every raw sample risks flooding the model's context for a marginal benefit — the tool instead returns each series' label set plus `num_points`, `first`, and `last`, enough for trend detection (is this climbing, flat, dropping) without the noise. `time_range` is validated (regex `^\d+[smh]$`) and rejected as a tool execution error (`isError: true`) rather than silently defaulting, so a malformed argument is visible to the model rather than silently producing a wrong window. A query for a metric that doesn't exist for a given service returns a normal (non-error) explanatory result rather than an error — per NOTES.md, this is expected and routine (not every service emits every metric), not a failure.

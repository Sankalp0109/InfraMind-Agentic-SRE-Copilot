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

### `get_traces` extracts, doesn't dump, the trace tree
A single checkout-flow trace can carry 100+ spans across every service involved (confirmed in Phase 0: one payment-failure trace had 103 spans). Rather than returning Jaeger's raw trace JSON, the tool filters to only the spans belonging to the *requested* service (via the trace's `processes` map) and extracts just `operation`, `error`, `status_description`, and any exception `type`/`message` found in that span's logs. `error_only` defaults to `true` since the doc's own rationale for this tool is finding cascading failures — an agent investigating an incident wants errors first, and can pass `error_only=false` explicitly for a broader look.

### `get_logs` shells out to the real `docker` CLI rather than the Docker SDK
Per the build plan ("container logs to start"). Went with `subprocess.run(["docker", "logs", ...])` instead of adding the `docker` Python SDK as a dependency — one more instance of stdlib-only until something genuinely needs more. `docker logs` on an unknown container name exits non-zero with a clear stderr message ("No such container: X"), which the tool surfaces directly as the `isError: true` text rather than writing a redundant custom error message.

### `get_recent_deploys` is deterministic-fake, not random-fake
otel-demo has no real deploy pipeline, so this is explicitly simulated per the build plan. Seeded `random.Random(sha256(service_name))` rather than an unseeded RNG, so the same service always returns the same fake history across calls and process restarts — matters for Phase 5's eval harness, where a scenario's expected answer needs to be stable. Every returned string is prefixed `[SIMULATED — ...]` so neither the agent nor a human reading a transcript could mistake it for real deploy data.

### First mutating tools: `create_incident_ticket` (SQLite) and `post_to_slack` (webhook-or-mock)
These are the first two tools where `READ_ONLY = False` actually matters — Phase 3's guardrails will gate on exactly this flag. `create_incident_ticket` writes to a local SQLite DB (`mcp-server/incidents.db`, gitignored — generated state, not source) with an autoincrement id, confirmed to persist correctly across separate process invocations (ticket #1 and #2 from two different `tools/call` runs). `post_to_slack` checks for `SLACK_WEBHOOK_URL`: real POST if set, otherwise a message clearly prefixed `[SIMULATED — ...]` and logged rather than silently dropped — no Slack workspace is wired up for local dev, and the build plan explicitly allows "real/mocked" here.

### Resources use a custom URI scheme, not raw `file://`
`mcp-server/resources/runbooks.py` exposes `data/postmortems/*.md` via `resources/list`/`resources/read`, ahead of Phase 2 actually populating that directory — `resources/list` on an empty corpus correctly returns `{"resources": []}` today, and will start returning real entries automatically the moment Phase 2 adds files, with no server change needed. URIs are `inframind://postmortems/<filename>` rather than `file:///...`, specifically so a resource identifier can never double as a real filesystem path — the spec calls out path-traversal as a `file://` risk, and `resources/read` rejects any URI containing `/` after the prefix (verified with a `../../../etc/passwd`-style attempt, correctly rejected with `-32602`) rather than trying to sanitize a real path.

### Refactored `server.py` around a transport-agnostic `dispatch()` core
Before adding the HTTP transport, split the handlers so each returns a result dict instead of writing to stdout directly, and pulled the version-check/method-lookup/error-handling logic into one `dispatch(message, allow_legacy=True) -> dict | None` function. Both transports now share the exact same protocol core and tool registry — `main()` (stdio) just reads lines and writes whatever `dispatch()` returns; `http_transport.py` does the same over HTTP. No behavior was duplicated between the two.

### Bearer auth lives at the HTTP layer only, not stdio
The build plan lists "bearer-token check in the transport layer" as a Phase 1 step. Stdio is a subprocess the client itself spawns — the process boundary *is* the trust boundary there, so a bearer check on stdio would just be checking a secret against itself (whoever can spawn the process can also read whatever token it's configured with). Auth only means something once the server is reachable over a network, so it's implemented in `http_transport.py`: enforced only if `MCP_BEARER_TOKEN` is set (so local dev without it configured keeps working), checked before any JSON-RPC parsing happens.

### The legacy `initialize` shim is stdio-only, not shared with HTTP
Streamable HTTP in the 2026-07-28 revision explicitly removed protocol-level sessions (no more `Mcp-Session-Id`) — the transport is stateless by design in this revision, full stop. The stdio legacy shim's `_legacy.initialized` flag is a single boolean scoped to one subprocess = one caller, which is safe. Reusing that same flag for HTTP would be wrong: HTTP serves multiple unrelated clients concurrently, and one client's legacy `initialize` would incorrectly exempt every *other* client's requests from version checking too. `http_transport.py` calls `dispatch(message, allow_legacy=False)` and simply doesn't implement legacy fallback — matching what this revision of the spec actually defines for this transport, rather than inventing non-spec session behavior to route around the gap.

### HTTP transport implements the header/body validation this revision actually requires, nothing speculative
`MCP-Protocol-Version`, `Mcp-Method`, and (for `tools/call`/`resources/read`/`prompts/get`) `Mcp-Name` are validated against the request body per the spec's "Server Validation" section, returning `400` + JSON-RPC `-32020 HeaderMismatch` on any mismatch — verified for a missing version header, a mismatched tool name header, and the success path. `Origin` validation (403 on a disallowed value, but not on an absent one — non-browser clients like curl don't send it) and localhost-only binding are both implemented per the spec's DNS-rebinding guidance. Deliberately **not** implemented: SSE streaming responses (a server may always choose plain JSON instead — legal per spec, and none of these tools run long enough to need progress notifications), `subscriptions/listen`, and `x-mcp-header` parameter mirroring — all real parts of the spec, none of them load-bearing for this project's tool set, so building them now would be speculative work against requirements that don't exist yet.

### First real external dependencies: Starlette + uvicorn
The stdio transport and every tool up to this point stayed stdlib-only. HTTP serving is the first place that's genuinely impractical to hand-roll well (correct chunked/keep-alive handling, async request bodies) — added `starlette` (ASGI app/routing) and `uvicorn` (ASGI server) as the project's first `requirements.txt`, matching the build plan's original suggestion (`sse-starlette` was also suggested there, but isn't used — see above, no SSE responses are implemented).

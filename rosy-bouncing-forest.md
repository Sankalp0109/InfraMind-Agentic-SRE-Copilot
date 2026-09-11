# InfraMind — Full Implementation Plan

## Context

The working directory holds a vision doc (`InfraMind_Final_Plan.md`) for an agentic SRE copilot: a custom MCP server (built from raw JSON-RPC, no SDK) exposing live observability tools against the OpenTelemetry Demo, a hybrid RAG pipeline over historical postmortems, and a ReAct agent that ties them together with human-approval guardrails on anything mutating. Nothing exists yet — no git repo, no code, Docker isn't installed.

The doc is used here as a direction, not a spec. It says itself that the OTel Demo repo "moves fast" and needs confirming — that turned out to be true (see below), so rather than trust its specifics wholesale, this plan corrects what's been checked against the live repo and otherwise carries the doc's engineering choices forward as reasoned defaults, flagging anywhere a later phase should re-check something fast-moving (protocol spec revisions, model names, library APIs) before building on it, the same way Phase 0's facts were checked live instead of assumed.

This is a full plan across all phases so the whole shape is visible up front — **execution still happens phase by phase**, each with its own review and verification gate before moving to the next, per the doc's own "build and verify one thing at a time" approach.

**Already decided with the user (Phase 0):**
- Container runtime: **Docker Desktop**, via `brew install --cask docker` (nothing installed currently — no Docker, Colima, or Podman found on this machine)
- Python: venv built on **Anaconda's `python3.13`** (`/opt/anaconda3/bin/python3.13`, already present), since system `python3` is 3.9.6

**Verified live against `open-telemetry/opentelemetry-demo` (checked `main` and the newest release tag `3.0.0`, published 2026-07-24) — replacing what the doc assumed:**

1. **No single `docker-compose.yml` ships.** Current layout is layered Compose v2 files — `compose.yaml` (core), `compose.full.yaml` (+Kafka/accounting/fraud-detection), `compose.observability.yaml` (+Jaeger/Prometheus/Grafana/OpenSearch/OpAMP), plus `compose.agent.yaml`/`compose.extras.yaml`/`compose.profiling.yaml`/`compose.tests.yaml`. Full stack with observability:
   ```
   docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml up
   ```
2. **Images pull pre-built** from `ghcr.io/open-telemetry/demo:latest` — no `--build` needed.
3. **Ports** (from `.env`): web store + flagd UI behind envoy on **8080** (flags at `localhost:8080/feature`), Grafana on **3000**, Jaeger UI on **16686**, Prometheus on **9090**.
4. **The repo does ship its own Agent/MCP/Chatbot services** (`compose.agent.yaml`; ports 8010/8011/7860). Real, not invented by the doc — worth referencing, not conflating with InfraMind's own MCP server (Section 8 talking point below).
5. **Several flagd flag names have changed.** Checked `src/flagd/demo.flagd.json` directly:

   | Doc assumed | What exists now | What it does |
   |---|---|---|
   | `paymentServiceFailure` | `paymentFailure` | Fail payment service charge requests n% |
   | `cartServiceFailure` | `cartFailure` | Fail cart service n% of the time |
   | `kafkaQueueProblems` | `kafkaQueueProblems` (matches) | Kafka queue overload + consumer-side lag spike |
   | `adServiceHighCpu` | `adHighCpu` | High CPU load in the ad service |
   | recommendation-service memory leak | doesn't exist — `emailMemoryLeak` is the only memory-leak flag; recommendation instead has `recommendationCacheFailure` | |

   Other real flags the doc doesn't mention, useful for the eval set: `adFailure`, `adManualGc`, `failedReadinessProbe`, `imageSlowLoad`, `intlShippingSlowdown`, `loadGeneratorFloodHomepage`, `paymentUnreachable`, `productCatalogFailure`, `productCatalogLockContention`.

---

## Repo layout

```
inframind/
├── README.md
├── .gitignore
├── .venv/                          # python3.13, not committed
├── otel-demo/                      # git submodule, pinned to release 3.0.0
├── docker-compose.yml              # added in Phase 2/3 once InfraMind has its own
│                                    # services to join the otel-demo network — not
│                                    # created speculatively in Phase 0
├── mcp-server/
│   ├── server.py                   # JSON-RPC 2.0 loop, stdio transport
│   ├── protocol.py                 # handshake, capability negotiation
│   ├── tools/
│   │   ├── get_logs.py
│   │   ├── get_metrics.py          # Prometheus HTTP query API
│   │   ├── get_traces.py           # Jaeger query API
│   │   ├── get_active_alerts.py
│   │   ├── get_recent_deploys.py   # simulated — otel-demo has no deploy history
│   │   ├── create_incident_ticket.py
│   │   └── post_to_slack.py
│   └── resources/
│       └── runbooks.py             # exposes data/postmortems/*.md as MCP resources
├── rag-pipeline/
│   ├── ingest.py
│   ├── retrieve.py
│   └── eval_retrieval.py
├── agent/
│   ├── loop.py                     # ReAct orchestrator
│   ├── llm.py                      # call_llm() wrapping litellm
│   ├── guardrails.py                # read_only vs mutating gating
│   └── prompts.py
├── eval/
│   ├── scenarios.yaml               # each scenario maps to a real flagd flag
│   └── run_eval.py
├── data/postmortems/                # 15-20 seed docs
└── terraform/                       # stretch
```

---

## Phase 0 — Stand up the real environment

**Goal:** a real, running OTel Demo, verified by hand, with the exact APIs Phase 1 needs to wrap identified.

1. Fix the flag names in `InfraMind_Final_Plan.md` (Section 5's table and flag list) so it reflects the real repo — it's the reference doc for the rest of the build, no point propagating stale names forward.
2. `brew install --cask docker`; launch Docker.app once for first-run setup; confirm with `docker info` and `docker compose version`.
3. `/opt/anaconda3/bin/python3.13 -m venv .venv`. No dependencies pinned yet — added only as each library is actually used, starting in Phase 1/2.
4. `git init`, `.gitignore` (`.venv/`, `__pycache__/`, `.DS_Store`, standard Python/Docker artifacts), minimal root `README.md`.
5. Scaffold the repo skeleton above — directories only, `.gitkeep` placeholders, no code yet.
6. `git submodule add https://github.com/open-telemetry/opentelemetry-demo.git otel-demo`, `cd otel-demo && git checkout 3.0.0` — pinned to a release, not `main`, so the environment stays reproducible for anyone checking the project out later.
7. Bring it up and verify by hand:
   ```
   cd otel-demo
   docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml up --detach
   ```
   Confirm the web store (`:8080`), feature flag UI (`:8080/feature`), Grafana (`:3000`), Jaeger UI (`:16686`), and Prometheus (`:9090`) all load. Flip each real flag by hand one at a time — `paymentFailure`, `cartFailure`, `kafkaQueueProblems`, `adHighCpu`, `emailMemoryLeak`, `recommendationCacheFailure` — confirm the effect in Grafana/Jaeger, then revert before the next.
8. Write `NOTES.md` from what's actually found poking at the running stack: Prometheus's query API shape and which metric names exist for these services, Jaeger's query API for traces/errors by service, how to pull per-service logs.

**Deliverable:** flip a flag, watch a real failure in Grafana/Jaeger, revert it — with the exact APIs identified for Phase 1.

---

## Phase 1 — MCP server from scratch

**Goal:** a working MCP server, one tool at a time, each verified with the official MCP inspector before adding the next.

Before writing the transport layer: check the current MCP spec revision at modelcontextprotocol.io (the protocol has moved fast — e.g. Streamable HTTP replaced HTTP+SSE, batching rules and auth framework have changed across revisions) and confirm the JSON-RPC framing/handshake details below still match the current spec rather than an older one, the same way Phase 0 checked the OTel Demo repo instead of assuming.

1. Transport + handshake: JSON-RPC 2.0 over stdio, newline-delimited messages, `initialize` handshake with capability negotiation, `tools/list`
2. `get_active_alerts()` first — verify against whatever alert rules actually exist in the running otel-demo (check Prometheus's rule config directly rather than assuming `CartAddItemHighLatency` still exists)
3. `get_metrics(service, metric_name, time_range)` — Prometheus HTTP query API, using the metric names captured in Phase 0's `NOTES.md`
4. `get_traces(service, error_only)` — Jaeger's query API
5. `get_logs(service, time_range)` — container logs via `docker compose logs <service>` to start
6. `get_recent_deploys(service)` — mocked/simulated, otel-demo has no real deploy history
7. `create_incident_ticket`, `post_to_slack` — SQLite table + a real or mocked webhook
8. Resources: expose `data/postmortems/*.md` via `resources/list` / `resources/read`
9. Auth: bearer-token check in the transport layer
10. Add Streamable HTTP transport (Starlette + sse-starlette) once stdio is solid

**Deliverable:** every tool independently passes in the MCP inspector; a short README documenting the protocol implementation choices — framing, error handling, why stdio first.

**Why hand-roll instead of the official MCP SDK:** this is the centerpiece skill of the project — the point is understanding the handshake, framing, and dispatch mechanics well enough to explain them without a framework's abstraction in the way (Section 7-style rationale, worth being able to defend unprompted in review).

---

## Phase 2 — RAG pipeline (parallel with Phase 1)

**Goal:** hybrid retrieval that reliably surfaces the right past incident.

1. Write 15-20 postmortems in markdown, grounded in otel-demo's real services (payment, cart, checkout, recommendation, currency, shipping, email, Kafka queue) and the real flag list from Phase 0 — not the stale names. Sections: Summary / Timeline / Root Cause / Fix.
2. Chunk by heading, not fixed windows.
3. Embed (Voyage or OpenAI embeddings — check current pricing/free-tier limits before committing, this shifts often) and store in Qdrant with metadata (`service`, `failure_type`, `severity`, `date`).
4. Hybrid retrieval: Qdrant vector search + BM25 (`rank_bm25`), merged and reranked with a local cross-encoder (`sentence-transformers`).
5. Register as an agent tool: `search_past_incidents(query, service?, top_k)` — called by the agent when useful, not run automatically.
6. Test retrieval standalone before the agent touches it — 10 query strings mimicking real incident descriptions, confirm top-3 precision by hand.
7. This is also the natural point to build the root `docker-compose.yml` (Qdrant + otel-demo's network) that Phase 0 deliberately deferred, now that there's a real second service to wire in.

**Deliverable:** `python retrieve.py "payment service latency spike after config change"` returns the correct postmortem in the top 3, every time.

**Why hybrid instead of pure vector search:** pure vector search can conflate semantically similar incidents across different services; BM25 anchors on exact service names and error strings while vector search catches paraphrased symptoms — verify this empirically with the standalone eval rather than asserting it.

---

## Phase 3 — Agent loop

**Goal:** end-to-end investigation from a triggered fault to a cited diagnosis, stopping for approval on anything mutating.

1. `agent/llm.py`: `call_llm(messages, tools) -> response` wrapping `litellm`, so the ReAct loop never calls a provider SDK directly. Before picking a specific free-tier provider/model (the doc suggests Gemini Flash or Groq/Llama), check current model names and free-tier limits — these shift often and the doc's specific names may already be stale by the time this phase starts.
2. Register MCP tools + `search_past_incidents` as tools through that interface.
3. ReAct loop (`agent/loop.py`): alert → reason about what to check → call tools (logs/metrics/traces first, RAG once symptoms are established) → synthesize a cited diagnosis → propose remediation.
4. Guardrails (`agent/guardrails.py`): tag every tool `read_only` or `mutating`. Mutating actions pause for human approval; read-only tools run freely.
5. Log the full thought/action/observation trace per run for eval and demos.

**Deliverable:** flip `paymentFailure`, watch the agent pull metrics → traces → logs → retrieve a similar postmortem → produce a cited diagnosis, and stop at the approval gate for any mutating step.

---

## Phase 4 — Interface

**Goal:** something to actually run and watch.

CLI streaming the trace live (thought/action/observation, colorized) is the minimum. If time allows, a small Slack bot: post alert → agent investigates in-thread → reply with follow-ups.

---

## Phase 5 — Eval + tracing

**Goal:** numbers, not "it worked in the demo."

Scenario table, using the corrected flag names from Phase 0 (replacing the doc's stale ones):

| Scenario | Flag | Expected diagnosis |
|---|---|---|
| Payment charge failures | `paymentFailure` | Root cause in payment service charge endpoint |
| Cart failures | `cartFailure` | Cart service failing n% of requests |
| Kafka lag spike | `kafkaQueueProblems` | Consumer-side lag from queue overload |
| Ad service CPU spike | `adHighCpu` | High CPU load in ad service |
| Email memory leak | `emailMemoryLeak` | Gradual memory growth, not a hard crash |
| Recommendation cache failure | `recommendationCacheFailure` | Recommendation service cache failing |
| Payment unreachable | `paymentUnreachable` | Payment service unreachable, not a slow failure |
| Product catalog failure | `productCatalogFailure` | Root cause in product catalog service |

Pick 8-10 of these (plus any others from Phase 0's full flag list) for the eval set. Metrics: time-to-diagnosis, retrieval precision@3, tool-call correctness (right tools, not just any tools), false-positive remediation rate. Add OpenTelemetry spans around every agent step and tool call.

---

## Phase 6 — Terraform (stretch)

Deploy the MCP server + agent to a small cloud instance; Qdrant self-hosted or managed; otel-demo stays local. Only after everything above is solid.

---

## Design decisions worth being able to defend unprompted

- **MCP from scratch, LLM calls through litellm** — MCP and RAG are the protocol/retrieval work worth doing by hand; the LLM call itself is plumbing.
- **Hybrid retrieval over pure vector search** — verified empirically in Phase 2's standalone eval, not asserted.
- **read_only / mutating as the guardrail split** — simple, defensible, matches how real incident-response tooling is usually gated.
- **A real demo environment over toy services** — real telemetry, real failure modes, independently verifiable by anyone reviewing the project.
- **Be able to distinguish InfraMind's own MCP server from otel-demo's native Agent/MCP/Chatbot services** — confirmed real in Phase 0, don't conflate the two when explaining the project.

## Stretch ideas (after core is done)

- Multi-agent split: a "detective" agent investigating, a "communicator" agent drafting updates
- Knowledge graph linking otel-demo's real service dependency graph to past incidents for blast-radius reasoning
- Feed resolved incidents back into the vector store so retrieval quality compounds over time
- Compare InfraMind's own OTel traces against otel-demo's native Agent/MCP traces as a demo of instrumented agent tooling across two independent implementations

---

## Verification (Phase 0, executed first)

- `docker info` succeeds, `docker compose version` shows Compose v2
- `docker compose -f otel-demo/compose.yaml -f otel-demo/compose.full.yaml -f otel-demo/compose.observability.yaml ps` (from `otel-demo/`) shows all services healthy
- The 5 URLs above all load
- Flipping `paymentFailure` visibly produces failed requests in Grafana or Jaeger, and reverting stops them
- `git submodule status` shows `otel-demo` pinned at `3.0.0`; `.venv/bin/python --version` reports `3.13.x`

Each later phase gets its own review/verification gate at the start of its session (MCP inspector for Phase 1, standalone retrieval eval for Phase 2, end-to-end flag-to-diagnosis run for Phase 3) before moving on — this plan sets direction for all of them, but only Phase 0 gets executed now.

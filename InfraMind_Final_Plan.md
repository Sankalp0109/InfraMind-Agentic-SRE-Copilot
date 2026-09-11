# InfraMind — Agentic SRE Copilot
### Final Build Plan

An agent that investigates production incidents by combining live observability tools (through a hand-built MCP server) with historical postmortems (through a hybrid RAG pipeline), running against a real open-source microservices environment.

---

## 1. Goal & Success Criteria

Given a production incident — triggered by a real fault-injection flag in the OpenTelemetry Demo — InfraMind investigates by pulling live logs, metrics, and traces through a custom MCP server, cross-references historical postmortems via RAG, and produces a grounded, cited diagnosis plus a human-approved remediation.

**Done means:**
- Flipping a real flagd flag (e.g. `paymentServiceFailure`) at `localhost:8080/feature` produces a diagnosis within ~30 seconds, citing specific logs, metrics/traces, and a similar past incident
- Every mutating action pauses for human approval; every read-only action runs automatically
- An 8-10 scenario eval set, each mapped to a real flagd flag, with measured time-to-diagnosis and retrieval precision
- You can explain, unaided, how the MCP JSON-RPC handshake works and why hybrid retrieval beats pure vector search on this corpus — because you built and tested both yourself

---

## 2. Final Tech Stack

| Component | Choice | Reasoning |
|---|---|---|
| Environment | **OpenTelemetry Demo (Astronomy Shop)** | Real polyglot microservices, built-in Prometheus/Grafana/Jaeger, native flagd fault injection — no toy services or custom chaos scripts to build and maintain |
| MCP server | **Python, raw JSON-RPC 2.0, no MCP SDK** | The centerpiece skill. Stdio transport first (newline-delimited JSON, per spec — no Content-Length framing), Streamable HTTP added later via Starlette + sse-starlette |
| RAG | **Qdrant + hybrid retrieval** (vector + BM25) + cross-encoder rerank | Pure vector search alone misses exact service names/error strings; hybrid catches both semantic and literal matches |
| Agent loop | **ReAct pattern**, own `call_llm(messages, tools)` interface, **litellm** underneath | Provider-agnostic LLM calling is plumbing, not a skill to hand-build. MCP and RAG are the protocol/retrieval work worth doing from scratch; the LLM call itself isn't |
| LLM provider (dev/free) | **Gemini Flash or Groq (Llama 3.3 70B)**, Claude API optional for final polish | Strong native function-calling on the free tier — matters more here than raw model size, since the agent depends on correct tool selection |
| Guardrails | Tool-level `read_only` / `mutating` tagging | Simple, defensible split; anything mutating needs human sign-off |
| Interface | CLI (required), Slack bot (stretch) | CLI streams the reasoning trace live; Slack is a stronger demo if time allows |
| Eval + tracing | Custom eval harness + OpenTelemetry spans | Scenarios map 1:1 to real flagd flags; traces turn "it worked in the demo" into actual numbers |
| Deploy (stretch) | Terraform | Optional — strengthens the story for infra-heavy roles, not required for the core pitch |

**A note on the environment:** the OpenTelemetry Demo itself now ships its own Agent, MCP, and Chatbot services (added in v3.0, July 2026) for shop-domain tasks like cart/checkout. Worth reading as a reference implementation — but InfraMind's MCP server is a separate, from-scratch build for observability tools, not a reuse or wrapper of theirs. Confirm the current repo structure against `github.com/open-telemetry/opentelemetry-demo` before starting, since it moves fast.

---

## 3. Final Architecture

```
OTel Demo environment (real services, flagd faults)
        │
        ▼
Custom MCP server (built from scratch, JSON-RPC)
        │                              ▲
        ▼                              │
   Agent loop  ◄─────────────  RAG pipeline (Qdrant, hybrid retrieval)
 (call_llm() over litellm,
  read-only vs mutating guardrails)
        │
        ▼
  CLI / Slack interface

  [Eval + OTel tracing wraps the whole system, scenarios mapped to flagd flags]
```

**Data flow for one incident:**
1. Flagd flag flipped (or a Prometheus alert fires as a result)
2. Agent reads the alert, plans its investigation
3. Calls MCP tools — `get_metrics`, `get_traces`, `get_logs` — against the real OTel Demo services
4. Calls `search_past_incidents` (RAG) once symptoms are established
5. Synthesizes a diagnosis, citing specific evidence plus a similar past incident
6. Proposes a remediation
7. Human approves if the action is mutating; read-only steps already ran automatically
8. MCP executes the approved action
9. Outcome is logged and fed back into the RAG corpus for next time

---

## 4. Repo Structure

```
inframind/
├── docker-compose.yml              # brings up otel-demo + inframind services
├── otel-demo/                      # git submodule: open-telemetry/opentelemetry-demo
├── mcp-server/
│   ├── server.py                   # JSON-RPC 2.0 loop, stdio transport
│   ├── protocol.py                 # handshake, capability negotiation
│   ├── tools/
│   │   ├── get_logs.py
│   │   ├── get_metrics.py          # queries otel-demo's Prometheus
│   │   ├── get_traces.py           # queries otel-demo's Jaeger API
│   │   ├── get_active_alerts.py
│   │   ├── get_recent_deploys.py   # simulated — otel-demo has no deploy history
│   │   ├── create_incident_ticket.py
│   │   └── post_to_slack.py
│   └── resources/
│       └── runbooks.py             # exposes postmortem/runbook files as MCP resources
├── rag-pipeline/
│   ├── ingest.py                   # chunk + embed + upsert to Qdrant
│   ├── retrieve.py                 # hybrid search + rerank
│   └── eval_retrieval.py           # standalone retrieval quality tests
├── agent/
│   ├── loop.py                     # ReAct orchestrator
│   ├── llm.py                      # call_llm() interface, wraps litellm
│   ├── guardrails.py               # read_only vs mutating tool gating
│   └── prompts.py
├── eval/
│   ├── scenarios.yaml              # each scenario maps to a real flagd flag
│   └── run_eval.py
├── data/postmortems/                # 15-20 seed docs, based on otel-demo's real services
└── terraform/                       # stretch goal
```

---

## 5. Phase-by-Phase Plan

### Phase 0 — Stand up the real environment (Days 1-3)
- Clone/submodule `opentelemetry-demo`, bring it up with `docker compose up`
- Verify web store, Grafana, Jaeger, feature-flags UI, and load generator all load at `localhost:8080/*`
- Toggle each fault-injection flag once by hand (`paymentFailure`, `cartFailure`, `kafkaQueueProblems`, `adHighCpu`, `emailMemoryLeak`, `recommendationCacheFailure`) and confirm the effect shows up in Grafana/Jaeger — verified against `src/flagd/demo.flagd.json` in release `3.0.0`; several flag names differ from earlier drafts of this doc (e.g. `paymentServiceFailure` → `paymentFailure`, `adServiceHighCpu` → `adHighCpu`, and there is no recommendation-service memory leak flag — recommendation instead has `recommendationCacheFailure`)
- Note Prometheus's query API, Jaeger's trace query API, and how to pull per-service logs — these are exactly what the MCP tools will wrap

**Deliverable:** flip a flag, watch a real failure appear in Grafana/Jaeger, revert it — with the exact API calls identified for Phase 1.

### Phase 1 — MCP server from scratch (Days 4-10)
Build and verify one tool at a time with the official MCP inspector before adding the next.

1. Transport + handshake: JSON-RPC 2.0 over stdio, newline-delimited messages, `initialize` handshake with capability negotiation, `tools/list`
2. `get_active_alerts()` first — otel-demo ships a real `CartAddItemHighLatency` alert rule to test against
3. `get_metrics(service, metric_name, time_range)` — Prometheus HTTP query API
4. `get_traces(service, error_only)` — Jaeger's query API; strongest signal for cascading failures across the polyglot service graph
5. `get_logs(service, time_range)` — container logs to start
6. `get_recent_deploys(service)` — mocked/simulated
7. `create_incident_ticket`, `post_to_slack` — SQLite table and a real/mocked webhook
8. Resources: expose `data/postmortems/*.md` via `resources/list` / `resources/read`
9. Auth: bearer-token check in the transport layer
10. Add the Streamable HTTP transport (Starlette + sse-starlette) once stdio is solid — makes the server usable as a real network service

**Deliverable:** every tool independently passes in the MCP inspector; a short README documenting your protocol implementation choices — framing, error handling, why stdio first.

### Phase 2 — RAG pipeline (Days 8-14, parallel with Phase 1)
1. Write 15-20 postmortems in markdown, based on otel-demo's real services (payment, cart, checkout, recommendation, currency, shipping, email, Kafka queue) so the corpus mirrors your actual fault-injection scenarios. Sections: Summary / Timeline / Root Cause / Fix.
2. Chunk by heading, not fixed windows
3. Embed with Voyage or OpenAI embeddings; store in Qdrant with metadata (`service`, `failure_type`, `severity`, `date`)
4. Hybrid retrieval: Qdrant vector search + BM25 (`rank_bm25`), merged and reranked with a local cross-encoder (`sentence-transformers`)
5. Register as an agent tool: `search_past_incidents(query, service?, top_k)` — called by the agent when useful, not run automatically
6. Test retrieval standalone before the agent touches it — 10 query strings mimicking real incident descriptions, confirm top-3 precision by hand

**Deliverable:** `python retrieve.py "payment service latency spike after config change"` returns the correct postmortem in the top 3, every time.

### Phase 3 — Agent loop (Days 15-21)
1. Write `agent/llm.py`: a small `call_llm(messages, tools) -> response` interface wrapping `litellm`, so the ReAct loop never calls a provider SDK directly
2. Register MCP tools + `search_past_incidents` as tools through that interface
3. ReAct loop (`agent/loop.py`): alert → reason about what to check → call tools (logs/metrics/traces first, RAG once symptoms are established) → synthesize a cited diagnosis → propose remediation
4. Guardrails (`agent/guardrails.py`): tag every tool `read_only` or `mutating`. Mutating actions pause for human approval; read-only tools run freely.
5. Log the full thought/action/observation trace per run for eval and demos

**Deliverable:** flip `paymentFailure`, watch the agent pull metrics → traces → logs → retrieve a similar postmortem → produce a cited diagnosis, and stop at the approval gate for any mutating step.

### Phase 4 — Interface (Days 22-24)
CLI streaming the trace live (thought/action/observation, colorized) is the minimum. If time allows, a small Slack bot: post alert → agent investigates in-thread → reply with follow-ups.

### Phase 5 — Eval + tracing (Days 25-28)

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

Metrics: time-to-diagnosis, retrieval precision@3, tool-call correctness (right tools, not just any tools), false-positive remediation rate. Add OpenTelemetry spans around every agent step and tool call.

### Phase 6 — Terraform (stretch, Days 29+)
Deploy MCP server + agent to a small cloud instance; Qdrant self-hosted or managed; otel-demo can stay local.

---

## 6. Timeline Summary

| Week | Focus | Exit criteria |
|---|---|---|
| 1 | Stand up otel-demo, explore flags, start MCP server | Real failures visible in Grafana/Jaeger by flipping flags |
| 2 | Finish MCP server, build RAG pipeline | All tools pass MCP inspector; retrieval hits top-3 correctly |
| 3 | Agent loop + guardrails | End-to-end run on a real flagd-triggered failure, stops at approval gate |
| 4 | Interface, eval, tracing, writeup | Eval report across 5 flag-mapped scenarios, OTel traces, demo-ready |

~4 weeks solo at a steady pace; ~2-3 if you cut the Slack bot and Terraform.

---

## 7. Key Design Decisions & Rationale

These are the decisions worth being able to explain unprompted, since they're what actually gets probed in review:

- **Why build the MCP server from scratch, but not the LLM-calling layer?** MCP is a centerpiece skill of this project, alongside RAG and the agent loop — the whole point is understanding the protocol's handshake, framing, and dispatch mechanics well enough to explain them without a framework's abstraction in the way. LLM provider calls are incidental plumbing; using `litellm` there costs nothing in credibility and saves real time better spent elsewhere.
- **Why hybrid retrieval instead of pure vector search?** Pure vector search can conflate semantically similar incidents across different services. BM25 anchors on exact service names and error strings; vector search catches paraphrased symptoms. Verified empirically via the standalone retrieval eval in Phase 2.
- **Why split guardrails on read-only vs. mutating rather than something more granular?** Simple, defensible, and matches how real incident-response tooling is usually gated — automate observation, require a human for anything that changes system state.
- **Why a real demo environment instead of toy services?** Real telemetry, real failure modes, and a project people (interviewers included) can independently verify and explore themselves.

---

## 8. Interview / Portfolio Talking Points

- Walk through what happens on the wire during an MCP tool call — handshake, capability negotiation, the `tools/call` request/response
- Why hybrid retrieval beat pure vector search on your postmortem corpus, with actual precision numbers from your eval
- The guardrail design and what could go wrong without it
- What your eval numbers showed, and what failure modes you found — e.g. the agent misattributing root cause when two flags are toggled simultaneously
- Being aware of the OTel Demo's own native Agent/MCP/Chatbot addition without conflating it with your own build — shows awareness of the broader agentic-observability landscape

---

## 9. Stretch Ideas

- Multi-agent split: a "detective" agent investigating, a "communicator" agent drafting updates
- Knowledge graph linking otel-demo's actual service dependency graph to past incidents, for blast-radius reasoning
- Auto-feed resolved incidents back into the vector store so retrieval quality compounds over time
- Compare your own agent's OTel traces against otel-demo's native Agent/MCP traces as a demo of instrumented agent tooling across two independent implementations

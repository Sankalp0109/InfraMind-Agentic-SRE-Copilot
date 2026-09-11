---
service: product-catalog
failure_type: lock_contention
severity: warning
date: 2026-03-03
flag: productCatalogLockContention
---

# Product catalog slow, not failing — database lock contention

## Summary
Unlike the outright-failure incident on 2026-04-25, this incident showed
product-catalog *slowing down* rather than erroring — requests queued up
waiting on what turned out to be lock contention, with zero errors the
entire time.

## Timeline
- 22:10 — `product-catalog` p95 latency climbs from ~15ms to over 1s over about 10 minutes; error rate stays at exactly zero throughout.
- 22:15 — Downstream services (`cart`, `recommendation`) show matching latency increases specifically on their product-catalog calls, but no errors — same shape as the 2026-04-25 outage's blast radius, different symptom (slow, not failing).
- 22:20 — Confirmed via flagd UI: `productCatalogLockContention` enabled, simulating a database lock-contention scenario.
- 22:21 — Flag disabled. Latency returns to baseline over the following minute as queued requests drain.

## Root Cause
`productCatalogLockContention` simulates database-level lock contention —
representative of a real cause like a long-running write transaction (bulk
catalog update) holding a lock that read queries are blocked behind.

## Fix
No code fix (drill). Real-world equivalent: check for concurrent
long-running write transactions against the catalog database (e.g. a bulk
import job) before assuming a code-level bug in product-catalog itself.

## Diagnostic signal for future incidents
- Same blast radius as the outright product-catalog failure (cart,
  recommendation, checkout all affected via their catalog dependency), but
  **zero errors, only latency** — this distinguishes a lock-contention /
  resource-queuing problem from an actual failure, and should point
  straight at the database layer rather than product-catalog's application
  code, which isn't erroring at all.

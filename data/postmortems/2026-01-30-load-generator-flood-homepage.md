---
service: frontend
failure_type: traffic_spike
severity: warning
date: 2026-01-30
flag: loadGeneratorFloodHomepage
---

# Synthetic traffic flood to the homepage causes broad latency increase

## Summary
Every service touched by the homepage (product-catalog, ad, recommendation,
currency) showed elevated latency simultaneously, with request volume on
all of them spiking together. This is a genuine load-driven slowdown, not a
single-service failure.

## Timeline
- 09:00 — Request rate to `frontend`'s homepage handler triples abruptly.
- 09:01 — `product-catalog`, `ad`, `recommendation`, and `currency` all show correlated request-rate increases and latency increases at the same moment — every service the homepage fans out to, and nothing else.
- 09:03 — No errors anywhere, purely a capacity/latency effect from increased volume.
- 09:10 — Confirmed via flagd UI: `loadGeneratorFloodHomepage` enabled, which directs the load generator to hammer the homepage specifically rather than its usual mixed traffic pattern.
- 09:15 — Flag disabled. Traffic and latency return to baseline within a minute as the load generator resumes its normal pattern.

## Root Cause
`loadGeneratorFloodHomepage` reconfigures the synthetic load generator's
traffic mix — not a fault in any service, a test of how the whole homepage
fan-out behaves under a realistic traffic surge.

## Fix
No code fix needed — this is a load test, and every service degraded
gracefully (latency up, no errors) under 3x homepage traffic, which is the
desired outcome.

## Diagnostic signal for future incidents
- The signature that distinguishes this from a single-service failure:
  request rate *and* latency rise together, simultaneously, across every
  service that's a homepage dependency, and nowhere else in the service
  graph. A single-service failure or slowdown does not produce this
  fan-out-wide, request-count-correlated pattern — check whether the
  triggering service's own inbound request rate actually changed before
  assuming a capacity problem versus investigating a specific service bug.

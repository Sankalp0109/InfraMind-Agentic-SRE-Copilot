---
service: recommendation
failure_type: cache_failure
severity: warning
date: 2026-03-27
flag: recommendationCacheFailure
---

# Recommendation service cache failures degrade to slow fallback path

## Summary
Product recommendations kept working, but got noticeably slower — the
recommendation service's cache lookups started failing, forcing every
request onto its uncached fallback path. No customer-facing errors, just a
latency regression on the product page's "you might also like" section.

## Timeline
- 15:30 — `recommendation` p95 latency roughly triples; error rate stays at zero throughout — the service degrades gracefully rather than failing.
- 15:32 — Logs show repeated cache-lookup failures, each one falling through to a direct (uncached) computation path — confirmed via the exception log pattern, one entry per request rather than a sustained outage marker.
- 15:40 — Confirmed via flagd UI: `recommendationCacheFailure` enabled.
- 15:41 — Flag disabled. Latency returns to baseline within one cache TTL window.

## Root Cause
`recommendationCacheFailure` forces the service's cache layer to fail on
every lookup, exercising the fallback path — representative of a real cache
backend outage (e.g. the underlying Redis/Valkey instance becoming
unreachable) where the application correctly degrades rather than failing
outright.

## Fix
No code fix needed (the graceful degradation is the intended, correct
behavior). Follow-up: added an explicit alert on cache-miss rate
approaching 100%, since the previous alerting only covered hard errors and
would have missed this "still working, just slow" degradation entirely.

## Diagnostic signal for future incidents
- Zero error rate combined with a latency increase and repeated
  cache-related exception log lines (not request-level failures) is the
  signature of a cache-layer problem with working fallback logic — the
  service is telling you it recovered from something, not that it's
  broken. Worth alerting on even though nothing is technically failing.

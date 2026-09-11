---
service: ad
failure_type: request_failure
severity: warning
date: 2026-01-22
flag: adFailure
---

# Ad service failing requests outright (not slow — down)

## Summary
Unlike the high-CPU incident where every request eventually succeeded, this
incident saw the `ad` service return errors directly, with normal latency
on the requests that did fail (fast failure, not a slow timeout).

## Timeline
- 17:02 — `ad` error rate rises to ~15%, latency on both failing and succeeding requests stays normal (~10ms) — a fast-fail pattern, not resource exhaustion.
- 17:05 — Error spans show `error: true` with no exception detail, matching the "injected fault" signature seen in the cartFailure incident.
- 17:10 — Confirmed via flagd UI: `adFailure` enabled for a resilience drill.
- 17:11 — Flag disabled, error rate returns to zero.

## Root Cause
`adFailure` injects outright request failures at a configured rate,
independent of the `adHighCpu` flag — the two simulate different failure
modes for the same service (down vs. slow) and should not be conflated.

## Fix
No code fix (scheduled drill).

## Diagnostic signal for future incidents
- Fast failures with normal latency on both success and failure paths, no
  exception detail in the error span: an injected `adFailure`-style fault.
  Contrast with `adHighCpu` (everything succeeds, just slowly) — check
  latency on the *successful* requests, not just the error rate, to tell
  these apart quickly.

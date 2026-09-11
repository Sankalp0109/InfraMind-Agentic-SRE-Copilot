---
service: email
failure_type: memory_leak
severity: warning
date: 2026-04-18
flag: emailMemoryLeak
---

# Email service gradual memory growth, eventual OOM restart

## Summary
The `email` service's memory usage climbed steadily over several hours with
no corresponding change in request volume, eventually hitting its container
memory limit and getting OOM-killed and restarted by Docker's restart
policy. Confirmation emails were briefly unavailable during each restart.

## Timeline
- 06:00 — Baseline: `email` container memory ~80MB, stable.
- 06:00–11:00 — Memory climbs linearly, roughly 2MB every 10 minutes, tracking uptime rather than request volume (confirmed by comparing against `email`'s request-count metric, which stayed flat).
- 11:20 — Container hits its memory limit, OOM-killed, restarts automatically. Memory resets to baseline and the climb begins again.
- 11:20–11:22 — Brief window where confirmation emails failed to send during the restart.
- 14:00 — Pattern recognized as periodic (roughly every 5 hours) rather than a one-off.

## Root Cause
`emailMemoryLeak` deliberately leaks a small allocation per some internal
timer tick, independent of request traffic — a stand-in for a real leak
like an unbounded cache, an event listener that's never unregistered, or a
connection object that's created but never closed.

## Fix
No code fix (this is the demo's injected scenario). For a real leak with
this signature — steady growth correlated with *uptime*, not request
volume — the standard approach is a heap snapshot diff between two points
in the growth curve to identify what's accumulating, rather than guessing.

## Diagnostic signal for future incidents
- The defining signal: memory growth correlates with **time since last
  restart**, not with request count. Plot `get_metrics` for a request-count
  metric alongside container memory — if request count is flat while
  memory climbs, it's a leak independent of traffic, not a traffic-driven
  memory issue (which would track request volume instead).

---
service: ad
failure_type: high_cpu
severity: warning
date: 2026-05-05
flag: adHighCpu
---

# Ad service high CPU load degrading response times

## Summary
The `ad` service's p95 latency rose from ~10ms to over 800ms without any
change in request volume. No errors — every request eventually succeeded,
just slowly. CPU utilization on the `ad` container was pegged near 100%.

## Timeline
- 08:44 — `ad` p95 latency alert fires. Request volume (`rpc_server_duration_milliseconds_count` for `ad`) is flat, ruling out a traffic spike.
- 08:45 — `docker stats ad` shows CPU at ~98%, sustained.
- 08:47 — No memory pressure, no GC-related log lines — CPU-bound, not memory-bound.
- 08:50 — Confirmed via flagd UI: `adHighCpu` was enabled as part of a scheduled resilience test.
- 08:51 — Flag disabled. CPU and latency return to baseline within seconds.

## Root Cause
The `adHighCpu` flag makes the ad service spin a busy-loop to simulate CPU
contention, standing in for real-world causes like an inefficient ad-ranking
algorithm change or noisy-neighbor contention on a shared host.

## Fix
No code fix (scheduled test). For a real CPU-bound slowdown with no traffic
or memory change, the runbook is: check for a recent deploy to the affected
service first (an algorithmic regression is the most common real-world
cause of this exact signature), then check host-level noisy-neighbor
contention if no recent deploy correlates.

## Diagnostic signal for future incidents
- Signature: latency up, error rate flat at zero, request volume flat,
  container CPU pegged. This combination points specifically at
  CPU-bound compute, not I/O wait, not a downstream dependency, not
  increased load — narrows the search space immediately.

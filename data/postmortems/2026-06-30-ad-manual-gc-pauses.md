---
service: ad
failure_type: gc_pause
severity: warning
date: 2026-06-30
flag: adManualGc
---

# Ad service latency spikes from forced garbage collection pauses

## Summary
Intermittent latency spikes on `ad` — most requests fast, but a periodic
subset (every ~30s) spiked to 200-500ms. Unlike the sustained high-CPU
incident, average CPU looked normal; the spikes were brief and periodic.

## Timeline
- 13:00 — p99 (not p95) latency alert fires — p50 and p95 look fine, only the tail is affected, and it's periodic rather than sustained.
- 13:05 — JVM GC logs (the `ad` service is Java) show forced full GC cycles occurring roughly every 30 seconds, each pausing the service for several hundred milliseconds.
- 13:12 — Confirmed via flagd UI: `adManualGc` enabled, which forces periodic `System.gc()` calls to simulate GC-pressure incidents.
- 13:13 — Flag disabled. Periodic pauses stop immediately.

## Root Cause
`adManualGc` deliberately forces JVM garbage collection on an interval, to
simulate a real-world cause like a memory-churny code path or misconfigured
heap sizing that triggers frequent full GCs.

## Fix
No code fix (drill). For a real occurrence, check JVM heap/GC configuration
and recent code changes that increased allocation rate, rather than
treating it as a CPU or network issue.

## Diagnostic signal for future incidents
- Periodic (not sustained) tail-latency spikes with normal average CPU and
  normal p50 is a strong signal to check GC logs on a JVM-based service
  before looking anywhere else — this pattern doesn't show up in
  request-count or error-rate metrics at all, only in the latency
  histogram's tail.

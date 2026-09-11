---
service: varies
failure_type: readiness_probe_failure
severity: critical
date: 2026-02-09
flag: failedReadinessProbe
---

# Service stuck failing its readiness probe, never serving traffic

## Summary
A service came up (process running, container "Up") but never started
receiving traffic — its readiness probe kept failing, so the orchestrator
never marked it ready. From the outside this looks identical to the
service being completely down, but `docker logs` shows the process alive
and otherwise healthy.

## Timeline
- 10:00 — Deploy completes; container shows `Up` in `docker ps` but health status never transitions to `healthy`.
- 10:02 — No traffic reaching the service (zero request-count metric), but the process itself isn't crash-looping — no restart count increase.
- 10:05 — `docker logs` shows the process fully started and listening, with no errors — the application itself thinks it's fine.
- 10:08 — Confirmed via flagd UI: `failedReadinessProbe` enabled for the affected service, which makes its readiness endpoint always return unhealthy regardless of actual internal state.
- 10:09 — Flag disabled. Health status flips to `healthy` within one probe interval; traffic resumes.

## Root Cause
`failedReadinessProbe` decouples the readiness endpoint's response from the
service's actual internal state — representative of a real bug where a
readiness check has a false-negative condition (e.g. checking a dependency
that isn't actually required, or a check that never resolves).

## Fix
No code fix (drill). Real-world equivalent: audit what the readiness probe
actually checks versus what it should check, since a probe that's stricter
than necessary causes exactly this "healthy process, zero traffic" pattern.

## Diagnostic signal for future incidents
- Zero traffic to a service whose container is `Up` (not restarting, not
  crash-looping) and whose own logs show no errors is a readiness-probe
  problem, not an application crash — check `docker inspect <service>`'s
  health status specifically, don't assume the process itself is broken.

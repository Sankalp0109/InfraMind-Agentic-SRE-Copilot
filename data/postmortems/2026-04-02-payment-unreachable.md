---
service: payment
failure_type: network_unreachable
severity: critical
date: 2026-04-02
flag: paymentUnreachable
---

# Payment service unreachable — checkout hangs, then times out

## Summary
Checkout requests began hanging for ~30 seconds before failing, rather than
failing immediately. No error spans appeared on the `payment` service at
all — because no requests were reaching it. `checkout`'s outbound gRPC calls
to `payment` were timing out at the network level.

## Timeline
- 09:14 — `checkout` p95 latency alert fires (~30s, matching the gRPC client's default deadline).
- 09:15 — `payment` pod itself reports healthy: CPU/memory nominal, no errors in its own logs, readiness probe passing.
- 09:17 — Jaeger shows `checkout` spans for the outbound call to `payment` ending in `DEADLINE_EXCEEDED`, but zero corresponding server-side spans on `payment` — the requests never arrived.
- 09:22 — Confirmed via `docker logs payment` that the container is up and listening; the issue is upstream of the process, not the process itself.
- 09:25 — Identified: a network policy change applied 09:10 blocked traffic between the `checkout` and `payment` pods' network namespaces.
- 09:33 — Network policy reverted. Traffic resumes immediately.

## Root Cause
A misconfigured network policy (part of an unrelated security hardening
change) inadvertently blocked pod-to-pod traffic on the payment service's
port. This is a connectivity failure, not an application-level failure —
`payment` itself never saw the requests, so it logged nothing unusual and
its own healthcheck stayed green throughout.

## Fix
Reverted the network policy change; added the `checkout -> payment` path to
the policy's explicit allow-list before re-applying it. Added an
alert on `checkout`'s outbound gRPC error rate broken down by status code,
so `DEADLINE_EXCEEDED`/`UNAVAILABLE` (connectivity) is distinguishable from
`INTERNAL`/`INVALID_ARGUMENT` (application-level failures like the
charge-failure incident from 2026-06-14) at a glance.

## Diagnostic signal for future incidents
- The tell: `checkout`'s trace shows an outbound call to `payment`, but
  there is no corresponding *server-side* span on `payment` at all — not
  an error span, no span whatsoever. If `payment`'s own logs and metrics
  look completely normal while callers report timeouts, suspect network
  connectivity, not application state, before touching payment's code or config.

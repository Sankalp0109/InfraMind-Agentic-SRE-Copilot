---
service: kafka
failure_type: broker_outage
severity: critical
date: 2026-02-18
flag: none
---

# Kafka broker crash — full processing outage, not just lag

## Summary
Unlike a lag spike where messages are slow but still flowing, this incident
was a hard outage: the `kafka` broker container crashed and consumer groups
lost their connection entirely. Order events queued at the producer side
but nothing was consumed until the broker came back.

## Timeline
- 20:11 — `kafka` container exits (visible in `docker ps` as restarting, not just slow).
- 20:11 — Both `accounting` and `fraud-detection` consumers simultaneously start logging connection errors — a clean break, not a gradual lag climb.
- 20:12 — Docker's restart policy brings the broker back up within ~15 seconds.
- 20:13 — Consumers reconnect automatically and begin draining the backlog that accumulated during the ~1 minute of downtime.
- 20:18 — Backlog fully drained, order-status pages catch up.
- 20:40 — Root cause traced to an out-of-memory kill — the broker's configured memory limit was too tight for a burst of larger-than-usual messages.

## Root Cause
An OOM kill of the Kafka broker process, triggered by an unusually large
batch of order events (a bulk-order customer) pushing the broker's heap
past its configured container memory limit.

## Fix
Raised the broker's memory limit and added a Prometheus alert on
`kafka` container memory approaching its limit, rather than only finding
out after an OOM kill.

## Diagnostic signal for future incidents
- A **simultaneous, clean connection break** across all consumer groups
  (not a gradual lag climb) plus the broker container itself restarting is
  a broker outage, not a lag/overload situation — check `docker ps` /
  `docker logs kafka` for a restart first. Contrast with the 2026-07-01
  lag-spike incident, where the broker stayed up the whole time and lag
  built up gradually instead of breaking cleanly.

---
service: kafka
failure_type: consumer_lag
severity: warning
date: 2026-07-01
flag: kafkaQueueProblems
---

# Kafka consumer lag spike from a simultaneous queue overload

## Summary
Order processing (accounting and fraud-detection, both Kafka consumers)
began falling behind — orders were accepted at checkout but their downstream
processing (accounting ledger entries, fraud checks) lagged by several
minutes. No orders were lost, but customer-facing order-status pages showed
stale "processing" states well past the usual few-second turnaround.

## Timeline
- 16:00 — Kafka producer throughput (checkout's order-placed events) roughly doubles for a synthetic load test.
- 16:02 — Consumer lag on the `accounting` and `fraud-detection` consumer groups starts climbing; producer-side metrics look completely normal.
- 16:04 — `kafka` broker metrics show elevated request queue time — the broker itself is under load, not just the consumers falling behind on healthy processing.
- 16:10 — Lag peaks at ~4 minutes behind.
- 16:25 — Synthetic load test ends; lag drains back to near-zero over the following 5 minutes without intervention.

## Root Cause
`kafkaQueueProblems` simultaneously increases producer volume and adds
consumer-side processing delay, by design — it's meant to simulate a queue
overload combined with a slow consumer, which is exactly what a real
under-provisioned Kafka setup looks like under a genuine traffic spike.

## Fix
No incident action needed (this run was a planned load test). For a real
occurrence, the runbook calls for: check broker resource limits first
(`kafka` container CPU/memory), then consumer group parallelism
(partition count vs. consumer instance count) before assuming the fix is
"add more consumers," since if the broker itself is saturated, more
consumers won't help.

## Diagnostic signal for future incidents
- Distinguish "consumers can't keep up because processing per-message is
  slow" (consumer-side metrics show elevated per-message duration, broker
  is healthy) from "the broker itself is overloaded" (broker request queue
  time and CPU both elevated, consumers can't be blamed) — this incident
  was the latter. Check `kafka` broker metrics before scaling consumers.

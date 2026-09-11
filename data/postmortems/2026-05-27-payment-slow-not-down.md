---
service: payment
failure_type: latency
severity: warning
date: 2026-05-27
flag: none
---

# Payment service slow but succeeding — a third payment failure mode

## Summary
A third distinct payment incident pattern, included specifically to
round out the payment postmortems: charges succeeded, but the `Charge` RPC
took 3-5 seconds instead of the usual ~50ms. No errors, no unreachability —
just slow.

## Timeline
- 20:00 — `payment` p95 latency alert fires; `demo_payment_transactions_total` keeps climbing normally — charges are succeeding, just slowly.
- 20:03 — Jaeger shows the `Charge` span itself taking 3-5s, with the time spent inside the span (not waiting on a network call to an external gateway) — ruling out an external payment-gateway slowdown.
- 20:10 — Traced to a recent deploy that added synchronous fraud-scoring logic directly in the charge path, calling an internal scoring model on every request.
- 20:45 — Fraud-scoring call moved to run asynchronously after the charge is accepted, rather than blocking it.

## Root Cause
A deploy added a blocking call to a fraud-scoring service directly in the
critical path of `Charge`, turning what should be a fast operation into one
gated on a slower dependency's response time.

## Fix
Made fraud scoring asynchronous (fire-and-forget, with a separate
reconciliation step for high-risk scores) so it no longer blocks the
charge response.

## Diagnostic signal for future incidents
- Payment has (at least) three distinct failure modes that look nothing
  alike and require different responses: charges *erroring* with a clear
  exception (see 2026-06-14, likely a config/code bug in payment itself),
  payment *unreachable* with no server-side span at all (see 2026-04-02,
  a network/connectivity problem), and payment *slow but succeeding* (this
  incident, almost always a newly-added synchronous dependency in the
  request path). Check which of these three shapes you're looking at
  before picking a remediation.

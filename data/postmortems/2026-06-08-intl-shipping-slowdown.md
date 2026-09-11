---
service: shipping
failure_type: latency
severity: warning
date: 2026-06-08
flag: intlShippingSlowdown
---

# Shipping quote calculation slow, but only for international addresses

## Summary
Checkout latency increased, but only intermittently — investigation showed
it correlated with the customer's shipping address being international
rather than domestic. Domestic-address checkouts were unaffected.

## Timeline
- 19:00 — Checkout p95 latency alert fires, but request-level investigation shows a bimodal distribution: most requests fast, a subset consistently slow.
- 19:05 — Cross-referencing slow requests against order data shows every slow one has a non-US shipping address; every fast one is domestic.
- 19:10 — `get_traces` on `shipping` confirms the slow span is `ShippingService/GetQuote`, specifically for international requests.
- 19:15 — Confirmed via flagd UI: `intlShippingSlowdown` enabled, adding latency specifically to the international quote code path.
- 19:16 — Flag disabled. International checkout latency returns to normal.

## Root Cause
`intlShippingSlowdown` targets latency injection at a specific code path
(international rate calculation) rather than the whole service —
representative of a real cause like an inefficient international-rates
lookup table, or a synchronous call to an external customs/duties API only
triggered for cross-border orders.

## Fix
No code fix (drill). Real-world equivalent: profile the specific
international-rate code path rather than the shipping service broadly,
since the domestic path is provably unaffected and a broad investigation
would waste time there.

## Diagnostic signal for future incidents
- A latency regression that's *conditional* on a specific input (here,
  address country) rather than affecting all traffic to a service is a
  strong clue to segment the metric/trace data by that dimension before
  investigating further — average-latency metrics alone would have hidden
  this entirely, since most requests were unaffected.

---
service: cart
failure_type: request_failure
severity: warning
date: 2026-05-20
flag: cartFailure
---

# Cart service failing a fraction of AddItem requests

## Summary
Intermittent failures on `CartService/AddItem` — roughly 1 in 5 requests
returned an error, with no clear pattern by customer, cart size, or item.
Users reported items silently failing to add to their cart.

## Timeline
- 11:40 — Error rate on `cart` spans rises to ~20%, flat and steady (not climbing) — consistent with a probabilistic fault, not a resource exhaustion curve.
- 11:42 — `valkey-cart` (the cart's Redis-compatible backing store) metrics show no elevated latency or connection errors — ruled out as the cause.
- 11:50 — Jaeger error spans on `cart` show no exception logs, just a bare `error: true` with no stack trace — points at an intentionally injected fault rather than a real code bug (a real bug usually leaves a stack trace).
- 12:05 — Confirmed via the flagd UI that `cartFailure` was set to a nonzero probability during a chaos-engineering drill that wasn't communicated to the on-call rotation.
- 12:06 — Flag reset to `off`. Error rate drops to zero immediately.

## Root Cause
Not a real failure — the `cartFailure` flagd flag was left partially enabled
after a chaos drill. Included here because the failure signature (flat
~20% error rate, no exception detail, no backend degradation) is exactly
what a real intermittent cart bug would look like from the outside, and is
worth recognizing on sight.

## Fix
No code fix needed. Process fix: chaos drills using flagd flags now require
posting to `#incidents` before and after, and the on-call runbook now lists
"check flagd UI for any nonzero fault-injection flag" as step one for any
otherwise-unexplained intermittent error.

## Diagnostic signal for future incidents
- A flat, steady error percentage with **no exception message or stack
  trace** in the error span's logs is the signature of an injected
  probabilistic fault (`cartFailure` or similar), not an organic bug.
- Always check active flags (`get_active_alerts` / flagd UI) before deep
  debugging an error pattern that looks "too clean."

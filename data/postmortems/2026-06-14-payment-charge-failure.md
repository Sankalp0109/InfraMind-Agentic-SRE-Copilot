---
service: payment
failure_type: charge_failure
severity: critical
date: 2026-06-14
flag: paymentFailure
---

# Payment charge requests failing with "Invalid token" errors

## Summary
Starting at 14:02 UTC, a growing share of checkout attempts began failing at
the payment step. Customers saw a generic "checkout failed" error; internally,
the `payment` service's `Charge` RPC was returning errors for roughly a third
of requests, rising to all requests by 14:15.

## Timeline
- 14:02 — First `PaymentService/Charge` errors appear in Jaeger, isolated to the `charge` span.
- 14:04 — `demo_payment_transactions_total` (Prometheus) flattens for the `checkout` service's dependent calls, while `checkout`'s own request rate stays normal — the failure is isolated to payment, not upstream traffic loss.
- 14:15 — Error rate reaches 100%. All checkout attempts fail.
- 14:18 — On-call pages triggered by cart-to-checkout conversion drop.
- 14:31 — Root cause identified: a bad config push disabled the payment gateway's token validation bypass for internal test traffic, causing legitimate loyalty-tier tokens to be rejected.
- 14:40 — Config reverted. Error rate returns to baseline within 2 minutes.

## Root Cause
The `charge` handler in the payment service raises `Error: Payment request
failed. Invalid token.` (see `charge.js:46`) whenever the configured gateway
token fails validation. A deploy at 13:58 rotated the gateway token but the
corresponding secret wasn't updated in the payment service's environment,
so every charge request presented a stale token.

## Fix
Rolled back the token rotation deploy. Added a startup healthcheck to the
payment service that performs a dry-run token validation against the gateway
before marking the pod ready, so a bad token surfaces at deploy time instead
of on the first real customer transaction.

## Diagnostic signal for future incidents
- Jaeger: look for `error: true` spans on the `payment` service with
  `otel.status_description` starting with "Payment request failed."
- Prometheus: `demo_payment_transactions_total` for the `payment` service
  goes flat (not to zero — it's a success counter) while `checkout`'s own
  request volume stays normal.
- This is distinct from payment being *unreachable* (connection-level
  failures, no charge span produced at all) — see the payment-unreachable
  postmortem for that failure mode.

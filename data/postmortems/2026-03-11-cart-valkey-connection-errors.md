---
service: cart
failure_type: backend_dependency_failure
severity: critical
date: 2026-03-11
flag: none
---

# Cart failures caused by valkey-cart connection pool exhaustion

## Summary
Cart requests began failing with connection errors, not application errors.
Unlike the 2026-05-20 `cartFailure` flag incident (flat, clean error rate,
no stack trace), this one showed climbing latency followed by connection
refused errors, with a clear stack trace pointing at the Redis client.

## Timeline
- 03:20 — `cart` p99 latency starts climbing steadily over ~15 minutes.
- 03:35 — First `ECONNREFUSED` errors from the valkey client appear in `cart`'s logs, with a full stack trace through the connection pool code.
- 03:36 — `valkey-cart` container metrics show connection count pinned at its configured max (the pool was never being released — a connection leak in a recent cart service deploy that forgot to close connections on a specific error path).
- 03:50 — Cart service restarted, temporarily clearing the leaked connections and restoring service while a proper fix was prepared.
- 05:10 — Fixed deploy shipped: the leaked code path now closes its connection in a `finally` block.

## Root Cause
A code change three days prior introduced an early-return path in the
add-to-cart handler that skipped releasing its valkey connection back to
the pool on a specific validation-failure branch. Under normal traffic this
leaked slowly enough to go unnoticed; a traffic spike accelerated the leak
past the pool's capacity within about 15 minutes.

## Fix
Added the missing connection release in a `finally` block. Added a
Prometheus alert on `valkey-cart` connection pool utilization approaching
its configured maximum, rather than only alerting once connections were
already exhausted.

## Diagnostic signal for future incidents
- Climbing latency followed by connection-level errors **with a stack
  trace through client/pool code** points at a real backend dependency
  problem — contrast with the flat, trace-less error rate of an injected
  `cartFailure` flag (see the 2026-05-20 postmortem).
- Check `valkey-cart`'s own connection/memory metrics directly rather than
  assuming the failure originates in `cart`'s own application code.

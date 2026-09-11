---
service: product-catalog
failure_type: request_failure
severity: critical
date: 2026-04-25
flag: productCatalogFailure
---

# Product catalog service failing lookups — empty product pages sitewide

## Summary
Product catalog lookups began failing outright, causing product pages
across the storefront to render empty (no product name, price, or
description). This is upstream of nearly everything — cart, recommendation,
and checkout all depend on catalog data and were affected indirectly.

## Timeline
- 16:40 — `product-catalog` error rate jumps from 0% to ~40% with no deploy immediately preceding it.
- 16:42 — Downstream effects visible in `cart` and `recommendation` traces — both show errors originating from their calls *into* `product-catalog`, not from their own logic (confirmed via `get_traces` filtering each service's spans to just the ones touching product-catalog).
- 16:45 — `product-catalog`'s own error logs show no exception detail — the "injected fault" signature.
- 16:50 — Confirmed via flagd UI: `productCatalogFailure` enabled.
- 16:51 — Flag disabled. Error rate returns to zero across all affected services simultaneously.

## Root Cause
`productCatalogFailure` injects request failures directly in
product-catalog — representative of a real catalog-service outage
(database connectivity, deploy regression, etc).

## Fix
No code fix (drill).

## Diagnostic signal for future incidents
- Because product-catalog sits upstream of cart, recommendation, and
  checkout, a real outage here shows up as *simultaneous* errors across
  multiple seemingly-unrelated services. The tell that it's one root cause,
  not several independent failures: every affected service's error spans
  trace back to the same downstream call (product-catalog), and each
  service's own logic outside that call path is unaffected. Start
  investigation at the common dependency, not at each symptom service.

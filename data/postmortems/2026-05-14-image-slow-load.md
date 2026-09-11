---
service: image-provider
failure_type: latency
severity: warning
date: 2026-05-14
flag: imageSlowLoad
---

# Product image loading slowed across the storefront

## Summary
Product page load times increased noticeably; investigation traced it to
the `image-provider` service taking 2-4 seconds to serve images that
normally return in under 100ms. No errors, just slow.

## Timeline
- 12:15 — Frontend real-user-monitoring shows increased "largest contentful paint" times; backend error rates are all at zero.
- 12:18 — `get_traces` on `frontend` shows the slowdown concentrated in calls to `image-provider`; every other backend call is normal speed.
- 12:20 — `image-provider`'s own CPU/memory look normal — it's not resource-starved, it's just slow to respond.
- 12:25 — Confirmed via flagd UI: `imageSlowLoad` enabled, which adds artificial latency to image-provider's responses.
- 12:26 — Flag disabled. Load times return to normal immediately.

## Root Cause
`imageSlowLoad` injects artificial response delay — representative of a
real cause like a slow upstream CDN/object-storage backend, or a synchronous
image-processing step (resize/compress) added to the request path without
being backgrounded.

## Fix
No code fix (drill). For a real slow-image incident with normal
CPU/memory, check the service's *external* dependencies (object storage,
CDN) and whether any processing was moved onto the synchronous request path,
since the service's own resource metrics won't show the cause.

## Diagnostic signal for future incidents
- A single downstream service's calls are slow while its own CPU/memory
  are normal and every other service's calls are unaffected: narrow
  straight to that service's *external* dependencies rather than its own
  resource usage — this pattern rules out a resource or code-path
  bottleneck inside the slow service itself.

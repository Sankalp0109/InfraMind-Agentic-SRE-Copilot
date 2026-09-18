"""OpenTelemetry tracing for the agent itself, exported to the same
otel-collector the rest of otel-demo uses — InfraMind's own investigation
spans show up in the same Jaeger UI as the services it investigates, which
lets them be compared directly against otel-demo's own native
Agent/MCP/Chatbot instrumentation (Section 8 of the build plan).

The collector's OTLP HTTP port is published on a random ephemeral host port
in this environment (same bare-port-number pattern found for Grafana/Jaeger
in Phase 0 — not a fixed one), so it's discovered at runtime via
`docker port` rather than hardcoded. If the collector isn't reachable (the
otel-demo stack isn't running), tracing degrades to a no-op tracer rather
than failing the agent — observability of the agent is a bonus, not a
dependency the agent's actual job should fail on.
"""

import os
import subprocess

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "inframind-agent"

_initialized = False
_provider: TracerProvider | None = None


def _discover_otlp_endpoint() -> str | None:
    override = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if override:
        return override
    try:
        result = subprocess.run(
            ["docker", "port", "otel-collector", "4318/tcp"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        # e.g. "0.0.0.0:52601\n[::]:52601" -- any line's trailing :port works
        host_port = result.stdout.strip().splitlines()[0].rsplit(":", 1)[-1]
        return f"http://localhost:{host_port}"
    except Exception:
        return None


def get_tracer():
    """Returns a tracer exporting real spans if the otel-collector is
    reachable, otherwise a no-op tracer (opentelemetry's default when no
    provider is configured) — callers don't need to know which."""
    global _initialized, _provider
    if not _initialized:
        endpoint = _discover_otlp_endpoint()
        if endpoint:
            _provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
            _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
            trace.set_tracer_provider(_provider)
        _initialized = True
    return trace.get_tracer(SERVICE_NAME)


def shutdown_tracing() -> None:
    """Force-flush and shut down the span processor. Short-lived CLI/eval
    processes exit as soon as the last line of code runs — the batch
    processor's background export thread might not have flushed yet, so
    this should be called once at the very end of any entry point that used
    get_tracer(), rather than relying on atexit behavior alone."""
    if _provider is not None:
        _provider.force_flush()
        _provider.shutdown()

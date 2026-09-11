"""get_traces: recent traces for a service from Jaeger, optionally error-only.

Base path is /jaeger/ui/api (Jaeger v2's jaeger_query extension serves both
the UI and its API under the same base_path) — see NOTES.md. A full trace can
carry 100+ spans across every service in the checkout flow; this tool
extracts just the spans belonging to the requested service and, for each,
pulls out the exception detail from its logs if present, rather than
returning the raw trace tree.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from config import JAEGER_URL

NAME = "get_traces"
DESCRIPTION = (
    "Get recent traces for a service from Jaeger, optionally filtered to only "
    "error traces. Read-only. Strongest signal for cascading failures across "
    "the polyglot service graph — a trace spans every service a request touched."
)
READ_ONLY = True
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "service": {
            "type": "string",
            "description": "Jaeger service name, e.g. 'payment', 'cart', 'checkout'.",
        },
        "error_only": {
            "type": "boolean",
            "description": "Only return traces containing an error span. Defaults to true.",
        },
        "limit": {
            "type": "integer",
            "description": "Max traces to return. Defaults to 5.",
        },
    },
    "required": ["service"],
    "additionalProperties": False,
}


def _extract_service_spans(trace: dict, service: str) -> list[dict]:
    processes = trace.get("processes", {})
    spans_out = []
    for span in trace.get("spans", []):
        if processes.get(span.get("processID"), {}).get("serviceName") != service:
            continue
        tags = {t["key"]: t.get("value") for t in span.get("tags", [])}
        exception = None
        for log in span.get("logs", []):
            fields = {f["key"]: f.get("value") for f in log.get("fields", [])}
            if fields.get("event") == "exception":
                exception = {
                    "type": fields.get("exception.type"),
                    "message": fields.get("exception.message"),
                }
                break
        spans_out.append(
            {
                "operation": span.get("operationName"),
                "error": bool(tags.get("error")),
                "status_description": tags.get("otel.status_description"),
                "exception": exception,
            }
        )
    return spans_out


def call(service: str, error_only: bool = True, limit: int = 5) -> tuple[list[dict], bool]:
    query = {"service": service, "limit": limit}
    if error_only:
        query["tags"] = json.dumps({"error": "true"})
    url = f"{JAEGER_URL}/api/traces?{urllib.parse.urlencode(query)}"

    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            body = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return [{"type": "text", "text": f"Failed to reach Jaeger: {exc}"}], True

    traces = body.get("data", [])
    if not traces:
        suffix = " (error_only=true — try error_only=false for a broader look)" if error_only else ""
        return [{"type": "text", "text": f"No traces found for service '{service}'{suffix}."}], False

    summary = [
        {
            "traceID": t.get("traceID"),
            "spans": _extract_service_spans(t, service),
        }
        for t in traces
    ]
    return [{"type": "text", "text": json.dumps(summary, indent=2)}], False

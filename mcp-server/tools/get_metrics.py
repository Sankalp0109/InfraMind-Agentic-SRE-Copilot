"""get_metrics: time-series data for a service's metric, from Prometheus.

Signature matches the build plan: get_metrics(service, metric_name, time_range).
Metric names actually present in this stack are cataloged in NOTES.md — not
every service emits the same metrics, so a query returning no data is a
normal, expected outcome, not necessarily an error.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from config import PROMETHEUS_URL

NAME = "get_metrics"
DESCRIPTION = (
    "Query a time-series metric for a specific service from Prometheus, over a "
    "recent time window. Read-only. See NOTES.md for which metric names exist "
    "per service — not every service emits the same metrics."
)
READ_ONLY = True
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "service": {
            "type": "string",
            "description": "Value of the service_name label, e.g. 'payment', 'cart', 'ad'.",
        },
        "metric_name": {
            "type": "string",
            "description": "Prometheus metric name, e.g. 'demo_payment_transactions_total'.",
        },
        "time_range": {
            "type": "string",
            "description": "Lookback window, e.g. '5m', '15m', '1h'. Defaults to '15m'.",
        },
    },
    "required": ["service", "metric_name"],
    "additionalProperties": False,
}

_RANGE_RE = re.compile(r"^(\d+)([smh])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def _parse_range_seconds(time_range: str) -> int:
    match = _RANGE_RE.match(time_range.strip())
    if not match:
        raise ValueError(f"Invalid time_range '{time_range}', expected e.g. '5m', '15m', '1h'")
    value, unit = match.groups()
    return int(value) * _UNIT_SECONDS[unit]


def call(service: str, metric_name: str, time_range: str = "15m") -> tuple[list[dict], bool]:
    try:
        duration = _parse_range_seconds(time_range)
    except ValueError as exc:
        return [{"type": "text", "text": str(exc)}], True

    end = time.time()
    start = end - duration
    step = max(15, min(300, duration // 60))

    query = f'{metric_name}{{service_name="{service}"}}'
    params = urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": step})
    url = f"{PROMETHEUS_URL}/api/v1/query_range?{params}"

    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            body = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return [{"type": "text", "text": f"Failed to reach Prometheus: {exc}"}], True

    if body.get("status") != "success":
        return [{"type": "text", "text": f"Prometheus query failed: {json.dumps(body)}"}], True

    result = body["data"]["result"]
    if not result:
        text = (
            f"No data for metric '{metric_name}' with service_name='{service}' over the "
            f"last {time_range}. The metric may not exist for this service — see NOTES.md, "
            "or try get_active_alerts / get_traces for corroborating signal."
        )
        return [{"type": "text", "text": text}], False

    # Summarize rather than dumping every sample: enough for trend detection
    # (first vs. last point) without flooding the model's context.
    series = [
        {
            "labels": r.get("metric", {}),
            "num_points": len(r.get("values", [])),
            "first": (r["values"][0] if r.get("values") else None),
            "last": (r["values"][-1] if r.get("values") else None),
        }
        for r in result
    ]

    return [{"type": "text", "text": json.dumps(series, indent=2)}], False

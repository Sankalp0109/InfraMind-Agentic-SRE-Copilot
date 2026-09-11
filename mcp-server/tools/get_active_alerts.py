"""get_active_alerts: currently firing alerts from Grafana's unified alerting.

Phase 0 found that otel-demo's alert rules (e.g. CartAddItemHighLatency) are
provisioned as Grafana alert rules, not Prometheus rule files — Prometheus's
own /api/v1/rules is empty in this stack. Firing instances are read from
Grafana's Alertmanager-compatible API.
"""

import base64
import json
import urllib.error
import urllib.request

from config import GRAFANA_PASSWORD, GRAFANA_URL, GRAFANA_USER

NAME = "get_active_alerts"
DESCRIPTION = (
    "List currently firing alerts across the OpenTelemetry Demo services, "
    "as tracked by Grafana's unified alerting. Read-only."
)
READ_ONLY = True
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "service_name": {
            "type": "string",
            "description": "Filter to alerts whose labels mention this service name. Omit for all active alerts.",
        }
    },
    "additionalProperties": False,
}


def _auth_header() -> str:
    token = base64.b64encode(f"{GRAFANA_USER}:{GRAFANA_PASSWORD}".encode()).decode()
    return f"Basic {token}"


def call(service_name: str | None = None) -> tuple[list[dict], bool]:
    url = f"{GRAFANA_URL}/api/alertmanager/grafana/api/v2/alerts"
    req = urllib.request.Request(url, headers={"Authorization": _auth_header()})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            alerts = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # A timed-out socket read raises a bare TimeoutError in this Python
        # version rather than being wrapped in URLError by urllib — caught
        # explicitly here so a slow/unreachable backend degrades to a tool
        # execution error instead of crashing the handler.
        return [{"type": "text", "text": f"Failed to reach Grafana alerting API: {exc}"}], True

    results = []
    for alert in alerts:
        labels = alert.get("labels", {})
        if service_name and labels.get("service_name") != service_name:
            continue
        results.append(
            {
                "alertname": labels.get("alertname"),
                "service_name": labels.get("service_name"),
                "severity": labels.get("severity"),
                "state": alert.get("status", {}).get("state"),
                "startsAt": alert.get("startsAt"),
                "summary": alert.get("annotations", {}).get("summary"),
                "description": alert.get("annotations", {}).get("description"),
            }
        )

    if not results:
        text = "No active alerts" + (f" for service '{service_name}'" if service_name else "") + "."
    else:
        text = json.dumps(results, indent=2)

    return [{"type": "text", "text": text}], False

"""get_logs: recent container logs for a service, via `docker logs`.

Per the build plan: container logs to start (rather than a log aggregation
backend the stack doesn't otherwise have). Container names match the
otel-demo compose service names 1:1, so `service` is passed straight through
to `docker logs <service>` — no separate name-mapping layer.
"""

import subprocess

NAME = "get_logs"
DESCRIPTION = (
    "Get recent container log lines for a service, via `docker logs`. "
    "Read-only. Service name must match a running otel-demo container, "
    "e.g. 'payment', 'cart', 'frontend-proxy'."
)
READ_ONLY = True
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "service": {
            "type": "string",
            "description": "Container/service name, e.g. 'payment'.",
        },
        "lines": {
            "type": "integer",
            "description": "Number of most recent log lines to return. Defaults to 50.",
        },
    },
    "required": ["service"],
    "additionalProperties": False,
}

_MAX_LINES = 500


def call(service: str, lines: int = 50) -> tuple[list[dict], bool]:
    lines = max(1, min(lines, _MAX_LINES))

    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(lines), service],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return [{"type": "text", "text": "docker CLI not found on this machine."}], True
    except subprocess.TimeoutExpired:
        return [{"type": "text", "text": f"Timed out fetching logs for '{service}'."}], True

    if result.returncode != 0:
        # docker logs writes "No such container" to stderr with a non-zero exit —
        # an unknown service name, not an infrastructure failure.
        return [{"type": "text", "text": result.stderr.strip() or f"Unknown container '{service}'."}], True

    # otel-demo services log OTel-instrumented JSON/plaintext to both stdout
    # and stderr depending on language; combine both, most recent last.
    output = (result.stdout + result.stderr).strip()
    if not output:
        return [{"type": "text", "text": f"No log output for '{service}' in the last {lines} lines."}], False

    return [{"type": "text", "text": output}], False

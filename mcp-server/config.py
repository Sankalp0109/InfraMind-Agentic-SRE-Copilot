"""Base URLs for the observability backends this server's tools wrap.

Defaults match the otel-demo stack as brought up per the project README
(DEMO_VERSION=3.0.0, full + observability compose files). Override via
environment variables to point at a different stack.
"""

import os

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
JAEGER_URL = os.environ.get("JAEGER_URL", "http://localhost:8080/jaeger/ui")
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:8080/grafana")
GRAFANA_USER = os.environ.get("GRAFANA_USER", "admin")
GRAFANA_PASSWORD = os.environ.get("GRAFANA_PASSWORD", "admin")

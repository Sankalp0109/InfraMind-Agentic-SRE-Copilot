"""Tool registry: aggregates each tool module into the MCP tools/list and
tools/call dispatch tables, plus a read_only/mutating tag per tool for the
guardrails Phase 3 adds on top of this server.
"""

from tools import (
    create_incident_ticket,
    get_active_alerts,
    get_logs,
    get_metrics,
    get_recent_deploys,
    get_traces,
    post_to_slack,
    search_past_incidents,
)

_MODULES = [
    get_active_alerts,
    get_metrics,
    get_traces,
    get_logs,
    get_recent_deploys,
    search_past_incidents,
    create_incident_ticket,
    post_to_slack,
]

TOOLS = [
    {
        "name": mod.NAME,
        "description": mod.DESCRIPTION,
        "inputSchema": mod.INPUT_SCHEMA,
    }
    for mod in _MODULES
]

TOOL_HANDLERS = {mod.NAME: mod.call for mod in _MODULES}

READ_ONLY_TOOLS = {mod.NAME for mod in _MODULES if mod.READ_ONLY}

"""create_incident_ticket: persist an incident record to a local SQLite DB.

MUTATING — this is the first tool that actually changes state rather than
just reading it, which is exactly the read_only/mutating split Phase 3's
guardrails will gate on. The DB file lives next to this module, created on
first use.
"""

import json
import sqlite3
import time
from pathlib import Path

NAME = "create_incident_ticket"
DESCRIPTION = (
    "Create an incident ticket recording a diagnosis and its evidence. "
    "MUTATING — writes a persistent record."
)
READ_ONLY = False
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short incident title."},
        "description": {
            "type": "string",
            "description": "Diagnosis, citing the specific evidence (metrics, traces, logs, past incidents) that led to it.",
        },
        "severity": {
            "type": "string",
            "enum": ["low", "warning", "critical"],
            "description": "Defaults to 'warning'.",
        },
        "service": {"type": "string", "description": "Primary service implicated, if known."},
    },
    "required": ["title", "description"],
    "additionalProperties": False,
}

_DB_PATH = Path(__file__).resolve().parent.parent / "incidents.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT NOT NULL,
            service TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def call(
    title: str, description: str, severity: str = "warning", service: str | None = None
) -> tuple[list[dict], bool]:
    if severity not in ("low", "warning", "critical"):
        return [{"type": "text", "text": f"Invalid severity '{severity}': must be low, warning, or critical."}], True

    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        conn = _connect()
        with conn:
            cursor = conn.execute(
                "INSERT INTO incidents (title, description, severity, service, status, created_at) "
                "VALUES (?, ?, ?, ?, 'open', ?)",
                (title, description, severity, service, created_at),
            )
        ticket_id = cursor.lastrowid
        conn.close()
    except sqlite3.Error as exc:
        return [{"type": "text", "text": f"Failed to write incident ticket: {exc}"}], True

    record = {
        "id": ticket_id,
        "title": title,
        "description": description,
        "severity": severity,
        "service": service,
        "status": "open",
        "created_at": created_at,
    }
    return [{"type": "text", "text": f"Created incident #{ticket_id}\n" + json.dumps(record, indent=2)}], False

"""Exposes data/postmortems/*.md as MCP resources.

Phase 2 populates the postmortem corpus; this module just reflects whatever
markdown files exist there, so today's empty resources/list result becomes
real content automatically once Phase 2 writes files — no server change
needed. URIs are a custom scheme (not bare file:// paths) so a resource
identifier never doubles as a real filesystem path outside this directory,
per the spec's own path-traversal warning for file:// resources.
"""

from pathlib import Path

from protocol import ProtocolError

POSTMORTEMS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "postmortems"
URI_PREFIX = "inframind://postmortems/"


def _uri_for(filename: str) -> str:
    return f"{URI_PREFIX}{filename}"


def _title_from(path: Path) -> str:
    """First markdown H1 in the file, e.g. '# Payment charge failing' -> that
    text. Falls back to a filename-derived title if no H1 is present."""
    for line in path.read_text().splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ")


def list_resources() -> list[dict]:
    if not POSTMORTEMS_DIR.is_dir():
        return []
    return [
        {
            "uri": _uri_for(path.name),
            "name": path.name,
            "description": f"Postmortem: {_title_from(path)}",
            "mimeType": "text/markdown",
        }
        for path in sorted(POSTMORTEMS_DIR.glob("*.md"))
    ]


def read_resource(uri: str) -> list[dict]:
    if not uri.startswith(URI_PREFIX):
        raise ProtocolError(-32602, "Resource not found", data={"uri": uri})

    filename = uri[len(URI_PREFIX) :]
    # Bare filename only — no traversal, no nested paths, no absolute paths.
    if not filename or "/" in filename or filename in (".", ".."):
        raise ProtocolError(-32602, "Resource not found", data={"uri": uri})

    path = POSTMORTEMS_DIR / filename
    if not path.is_file():
        raise ProtocolError(-32602, "Resource not found", data={"uri": uri})

    return [{"uri": uri, "mimeType": "text/markdown", "text": path.read_text()}]

"""read_only vs. mutating tool gating.

The split itself already exists — every mcp-server tool module tags itself
READ_ONLY at definition time (see mcp-server/tools/*.py), aggregated into
READ_ONLY_TOOLS by the tool registry. This module is deliberately thin: it
just answers "does this tool need human approval before running," and
leaves what "approval" means (a CLI prompt, a Slack button, auto-deny in a
non-interactive eval run) to the caller — the loop and the eval harness
need different approval mechanisms, and neither should be hardcoded here.
"""

import sys
from pathlib import Path

_MCP_SERVER_DIR = Path(__file__).resolve().parent.parent / "mcp-server"
if str(_MCP_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_SERVER_DIR))

from tools import READ_ONLY_TOOLS  # noqa: E402


def needs_approval(tool_name: str) -> bool:
    """True for any tool not explicitly tagged read-only — fail closed:
    an unrecognized tool name requires approval rather than running freely,
    since the safe default for "I don't know what this does" is to ask."""
    return tool_name not in READ_ONLY_TOOLS


def request_approval(tool_name: str, arguments: dict) -> bool:
    """Default interactive approval gate: a yes/no prompt on the CLI. The
    eval harness (Phase 5) should pass its own approval callback instead of
    calling this directly, since a batch of scenarios can't block on stdin.
    """
    print(f"\n[APPROVAL NEEDED] Run mutating tool '{tool_name}' with arguments:")
    print(f"  {arguments}")
    answer = input("Approve? [y/N] ").strip().lower()
    return answer == "y"

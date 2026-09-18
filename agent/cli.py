"""CLI: stream an investigation live, colorized, and log the full trace.

Minimum viable interface per the build plan — a Slack bot is the stretch
goal, not built here. Streaming works via run_investigation()'s on_event
hook (agent/loop.py), so each thought/action/observation prints the moment
it happens rather than only appearing once the whole investigation is done.
"""

import json
import sys
import time
from pathlib import Path

from loop import run_investigation
from tracing import shutdown_tracing

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"

_RUNS_DIR = Path(__file__).resolve().parent / "runs"
_MAX_DISPLAY_CHARS = 500


def _truncate(text: str) -> str:
    if len(text) <= _MAX_DISPLAY_CHARS:
        return text
    return text[:_MAX_DISPLAY_CHARS] + f"{DIM}... [{len(text) - _MAX_DISPLAY_CHARS} more chars, see log file]{RESET}"


def _print_event(event: dict) -> None:
    kind = event["type"]

    if kind == "thought":
        args = json.dumps(event["arguments"]) if event["arguments"] else "{}"
        print(f"{CYAN}[thought]{RESET} calling {BOLD}{event['tool']}{RESET}({args})")

    elif kind == "action":
        if event["approved"]:
            print(f"{YELLOW}[action]{RESET} running {event['tool']}...")
        else:
            print(f"{RED}[action]{RESET} denied by human approver: {event['tool']} was not run")

    elif kind == "observation":
        color = RED if event["is_error"] else GREEN
        label = "error" if event["is_error"] else "ok"
        print(f"{color}[observation:{label}]{RESET} {_truncate(event['text'])}")

    elif kind == "diagnosis":
        print(f"\n{BOLD}=== DIAGNOSIS ==={RESET}")
        print(event["content"])

    print()  # blank line between events for readability


def _log_run(alert_message: str, result: dict) -> Path:
    _RUNS_DIR.mkdir(exist_ok=True)
    path = _RUNS_DIR / f"{time.strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps({"alert": alert_message, **result}, indent=2))
    return path


def main() -> None:
    alert = " ".join(sys.argv[1:]) or "Payment error rate is elevated. Investigate."
    print(f"{BOLD}Investigating:{RESET} {alert}\n")

    result = run_investigation(alert, on_event=_print_event)

    log_path = _log_run(alert, result)
    print(f"{DIM}Full trace logged to {log_path}{RESET}")

    shutdown_tracing()


if __name__ == "__main__":
    main()

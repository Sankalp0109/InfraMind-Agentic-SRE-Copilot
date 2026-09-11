"""post_to_slack: notify a channel, via a real webhook if configured.

MUTATING — sends an externally-visible notification. No Slack workspace is
wired up for local dev, so this is mocked by default (matching the build
plan's "real/mocked webhook"): if SLACK_WEBHOOK_URL is unset, the message is
logged and a clearly-labeled simulated response is returned rather than
silently failing or pretending to have sent something it didn't.
"""

import json
import os
import urllib.error
import urllib.request

NAME = "post_to_slack"
DESCRIPTION = (
    "Post a message to a Slack channel. MUTATING — sends an external notification. "
    "Falls back to a simulated (logged, not sent) post if no webhook is configured."
)
READ_ONLY = False
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "channel": {"type": "string", "description": "Channel name, e.g. '#incidents'."},
        "message": {"type": "string", "description": "Message text to post."},
    },
    "required": ["channel", "message"],
    "additionalProperties": False,
}


def call(channel: str, message: str) -> tuple[list[dict], bool]:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    if not webhook_url:
        text = (
            "[SIMULATED — no SLACK_WEBHOOK_URL configured, message not actually sent]\n"
            f"channel: {channel}\nmessage: {message}"
        )
        return [{"type": "text", "text": text}], False

    payload = json.dumps({"channel": channel, "text": message}).encode()
    req = urllib.request.Request(
        webhook_url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return [{"type": "text", "text": f"Failed to post to Slack: {exc}"}], True

    return [{"type": "text", "text": f"Posted to {channel}."}], False

"""get_recent_deploys: simulated deploy history for a service.

otel-demo has no real deploy history — it's a static demo stack, not a
service with an actual release pipeline. Per the build plan, this is
mocked. Deterministic per service name (seeded, not random.seed(None)) so
eval runs are reproducible and results are stable across calls, rather than
generating a new fake history every time the agent asks.
"""

import hashlib
import json
import random
import time

NAME = "get_recent_deploys"
DESCRIPTION = (
    "Get recent deploy history for a service. SIMULATED DATA — otel-demo has "
    "no real deploy pipeline, so this returns a deterministic fake history for "
    "the given service name, useful as a plausible signal for the agent to "
    "correlate against ('did this start right after a deploy?')."
)
READ_ONLY = True
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "service": {
            "type": "string",
            "description": "Service name, e.g. 'payment'.",
        }
    },
    "required": ["service"],
    "additionalProperties": False,
}

_AUTHORS = ["a.chen", "m.rossi", "s.patel", "j.kim", "otel-bot"]


def call(service: str) -> tuple[list[dict], bool]:
    seed = int(hashlib.sha256(service.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)

    num_deploys = rng.randint(1, 4)
    now = time.time()
    deploys = []
    offset_hours = 0
    for i in range(num_deploys):
        offset_hours += rng.randint(2, 72)
        deployed_at = now - offset_hours * 3600
        deploys.append(
            {
                "service": service,
                "version": f"3.0.{num_deploys - i}",
                "commit": hashlib.sha1(f"{service}{i}{seed}".encode()).hexdigest()[:8],
                "deployed_by": rng.choice(_AUTHORS),
                "deployed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(deployed_at)),
            }
        )

    text = "[SIMULATED — otel-demo has no real deploy pipeline]\n" + json.dumps(deploys, indent=2)
    return [{"type": "text", "text": text}], False

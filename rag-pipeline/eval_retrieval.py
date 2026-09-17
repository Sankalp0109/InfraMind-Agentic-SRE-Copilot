"""Standalone retrieval quality check: does search_past_incidents surface
the right postmortem in the top 3 for realistic incident-description
queries? Run before wiring retrieval into the agent (Phase 3) — per the
build plan, retrieval quality should be verified on its own first.

Half the queries specifically target the corpus's deliberate near-duplicate
pairs (two cart incidents, two kafka incidents, three payment incidents) —
that's the actual point of having written them (see
IMPLEMENTATION_DETAILS.md): if hybrid retrieval can't tell "cart failing
with no error detail" apart from "cart failing with a connection-pool
stack trace," it isn't earning its complexity over plain vector search.

Run standalone: `python eval_retrieval.py`
"""

from retrieve import search_past_incidents

# (query, expected source_file among the top 3)
QUERIES = [
    ("payment charges failing with invalid token errors", "2026-06-14-payment-charge-failure.md"),
    ("checkout hangs and times out, payment unreachable", "2026-04-02-payment-unreachable.md"),
    ("payment slow after a new fraud scoring deploy blocking the request", "2026-05-27-payment-slow-not-down.md"),
    ("cart failing randomly with no exception detail in the logs", "2026-05-20-cart-failure.md"),
    ("cart backend connection pool exhausted, stack trace in the client", "2026-03-11-cart-valkey-connection-errors.md"),
    ("kafka consumer lag growing during a load test", "2026-07-01-kafka-queue-lag-spike.md"),
    ("kafka broker crashed from an out of memory kill", "2026-02-18-kafka-broker-outage.md"),
    ("ad service pegged at 100% cpu, latency up but no errors", "2026-05-05-ad-high-cpu.md"),
    ("email service memory usage climbing steadily over time", "2026-04-18-email-memory-leak.md"),
    ("product catalog queries slow from database lock contention", "2026-03-03-product-catalog-lock-contention.md"),
]


def run_eval() -> None:
    hits = 0
    for query, expected in QUERIES:
        results = search_past_incidents(query, top_k=3)
        top3_files = [r["source_file"] for r in results]
        hit = expected in top3_files
        hits += hit
        status = "PASS" if hit else "FAIL"
        print(f"[{status}] {query!r}")
        print(f"       expected: {expected}")
        print(f"       top-3:    {top3_files}")

    print(f"\n{hits}/{len(QUERIES)} queries hit the expected postmortem in the top 3")


if __name__ == "__main__":
    run_eval()

"""Per-node wall clock and cost.

`p50 / p90 / max`, not `p99`: 28 queries cannot support a p99 — the 99th
percentile of 28 samples IS the maximum, and printing it as a percentile would
dress the single slowest observation up as a distribution statistic. `max` is
reported under its own name instead.

There is no `grade` timing because there is no `grade` node. CLAUDE.md's contract
is `route -> retrieve -> grade -> (retrieve | resolve) -> answer`; the shipped
graph is `route -> retrieve -> resolve -> answer` (logs 009 ruling 3, 010).
`tries` is dead state. Reporting a 0.0 for a node that was never built would
imply it ran instantly.

A node that did not run on a given case contributes NOTHING to that node's
percentiles — `None`, not `0.0`. The two `game: null` cases without `route: auto`
never call `route` at all (as `eval/run.py` never calls it for them), and forced-
game cases take `route`'s free early-return branch, which is timed separately
from the branch that makes a model call.
"""

from __future__ import annotations

from benchmark.record import Measurement

NODES = ("route", "retrieve", "resolve", "answer")


def _percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile. No interpolation: with n<=28 an interpolated p90
    invents a value that was never observed."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(q * len(ordered) + 0.5)) - 1))
    return ordered[idx]


def node_latency(records) -> tuple[list[Measurement], dict]:
    measurements: list[Measurement] = []
    detail: dict = {}
    for node in NODES:
        samples = [r.timings.get(node) for r in records if not r.error]
        samples = [s for s in samples if s is not None]
        detail[node] = {
            "n": len(samples),
            "p50": _percentile(samples, 0.50),
            "p90": _percentile(samples, 0.90),
            "max": max(samples) if samples else None,
            "mean": (sum(samples) / len(samples)) if samples else None,
        }
        if not samples:
            measurements.append(Measurement(
                name=f"latency_{node}_p50", value=None, per_run=[], n=0,
                unit="seconds",
                basis=(f"node `{node}` did not run in this tier, so it has no "
                       "samples. Not reported as 0.0 — a node that never ran is "
                       "not a fast node."),
            ))
            continue
        for label, val in (("p50", detail[node]["p50"]),
                           ("p90", detail[node]["p90"]),
                           ("max", detail[node]["max"])):
            measurements.append(Measurement(
                name=f"latency_{node}_{label}", value=val, per_run=[val], n=1,
                unit="seconds",
                basis=(f"{label} of wall-clock time in `{node}` over {len(samples)} "
                       "queries that executed it, nearest-rank (no interpolation). "
                       "One timed pass per query: the percentile is across QUERIES, "
                       "not across repeats of one query, so it carries no "
                       "run-to-run variance estimate."
                       + (" POOLED ACROSS TWO BRANCHES whose costs differ by ~3 "
                          "orders of magnitude (forced early-return vs a real "
                          "router call) — read latency_route_forced_* and "
                          "latency_route_router_* instead."
                          if node == "route" else "")),
            ))
    # `route` has two branches with wall clocks three orders of magnitude apart,
    # and pooling them makes p50 describe one branch and max describe the other.
    # They are reported separately as well as together.
    for branch, label in (("forced", "route_forced"), ("router", "route_router")):
        samples = [r.timings.get("route") for r in records
                   if not r.error and r.route_branch == branch
                   and r.timings.get("route") is not None]
        detail[label] = {"n": len(samples),
                         "p50": _percentile(samples, 0.50) if samples else None,
                         "max": max(samples) if samples else None}
        if not samples:
            continue
        explain = ("the free early-return branch (graph.py:1516-1521): the caller "
                   "forced a slug, so `route` validates it and returns. No model "
                   "call, so this number is pure Python."
                   if branch == "forced" else
                   "the branch that makes a structured-output model call. This is "
                   "the ONLY chat spend on the free tier.")
        for stat, val in (("p50", _percentile(samples, 0.50)), ("max", max(samples))):
            measurements.append(Measurement(
                name=f"latency_{label}_{stat}", value=val, per_run=[val], n=1,
                unit="seconds",
                basis=(f"{stat} over the {len(samples)} queries taking {explain}"),
            ))

    # Full-trace latency: sum of the nodes that ran, per query.
    totals = [sum(v for v in r.timings.values() if v is not None)
              for r in records if not r.error]
    for label, q in (("p50", 0.50), ("p90", 0.90)):
        measurements.append(Measurement(
            name=f"latency_total_{label}", value=_percentile(totals, q),
            per_run=[_percentile(totals, q)], n=1, unit="seconds",
            basis=(f"{label} of the summed per-node time over {len(totals)} queries. "
                   "Excludes process startup, corpus load and the one-off Chroma "
                   "handle construction, which are amortised across the run and "
                   "are not per-query costs."),
        ))
    measurements.append(Measurement(
        name="latency_total_max", value=max(totals) if totals else None,
        per_run=[max(totals)] if totals else [], n=1 if totals else 0,
        unit="seconds",
        basis=f"slowest single query of {len(totals)}, summed across nodes.",
    ))
    detail["total"] = {"n": len(totals), "samples": totals}
    return measurements, detail


def cost(records, tier: str) -> tuple[list[Measurement], dict]:
    per_query = [r.cost_usd for r in records if not r.error]
    total = sum(per_query)
    detail = {
        "tier": tier,
        "total_usd": total,
        "per_query_usd": {r.case_id: r.cost_usd for r in records},
        "chat_tokens_in": sum(u.get("input", 0) for r in records for u in r.usage),
        "chat_tokens_out": sum(u.get("output", 0) for r in records for u in r.usage),
        "model_calls": sum(len(r.usage) for r in records),
    }
    return [
        Measurement(
            name="cost_per_query_mean", value=None, per_run=per_query,
            n=len(per_query), unit="usd",
            basis=(f"metered chat usage (model's own usage metadata x published "
                   f"price) plus a tiktoken-exact query-embedding charge, over "
                   f"{len(per_query)} queries on the {tier} tier. On this tier the "
                   "only chat spend is the router; every other case pays for one "
                   "query embedding and nothing else."),
        ),
        Measurement(
            name="cost_run_total", value=total, per_run=[total], n=1, unit="usd",
            basis=(f"sum of per-query cost across the {tier} tier, one pass. Does "
                   "NOT include the separate eval/run.py invocations made by "
                   "--gate-stability, which are reported under their own name."),
        ),
    ], detail

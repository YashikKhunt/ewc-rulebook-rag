"""Instrumented node driver.

`eval/run.py` already drives `graph`'s nodes directly rather than invoking the
compiled app (`eval/run.py:179-196`), and throws `ranks` away at line 195. This
module uses the same technique and keeps everything: per-node wall clock, the
fused relevance `ranks`, usage, and cost. That is why the benchmark needs **zero
changes to `graph.py`**.

Read-only contract: this module imports `graph` and calls its functions. It never
monkeypatches, never sets a seed, never mutates `FUSED_K` or `ACCOUNTABLE_RANK`.

The driver assumes the shipped graph is the linear chain
`route -> retrieve -> resolve -> answer`. That assumption is ASSERTED against
`graph.build_graph()` at startup, so the day a conditional edge is added (the
`grade` node CLAUDE.md specifies and the tree does not have) this fails loudly
instead of quietly measuring a pipeline that no longer exists.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import graph  # noqa: E402  -- imported directly; `eval/` has no __init__.py

from benchmark.record import QueryRecord  # noqa: E402

# The shape this driver is written against.
EXPECTED_NODES = {"__start__", "route", "retrieve", "resolve", "answer", "__end__"}
EXPECTED_EDGES = {
    ("__start__", "route"),
    ("route", "retrieve"),
    ("retrieve", "resolve"),
    ("resolve", "answer"),
    ("answer", "__end__"),
}

EMBEDDING_PRICE_PER_1M = {          # mirrors index.py:52-56
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}


class GraphShapeChanged(RuntimeError):
    """`graph.build_graph()` is no longer the chain this driver assumes."""


def assert_linear_graph() -> dict:
    """Fail loudly if the compiled graph is not the linear four-node chain.

    Returns the observed shape so `summary.json` can record it. Called once at
    the top of every run: a driver that silently measured `route -> retrieve ->
    resolve -> answer` while the app had grown a `grade` node with a conditional
    back-edge to `retrieve` would report latency and pool composition for a
    pipeline nobody ships."""
    compiled = graph.build_graph().get_graph()
    nodes = set(compiled.nodes)
    edges = {(e.source, e.target) for e in compiled.edges}
    conditional = sorted((e.source, e.target) for e in compiled.edges if e.conditional)

    problems = []
    if nodes != EXPECTED_NODES:
        problems.append(f"nodes {sorted(nodes)} != expected {sorted(EXPECTED_NODES)}")
    if edges != EXPECTED_EDGES:
        problems.append(f"edges {sorted(edges)} != expected {sorted(EXPECTED_EDGES)}")
    if conditional:
        problems.append(
            f"conditional edge(s) present: {conditional}. This driver runs the "
            "nodes in a fixed order; a branch means it is no longer measuring "
            "the pipeline that ships."
        )
    if problems:
        raise GraphShapeChanged(
            "benchmark/pipeline.py is written against the linear chain "
            "route -> retrieve -> resolve -> answer. " + "; ".join(problems)
        )
    return {"nodes": sorted(nodes), "edges": sorted(edges), "conditional_edges": []}


def assert_ranks_are_not_docs_order(record: QueryRecord) -> dict:
    """Prove `ranks` is relevance order and `docs` is authority order.

    `hybrid()` fuses to 8 by relevance, records the rank of each, THEN sorts by
    authority descending (`graph.py:243-246`). On any pool that mixes authority
    levels the two orders must differ. B5 was caused by conflating them, so the
    benchmark refuses to take it on trust: this is run against a real
    mixed-authority case and its result is stamped into `summary.json`.

    Returns a dict rather than raising, because "this pool happened to be
    single-authority" is a legitimate outcome that proves nothing either way and
    must be reported as such, not as a pass."""
    docs_order = {cid: i for i, cid in enumerate(record.chunk_ids, start=1)}
    authorities = {d["authority"] for d in record.docs}
    differs = docs_order != record.ranks
    return {
        "case_id": record.case_id,
        "authority_levels_in_pool": sorted(authorities),
        "mixed_authority": len(authorities) > 1,
        "docs_order": docs_order,
        "relevance_ranks": dict(record.ranks),
        "orders_differ": differs,
        "conclusive": len(authorities) > 1 and differs,
    }


def chat_cost(usage: list[dict], model: str) -> float:
    rate_in, rate_out = graph.CHAT_PRICE_PER_1M.get(model, (0.0, 0.0))
    tin = sum(u.get("input", 0) for u in usage)
    tout = sum(u.get("output", 0) for u in usage)
    return (tin * rate_in + tout * rate_out) / 1e6


def embedding_cost(question: str, model: str) -> float:
    """Exact token count of the one query embedding, priced. Tiny but real, and
    the only cost a retrieval-only run incurs on a forced-game case."""
    try:
        import tiktoken
        try:
            encoder = tiktoken.encoding_for_model(model)
        except KeyError:
            encoder = tiktoken.get_encoding("cl100k_base")
        tokens = len(encoder.encode(question))
    except Exception:                                   # pragma: no cover
        tokens = max(1, len(question) // 4)
    return tokens * EMBEDDING_PRICE_PER_1M.get(model, 0.0) / 1e6


def _doc_row(doc) -> dict:
    meta = doc.metadata
    return {
        "chunk_id": meta["chunk_id"],
        "game": meta["game"],
        "game_title": meta["game_title"],
        "scope": meta.get("scope", ""),
        "authority": int(meta.get("authority", 0)),
        "article": (meta.get("article") or "").strip(),
        "article_id": str(meta.get("article_id") or ""),
        "heading": meta.get("heading") or "",
        "page": meta.get("page"),
        "page_end": meta.get("page_end"),
        "chunk": meta.get("chunk"),
        "chunk_of": meta.get("chunk_of"),
        "n_chars": meta.get("n_chars"),
    }


def run_case(case: dict, generate: bool = False) -> QueryRecord:
    """Drive one case through the nodes, timing each.

    Router policy mirrors `eval/run.py:186-192` exactly, because a benchmark that
    routes differently from the gate is measuring a different system:

    * ``game`` forced  -> `route` is called with the game already set, which is
      the free early-return branch (`graph.py:1516-1521`). No model call.
    * ``game: null`` + ``route: auto`` -> `route` is called for real. One model
      call; this is the only spend on the free tier.
    * ``game: null`` without ``route: auto`` -> `route` is SKIPPED, as the gate
      skips it, and the route timing is recorded as None rather than as 0.0.
      Recording 0.0 would put a node that never ran into the latency percentiles.
    """
    record = QueryRecord(case_id=case["id"], bucket=case["bucket"],
                         question=case["question"])
    chat_model = graph._env("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    embed_model = graph._env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    usage: list[dict] = []
    timings: dict[str, float | None] = {"route": None, "retrieve": None,
                                        "resolve": None, "answer": None}

    game = case.get("game")
    try:
        # --- route -------------------------------------------------------
        if game is not None:
            t0 = time.perf_counter()
            routed_state = graph.route({"question": case["question"], "game": game})
            timings["route"] = time.perf_counter() - t0
            record.routed = "(forced)"
            record.route_branch = "forced"
            game = routed_state["game"]
        elif case.get("route") == "auto":
            t0 = time.perf_counter()
            routed_state = graph.route({"question": case["question"]})
            timings["route"] = time.perf_counter() - t0
            record.routed = routed_state["game"]
            record.route_branch = "router"
            game = routed_state["game"]
            usage.extend(routed_state.get("usage") or [])
        else:
            record.routed = "(not called)"
            record.route_branch = "not_called"

        record.game = game

        # --- retrieve ----------------------------------------------------
        t0 = time.perf_counter()
        part = graph.retrieve({"question": case["question"],
                               "query": case["question"], "game": game})
        timings["retrieve"] = time.perf_counter() - t0
        record.docs = [_doc_row(d) for d in part["docs"]]
        record.ranks = dict(part["ranks"])
        record.scope = part["scope"]

        # --- resolve -----------------------------------------------------
        t0 = time.perf_counter()
        resolved = graph.resolve({"docs": part["docs"], "ranks": part["ranks"]})
        timings["resolve"] = time.perf_counter() - t0
        record.conflicts = resolved.get("conflicts") or []
        record.note = resolved.get("note") or ""
        record.accountable = list(resolved.get("accountable") or [])
        record.top_findings = list(resolved.get("top_findings") or [])

        # --- answer (generation tier; never called on the free tier) ------
        if generate:
            t0 = time.perf_counter()
            out = graph.answer({
                "question": case["question"], "query": case["question"],
                "docs": part["docs"], "scope": part["scope"],
                "note": record.note, "accountable": record.accountable,
                "top_findings": record.top_findings, "usage": [],
            })
            timings["answer"] = time.perf_counter() - t0
            record.answer = out.get("answer", "")
            record.outcome = out.get("outcome", "")
            usage.extend(out.get("usage") or [])
            record.citation_spans = graph.citation_spans(record.answer, part["docs"])
    except Exception as exc:                             # noqa: BLE001
        record.error = f"{type(exc).__name__}: {exc}"

    record.usage = usage
    record.timings = timings
    record.cost_usd = (chat_cost(usage, chat_model)
                       + embedding_cost(case["question"], embed_model))
    return record

"""Retrieval metrics.

**Stage 1 computes ONLY**: MRR, judged-recall@4, judged-recall@8, the rank
histogram, and the leakage tripwire. Precision@k, NDCG, MAP and bpref are
deliberately NOT computed here — see `benchmark/qrels.py` for why, and
`benchmark/README.md` for the pre-registration. They unlock at Stage 2.

Every rank-based figure reads ``record.ranks[chunk_id]``. ``record.docs`` is
ordered by authority (``graph.py:245``); its index is a precedence position, not
a retrieval rank, and reporting one as the other is the bug (B5) this file exists
to avoid repeating.

Leakage lives here as a three-line tripwire rather than in its own module,
because retrieval leakage is structurally impossible: ``scope_filter``
(``graph.py:127-152``) enforces scoping at the store, and log 005 proved it
exhaustively — 24 title slugs x 2382 docs, 0 leaks. **A 0.00 here is a tripwire
reading, not a headline.** The leakage that actually exists in this system is
PROSE misattribution (log 009 B-2) and is measured in ``metrics/citation.py``.
"""

from __future__ import annotations

from collections import Counter

from benchmark.record import Measurement

BASIS_TRIPWIRE = (
    "tripwire, not a headline: scope_filter enforces scoping at the store "
    "(graph.py:127-152), so a non-zero reading means the filter itself broke. "
    "0.00 here says nothing about log 009's B-2, which is prose misattribution "
    "over a CLEAN pool and is measured in metrics/citation.py."
)


# ---------------------------------------------------------------------------
# Baseline A -- no labels required
# ---------------------------------------------------------------------------

def leakage(records, cases_by_id) -> tuple[Measurement, list[dict]]:
    """Foreign-game chunks in a scoped pool.

    Two populations, both counted: the five cases carrying an explicit
    ``must_exclude_games`` guard, and — more strictly — EVERY scoped case, where
    a chunk whose game is neither the searched slug nor ``global`` is a leak by
    construction.
    """
    detail = []
    leaks = 0
    scoped = 0
    for record in records:
        if record.error or record.game is None:
            continue
        scoped += 1
        allowed = {record.game, "global"}
        foreign = [d for d in record.docs if d["game"] not in allowed]
        declared = set((cases_by_id[record.case_id].get("retrieval") or {})
                       .get("must_exclude_games") or [])
        declared_hits = [d for d in record.docs if d["game"] in declared]
        if foreign or declared_hits:
            leaks += 1
        detail.append({
            "case_id": record.case_id, "searched_game": record.game,
            "foreign_chunks": [f"{d['game']}:{d['article'] or '-'}" for d in foreign],
            "declared_exclusions": sorted(declared),
            "declared_exclusion_hits":
                [f"{d['game']}:{d['article'] or '-'}" for d in declared_hits],
        })
    value = 0.0 if scoped == 0 else leaks / scoped
    return Measurement(
        name="retrieval_leakage_rate", value=value, per_run=[value], n=1,
        unit="ratio",
        basis=(f"scoped cases whose pool contains a chunk from a game other than "
               f"the searched slug or `global`, over {scoped} scoped cases "
               f"(n=1: retrieval is deterministic given a fixed index). "
               + BASIS_TRIPWIRE),
    ), detail


def scope_purity(records, cases_by_id) -> tuple[Measurement, list[dict]]:
    """Pools whose `scope` values all fall inside what the case permits.

    A scoped case may see {title, global, amendment}; a general case may see
    {global, amendment} (``scope_filter``'s two branches). Where the case declares
    ``only_scopes``, that narrower set is used instead.
    """
    detail, pure, total = [], 0, 0
    for record in records:
        if record.error:
            continue
        total += 1
        spec = (cases_by_id[record.case_id].get("retrieval") or {})
        if "only_scopes" in spec:
            allowed = set(spec["only_scopes"])
        elif record.game:
            allowed = {"title", "global", "amendment"}
        else:
            allowed = {"global", "amendment"}
        seen = {d["scope"] for d in record.docs}
        stray = sorted(seen - allowed)
        if not stray:
            pure += 1
        detail.append({"case_id": record.case_id, "scopes_seen": sorted(seen),
                       "allowed": sorted(allowed), "stray": stray})
    value = 0.0 if total == 0 else pure / total
    return Measurement(
        name="scope_purity", value=value, per_run=[value], n=1, unit="ratio",
        basis=(f"{pure}/{total} pools contained only permitted scopes. Permitted = "
               "the case's `only_scopes` where declared, else scope_filter's own "
               "branch ({title,global,amendment} scoped / {global,amendment} "
               "general). n=1: deterministic given a fixed index."),
    ), detail


def router_accuracy(records, cases_by_id) -> tuple[Measurement, list[dict]]:
    """Router output vs `route_expect`, over the cases that declare one.

    Only ``route: auto`` cases actually call the router. Measured here: 2 cases
    (the plan's "5 route: auto cases" is wrong against the shipped query set).
    """
    detail, hits, per_run = [], 0, []
    for record in records:
        spec = (cases_by_id[record.case_id].get("retrieval") or {})
        if "route_expect" not in spec:
            continue
        want = spec["route_expect"]
        want_val = None if want in (None, "none") else want
        ok = record.routed == want_val
        hits += ok
        per_run.append(1.0 if ok else 0.0)
        detail.append({"case_id": record.case_id, "expected": want,
                       "routed": record.routed, "ok": ok})
    total = len(per_run)
    value = None if total == 0 else hits / total
    return Measurement(
        name="router_accuracy", value=value, per_run=per_run, n=total,
        unit="ratio",
        basis=(f"{hits}/{total} router calls returned the expected slug, over the "
               "cases declaring `route_expect`. Each observation is one CASE, not "
               "one repeat — see router_stability for repeat-run variance."),
    ), detail


def router_stability(repeats: dict[str, list], cases_by_id) -> tuple[Measurement, list[dict]]:
    """Per-case agreement across N repeats of the router.

    The router is the only nondeterministic component on the free tier, so it is
    the only thing worth repeating. 1.0 means every repeat of every case returned
    the same slug as the first.
    """
    detail, per_run = [], []
    for case_id, outputs in sorted(repeats.items()):
        agree = sum(1 for o in outputs if o == outputs[0]) / len(outputs)
        per_run.append(agree)
        detail.append({"case_id": case_id, "outputs": outputs,
                       "expected": (cases_by_id[case_id].get("retrieval") or {})
                                   .get("route_expect"),
                       "agreement": agree})
    return Measurement(
        name="router_self_agreement", value=None, per_run=per_run,
        n=len(per_run), unit="ratio",
        basis=(f"per-case fraction of repeat router calls returning the same slug "
               f"as the first, over {len(per_run)} `route: auto` cases. One "
               "observation per case; the mean is across cases, not across runs."),
    ), detail


# ---------------------------------------------------------------------------
# Baseline B -- uses the 30 must_include labels
# ---------------------------------------------------------------------------

def _per_case_rank_hits(record, rows) -> list[dict]:
    """For each label on this case: the relevance ranks of its chunks that were
    actually retrieved, and the best (lowest) of them."""
    out = []
    for row in rows:
        found = [(cid, record.ranks[cid]) for cid in row["chunk_ids"]
                 if cid in record.ranks]
        found.sort(key=lambda pair: pair[1])
        out.append({
            "key": row["key"], "status": row["status"],
            "n_labelled_chunks": row["n_chunks"],
            "retrieved": [{"chunk_id": c, "rank": r} for c, r in found],
            "best_rank": found[0][1] if found else None,
            "article_found": bool(found),
        })
    return out


def judged_recall(records, labels, cutoffs, accountable_rank):
    """Article-level and chunk-level judged recall at each cutoff, plus MRR and
    the rank histogram. Returns (measurements, detail)."""
    per_case_detail = []
    art_hits = {k: [] for k in cutoffs}
    chunk_num = {k: 0 for k in cutoffs}
    chunk_den = {k: 0 for k in cutoffs}
    rr: list[float] = []
    chunk_macro = {k: [] for k in cutoffs}
    histogram: Counter = Counter()
    governing_ranks: list[int] = []

    for record in records:
        rows = labels.get(record.case_id)
        if record.error or not rows:
            continue
        hits = _per_case_rank_hits(record, rows)
        per_case_detail.append({"case_id": record.case_id, "labels": hits})

        best = [h["best_rank"] for h in hits if h["best_rank"] is not None]
        rr.append(1.0 / min(best) if best else 0.0)

        for h in hits:
            for entry in h["retrieved"]:
                histogram[entry["rank"]] += 1
            if h["best_rank"] is not None:
                governing_ranks.append(h["best_rank"])

        # Macro (per-case) chunk recall over the UNION of this case's labelled
        # chunk_ids, deduplicated — the same population pytrec_eval scores, so
        # the two are comparable like-for-like.
        labelled_union = {cid for row in rows for cid in row["chunk_ids"]}
        for k in cutoffs:
            found = {cid for cid in labelled_union
                     if record.ranks.get(cid, 99) <= k}
            chunk_macro[k].append(len(found) / len(labelled_union)
                                  if labelled_union else 0.0)

        for k in cutoffs:
            for h in hits:
                art_hits[k].append(
                    1.0 if (h["best_rank"] is not None and h["best_rank"] <= k) else 0.0)
                chunk_den[k] += h["n_labelled_chunks"]
                chunk_num[k] += sum(1 for e in h["retrieved"] if e["rank"] <= k)

    measurements = [
        Measurement(
            name="mrr", value=None, per_run=rr, n=len(rr), unit="ratio",
            basis=("mean of 1/rank of the FIRST judged-relevant chunk, using the "
                   "fused relevance rank `ranks[chunk_id]` (never docs order, "
                   "which is authority order). One observation per case that "
                   f"carries at least one must_include label ({len(rr)} of 28). "
                   "Labels are positive-only and partial; a case scoring 0.0 means "
                   "no LABELLED chunk was retrieved, not that nothing relevant was."),
        )
    ]
    for k in cutoffs:
        vals = art_hits[k]
        measurements.append(Measurement(
            name=f"judged_recall_article@{k}", value=None, per_run=vals,
            n=len(vals), unit="ratio",
            basis=(f"fraction of the {len(vals)} must_include labels for which AT "
                   f"LEAST ONE chunk of the labelled article appears at relevance "
                   f"rank <= {k}. This is exactly eval/run.py's own must_include "
                   "semantics (eval/run.py:207-224). At k=8 that makes it "
                   "ENTAILED BY A GREEN GATE and therefore carries no independent "
                   "information: every must_include entry is a must_pass "
                   "assertion, so a passing gate forces 1.0. It is reported for "
                   "the k=4 figure and as a consistency check on the wiring, not "
                   "as evidence about retrieval quality. Positive-only, partial "
                   "labels: this does not measure recall of everything relevant, "
                   "only of what the gate already pins."),
        ))
        num, den = chunk_num[k], chunk_den[k]
        val = 0.0 if den == 0 else num / den
        measurements.append(Measurement(
            name=f"judged_recall_chunk@{k}", value=val, per_run=[val], n=1,
            unit="ratio",
            basis=(f"{num}/{den} labelled CHUNKS retrieved at relevance rank <= {k}. "
                   "One label can span many chunks (up to 12 in this corpus; 192 "
                   "articles span more than one), so this figure has a CEILING "
                   "BELOW 1.0 wherever a labelled article has more chunks than the "
                   f"pool has slots (FUSED_K=8). n=1: a single deterministic pass, "
                   "no variance estimate. MICRO-averaged: chunks pooled across "
                   "all labels, so a label spanning 9 chunks weighs 9x a label "
                   "spanning 1. See judged_recall_chunk_macro@k for the "
                   "per-case average, which is what pytrec_eval reports."),
        ))
        macro = chunk_macro[k]
        measurements.append(Measurement(
            name=f"judged_recall_chunk_macro@{k}", value=None, per_run=macro,
            n=len(macro), unit="ratio",
            basis=(f"per-CASE chunk-level recall at rank <= {k}, averaged over the "
                   f"{len(macro)} cases carrying labels. Denominator is the union "
                   "of that case's labelled chunk_ids, deduplicated. This is "
                   "exactly the population and the aggregation pytrec_eval's "
                   f"`recall_{k}` uses, and the cross-check compares against it."),
        ))

    total_hits = sum(histogram.values())
    at_or_above = sum(v for r, v in histogram.items() if r <= accountable_rank)
    measurements.append(Measurement(
        name="judged_hits_within_accountable_rank", value=None,
        per_run=[1.0 if r <= accountable_rank else 0.0 for r in governing_ranks],
        n=len(governing_ranks), unit="ratio",
        basis=(f"fraction of the {len(governing_ranks)} labels whose BEST retrieved "
               f"chunk sits at relevance rank <= ACCOUNTABLE_RANK ({accountable_rank}, "
               "graph.py:857). Below that line `resolve` will not consider the "
               "excerpt at all (graph.py:1068-1078), so a label found at rank 5-8 "
               "is retrieved but invisible to precedence resolution."),
    ))

    detail = {
        "per_case": per_case_detail,
        "rank_histogram": {str(r): histogram.get(r, 0) for r in range(1, 9)},
        "rank_histogram_total_labelled_chunk_hits": total_hits,
        "labelled_chunk_hits_at_or_above_accountable_rank": at_or_above,
        "labelled_chunk_hits_below_accountable_rank": total_hits - at_or_above,
        "accountable_rank": accountable_rank,
    }
    return measurements, detail


def pytrec_cross_check(qrels_dict, run_dict, cutoffs) -> dict:
    """Re-derive MRR and chunk-level recall with pytrec_eval and compare.

    The in-house figures above are the ones reported. This runs the same numbers
    through the real trec_eval C implementation so that a disagreement surfaces
    as a diff rather than as silent confidence in hand-rolled arithmetic.
    """
    import pytrec_eval

    measures = {"recip_rank"} | {f"recall.{','.join(str(k) for k in cutoffs)}"}
    evaluator = pytrec_eval.RelevanceEvaluator(qrels_dict, measures)
    scored = evaluator.evaluate(run_dict)
    if not scored:
        return {"available": False}
    def mean(key):
        vals = [row[key] for row in scored.values() if key in row]
        return sum(vals) / len(vals) if vals else None
    return {
        "available": True,
        "implementation": "pytrec_eval-terrier (bindings over trec_eval C)",
        "compares_against": ("mrr <-> recip_rank; judged_recall_chunk_macro@k <-> "
                             "recall_k. NOT judged_recall_chunk@k, which is "
                             "micro-averaged over labels rather than macro-averaged "
                             "over queries."),
        "n_queries": len(scored),
        "recip_rank": mean("recip_rank"),
        **{f"recall_{k}": mean(f"recall_{k}") for k in cutoffs},
        "per_query": scored,
    }

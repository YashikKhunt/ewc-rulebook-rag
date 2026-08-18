"""Citation validity, coverage, and cross-title PROSE misattribution.

This is where the leakage that actually exists gets measured. `scope_filter`
keeps foreign chunks out of the pool (log 005: 0 leaks, exhaustively proven), so
`metrics/retrieval.py`'s leakage figure will read 0.00 and means only that the
store filter still works. Log 009's B-2 is a different failure entirely: the pool
is CLEAN and the PROSE relabels it — asked "What are the CS2 map veto rules?" at
valorant scope, the pipeline answered "The map veto rules for CS2 are as
follows…" citing VALORANT 5.5.1.1, 3/3 runs, `outcome: answered`.

Three things are measured, all mechanically, none by a model:

* **validity**   every cited locator matches a `citation=` line that was in the
                 context window. Reuses `graph.unsupported_citations` /
                 `graph.allowed_citations` — the pipeline's own post-check, so
                 the benchmark and the pipeline can never disagree about what
                 counts as a citation.
* **coverage**   fraction of the answer's paragraphs carrying at least one
                 citation. Non-negotiable #3 says every claim is cited; a
                 paragraph of rule statements with citations only on the last
                 sentence is the shape log 010 observed live (5 of 6 paragraphs
                 marked uncited by the UI's own marker).
* **misattribution** the question names a title that was NOT searched, and the
                 answer states rules under that title's name anyway. Computed
                 from the question, the pool and the prose — never from the
                 model's self-report.

Generation tier only. On the free tier these emit `n=0` measurements whose basis
says the generation tier did not run.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import graph  # noqa: E402

from benchmark.record import Measurement  # noqa: E402


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _aliases() -> dict[str, list[frozenset[str]]]:
    """slug -> alias variants, each a TOKEN SET, derived from the corpus.

    Derived, never hardcoded (CLAUDE.md's don't). `graph.catalog()` reads title
    names out of the indexed chunks themselves, so a re-crawl that renames a book
    is picked up with no code change here.

    Token sets rather than contiguous phrases, because the questions in the query
    set do not use the published word order: "the roster rules in women's MLBB"
    names `mlbb-women`, and a phrase matcher looking for "mlbb women" misses it
    and reports the men's book instead — a false NEGATIVE on exactly the probe
    that exists to catch B-2.
    """
    out: dict[str, list[frozenset[str]]] = {}
    for slug, title in graph.catalog():
        variants = {frozenset(_normalise(title).split()),
                    frozenset(_normalise(slug.replace("-", " ")).split())}
        if ":" in title:                    # "Call of Duty: Black Ops 7"
            head, tail = title.split(":", 1)
            variants.add(frozenset(_normalise(head).split()))
            variants.add(frozenset(_normalise(tail).split()))
        out[slug] = [v for v in variants if v]
    return out


def named_titles(text: str) -> set[str]:
    """Slugs the text names, largest-alias-wins.

    A variant matches when EVERY one of its tokens is present in the text.
    A slug is then dropped if some other slug matched on a strictly larger
    superset of tokens: "women's MLBB" satisfies both `mlbb` ({mlbb}) and
    `mlbb-women` ({mlbb, women}), and only the more specific book is named.
    """
    tokens = set(_normalise(text).split())
    matched: dict[str, frozenset[str]] = {}
    for slug, variants in _aliases().items():
        best = None
        for variant in variants:
            if variant <= tokens and (best is None or len(variant) > len(best)):
                best = variant
        if best is not None:
            matched[slug] = best
    return {
        slug
        for slug, variant in matched.items()
        if not any(other != slug and matched[other] > variant for other in matched)
    }


def misattribution(records, docs_by_case) -> tuple[list[Measurement], dict]:
    """Cases where the question names an unsearched title and the answer uses that
    title's name as the subject of a rule statement anyway."""
    generated = [r for r in records if r.answer and not r.error]
    rows, flags = [], []
    for record in generated:
        searched = {d["game"] for d in record.docs}
        if record.game:
            searched.add(record.game)
        named = named_titles(record.question) - {"global"} - searched
        prose = graph._strip_citations(record.answer)
        mentioned = named_titles(prose) - {"global"} - searched
        offending = sorted(named & mentioned)
        flags.append(1.0 if offending else 0.0)
        rows.append({
            "case_id": record.case_id, "searched": sorted(searched),
            "question_names_unsearched": sorted(named),
            "prose_names_unsearched": sorted(mentioned),
            "misattributed": offending,
        })
    detail = {"n_generated": len(generated), "rows": rows}
    if not generated:
        return [Measurement(
            name="cross_title_misattribution_rate", value=None, per_run=[], n=0,
            unit="ratio",
            basis=("NOT MEASURED: the generation tier did not run. This is the "
                   "measurement for log 009's B-2 and it is the one that must be "
                   "non-zero if the benchmark is honest — see the pre-registration "
                   "in benchmark/README.md."),
        )], detail
    return [Measurement(
        name="cross_title_misattribution_rate", value=None, per_run=flags,
        n=len(flags), unit="ratio",
        basis=(f"fraction of the {len(flags)} generated answers where the QUESTION "
               "names a title absent from the retrieved pool AND the answer's prose "
               "(citations stripped) uses that title's name. Aliases derived from "
               "graph.catalog(), longest-match-wins. This is measured over a CLEAN "
               "pool: it is not store leakage, it is relabelling."),
    )], detail


def validity_and_coverage(records, doc_objects) -> tuple[list[Measurement], dict]:
    """Cited locators supported by evidence, and paragraph-level citation coverage."""
    generated = [r for r in records if r.answer and not r.error]
    valid, coverage, rows = [], [], []
    for record in generated:
        docs = doc_objects.get(record.case_id) or []
        allowed = graph.allowed_citations(docs)
        bad = graph.unsupported_citations(record.answer, allowed)
        valid.append(0.0 if bad else 1.0)
        paragraphs = [p for p in re.split(r"\n\s*\n", record.answer) if p.strip()]
        cited = [p for p in paragraphs if graph.cited_locators(p)]
        cov = (len(cited) / len(paragraphs)) if paragraphs else 0.0
        coverage.append(cov)
        rows.append({"case_id": record.case_id, "unsupported": bad,
                     "paragraphs": len(paragraphs), "cited_paragraphs": len(cited),
                     "coverage": cov})
    detail = {"n_generated": len(generated), "rows": rows}
    if not generated:
        return [Measurement(
            name="citation_validity", value=None, per_run=[], n=0, unit="ratio",
            basis="NOT MEASURED: the generation tier did not run.",
        ), Measurement(
            name="citation_paragraph_coverage", value=None, per_run=[], n=0,
            unit="ratio",
            basis="NOT MEASURED: the generation tier did not run.",
        )], detail
    return [
        Measurement(
            name="citation_validity", value=None, per_run=valid, n=len(valid),
            unit="ratio",
            basis=(f"fraction of the {len(valid)} answers with ZERO unsupported "
                   "locators, via graph.unsupported_citations over that run's own "
                   "docs. Per-ANSWER, not per-citation: one bad locator fails the "
                   "answer. Note the known blind spot (log 009 B-1): a citation at "
                   "the wrong GRANULARITY (9.1 for 9.1.4) passes, because the "
                   "parent locator is itself allowed."),
        ),
        Measurement(
            name="citation_paragraph_coverage", value=None, per_run=coverage,
            n=len(coverage), unit="ratio",
            basis=(f"mean fraction of paragraphs carrying at least one citation, "
                   f"over {len(coverage)} answers. Paragraph granularity, not claim "
                   "granularity — a paragraph can carry one citation and six "
                   "uncited claims and still score 1.0. An upper bound on "
                   "non-negotiable #3 compliance, never a proof of it."),
        ),
    ], detail

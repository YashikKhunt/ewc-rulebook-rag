"""Ground truth, and an honest account of what it is not.

The only labels that exist today are the 30 ``must_include`` entries in
``eval/queries.yaml``. Three properties matter and all three are load-bearing:

1. **They are `(game, article)` pairs, not chunk_ids.** One article can span
   several chunks (``chunk_of`` runs up to 12 in this corpus; 192 articles span
   more than one). Resolving a label therefore yields a SET of chunk_ids, and
   that set can be larger than the whole retrieval pool.
2. **They are positive-only and partial.** Nothing claims they enumerate every
   relevant article. An unlabelled retrieved chunk is *unknown-relevance*, not
   irrelevant — which is why Precision@k, NDCG, MAP and bpref are not computed at
   this stage. They unlock at Stage 2, after pool judging.
3. **They are the gate's own fixtures.** They were written to pin behaviour, not
   sampled to represent a query distribution. Recall over them measures "does the
   pipeline still find the things we already knew it found", which is a weaker
   claim than "does the pipeline find the relevant things".

Two recall figures are produced because they answer different questions:

* **article-level** — a label counts as found when ANY chunk of that article is
  in the pool. This is exactly the gate's semantics (``eval/run.py:207-224``), so
  it is directly comparable with a green/red gate run.
* **chunk-level** — every chunk of a labelled article is a relevant document.
  This is what ``pytrec_eval`` scores. Its ceiling is BELOW 1.0 wherever a
  labelled article has more chunks than the pool has slots, and the basis string
  on the measurement says so.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import graph  # noqa: E402


class UnparseableQrels(RuntimeError):
    """A declared label matches nothing in the corpus. Infrastructure failure."""


def _corpus_rows() -> list[dict]:
    rows = []
    for doc in graph.load_chunks():
        meta = doc.metadata
        rows.append({
            "chunk_id": meta["chunk_id"],
            "game": meta["game"],
            "scope": meta.get("scope", ""),
            "article": (meta.get("article") or "").strip(),
            "page": meta.get("page"),
            "chunk": meta.get("chunk"),
            "chunk_of": meta.get("chunk_of"),
        })
    return rows


_ROWS: list[dict] | None = None


def corpus_rows() -> list[dict]:
    global _ROWS
    if _ROWS is None:
        _ROWS = _corpus_rows()
    return _ROWS


def resolve_label(label: dict) -> list[str]:
    """A ``must_include`` entry -> every chunk_id in the corpus that satisfies it.

    Honours all three forms the gate supports: exact ``article``, ``article_prefix``
    (the article itself or any dotted descendant), and the optional ``scope``
    narrowing that distinguishes an amendment from the article it amends — they
    share a game AND an article number, so without it the two are indistinguishable.
    """
    game = label["game"]
    scope = label.get("scope")
    prefix = label.get("article_prefix")
    exact = label.get("article")
    out = []
    for row in corpus_rows():
        if row["game"] != game:
            continue
        if scope is not None and row["scope"] != scope:
            continue
        article = row["article"]
        if prefix is not None:
            hit = article == prefix or article.startswith(prefix + ".")
        else:
            hit = article == exact
        if hit:
            out.append(row["chunk_id"])
    return sorted(out)


def label_key(label: dict) -> str:
    bits = [label["game"]]
    if "article_prefix" in label:
        bits.append(label["article_prefix"] + ".*")
    else:
        bits.append(str(label.get("article")))
    if label.get("scope"):
        bits.append(f"[{label['scope']}]")
    return ":".join(bits)


def build_labels(cases: list[dict]) -> dict[str, list[dict]]:
    """case_id -> [{key, label, chunk_ids, status}] for every must_include entry.

    Raises ``UnparseableQrels`` if any label resolves to nothing: a label that
    matches no chunk cannot be recalled, and silently scoring it as a miss would
    understate retrieval by blaming it for a fixture defect.
    """
    out: dict[str, list[dict]] = {}
    empty: list[str] = []
    for case in cases:
        entries = (case.get("retrieval") or {}).get("must_include") or []
        rows = []
        for label in entries:
            chunk_ids = resolve_label(label)
            if not chunk_ids:
                empty.append(f"{case['id']} -> {label_key(label)}")
            rows.append({
                "key": label_key(label),
                "label": dict(label),
                "chunk_ids": chunk_ids,
                "n_chunks": len(chunk_ids),
                "status": label.get("status", "must_pass"),
            })
        if rows:
            out[case["id"]] = rows
    if empty:
        raise UnparseableQrels(
            "must_include labels that match no chunk in the corpus: " + "; ".join(empty)
        )
    return out


def trec_qrels(labels: dict[str, list[dict]]) -> dict[str, dict[str, int]]:
    """TREC qrel dict: {case_id: {chunk_id: 1}}.

    Binary at Stage 1. The graded 0/1/2 scale (irrelevant / relevant /
    **governing**) needs human judgements and arrives with ``qrels/pool_v1.jsonl``
    at Stage 2; grade 2 is what makes NDCG meaningful here, because it rewards
    ranking the DECIDING rule first rather than merely a related one.
    """
    qrels: dict[str, dict[str, int]] = {}
    for case_id, rows in labels.items():
        bucket = qrels.setdefault(case_id, {})
        for row in rows:
            for chunk_id in row["chunk_ids"]:
                bucket[chunk_id] = 1
    return qrels


def trec_run(records, fused_k: int) -> dict[str, dict[str, float]]:
    """TREC run dict from the fused RELEVANCE ranks.

    ``record.ranks`` — never ``enumerate(record.docs)``. ``docs`` is sorted by
    authority descending (``graph.py:245``); using its position as a rank would
    report precedence order as retrieval quality, which is precisely the
    conflation that caused B5. Score is ``fused_k - rank + 1`` so rank 1 scores
    highest and ties cannot occur (ranks are a bijection onto 1..k).
    """
    run: dict[str, dict[str, float]] = {}
    for record in records:
        if record.error:
            continue
        run[record.case_id] = {
            chunk_id: float(fused_k - rank + 1)
            for chunk_id, rank in record.ranks.items()
        }
    return run


def summarise(labels: dict[str, list[dict]]) -> dict:
    counts = [row["n_chunks"] for rows in labels.values() for row in rows]
    return {
        "cases_with_labels": len(labels),
        "labels": len(counts),
        "labelled_chunk_ids": sum(counts),
        "distinct_labelled_chunk_ids": len(
            {cid for rows in labels.values() for row in rows for cid in row["chunk_ids"]}
        ),
        "max_chunks_per_label": max(counts) if counts else 0,
        "labels_spanning_multiple_chunks": sum(1 for c in counts if c > 1),
        "labels_exceeding_pool_size": sum(1 for c in counts if c > graph.FUSED_K),
    }

# `qrels/` — human relevance judgements

Empty until **Stage 2**. The judgements that will live here are the most expensive
artefact in the project, so they are committed to git rather than left under the
gitignored `data/`.

Planned: `pool_v1.jsonl`, TREC-style pool judging over the 28 queries × 8 retrieved
chunks (~180 unique pairs after dedup by `chunk_id`), graded
`0` irrelevant · `1` relevant · `2` **governing** (the article that actually decides the
question). Grade 2 is what makes NDCG meaningful here: it rewards ranking the *deciding*
rule first, not merely a related one.

Labels are **append-only**. Corrections go to `pool_v2.jsonl` with a reason;
`benchmark/qrels.py` reads the version named in `config.yaml` (`qrels.pool_version`, `null`
today). Relabelling to move a score must be as visible in the diff as a code change.

Until this file has content, `benchmark/qrels.py` builds binary qrels from
`eval/queries.yaml`'s 30 `must_include` entries, which are **positive-only and partial** —
which is why Precision@k, NDCG, MAP and bpref are not computed at Stage 0 or 1.

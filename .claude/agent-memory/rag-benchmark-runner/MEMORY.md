# rag-benchmark-runner — project memory

## Where things are
- Benchmark package: `/benchmark` (Stages 0+1 built). Entry: `python -m benchmark.run`.
- Gate: `eval/run.py` (boolean, 28 cases). **Only** build gate. `benchmark/run.py` exits 0
  unless infrastructure failed — never on a metric value.
- `eval/` has **no `__init__.py`**. Import `graph` directly; load `eval/run.py` with
  `importlib.util.spec_from_file_location` when you need its `Result` objects.
- `corpus_fingerprint()` lives in `server.py:343`, not `graph.py`. `/benchmark` recomputes
  it (first 8 hex of `data/chunks.pkl` sha256) rather than importing `server`.
- Run with `./.venv/bin/python`. No `pip` in the venv; use `VIRTUAL_ENV=$PWD/.venv uv pip`.

## The one rule that matters most
`hybrid()` (`graph.py:230-246`) returns **two orders**. `ranks` is fused RELEVANCE rank;
`docs` is AUTHORITY order (`sorted(-authority)`). Every rank metric must read
`ranks[chunk_id]`. Conflating them caused B5, and the fixture notes in
`eval/queries.yaml` (lines 302, 338-339) still record `docs` positions as "rank" — verified
wrong on two cases. Measured 21/23 mixed-authority pools where the two orders differ.

## Corrections to the plan / spec, verified against the tree
- `route: auto` cases: **2**, not 5 (`xscope-ow2-abstain`, `xscope-forfeit-grace-abstain`).
- `generate: true` cases: **16**, not 17. Forced-game cases: 24. `game: null`: 4.
- `must_include` labels: 30, resolving to 48 chunk_ids / 36 distinct. 7 labels span >1
  chunk; 1 (`global:3.2.*`, 9 chunks) exceeds the pool size, capping chunk recall below 1.
- A `must_include` on `global:3.2.3` with no `scope:` matches BOTH the PDF chunk and the
  amendment chunk — they share game and article number. Matches the gate's semantics.

## Baseline values (run 2026-08-18_152335, corpus 49c0a952, free tier, $0.002061)
- MRR 0.8730 ± 0.2351 (n=21) · judged_recall_article@4 0.9000 · chunk_macro@8 0.9444
- article@8 = 1.0 is **entailed by a green gate** — carries no information.
- Rank histogram of judged hits: r1=16 r2=10 r3=6 r4=0 r5=0 r6=1 r7=5 r8=1. Bimodal with an
  empty gap exactly at `ACCOUNTABLE_RANK = 4`.
- Gate stability (retrieval + pins only): 1.0 over 10 runs, 71 assertions, zero flake. This
  does **not** refute log 009's ~47% — that is a GENERATION assertion.
- Retrieval determinism: identical chunk_id sets and rank maps over 5 repeats. N=1 for
  non-router cases is justified.
- latency: retrieve p50 0.19s, resolve p50 0.001s, router call p50 0.97s.

## Tooling
- `pytrec_eval-terrier==0.5.10` installs cleanly on Python 3.11.15 / darwin-arm64. Pulls
  scipy transitively; does **not** move numpy (2.4.6) or chromadb (1.5.9). Cross-checked
  3/3 to 1e-9 against in-house MRR and macro recall.
- pytrec macro-averages per query; a micro-average over labels gives a different number.
  Always state which aggregation a recall figure uses.

## Traps
- Never report Precision@k / NDCG / MAP / bpref before Stage 2 pool judging. 30 positive-only
  partial labels over 224 slots produces a labelling artefact that reads as a score.
- Retrieval leakage will always read 0.00 (`scope_filter` is store-level). It is a tripwire.
  The real leakage is PROSE misattribution (B-2) and belongs in `metrics/citation.py`.
- Title-alias matching must be TOKEN-SET, not contiguous phrase: "women's MLBB" fails a
  phrase match for `mlbb-women` and falsely reports `mlbb`.
- There is no `grade` node. Do not emit a 0.0 latency for it.

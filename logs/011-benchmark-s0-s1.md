# Iteration 011 — Benchmark Stages 0–1 (`/benchmark`)

- **Date:** 2026-08-18
- **Kind:** build
- **Verdict:** PASS
- **Next action:** Stage 2 — pool judging (blocked on ~2–4 h of human labelling)

New loop shape: the human added `.claude/agents/rag-benchmark-runner.md`, which built this
stage. Verification was performed inline by the orchestrator rather than by `ewc-verifier`
(the human declined the agent spawn); scope is narrower than a full verifier pass and this
entry says so explicitly rather than implying full coverage.

## What was built

`benchmark/` — `record.py`, `pipeline.py`, `qrels.py`, `run.py`, `config.yaml`, `README.md`,
`.gitignore`, `queries/overlay.yaml`, `metrics/{retrieval,latency,abstention,citation}.py`.
Results at `benchmark/results/2026-08-18_152335/`.

Only edit outside `/benchmark`: one pinned line, `pytrec_eval-terrier==0.5.10`, in
`requirements.txt`. Install verified on Python 3.11.15 / darwin-arm64.

`pipeline.py` drives `graph.route/retrieve/resolve/answer` directly, which is why `ranks` and
per-node latency are captured with **zero changes to `graph.py`**. It asserts the compiled
graph is still the linear 4-node chain it assumes (verified: 5 edges, 0 conditional).

## What was verified — independently re-derived

Re-derivation used `graph` directly, not the benchmark's own code:

- **MRR 0.8730 (n=21) — exact match.**
- **The r4 = r5 = 0 gap at `ACCOUNTABLE_RANK = 4` — confirmed.**
- **The three judged labels below the accountability line — identical:**
  `conflict-a16-number-collision` → `cs2 3.2.3` @ **r7**;
  `conflict-vac-six-year` → `global 5.1.12` @ **r7**;
  `normal-cs2-lateness-ladder` → `cs2 2.8.4` @ **r6**.
- **`basis` enforcement is real**: empty, whitespace and `None` all raise `MissingBasis` at
  render. A number cannot be published without saying what it is computed over.
- **Withheld metrics are unreachable, not merely uncalled**: the only measures requested from
  pytrec_eval are `recip_rank` and `recall.{k}`. No NDCG, MAP, bpref or Precision@k.
- **`benchmark/run.py` cannot fail on a metric** — every non-zero return is
  `EXIT_INFRASTRUCTURE`. `eval/run.py` remains the only build gate.
- **Scope clean**: `git status` shows only `M requirements.txt` plus untracked `benchmark/`
  and `.claude/agent-memory/`. `eval/queries.yaml` byte-identical. `chunks.pkl` sha256
  `49c0a952…` and Chroma 2382 vectors unchanged. No re-index.

### Histogram definition differs between the two derivations — both correct

Shipped: `{1:16, 2:10, 3:6, 4:0, 5:0, 6:1, 7:5, 8:1}` = **39** hits, counting *every*
judged-relevant chunk. The independent re-derivation counted the *best chunk per label* and got
**30** (= the 30 `must_include` entries). Neither is wrong; they answer different questions. The
shipped `basis` should name which one it counts, or a reader will assume per-label.

## Baseline A

Leakage **0.0000** (labelled a tripwire, not a headline — `scope_filter` makes retrieval leakage
structurally impossible). Scope purity **1.0000**. Router accuracy **1.0000 (n=2)**.
Latency: retrieve p50/p90/max **0.1905 / 0.2155 / 1.3561 s**; resolve **0.0010 / 0.0021 /
0.0029 s**; router call p50 **0.9743 s**. Cost **$0.000017 ± $0.000062** per query.

**Embedding determinism confirmed**: identical `chunk_id` sets *and* identical rank maps across
5 repeats plus 10 full-set replays. This justifies the N=1 free-tier policy by measurement
rather than assumption.

**Gate stability 1.0000 ± 0.0000 over 10 runs / 71 must_pass assertions, zero flake.** This does
**not** contradict log 009's "~47%" — it **localises** it. The metric's own `basis` states that
generation assertions are excluded and that B-1 is `conflict-vac-six-year`'s *generation*
assertion. The metric is named `gate_stability_whole_run` and is honest about its own scope.

## Baseline B

MRR **0.8730 ± 0.2351 (n=21)**. `judged_recall_article@4` **0.9000**, `@8` **1.0000**.
`judged_recall_chunk_macro@4/@8` **0.8598 / 0.9444**. Micro chunk recall **0.6667 / 0.8125**.

`judged_recall_article@8 = 1.0` is **tautological** — every `must_include` is a must_pass, so a
green gate entails it. Correctly reported as a wiring consistency check. It must never be quoted
as "perfect recall".

## Checks not run

No full `ewc-verifier` pass (human declined the spawn). Specifically **not** independently
verified: the latency percentiles, the cost figures, the pytrec_eval-vs-in-house cross-check
(3/3 to 1e-9, claimed), scipy's effect on the pinned environment beyond the builder's own
report, and the reproducibility of the shipped results dir from a clean run. Generation-tier
metrics (citation validity, prose misattribution, precedence, faithfulness) are **wired but
emit n=0** — nothing generation-side has been measured yet.

## Findings

**Advisory only; nothing blocking.**

- **A-1 — `eval/queries.yaml` fixture notes record authority-order positions as "rank".**
  Confirmed by measurement. Line ~302 says `cs2 3.2.3` is "at rank 2"; measured relevance rank
  is **7**. Lines ~338-339 say `cs2 4.8` at "rank 2" and `global 5.1.12` at "rank 8"; measured
  relevance rank for `global 5.1.12` is **7**. These are `docs` positions (authority order), not
  `ranks` (relevance). This is B5's exact conflation, still live in documentation. No gate
  outcome changes, but anyone tuning `ACCOUNTABLE_RANK` or `FUSED_K` against those notes tunes
  against the wrong number.
- **A-2 — the rank-histogram `basis` does not state whether it counts per-chunk or per-label.**
  Shipped 39 vs re-derived 30 is entirely this. One clause fixes it.
- **A-3 — the plan's counts were wrong**: **2** `route: auto` cases, not 5; **16** generative,
  not 17. The builder caught this; the plan file still carries the wrong figures.
- **A-4 — `scipy` now arrives transitively** via `pytrec_eval-terrier`. numpy stayed at 2.4.6
  and `chromadb==1.5.9` still imports, per the builder — not independently confirmed here.
- **A-5 — the builder deleted an earlier results dir** (`2026-08-18_151922`) produced before it
  fixed three defects in its own measurement code (route latency pooled across branches with
  3-orders-of-magnitude different costs; unit-blind stdev rendering; micro/macro recall compared
  against pytrec's macro). Disclosed, and defensible — those numbers were not reproducible from
  the shipped tree. Recorded so the deletion is on the record rather than invisible.
- **A-6 — title-alias matching had to be token-set, not contiguous-phrase**: `"women's MLBB"`
  phrase-matches `mlbb` and misses `mlbb-women` — a false negative on precisely the probe that
  exists to catch B-2.

## Contract deltas

None new. `requirements.txt` gained a benchmark-only dependency that neither the pipeline nor
`eval/run.py` imports, so a missing wheel cannot break the gate. All prior open deltas stand.

## Carry-forward

- **S5's B-3 reproduced independently and cheaply.** `resolve`'s `global_groups` for
  `conflict-a16-number-collision` is `['5.1.19.3','3.2.7','3.3.3','3.5.3']` — **Global Article
  3.2.3 is absent from resolve's own Global view**, and that is the article CLAUDE.md #1's
  express-primacy exception rests on. Still unrepaired. The benchmark now measures it.
- **The r4/r5 gap means 4 is currently a safe cutoff, not the binding constraint** — but three
  judged-relevant articles do sit below it, so `resolve` reasons over a pool that excludes them.
  Revisit if the gap closes.
- **Stage 2 is blocked on ~2–4 h of human labelling** (~180 unique pairs). Until then
  Precision@k, NDCG, MAP and bpref stay uncomputable and must not be reported.
- Thresholds remain empty in `config.yaml` by design; they are set at Baseline C from measured
  values, as a ratchet.
- Still open: S5's four blocking findings, S6's B-2 stale-store handle, `grade` never built,
  contract #2's superseded path unproven, apex/ALGS and mlbb defaults unratified.

## Spend

Builder **$0.002061**; inline verification ~**$0.0001**. Iteration ≈ **$0.0022**.
Project total ≈ **$0.588 of $5**. No re-embed.

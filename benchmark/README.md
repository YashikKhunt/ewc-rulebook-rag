# `/benchmark` — the measurement layer

`eval/run.py` answers one question: *did every named assertion hold?* It is boolean by
design and it is the only build gate. This package answers a different question: *by how
much, over what, and with what variance?* It never gates anything.

**Read this section before reading any number below it.**

---

## Pre-registration — what these numbers are EXPECTED to look like

Written **before Baseline A was run** (`benchmark/` created 2026-08-18; the expected-bad
list below predates the first `run.py` invocation). It is here so that a healthy-looking
first result is read as evidence the *benchmark* is wrong, not as evidence the system is
well. Four blocking defects are open against this pipeline right now — logs 009 and 010.

| Open defect | What the benchmark should show if it is measuring honestly |
|---|---|
| **B-2 (S5)** cross-title prose misattribution, 3/3 reproducible | A **non-zero** cross-title misattribution rate in `metrics/citation.py` at Stage 3. **Retrieval leakage will read 0.00 and that is not a rebuttal** — `scope_filter` enforces scoping at the store (log 005: 0 leaks, 24 slugs × 2382 docs). The leak that exists is in the prose, not the pool. |
| **B-1 (S5)** the gate passes ~47% of runs at `runs: 3` | Gate stability **below 1.0** where generation is involved. Baseline A measures the *retrieval* assertions only, which are expected to be **stable at 1.0** — that is not a refutation of the 47%, it localises it: the instability is entirely in the generation tier, which Baseline A does not run. Do not report Baseline A's gate stability as "B-1 not reproduced". |
| **B-3 (S5)** `resolve` drops the Global article from its own view for any amended article | On `amendment-global-3-2-3`, `conflicts` should contain an `amended` finding but **no** `conflict`/`agreement`/`restatement` finding keyed on `global 3.2.3`, because `Group.scope` inherits from the amendment member. Blast radius today is one article. |
| **B-4 (S5)** verbatim over-quoting, measured 90w against a recorded "≤34w" | Verbatim-run distribution at Stage 3 with a max well above the 25-word gate threshold. |
| **`grade` never built** | `tries` is dead state; there is no retrieval-sufficiency loop and no per-node latency for it. The plan drops `grade` from the latency surface deliberately. |

Additional expectations recorded in advance:

- **`ACCOUNTABLE_RANK = 4`** (`graph.py:857`) gates what `resolve` will even consider. If
  Baseline B's rank histogram shows judged-relevant articles clustering at ranks 5–8, then
  `resolve` is reasoning over a pool that excludes them. This is the single most diagnostic
  artefact in the whole plan and it costs a tenth of a cent.
- **Precision@k, NDCG, MAP and bpref are NOT reported at Stage 0 or 1.** The only labels
  today are 30 `must_include` entries: positive-only, partial, and nothing claims they are
  complete. An unlabelled retrieved chunk is *unknown-relevance*, not irrelevant. `P@8 =
  0.19` computed from 30 labels across 224 slots is a labelling artefact that would be read
  as a score. These metrics unlock at Stage 2, after pool judging.
- **Thresholds are absent from `config.yaml` on purpose.** Every threshold in the agent
  spec is unbaselined. A guessed threshold the system happens to clear reads as validation.
  They get set at Baseline C, at the measured value, never above it.

---

## Metrics, and the `basis` discipline

Every number this package emits is a `Measurement` (`record.py`) and every `Measurement`
carries a mandatory `basis` string stating what the number is computed over. **A
`Measurement` with an empty `basis` refuses to render and refuses to serialise** — it
cannot reach `summary.json`, `details.json` or the console. That is the structural defence
against the Precision@k trap above: you cannot report a ratio without saying what the
denominator is.

`n > 1` renders as `0.71 ± 0.09 (n=3)`. `n = 1` renders with an explicit
`no variance estimate` marker rather than a bare number.

### Stage 0 (Baseline A) — free, no labels required

| Metric | Module | What it is over |
|---|---|---|
| retrieval leakage (tripwire) | `metrics/retrieval.py` | foreign-game chunks in a title-scoped pool. Structurally impossible via `scope_filter`; reported as a **tripwire, not a headline**. |
| scope purity | `metrics/retrieval.py` | distinct `scope` values in each pool vs what the case allows |
| router accuracy | `metrics/retrieval.py` | the 2 `route: auto` cases with a `route_expect` |
| outcome distribution | `metrics/abstention.py` | `state["outcome"]` × overlay `answerable`. Generation-tier; empty at Stage 0/1. |
| per-node latency p50/p90/max | `metrics/latency.py` | wall-clock `perf_counter` per node, per query. No `grade` node exists. |
| cost per query | `metrics/latency.py` | model usage metadata + published price, plus a tiktoken estimate of the query embedding |
| embedding determinism | `run.py --determinism-probe` | one query run 5×, chunk_id sets diffed |
| gate stability | `run.py --gate-stability` | `eval/run.py --retrieval-only` run N×, per-assertion pass probability |

### Stage 1 (Baseline B) — free, uses the 30 `must_include` labels

| Metric | Module | What it is over |
|---|---|---|
| MRR | `metrics/retrieval.py` | first judged-relevant chunk **by `ranks`**, over cases carrying at least one label |
| judged-recall@4, @8 | `metrics/retrieval.py` | judged-relevant chunk_ids found / judged-relevant chunk_ids that exist in the corpus |
| rank histogram | `metrics/retrieval.py` | `ranks` of every judged-relevant chunk retrieved, bucketed 1–8, with an `ACCOUNTABLE_RANK` split at 4 |

**`ranks` is relevance order. `docs` is authority order.** `hybrid()` (`graph.py:230-246`)
returns both, and conflating them caused a prior bug (B5). Every rank-based metric here
reads `ranks[chunk_id]`. `pipeline.py` asserts on a real mixed-authority case that the two
genuinely differ, so a future refactor that collapses them fails loudly instead of
silently reporting authority position as relevance rank.

### Not built yet

`metrics/precedence.py` (Stage 3), `metrics/faithfulness.py` + `calibration/` (Stage 4),
`compare.py` (Stage 5), `label.py` + `qrels/pool_v1.jsonl` (Stage 2, needs a human).

---

## Running

```bash
python -m benchmark.run                      # Baselines A + B, free tier
python -m benchmark.run --gate-stability 10  # + eval/run.py retrieval assertions x10
python -m benchmark.run --determinism-probe  # + one query x5, chunk_id sets diffed
python -m benchmark.run --out-dir DIR        # override the timestamped results dir
```

Exit codes: **0 unless INFRASTRUCTURE failed.** Infrastructure failure means the corpus
fingerprint does not match `config.yaml`'s pin, more than 20% of queries errored, or the
qrels are unparseable. It **never** exits non-zero on a metric value — two gates means
pressure to weaken the numeric one, and `eval/run.py` is the gate.

Results land in `benchmark/results/YYYY-MM-DD_HHMMSS/` (gitignored). Every `summary.json`
pins the sha256 of `graph.py`, `eval/run.py`, `eval/queries.yaml` and the live
`corpus_fingerprint()`, so an "improvement" produced by editing the gate or the labels
shows up as a hash delta next to the score delta, in the same file.

## Query set

`eval/queries.yaml` is **byte-untouched** — the benchmark verifies its sha256 before and
after every run. `queries/overlay.yaml` is keyed by the same case ids and adds only what
the gate does not encode: `answerable`, `expected_governs`, `governing_article`,
`category`. Two divergent query sets is how you end up benchmarking something the gate
does not test.

## Cost

Free tier is retrieval + offline only: 28 query embeddings plus a router call on each of
the **2** `route: auto` cases (the plan's "5 route: auto cases" is wrong; measured 2).
Measured at ~$0.0002–0.0007 per full free-tier run. Retrieval is deterministic given a
fixed index, so the free tier runs at N=1 for the 26 cases that never call the router and
N=3 for the 2 that do; the determinism claim is verified by `--determinism-probe` rather
than assumed.

---

## Baselines A and B — first measured values

Recorded here because `results/` is gitignored and these are the reference points every
later run is read against. Run `2026-08-18_152335`, free tier, measured spend **$0.002061**.

Integrity for this run: corpus fingerprint `49c0a952` (matches pin) · `graph.py`
`ac55c6b7…` · `eval/run.py` `0e54c210…` · `eval/queries.yaml` `50fb9f03…` (byte-identical
before and after) · Chroma 2382 vectors · `eval/run.py --retrieval-only` exit **0** before
and after.

### Baseline A

| metric | value |
|---|---|
| `retrieval_leakage_rate` | 0.0000 (n=1) — **tripwire** |
| `scope_purity` | 1.0000 (n=1) |
| `router_accuracy` | 1.0000 ± 0.0000 (n=2 cases) |
| `router_self_agreement` | 1.0000 ± 0.0000 (n=2 cases × 3 repeats) |
| `latency_retrieve_p50 / p90 / max` | 0.1905s / 0.2155s / 1.3561s |
| `latency_resolve_p50 / p90 / max` | 0.0010s / 0.0021s / 0.0029s |
| `latency_route_forced_p50` | 0.0004s (free early-return branch) |
| `latency_route_router_p50` | 0.9743s (n=2, the only chat spend on this tier) |
| `latency_total_p50 / p90 / max` | 0.1927s / 0.7352s / 1.3579s |
| `cost_per_query_mean` | $0.000017 ± $0.000062 (n=28) |
| `cost_run_total` | $0.000482 |
| `gate_stability_whole_run` | **1.0000 ± 0.0000 (n=10)** |
| `gate_assertion_pass_rate_mean` | 1.0000 ± 0.0000 (n=71 assertions) |
| `retrieval_determinism_pool` / `_ranks` | 1.0000 (n=5) |

**Gate stability 1.0 does not refute B-1.** These are the retrieval + offline-pin
assertions only, 71 of them, 10× each, zero flake. Log 009's ~47% is
`conflict-vac-six-year`'s *generation* assertion. The measurement localises the
instability to the generation tier; it does not measure it. Stage 3 does.

**Retrieval determinism is confirmed, not assumed**: identical chunk_id sets AND identical
rank maps across 5 repeats, and 10 independent full-set gate replays with zero variation.
The cost model's N=1 policy for non-router cases is therefore justified rather than hoped.

### Baseline B

| metric | value |
|---|---|
| `mrr` | 0.8730 ± 0.2351 (n=21 cases with labels) |
| `judged_recall_article@4` | 0.9000 ± 0.3051 (n=30 labels) |
| `judged_recall_article@8` | 1.0000 — **entailed by a green gate, no independent information** |
| `judged_recall_chunk_macro@4` | 0.8598 ± 0.2736 (n=21) |
| `judged_recall_chunk_macro@8` | 0.9444 ± 0.1774 (n=21) |
| `judged_recall_chunk@4` / `@8` (micro) | 0.6667 / 0.8125 |
| `judged_hits_within_accountable_rank` | 0.9000 ± 0.3051 (n=30 labels) |

Cross-checked against `pytrec_eval-terrier` 0.5.10: `mrr` ↔ `recip_rank` and
`judged_recall_chunk_macro@{4,8}` ↔ `recall_{4,8}` agree to **1e-9, 3/3**.

### The rank histogram — the diagnostic artefact

Relevance ranks of all 39 retrieved judged-relevant chunks:

| rank | 1 | 2 | 3 | **4** | **5** | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| judged hits | 16 | 10 | 6 | **0** | **0** | 1 | 5 | 1 |

`ACCOUNTABLE_RANK = 4` (`graph.py:857`) is the line below which `resolve` will not consider
an excerpt at all (`graph.py:1068-1078`). **32 of 39 judged hits sit at ranks 1–3; 7 sit at
ranks 6–8; ranks 4 and 5 are empty.** Three labels have their *best* chunk below the line:

- `conflict-a16-number-collision` → `cs2:3.2.3` at **rank 7**
- `conflict-vac-six-year` → `global:5.1.12` at **rank 7**
- `normal-cs2-lateness-ladder` → `cs2:2.8.4` at **rank 6**

The distribution is bimodal with a clean gap exactly at the cutoff, which means
`ACCOUNTABLE_RANK = 4` is currently a *safe* choice — nothing is being clipped at the
margin. It is not evidence the value is right; it is evidence that on this query set the
value is not the binding constraint.

### Two facts the fixture notes get wrong

Found while wiring `ranks`, and both are the `docs`-vs-`ranks` conflation (B5's shape):

1. `eval/queries.yaml:338-339` records for `conflict-vac-six-year`: *"cs2 4.8 at rank 2,
   global 5.1.12 at rank 8"*. Measured: those are **authority-order `docs` positions** 2 and
   8. The fused **relevance ranks** are **3 and 7**.
2. `eval/queries.yaml:302` records that `cs2 3.2.3` "is retrieved at rank 2" for
   `conflict-a16-number-collision`. Measured: `docs` position **3**, relevance rank **7**.
   The note matches neither.

Neither changes a gate outcome — `must_include` asserts presence in the top 8, not position
— but a future reader tuning `ACCOUNTABLE_RANK` or `FUSED_K` against those notes would be
tuning against the wrong number.

### B-3 reproduced independently

`graph.group_articles` buckets on `(game, article_id)` and takes `Group.scope` from
`members[0]`, which is authority-ordered — so the amendment. Measured live on
`conflict-a16-number-collision`:

```
group game=global article_id=3.2.3 SCOPE=amendment docs=2
global_groups seen by resolve: ['5.1.19.3', '3.2.7', '3.3.3', '3.5.3']
```

Global Article 3.2.3 — the article CLAUDE.md #1's express-primacy exception rests on — is
absent from `resolve`'s own Global view. Confirms log 009 B-3, still unrepaired.

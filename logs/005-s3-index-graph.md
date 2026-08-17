# Iteration 005 — S3 index + bare retrieve-and-answer

- **Date:** 2026-08-13
- **Kind:** build
- **Verdict:** FAIL
- **Next action:** repair S3 — **B1 ONLY**. Advisory findings A1–A6 are **not** repair scope
  unless the human says otherwise.

> **⚠ PARTIALLY RETRACTED BY ITERATION 006 (2026-08-13).** The **"Precedence (#1) — works, but
> NON-DETERMINISTICALLY"** finding below is **WRONG** and has been struck in place — all three
> cited cases retrieve pools containing **no Global rule differing on the same point**, so those
> precedence assertions were unfounded **in exactly the B1 way**. The **non-determinism** half of
> the finding (A2, no `seed`) **still stands**. See `006-s3-repair-b1.md`. Everything else in this
> entry is unaffected. **This is the THIRD verifier self-correction in this log series** (A18 in
> 004, ruling 5 in 004-retracted-by-005, and this one).
>
> **The S0/S2 `OPENAI_API_KEY` blocker is CLEARED.** 004 predicted S3 would return BLOCKED
> without a key. A key was present; both agents made real API calls; the stage was fully
> verified and returned a substantive FAIL, not a BLOCKED.
>
> **This iteration also RETRACTS a ruling from log 004.** See *Findings → Retraction of 004
> ruling 5* and the correction note now embedded in `logs/004-s2-chunker-repair.md`. This is
> the **second** verifier self-correction in this log series (A18 in 004 was the first) — the
> record is self-revising, and a reader must check later entries before trusting an earlier one.

## What was built

- `index.py` — **new.** Chunks via `chunker.chunk_corpus()`, runs `validate()` as a **hard
  gate**, prices the embed with tiktoken, drops + rebuilds the Chroma collection, pickles the
  **same** `Document` list for BM25, writes `data/index_stats.json`.
- `graph.py` — **new.** LangGraph `route → retrieve → answer`, hybrid dense+BM25 retrieval with
  RRF, **store-level** scope filter, citation/abstention/precedence prompt, CLI entry point.

Nothing else modified. No `articles.py`, no `eval/`, no `resolve`/`grade` node, no UI.

**Destructive step RUN ONCE:** `python index.py` dropped and rebuilt the Chroma collection.
Announced before running. Corpus embedded **exactly once** for the whole iteration.

## What was verified

Everything below was **executed** by `ewc-verifier`. Every builder claim was independently
re-derived.

**Artifacts — all builder claims MATCHED:**

| check | result |
|---|---|
| Chroma `ewc_rulebooks` vectors | **2381** |
| `chunks.pkl` Documents | **2381** |
| id sets chroma vs pickle | **identical, 0 diff either direction** |
| `page_content` identical | **2381 / 2381** |
| metadata identical, all 11 required keys | **0 mismatches** |
| fresh `chunk_corpus()` vs pickle | **identical IN ORDER**, hash `502b2221d0996101` both sides |
| `validate()` violations | **0** |
| embedding dimension | **1536**, non-null |
| `--estimate` re-run | exact match: **2381 chunks / 0 violations / 302,864 tokens / $0.006057** |
| pickle size | **1,938,007 bytes** |
| embed wall time | **12.1 s** for 2381/2381 |

**Retrieval mechanics — verified by code reading AND by measurement:**

- `DENSE_K=12  LEXICAL_K=12  FUSED_K=8  RRF_K=60` — matches CLAUDE.md's "retrieve 12 + 12,
  fuse, keep top 8".
- RRF is genuine (`1.0/(k+rank)`, rank counted from 1). The verifier **hand-computed a 4-doc
  example** and the implementation reproduced the **exact expected order**.
- Live measurement: dense returned 12, lexical 12, union 18 → truncated to 8.
- Authority sort confirmed **STABLE** (RRF order preserved within an authority tier) and
  **non-increasing** across all **24** titles.

**The four non-negotiable behaviours:**

- **Cross-title leakage (#5) — CLEAN. Strongest result of the iteration.**
  Scope parity **exact** for all **24** titles and for general scope (**159/159** chroma vs
  BM25). **Zero** off-title chunks in any of the 24 chroma pools. **8** adversarial sibling
  probes on the pairs S1 flagged (`cod-mw3`↔`warzone`, `mlbb`↔`mlbb-women`) leaked **0**. Two
  generation prompts *explicitly demanding* the sibling title ("also tell me the men's MLBB
  roster rules"; "in Warzone, what are the MW3 map veto rules") both **refused correctly**.
  Filtering is genuinely at the store; `_matches()` replicates the same filter dict for BM25.
- **Abstention (#4) — CLEAN.** 4/4 genuinely-absent questions abstained **and named the scope
  searched**. **0 hedge words across all 39 generated answers.**
  The verifier's 5th "absent" probe was **its own error, not the system's**: the $750,000
  Dota 2 prize claim is **REAL** — dota2 Art. 2.8 p.15 carries the prize table and the model
  read a badly-extracted table correctly.
- **Citation (#3) — one reproducible failure (B1).** Broad rate is good: **0/24 unsupported
  citations** across 12 varied questions; PyMuPDF audit of 12 articles found heading and
  body-start on the recorded page **12/12**.
- ~~**Precedence (#1) — works, but NON-DETERMINISTICALLY and unsafely at the edge.** Correct on
  LoL roster replacement, MLBB sponsorship, CS2 punctuality.~~ But the **same question at
  temperature 0** produced "overlapping but distinct punishments" on one run and "the Dota 2
  rulebook governing here" on another. **Compliance with #1 is not reproducible.** No `seed`
  is set.

  > **RETRACTED (see 006) — "Precedence works" is WRONG.** The **builder challenged this finding
  > and the builder is right**; the verifier has retracted its own finding. Retrieval-only pool
  > dumps at 006: **MLBB sponsorship — 8/8 title, 0 global, no Global chunk in the pool at all**;
  > **CS2 punctuality — 7 title + 1 global, but the single Global chunk is `5.1.7.1` Cheat
  > Software, unrelated to lateness**; **LoL roster replacement — 7 title + 1 global, where
  > `global 2.2.1` IS on substitutes but states COMPLEMENTARY rules (substitute types) against
  > LoL's PROCEDURAL rule (swap between games, 5-min notice) — no divergence.**
  > **In none of the three was there a Global rule differing on the same point**, so the
  > precedence assertions the model produced were **unfounded in exactly the B1 way**.
  > **STILL STANDS:** the non-determinism half — same question, different citations and different
  > precedence language at temperature 0, no `seed` set (A2). Only the "works" claim is retracted.
  > 006 further measured **zero precedence statements across all 28 live answers**, including on
  > the two **genuine** conflict pairs it found (`dota2 5.5` vs `global 5.1.19.4.1`;
  > `cs2 4.8` vs `global 5.1.12`) — see 006 **B4**.
  > This is the **THIRD** verifier self-correction in this log series (A18 in 004 was the first,
  > ruling 5 in 004 — retracted by this entry — the second).

**Part B — end-to-end seams: byte-exact today, but nothing enforces it.**
Global 3.2.3 traced through every hop: PDF p.17 → chunker (`global:3.2.3:0`, page 17, "Team
Roster Integrity") → pickle (identical) → chroma (identical, page meta 17) → retrieved
**RANK 1** → rendered header `citation=(EWC Global Rulebook 2026 — Article 3.2.3, p.17)`.
Article number and page survive unchanged. **8/8** rendered blocks carry the full metadata
header (contract "don't let the answer prompt see raw chunks without metadata" holds).
But dense and lexical **can** drift out of sync — see A1.

**Scope compliance — CLEAN.**
Modules kept separate. No hardcoded CDN URL and no hardcoded slug list in `index.py` /
`graph.py` — `catalog()` derives **24 `(slug, title)` pairs from the corpus itself**. No answer
caching (no `lru_cache`; `ask()` invokes the graph every call).
`index.py` guards all fire **BEFORE** `drop_collection`: `--estimate` exits 0 with no network;
`--max-usd 0.0001` refuses with exit 2; an unpriced model refuses with exit 2 — collection
still **2381** after all three.

**Builder-disclosed defects, both re-tested by the verifier:**

- **Q3 initially FAILED.** "Can a Mobile Legends: Bang Bang team take an alcohol brand as a
  sponsor?" routed to `None`, searched Global only, and **abstained on a question the corpus
  answers at mlbb 9.1.4**. Cause: a router prompt preferring `none` on tournament-wide subject
  matter, overriding an **explicitly named title**. Fixed to route on the title named.
  Verifier's router regression sweep after the fix: **18/18** (see ruling 4).
- **Tokenizer defect found and fixed.** Dotted tokens were atomic, so a parent-article query
  never matched children — "Article 5.1.19 sanctions" returned **0 of 12** BM25 hits in
  5.1.19.x. `tokenize()` now emits dotted prefixes (≥2 components) on query and corpus.
  Verifier confirmed the win and found an **unreported regression** — see ruling 3.

## Checks not run

- **`resolve` / `grade` nodes not built, therefore not verified.** The LangGraph contract's
  full node list (`route → retrieve → grade → (retrieve | resolve) → answer`) is not yet
  implemented; only `route → retrieve → answer` exists. The grade-and-rewrite loop and the
  precedence-note mechanism are **unverified because absent** — precedence today is handled
  entirely inside the answer prompt, which is exactly what B1 exploits.
- **Amendments layer (contract #2) not testable.** `articles.py` does not exist; no amendment
  chunks are in the store. "Amendments supersede" has **zero** coverage.
- **No `eval/` harness.** All S3 evidence is hand-run probes, not a repeatable suite. Nothing
  regression-pins any of it.
- **The builder's exact Q5 could not be reproduced** — its question text is not recorded in
  `logs/`. The verifier ruled on the **class** instead (ruling 1).
- **Determinism was not pinned** — the verifier established non-determinism at temperature 0
  (A2) but did not measure its rate across a large sample.
- **Still not a git repository.** `.gitignore` correctness remains proxy-tested only.
  Unchanged since S0. (A6)
- **A4's honor-of-kings +6 printed-page offset still uncorrected** and still un-retested at
  S3; it remains the most severe citation-locator defect in the corpus (see ruling 6).

## Findings

### BLOCKING

**B1 — `graph.py:246-249` (SYSTEM prompt, PRECEDENCE paragraph): fabricated title-book
citation + false precedence assertion when the title rulebook is SILENT. Reproducible 5/5.**

- **Input:** `--game cs2` — *"If a Counter-Strike 2 player is caught cheating, what sanction
  applies and for how long are they banned?"*
- **Behaviour:** all **5** runs opened with **"The Counter-Strike 2 rulebook governs here over
  the Global Rulebook"** and attributed **Global's** 5-year cheating ban to CS2.
  Runs 1–3 cited `(Counter-Strike 2 — Article 5.1.7.3, p.25; EWC Global Rulebook 2026 —
  Article 5.1.7.3, p.25)`; runs 4–5 cited `(Counter-Strike 2 — Article 4.8, p.21; ...)`.
- **Verified against the PDF:** **CS2 has NO article 5.1.7.3** (0 chunks; the deepest 5.1-series
  article is 5.1.1); the literal string `5.1.7.3` appears on **zero pages** of the CS2 PDF;
  **CS2 p.25 is the map-veto section** and contains neither "cheat" nor "5 years".
  **A compliance reader following the citation finds veto rules.**
- **Contract:** breaches **#3** (a citation must resolve to the right article and page — the
  "present-but-wrong citation" case) **AND #1** (title precedence asserted over a rule that
  exists **only** at Global level).
- **Root cause is precise and is NOT a rendering bug.** `render()` emits the correct,
  unambiguous `citation=(EWC Global Rulebook 2026 — Article 5.1.7.3, p.25)`. The PRECEDENCE
  paragraph tells the model what to do when **both** tiers address a point but says **nothing**
  about the common case where **only Global does**, while the question frame is title-scoped.
- **Mirror-image defect also observed:** the valorant roster question returned "the EWC Global
  Rulebook governs here over the Valorant rulebook" — the precedence relation stated
  **BACKWARDS**.
- **Two fixes, both cheap (verifier's):**
  1. Add a **third branch** to PRECEDENCE covering *"only Global addresses this — say the title
     book is silent and cite Global alone; do not assert precedence."*
  2. `render()` already emits exact `citation=` strings, so a **mechanical post-check that every
     `(Game — Article X, p.N)` in the answer appears verbatim among the rendered lines would
     have caught this 5/5 at ZERO API cost.**
- **Honest scope (verifier's own framing):** the broad citation rate is **0/24** — this is a
  specific reproducible trigger, not an endemic problem. But a **5/5 misattribution of a
  cheating sanction to the wrong rulebook is exactly the failure class this product exists to
  prevent.**

### Retraction of 004 ruling 5 — the verifier has retracted its own S2 ruling

**004 recorded: "thin bodies will be found by BM25 and essentially never by dense."
THAT IS WRONG, and the verifier says so explicitly.**

Measured at S3: `mlbb:9.1.4` (body `alcohol;`) ranks **5** dense on a natural question,
**1** on the bare word "alcohol", **2** on another phrasing, and **5** even at k=100.
Generalised across **all 14** thin-body chunks queried by their own heading+body:
**dense top-12 hit 14/14; BM25 14/14.**

**Mechanism the verifier had missed:** CLAUDE.md's mandated context label
`[<game_title> · Article <n> — <heading>]` puts the heading into the **EMBEDDED TEXT**, and for
these chunks **the heading IS the rule text** — so the vector is not near-null.
**The contract's label requirement is doing exactly the job it was specified to do.**
(Builder measured rank 4, verifier measures 5; rank varies with phrasing, conclusion identical.)

**What survives from 004 ruling 5:** the **"do NOT widen `k`"** constraint still stands on its
own merits — CLAUDE.md forbids papering over a retrieval failure by widening `k`. Only the
dense-retrieval prediction is retracted. `logs/004-s2-chunker-repair.md` has been annotated
in place at ruling 5 and at the derived carry-forward bullet; the original text is preserved,
not deleted.

### Verifier's six rulings

1. **Q5's "they agree on the severity of the consequences" — a genuine #4 violation; ADVISORY
   in isolation, but the visible tip of B1.** The verifier could not reproduce the builder's
   exact Q5 (its question text is not in `logs/`), so ruled on the class. Standing alone it is
   a soft closing gloss misdirecting no reader to a wrong article, so it **does not block on its
   own**. But it is an **uncited comparative legal conclusion absent from both excerpts**,
   produced by the same generator behaviour that produces B1 — the verifier reproduced the same
   shape **twice** ("overlapping but distinct punishments"). **Do not wave it through; fixing B1
   should fix it.**
2. **Q1's incompleteness — NOT a contract violation, and not reproducible.** The verifier's run
   of the CS2 lateness question returned the **COMPLETE** rule: warning, 1 pt per 5 min to max
   8, then 1.5 pts per 2 min to max 12, then no-show — plus 2.8.4's forfeit ladder. The
   builder's omission was a phrasing artifact. On principle: a partial answer is **not per se**
   a violation — CLAUDE.md #4 blesses partial coverage — what **would** violate is **SILENT
   partiality on a forfeit rule**. **Add an S4 fixture asserting the no-show threshold appears.**
3. **Tokenizer dotted-prefix — SOUND, ship it, but with one regression the builder did not
   report.** Confirmed win: "Article 5.1.19" went **0/12 → 5/12** prefix hits with **5.1.19.1 at
   rank 1**. No precision cost on the dominant query class: **3/3** non-numeric controls returned
   **BYTE-IDENTICAL** top-12; corpus token inflation only **0.93%**; leaf queries unaffected
   (3.2.3 stays rank 1).
   **The unreported cost:** when a parent article exists as its own chunk, prefix emission
   collapses its IDF and it loses — BM25 `"Article 3.2"` went from **rank 1 (old) to NOT IN THE
   TOP 6 (new)**, all six slots taken by its children. At the hybrid level dense partially
   rescues it (rank 7 on one phrasing, absent on another). **Net win; pin BOTH directions with
   an S4 fixture.**
4. **Router fix — CORRECT, no trade-off. 18/18.** Both directions tested: **6/6**
   tournament-wide-with-no-title-named → `None`; **8/8** title-named-but-topic-sounds-global →
   the right slug (including `cod-mw3` and `warzone` distinguished, and `mlbb` vs `mlbb-women`);
   **4/4** games absent from the corpus (OW2 ×2, Minecraft, StarCraft II) → `None` with **no
   substitution of a corpus title**. The builder did **not** trade over-routing for
   under-routing.
5. **Retraction of 004 ruling 5 — see the dedicated section above.**
6. **Page-span citations naming the start page — ADVISORY, acceptable convention, not a #3
   defect.** Real and quantified: **429/2381 = 18.0%** of chunks span pages; confirmed with
   PyMuPDF that cited text lands on the **next** page in three cases (mlbb-women 2.3.1 cited
   p.6 → second sentence p.7; dota2 1.4.1 cited p.7 → third sentence p.8; global 3.2.3 cited
   p.17 → second sentence p.18). **Not a defect** because CLAUDE.md's mandated citation format
   has **no slot for a range**, and the article number — exact in 12/12 audited — is the primary
   locator. But `page_end` is already in metadata, so rendering `p.6-7` costs nothing.
   **Far milder than the still-live A4 honor-of-kings +6 printed-page offset, which names a page
   the reader cannot find at all.**

### Advisory findings

- **A1 — no guard keeps dense and lexical from drifting (Part B's central question).**
  `index.py:238-243` calls `build()` (drop + re-embed) **BEFORE** `write_pickle()`, with **no
  try/except and no rollback**. If `build()` raises mid-embed, the collection is left
  dropped/partial while `chunks.pkl` still holds the **previous full corpus**.
  `graph.py` **cannot detect this**: chroma collection metadata is `None`, no corpus hash is
  written anywhere, and `graph.py` never compares pickle count to chroma count nor reads
  `index_stats.json`. Editing `chunker.py` without re-running `index.py` is likewise invisible —
  the only signal is mtime, which nothing checks. Same class: `--games` drops the **WHOLE**
  collection but pickles only the **subset**, and `index_stats.json` then describes a partial
  corpus with no marker.
  **Consistency here is a property of the last successful run, not an invariant.** A corpus hash
  written into both artifacts and asserted at load would close all of it.
- **A2 — temperature 0 is NOT deterministic; no `seed` is set** (`graph.py:290-294`). Same
  question, different citations and different precedence language across runs.
  **S4's regression detection needs this pinned.**
- **A3 — router schema is a free-form `str`, not `Literal`/Enum** (`graph.py:324-329`).
  CLAUDE.md says "structured output **constrained to the known slug list**"; the constraint is
  actually enforced by **post-validation** (`choice if choice in slugs else None`). Fallback
  direction is safe, but the contract asks for **schema-level** constraint. See Contract deltas.
- **A4 — 192 `(game, article)` pairs are non-unique corpus-wide** (e.g. `global 1.2` twice).
  `chunk_id` disambiguates correctly (**2381 unique**, verified) and page disambiguates the
  rendered citation. **Confirms and EXTENDS S2's A2: `resolve` must group on `article_id`,
  never `article`.**
- **A5 — `data/index_stats.json` embeds absolute personal paths** (`/Users/yashik/...`). No
  `.py` source contains a secret, key, or absolute path, and `data/` is gitignored, so this is
  **not** a leak into a committed artifact — but gratuitous.
- **A6 — still not a git repository.** `.gitignore` correctly covers `.env`, `data/`, `*.pdf`,
  `*.pkl`, `chroma/`, but remains **proxy-tested only**. Carried from S0/S1/S2.

## API spend

| party | detail | cost |
|---|---|---|
| **builder** | 302,864 embed tokens | **$0.006057** |
| | ~845 query-embed tokens | $0.000017 |
| | gpt-4o-mini 13,841 in / 693 out | $0.002492 |
| | gpt-4o-mini 5,060 / 61 | $0.000796 |
| | gpt-4o-mini 2,437 / 49 | $0.000395 |
| | **builder subtotal** | **≈ $0.0098** |
| **verifier** | 18 router calls (9,063 in / 103 out) | |
| | 12 adversarial answers (35,901 / 1,539) | |
| | 5 precedence (10,896 / 772) | |
| | 5 fabrication repro (10,585 / 506) | |
| | 12 citation-rate sweep (27,825 / 1,757) | |
| | 1 `python -m graph` (2,392 / 140) | |
| | ~350 query embeddings (~8k tokens) | |
| | **verifier subtotal** | **≈ $0.0176** |
| | **ITERATION TOTAL** | **≈ $0.0274** |

Against the **$5** credit — roughly **0.55%** of budget for the iteration; the builder's share
alone is **~0.2%**.

**The corpus was embedded EXACTLY ONCE** (302,864 tokens, $0.006057) and was **NOT re-embedded
during verification**. The verifier confirmed the store still held **2381** vectors at exit.

## Contract deltas

**CLAUDE.md is the source of truth and only the human may amend it. The logger has not touched
it.**

**NEW in this iteration:**

1. **A3 — structured-output constraint gap.** CLAUDE.md's LangGraph contract says `route` "uses
   structured output **constrained to the known slug list**". The implementation
   (`graph.py:324-329`) declares a free-form `str` and constrains by **post-validation**
   (`choice if choice in slugs else None`). Behaviourally safe (18/18, fallback direction is
   `None`), but the mechanism the spec names is not the mechanism used. **Human ruling: amend
   the spec to bless post-validation, or require `Literal`/Enum.**

**Still open from earlier iterations — carried forward UNRESOLVED:**

2. **`\d{1,2}` narrows CLAUDE.md's stated `\d{1,3}` sub-level component**, and the spec's own
   regex has a **latent flaw**: `\d{1,3}` **MATCHES `70.000 USD`**. Measured at S2: 24
   three-digit-component candidates corpus-wide, all 24 prize amounts, zero genuine headings.
   **Verifier recommends AMENDING CLAUDE.md rather than reverting the code. Human ruling
   needed.** (004 delta 1.)
3. **The `[A-Z]` guard is RELAXED under multi-level numbers**, deviating from CLAUDE.md's
   literal heading regex. Measured: **+8 genuine articles, 0 junk**. **Human ruling needed.**
   (004 delta 2.)
4. **The ">80% of Global chunks have non-empty article numbers" gate is GAMEABLE as written.**
   The literal spec regex scores Global 98.9% while producing an **11-article** corpus.
   **Recommend the human add a distinct-article floor.** (003 delta 1.) Unchanged.
5. **CLAUDE.md line 150 — "manifest of 26 docs" contradicts the confirmed 25 PDFs** (OW2 ships
   a Google Doc); the same line's `version`/`effective_date` expectation is present-as-null for
   **24/25** documents. (S1 deltas 1–2.)
6. **CLAUDE.md line 26 — Global has no `/rulebooks/<slug>` detail page.** True for the 25
   titles, false for Global. (S1 delta 3.)
7. **CLAUDE.md lines 35-36 — there is no `<noscript>` fallback.** The 25 links are ordinary
   server-rendered anchors; the outcome the spec wants holds, the mechanism it names does not.
   (S1 delta 4.)
8. **CLAUDE.md line 22 — "annexed to the Global Rulebook" is textually false for the EA/ALGS
   apex document.** (S1.)
9. **`fitz` vs `pymupdf`** — CLAUDE.md says "PyMuPDF (`fitz`)"; the code imports `pymupdf`, the
   modern canonical name. **Until the human rules, this is NOT a deviation.** (S0 delta 1.)

**Record-keeping note:** the verifier **corrected its own prior ruling** this iteration
(004 ruling 5, retracted above). This is the **second** such self-correction — A18 in 004 was
the first. **The log is self-revising: do not treat an earlier entry's ruling as final without
checking later entries.**

## Carry-forward

**Corpus and index state — do NOT redo.**
`data/pdfs/` (25 PDFs) and `data/manifest.json` cached. **Chroma `ewc_rulebooks` is BUILT with
2381 vectors**; `chunks.pkl` holds the same 2381 Documents, byte-identical ids/content/metadata;
`data/index_stats.json` written. **The destructive `python index.py` has ALREADY BEEN RUN once.**
Re-running it re-embeds the whole corpus at $0.006057 — do it only when `chunker.py` changed.
**The B1 repair touches only `graph.py` prompts / post-check logic and MUST NOT require a
re-index.**

### For the S3 repair — B1 ONLY

- **Fix (a): add a THIRD branch to the PRECEDENCE paragraph** (`graph.py:246-249`) covering
  *"only Global addresses this — say the title book is silent, cite Global alone, do not assert
  precedence."* This also fixes the mirror-image backwards assertion (valorant roster) and,
  per ruling 1, should fix Q5's uncited comparative gloss.
- **Fix (b): add a MECHANICAL citation post-check.** `render()` already emits exact `citation=`
  strings, so asserting every `(Game — Article X, p.N)` in the answer appears **verbatim** among
  the rendered lines **would have caught B1 5/5 at ZERO API cost.** Prefer this — it is a
  permanent guard, not a prompt hope.
- **Repro fixture to keep:** `--game cs2` + *"If a Counter-Strike 2 player is caught cheating,
  what sanction applies and for how long are they banned?"* — must stop asserting CS2
  precedence and must stop emitting a CS2 article 5.1.7.3 / 4.8 citation.
- **Do NOT expand scope.** A1–A6 are advisory. Do not re-index, do not add `resolve`, do not
  widen `k`.

### For S4 (`eval/`)

- **A2 — pin `seed`.** Temperature 0 is not deterministic; regression detection is impossible
  without it.
- **Ruling 2 — add a fixture asserting the CS2 lateness answer contains the NO-SHOW THRESHOLD.**
  Silent partiality on a forfeit rule is the violating case.
- **Ruling 3 — pin the tokenizer in BOTH directions.** The win (`"Article 5.1.19"` 0/12 → 5/12,
  5.1.19.1 at rank 1) **and** the regression (`"Article 3.2"` BM25 **rank 1 → out of the top
  6**, six slots taken by its children; dense rescues to rank 7 on one phrasing, absent on
  another).
- **A9 (from S2) — the regression fixture MUST pin per-book chunk count AND distinct-article
  count**, plus `\d{1,2}` and `_wraps_previous_line`.
- **`_wraps_previous_line` comma-list fragility (004 ruling 3):** it accepts mlbb 9.1.2–9.1.8
  only because each predecessor line ends in `;`. **A list punctuated with `,` — common in legal
  drafting — would be rejected wholesale.**
- **Mandated leakage cases: `cod-mw3`↔`warzone` and `mlbb`↔`mlbb-women`.**
  **NOTE: these now PASS at S3 — 0 leaks across 8 adversarial probes and 24 title pools — so the
  fixture is a REGRESSION GUARD, not a known bug.** Valorant-vs-cs2 will never expose realistic
  leakage.

### For S5 (`articles.py` + `resolve`)

- **A4 / S2-A2 — `resolve` MUST group on `article_id`, NOT `article`.** Now measured at
  **192 non-unique `(game, article)` pairs** corpus-wide (e.g. `global 1.2` twice). `chunk_id`
  is unique 2381/2381.
- **mlbb ships a 17-chunk COPY of the Global Rulebook at `authority=1`**
  (`Appendix B - EWC26 Global Rules`), sharing Global's numbering and **outranking** it under
  CLAUDE.md's precedence rule. **Human ruling needed.**
- **apex/ALGS precedence — HUMAN RULING STILL OPEN since S1.** Chunker leaves apex at
  `authority=1` with `external_host=True`; a neutral default, not a decision.
- **OW2 corpus hole — open, for the human.** No Overwatch 2 rules exist; every OW2 question
  abstains (router correctly returns `None` and does not substitute a corpus title).
- **Contract #2 (amendments supersede) has ZERO coverage today** — no amendment chunks exist.

### Housekeeping

- **A1 — drift risk between chroma and `chunks.pkl` is UNGUARDED.** Write a corpus hash into
  both artifacts and assert it at load. Until then, treat consistency as "true as of the last
  successful `index.py` run", not as an invariant.
- **A5 — `data/index_stats.json` contains absolute personal paths.** `data/` is gitignored, so
  not a committed leak; still worth making relative.
- **A6 — still not a git repository.** Run `git status` before any first commit — `data/`
  (~29 MiB of redistributable PDFs owned by the Esports Foundation) must never be staged.
- **A4 (S2) — honor-of-kings printed-page offset is +6** on 44/60 pages. Rendered `p.N`
  citations name a page the reader cannot find in that book. **Still uncorrected**, and per
  ruling 6 it is materially worse than the page-span convention.
- **A real UA contact is still unset** (`ingest.py:47` / `.env.example:24` carry
  `you@example.com`). Set it before any further crawling.
- **`OPENAI_API_KEY` blocker CLEARED** — carried since S0, resolved this iteration.

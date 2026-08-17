# Iteration 009 — S5 articles + resolve

- **Date:** 2026-08-14
- **Kind:** build (+ repair of S3's B4/B5/B6/B7, per the 007 halt ruling)
- **Verdict:** FAIL
- **Next action:** repair S5. Repair scope is the verifier's ranked list: (1) B-2, (2) B-1,
  (3) B-3, (4) B-4, (5) advisory B-5 and A-S4-1.

> **The builder's headline "EVAL PASS exit 0" did NOT reproduce.** The verifier ran the shipped
> gate at its own default (`runs: 3`, no args) and measured **exit 1**. This is the first
> iteration in this project where the eval gate itself — not just a probe against it — is the
> thing that failed. Treat any "PASS" claim from a builder handoff as provisional until an
> independent re-run confirms it at the shipped default.

## What was built

- **`articles.py` NEW** — polite crawl (identifying UA, serial requests, `DEFAULT_CRAWL_DELAY =
  0.6` with an unbypassable floor) → `data/amendments.json` → `amendment_documents()`. One chunk
  per notice, never split, so a "Previous rule" section cannot be retrieved without its
  superseding text.
- **`index.py`** — +8 lines to index amendment documents.
- **`graph.py`** — new `resolve` node plus `group_articles`, `subject_score`, `agree`,
  `express_primacy`, `cross_references`, `restates_global`, `false_gap_violations`,
  `verbatim_violations`; A13 fix; B5 gating; `hybrid` now returns fused ranks; scope filter
  extended; prompt shrunk; graph rewired `route → retrieve → resolve → answer`.
- **`eval/queries.yaml`** — pins updated, 3 new cases, A-S4-1 nominally "fixed" (see findings),
  `runs: 2 → 3`, 9 assertion promotions known_fail → must_pass.
- **`eval/run.py`** — amendment pins, scope-aware `must_include`.

**Deliberately deferred:** priority 3, the `grade` retrieval-sufficiency loop. Builder's stated
reasoning: retrieval is deterministic, a rewrite loop would make every S5 measurement
conditional, and the one case where a rewrite looked useful (recovering global 5.1.12) turned out
not to need one. The verifier ruled this deferral sound in isolation but flagged it as an
**outstanding contract gap** — see Findings and Carry-forward.

## What was verified

**Verified CLEAN by the verifier (executed, not read):**
- Scope-filter extension leak-free — exhaustive proof, 24 title slugs × all 2,382 docs → **0
  leaks**. A hypothetical cs2 amendment is invisible to valorant/mlbb-women, visible to cs2.
- Pins exact, delta is exactly the amendment: pickle sha256 `e5819299…`, 1,942,199 bytes, 2,382
  docs; Chroma 2,382; global 160/128 all match reality. Set-difference `pickle − pdf =
  ['amendment:article:global:3.2.3:0']`, `pdf − pickle = []` — independently proves `chunker.py`
  output is unchanged since S4.
- A16 acid test PASSES: `group_articles` produces two separate groups for cs2 3.2.3 and global
  3.2.3. No fabricated conflict.
- Contract #2 `incorporated` branch genuinely correct for its one live instance: verifier checked
  the real PDF — para 1 on p.17, the amendment's added paragraph on **p.18** (the publisher
  silently re-uploaded the PDF). Shingle containment 0.864 ≥ 0.70. Renders "current AS AMENDED"
  with the notice's own caveat verbatim.
- B5 closed BEYOND its fixture: 3 non-fixture questions (valorant/tekken-8/lol) — 0 padding
  words, 0 disavowal sentences.
- A13 closed 6/6, including the partial-gap sentence the prompt itself mandates.
- Prompt shrink verified exactly: 6 sections / 508 words (was 8 sections / 770 words at 007/008);
  DEFAULT CASE, three-part test, COMPLETENESS all absent from SYSTEM.
- Human-ruling defaults implemented and single-switch reversible: apex 161 chunks
  `external_host=True`, authority unchanged, provenance branch at `graph.py:1119-1128`; mlbb's 17
  Appendix-B chunks classified `restatement` at `graph.py:1104`. Both derived at runtime.
- No hardcoded CDN URLs/slug literals/secrets/absolute paths. `chunker.py`/`ingest.py`/
  `CLAUDE.md` mtimes predate S5. `index.py` change is 8 lines. State keys = contract + 7 plumbing;
  every node returns a partial dict; no in-place mutation anywhere.
- The `queries.yaml` diff is COMPLETE, not sampled — verifier recovered the S4 baseline from the
  S4 verifier's own mutant copies in the shared scratchpad and diffed structurally: **3 cases
  added, 0 removed, 0 questions changed, 0 retrieval assertions changed, no pin loosened or
  deleted**; `runs: 2 → 3` (tightening); **9 assertions promoted** known_fail → must_pass
  (media-fines ×2, publisher-bans ×2, express-primacy ×3, B5 ×2). Exactly TWO changes to existing
  assertions were NOT promotions: the B-5 relaxation and the A16 narrowing (see Findings).

**Builder's self-reported numbers (NOT independently reproduced at the shipped default — see
B-1):** EVAL PASS exit 0 claimed — conflict 9/9, cross-scope 7/7, normal 11/11, pipeline 1/1,
pins 32/32, 17/17 offline probes; B4 CLOSED (media-fines 8/8, publisher-bans 8/8, VAC
discriminator 8/8); B5 CLOSED (padding gone 3/3); B6 CLOSED; A13 CLOSED (6/6); **B7 reduced, not
closed** (builder's own framing: "115w → ≤34w"); two NEW self-reported findings — **B9** (A16
question answered only for Global 3.2.3, never the CS2 one) and **B10** (primacy stated under
decision phrasing 3/3, not descriptive phrasing 0/3).

## Checks not run

- `grade` / retrieval-sufficiency loop — not built at S3, S4, or S5. Still zero coverage.
  CLAUDE.md's LangGraph contract requires `route → retrieve → grade → (retrieve | resolve) →
  answer`; the shipped graph is `route → retrieve → resolve → answer`.
- Full must_pass set re-run at `runs: 3` across sessions beyond the verifier's own re-runs (the
  verifier's B-1 finding is itself evidence this matters — see Findings).
- Contract #2's `superseded` branch has no live instance to test against (the one real amendment
  is `incorporated`, not `superseded`); unit-tested only, not proven end to end.
- Offline probe files from the builder's own session are again absent from the tree (carried
  forward from S4/S3 as A-6).

## Findings

### Blocking

- **B-1 — `eval/run.py` FAILS on independent re-run at the shipped default.** No args, `runs:
  3` → **EVAL FAIL, exit 1**. conflict 8 pass / **1 fail**, cross-scope 7/7, normal 10 pass /
  **1 fail**, pipeline 1/1, pins 32/32. `conflict-vac-six-year` → `require
  /(govern|prevail|precede|take[s]? precedence)/` runs = `['F','F','P']`. This is the exact case
  008's ruling 5 demanded be added because the other two conflict wordings flatter the pipeline,
  and it is one of the assertions the builder promoted to must_pass. Across all samples measured:
  **7/9**; at `runs: 3` the gate passes roughly **47%** of the time. Also
  `normal-mlbb-alcohol-sponsor` → cite MLBB 9.1.4, runs = `['P','F','P']`; the failing run cited
  `Article 9.1, p.50` — right page, wrong granularity, and the citation post-check cannot see it
  because 9.1 is itself an allowed locator. Ruling: B4 is closed on the two flattered wordings
  (media-fines 7/7, publisher-bans 8/8 measured) but **not** on the natural discriminating
  wording. That promotion got lucky; the stage's headline claim does not reproduce.
- **B-2 — Cross-title MISATTRIBUTION: the answer presents another title's rules under the asked
  title's name. 3/3, and it is a REGRESSION from 007.** `graph.py` `_coverage_lines()`
  (1139-1182). `--game valorant` "What are the CS2 map veto rules?" → answer opens "The map veto
  rules for CS2 are as follows: 1. The higher-seeded team decides…" citing
  `(VALORANT — Article 5.5.1, p.11; VALORANT — Article 5.5.1.1, p.11)`. 3/3 runs, 167-201 words.
  Reproduces on `--game cod-mw3` "Warzone loadouts?" → answered from Call of Duty: Black Ops 7's
  rules, labelled Warzone; and `--game mlbb-women` "men's MLBB roster rules?" → answered from the
  Women's book. The store filter itself is CLEAN in every case (0 foreign chunks — CLAUDE.md #5
  holds at the retrieval level). What breaks is completeness/faithfulness (#4/#3): a compliance
  reader asking about Warzone is handed Black Ops 7's rules labelled as Warzone's. **007 measured
  a REFUSAL on this exact probe** — this is a regression, not a new gap. Mechanism: the `SCOPE.`
  guard in `_coverage_lines` fires only when NO title book is in evidence, while the `COVERAGE.`
  clause actively instructs the model "do not stop at the first excerpt that answers the
  question, and do not report the excerpts as silent while any of these speaks to it." The routed
  title's own veto article sits at rank 1 and the model relabels it. **The eval harness is
  structurally blind to this: all five `xscope-leak-*` cases are `generate: false`** — "cross-scope
  7/7" attests retrieval only, never generation.
- **B-3 — `resolve` silently disables Global-vs-title precedence for any amended article.**
  `graph.py:950-972` (`group_articles`) + `1028-1029`. `hybrid()` sorts authority-descending so
  the amendment chunk precedes its base article in `docs`; `group_articles` buckets on `(game,
  article_id)` and `Group.scope` is taken from `members[0]` — the amendment. Proven:
  `group game=global article_id=3.2.3 SCOPE='amendment' cite=…Amendment 2026-07-17 (Article
  3.2.3, p.1) docs=2` and `global_groups seen by resolve: []` — the Global article has vanished
  from resolve's own view. Any title article on the same point can then produce no
  conflict/agreement/restatement/cross_ref finding against it, and if it did, `Group.cite` would
  cite the notice's p.1 for rulebook text. Live blast radius today is exactly one article
  (3.2.3), whose `amended` and `primacy` findings iterate raw docs directly and so still fire —
  but this is a correctness defect inside the node this very stage delivers, and it grows with
  every future amendment.
- **B-4 — B7 is materially worse than reported, and the recorded justification is FALSE against
  the shipped tree.** Builder claimed "115w → ≤34w"; `queries.yaml:47` records "now ≤28w on ONE
  case (28/28/23 at --runs 3)". Measured by the verifier on the shipped tree:
  `normal-cs2-lateness-ladder` → 34w / **90w** / 33w (vs cs2 2.8.4, 2.8.2 p.11);
  `conflict-express-global-primacy` → 39w/39w/39w (vs the amendment chunk);
  `conflict-express-global-primacy-rephrased` → 18w/27w. A 90-word unmarked run is in the same
  band as 007's 104/105w — not "≤34". It survives `VERBATIM_LIMIT = 20` because verbatim is
  classed as not-`untrustworthy`, so it ships after the single retry. The `finding:` text is what
  a future reader will trust, and it is wrong.

### Advisory

- **A-1 — the amendment's `incorporated` match crosses a FLIPPED NEGATION.** Notice: "even where
  no majority … **is unable** to participate"; PDF: "even where no majority … **is able** to
  participate." Shingle containment (0.864) cannot see this. Classification is right on substance
  here, but the check would not notice a semantically inverted "incorporation" if one occurred.
- **A-2 — the primacy note OVER-CLAIMS on the amended article.** Renders "This is the one
  direction in which Global outranks a title book. Say that the Global Rulebook governs on this
  point" while 3.2.3's own amended paragraph adds "provided such determination does not conflict
  with the applicable game-specific rules." Live answers reproduce the tension in one breath.
- **A-3 — COMPLETENESS is RELOCATED, not removed.** The prompt is genuinely 508 words, but
  `_coverage_lines` injects ~110 words of exhortation per request, and it is the proximate cause
  of B-2. (The precedence three-part test IS genuinely replaced by computed facts — that part of
  ruling 4 from 007 held.)
- **A-4 — `restates_global` fires on 38 chunks, not mlbb's 17.** The other 21 are each title
  book's own boilerplate "1.2 EWC Global Rulebook" incorporation clause. Benign and arguably
  correct, but wider than the human ruling described.
- **A-5 — doc drift in `articles.py`.** Module docstring says "2 HTTP requests" and "The other
  three records"; `amendments.json` records `http_requests: 1` and **4** skipped. The builder's
  "5 requests total" is a session count the verifier cannot verify from artifacts; the
  *mechanism* is verified — serial Session, `DEFAULT_CRAWL_DELAY = 0.6` with an unbypassable
  floor, identifying UA.
- **A-6 — carried unchanged.** UA contact still `you@example.com`; A2 (no seed) still unresolved
  and now demonstrably load-bearing (B-1); A-S4-3 (generation re-routes independently of the
  retrieval phase) still true, now reproduced across all 16 generative cases; builder's offline
  probe files still absent from the tree.

## Contract deltas

**NEW this iteration:**
- **Scope-filter extension — JUSTIFIED, leak-free, and IS a contract delta requiring human
  ratification.** Read literally, CLAUDE.md's title branch (`{"$or": [{"game": slug}, {"scope":
  "global"}]}`) makes contract #2 (amendments supersede) unreachable for title questions, since
  the only live amendment amends a Global article at `scope=amendment`. The builder added a third
  clause: `scope=amendment AND game=global`. Leak claim proven exhaustively (24 slugs × 2,382
  docs, 0 leaks), not sampled. Ratification required because CLAUDE.md quotes the filter
  verbatim.
- **Latent gap in CLAUDE.md's own spec, found by the verifier, NOT the builder's deviation.**
  CLAUDE.md's GENERAL branch (`scope $in [global, amendment]`) has no game clause, so a future
  TITLE-targeted amendment would be visible at tournament-wide scope regardless of which title
  asked. Worth fixing when the contract is next amended; not exercised live because the only
  amendment is Global-scoped.

**All still-open deltas from prior stages carried forward unchanged** (see 008's Contract
deltas section, items 2–11). **A11 remains RESOLVED** (closed at 007).

## Verifier rulings

1. **Scope-filter extension — JUSTIFIED and leak-free**, ratification required per above.
2. **The A16 narrowing (a change to an existing S4 must_pass forbid) — LEGITIMATE fixture
   correction, verified 5/5.** The answer contains exactly "The Global Rulebook prevails over any
   game title rulebook on this point (EWC Global Rulebook 2026 — Article 3.2.3, p.17)."; the S4
   blanket forbid did forbid the sentence CLAUDE.md #1 now mandates, so narrowing it was correct.
   **But the builder's claim that "every other change is a promotion or a tightening" is NOT
   TRUE.** Two caveats: (a) A-S4-1 is not actually fixed — the replacement positive assertion is
   itself `known_fail`, so for gating purposes the case is still forbid-only and a bare
   abstention still passes it; "now ENCODED rather than absent" is true as documentation and
   false as a gate. (b) B-5 (advisory, undisclosed) — a second relaxation:
   `conflict-express-global-primacy-rephrased` went from `require_any: ['even if the respective
   game title rulebook', 'game title rulebook allows bigger']` to `require:
   '(even if|regardless of|notwithstanding)[^.]{0,60}game[- ]title rulebook'` — strictly broader,
   with a known_fail (B10) added alongside, so the gate got LOOSER on that case. Documented in
   the file, but contradicts what the builder reported. Justification weak: the clause is ~15
   words, under both the 20-word pipeline limit and the 25-word gate, and #6 expressly permits
   short load-bearing quotes.
3. **`grade`'s deferral — the pipeline is NOT contract-complete, and the human must be told
   plainly.** Builder's sequencing reasoning is sound, and `answer()`'s bounded single retry
   honours "one grade-and-rewrite loop maximum" in spirit — but only for answer quality.
   CLAUDE.md's `grade` gates RETRIEVAL SUFFICIENCY and can route back to `retrieve`; nothing in
   the tree does that. Deferred at S3 and again at S5; `tries` is dead state. This is an
   outstanding gap, not a closed decision. **B-2 is exactly the shape a retrieval-sufficiency
   grade would have caught.**
4. **B7 — leaving `verbatim_max_run` as known_fail is the RIGHT CALL; its recorded severity is
   not.** 008's ruling 2 already held the 25-word threshold is a tripwire, not a definition of
   #6 — so yes, a ≤34-word unmarked verbatim run is still a #6 violation, and so is the 39-word
   amendment transcription. Keeping it non-blocking is correct because promoting it now would
   fail the gate for a reason the stage did not undertake to fix. **But B-4 must be corrected:
   the max is 90w, not 34w.**
5. **Contract #2's `superseded` branch — BLOCKED, never PASS. The headline capability is
   HALF-PROVEN.** No live instance exists, and the reason is verifiable and benign — the
   publisher re-uploaded the Global PDF with the amended paragraph already in it (PDF p.18), so
   `incorporated` is the honest classification for the one real case. Proven live: the notice is
   scraped, indexed at `scope=amendment`/`authority=2`, dense- and BM25-retrievable, fused to rank
   1-2, grouped with its base, rendered as "current AS AMENDED" with the notice's own caveat
   carried into the answer. NOT proven live: "never quote a superseded article as current" —
   unit-tested only. Do not record contract #2 as verified end to end.
6. **Overall fitness — NOT YET fit for its stated purpose.** Abstention is genuinely a success
   state where the corpus is silent (drone-racing probe: clean abstention, names the scope
   searched, zero hedge words, zero citations). Precedence, citation integrity, and store-level
   scoping are all in far better shape than at 007. **But B-2 is precisely the failure mode the
   product exists to prevent** — a confident, fluent, correctly-cited answer that attributes one
   title's rules to another, produced 3/3 on the very probe CLAUDE.md #5 uses as its own example,
   and invisible to the gate.

**Verifier's ranked repair scope for S5:**
1. B-2 — make `_coverage_lines`'s SCOPE guard fire when the question names a title other than the
   routed one, AND add `generate: true` + a misattribution `forbid` to at least two
   `xscope-leak-*` cases so the gate can see it.
2. B-1 — either stabilise `conflict-vac-six-year`'s precedence statement or demote it back to
   known_fail with an honest finding; do not ship a gate that is a coin flip.
3. B-3 — key `Group.scope`/`Group.cite` off the non-amendment member, or exclude amendment docs
   from `group_articles` and keep them in the `amendments` list only.
4. B-4 — correct the `verbatim_max_run` finding text to the measured 90w.
5. Advisory B-5 and A-S4-1 — restore a substantive gating assertion to each of the two re-aimed
   cases.

## Carry-forward

### What this stage genuinely achieved (hold this alongside the FAIL)

- B5, B6, A13 closed and **independently confirmed** by the verifier beyond their fixtures.
- Prompt shrunk 770 → 508 words, verified exactly (6 sections, DEFAULT CASE / three-part test /
  COMPLETENESS all removed from SYSTEM).
- Amendments layer is live end-to-end for its one real instance: scrape → index → retrieve →
  fuse → group → render, with the notice's own caveat carried into the answer.
- A16 number-collision handled correctly — `resolve` produces two separate groups for cs2 3.2.3
  and global 3.2.3, no fabricated conflict.
- Scope-filter extension proven leak-free exhaustively (24 slugs × 2,382 docs, 0 leaks).
- Human-ruling defaults (apex `external_host=True` + provenance caveat; mlbb Global copy forced
  to `restatement`) implemented as flagged, single-switch-reversible defaults, not silently
  baked in.
- Builder self-reported B9 and B10 honestly, and self-flagged both changes the verifier was asked
  to scrutinise (the scope-filter extension and the A16 narrowing) — but its claim that "every
  other change is a promotion or a tightening" was **not true**; B-5 is a second, undisclosed
  relaxation.

This stage delivered a lot and still fails. The FAIL is not a rejection of the architecture — it
is B-2 (a real regression from 007, structurally invisible to the current gate) plus B-1 (a
promoted must_pass that is a coin flip) plus B-3 (a defect inside the node this stage exists to
deliver) plus a materially wrong severity claim on B-4.

### `grade` — outstanding gap, human decision needed

Deferred at S3 and again at S5. CLAUDE.md's LangGraph contract specifies `route → retrieve →
grade → (retrieve | resolve) → answer`; the shipped graph is `route → retrieve → resolve →
answer`. `tries` is dead state. The builder's reasoning for deferring (retrieval is
deterministic; a rewrite loop would make every S5 measurement conditional; the one case that
looked like it needed a rewrite — recovering global 5.1.12 — didn't) is sound as sequencing
logic, but does not make the pipeline contract-complete. B-2 is exactly the failure shape a
retrieval-sufficiency grade would have caught. The human must decide whether S5's repair pass
also builds `grade`, or whether it stays deferred again with the gap explicitly acknowledged.

### API spend

| party | detail | cost |
|---|---|---|
| **builder** | `articles.py`, `resolve` + B4/B5/B6/B7 repairs, `eval/` updates; re-index | **≈ $0.24** (re-index $0.006068 + ≈$0.232 generation) |
| **verifier** | read-only checks, no re-index | **$0.064** |
| | **ITERATION TOTAL** | **≈ $0.304** |

**Project total ≈ $0.568 of $5 (~11%).**

### Corpus and index state

Corpus re-embedded **exactly once** this stage (first re-index since S3). Chroma `ewc_rulebooks`:
2381 → **2382** vectors (the one amendment chunk). `chunks.pkl`: sha256 `e5819299…`, **1,942,199
bytes**, 2,382 docs. `pickle − pdf = ['amendment:article:global:3.2.3:0']`; `pdf − pickle = []`.
Re-running `index.py` re-embeds the whole corpus — do it only when `chunker.py` or `articles.py`
output changes.

### Still open, unresolved (carried across multiple stages)

- Apex/ALGS authority ruling and mlbb Global-copy classification: **implemented as reversible
  defaults, still unratified by a human.**
- TPA PDF: recorded in the skipped list, not ingested — awaiting a decision.
- OW2 corpus hole (ships a Google Doc, not a PDF).
- honor-of-kings +6 printed-page offset.
- UA contact placeholder (`you@example.com`).
- A2 (seed) — now demonstrably load-bearing per B-1; N-runs is a workaround, not a fix.
- Builder's own offline probe files absent from the tree, across three consecutive stages now.

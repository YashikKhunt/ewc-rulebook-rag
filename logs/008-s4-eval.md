# Iteration 008 — S4 eval

- **Date:** 2026-08-13
- **Kind:** build
- **Verdict:** PASS
- **Next action:** advance to S5 (`articles.py` + `resolve` node), which also carries the S3
  blocking findings B4/B5/B6/B7 as its repair scope per the 007 halt ruling.

> **First stage since S1 to PASS on first verification.** The known_fail machinery worked as
> designed this iteration: B6 flipped between the builder's and verifier's sessions and was
> correctly reported as **intermittent**, not silently fixed and not hidden — the harness printed
> a NOTICE and did not block the gate.

## What was built

**`eval/queries.yaml` NEW** — 25 cases: conflict 6 / cross-scope 7 / normal 11 / pipeline 1, plus
30 offline regression-pin assertions. Conflict bucket written first, using the four real 006
pairs, zero synthesis:
- `dota2 5.5` vs `global 5.1.19.4.1` (media fines)
- `cs2 4.8` vs `global 5.1.12` (publisher bans)
- agreement case: `dota2 1.4.1.1` ≡ `global 5.1.2.1`
- express-primacy `global 3.2.3` — both the B6 failing shape AND a rephrased passing variant, both
  pinned
- the A16 cs2-3.2.3 / global-3.2.3 number-collision guard (`conflict-a16-number-collision`)

**`eval/run.py` NEW** — mechanical checks only, no LLM judge (justified: gpt-4o-mini judging
gpt-4o-mini is weak evidence). 13 cases `generate: true`, 12 retrieval-only/offline free.
- `must_pass` is assertion-level and gates the exit code; must hold in **every** run (N=2 default);
  invariant checks, never exact-string matches.
- `known_fail` tracked with a `finding` pointer into `logs/`; reported CONFIRMED / NOW-PASSING;
  never blocks the gate.
- Exit semantics 0/1/2, negative-tested live: corrupted pin → 1; impossible retrieval assertion →
  1; real set → 0; `--max-usd 0.001` → 2 with zero generation spend.
- `--retrieval-only` free (~$0.0002). Generation gated behind a printed tiktoken estimate +
  `--max-usd` (default 0.50).
- Auto-checks on every generated answer: citations-supported (reuses `graph.py` machinery); hedge
  detector keyed on excerpt text with class-level attribution (006 ruling 3 design — corpus
  contains 44 "usually" / 12 "generally" / 8 "typically" / 2 "commonly" chunks, so a flat regex
  would fail faithful answers); verbatim-run ≤25 words (justified: load-bearing quotes ~15 words;
  measured violations 28–115).

## What was verified

**Builder's final run:** conflict 6/6, cross-scope 7/7, normal 11/11, pipeline 1/1, pins 30/30,
exit 0.

**Builder's known_fails, CONFIRMED:**
- B6 — all three probes with `global 3.2.3` at rank 1.
- B4 — precedence statement absent on both pairs.
- B5 — travel padding 3/3.
- **B7 — on 5 of 13 generative cases** (104w / 105w / 71w / 60w / 28w verbatim runs — fires well
  beyond the original B2 fixture).

**Builder's surprises, honestly reported:**
- B4's citation half **NOW PASSES 3/3 both pairs** (006 measured 0/2) — the builder itself
  attributed this to its own question wordings inviting dual coverage, before the verifier ruled
  on it.
- B5's disavowal half did not reproduce.
- One spontaneous correct precedence statement observed (`dota2 1.4.2` vs `global 5.1.4`) — first
  live precedence statement since 006, proving the prompt's three-part test CAN fire.
- Hedge detector caught a paraphrase edge ("usually" → "generally").

**Verifier's independent run (ewc-verifier — VERDICT: PASS — stage S4):**
- Negative gate tests re-run via `--queries` on scratchpad copies (tree untouched): corrupted pin
  exit 1; impossible assertion exit 1; budget refusal exit 2 with $0 chat spend; empty selection
  exit 2. `--retrieval-only` exit 0 at $0.0002 measured.
- Full harness run: **tallies IDENTICAL to the builder's** — 6/6, 7/7, 11/11, 1/1, 30/30, exit 0.
  Cost $0.0255 measured.
- Stability probe: 8 riskiest generative `must_pass` cases at `--runs 3` → all held 3/3, $0.0240;
  riskiest musts now have ≥5 clean samples across sessions.
- Offline pins re-derived independently: fresh `chunk_corpus()` → 2381 docs, **all 25 per-book
  chunk/distinct-article pins match exactly, 0 mismatches**; sha256/bytes/Chroma pins match
  reality.
- Unit probes: faithful quoted "usually" NOT flagged; model-voice "typically" flagged; a 26-word
  run fails, 25 passes, punctuation/case-insensitive; `parse_citations` round-trips multi-citation
  parentheticals.
- B6/A16 retrieval geometry confirmed: `global 3.2.3` rank 1; cs2+global 3.2.3 co-retrieved ranks
  2/3.
- Withhold-branch/abstention interaction unit-tested: a withheld message does NOT satisfy the
  abstention `require_any` — cannot masquerade as a pass.

**known_fail cross-check (verifier vs builder):**
- B4 CONFIRMED 2/2 both pairs; B4 citation half NOW PASSING 2/2 (corroborated).
- B5 CONFIRMED 2/2, disavowal NOW PASSING.
- B7 CONFIRMED on the SAME 5 cases with near-identical run lengths (104/105/71/45/28w vs
  builder's 104/105/71/60/28w).
- **B6 DIVERGED: all three probes NOW PASSING 2/2 in the verifier's run vs the builder's
  CONFIRMED — B6 is SAMPLING-SENSITIVE/INTERMITTENT, not fixed.** The harness handled the flip
  correctly: non-blocking, NOTICE printed.

**Scope/store checks:** `chunks.pkl` sha256 `215c1862…` and Chroma 2381 unchanged at exit;
`graph.py` mtime predates the 007 log — untouched by the S4 builder; `CLAUDE.md` mtime matches
the human's #1 amendment only; only `eval/` written in the S4 window; no `articles.py`/`resolve`/
UI added; no CDN URLs/secrets/absolute paths in `eval/`.

## Checks not run

- No LLM-judge pass over generated answers — ruled the right call at this stage (see verifier
  ruling 1), but it means factually-inverted paraphrases with correct citations, numeric
  substitution on non-pinned facts, and mis-scoped prose attribution are NOT mechanically caught.
- `must_pass` stability attested by only 3 runs/case (the verifier's stability probe), not
  exhaustively re-run across the full 25-case set at N=3.
- `route_expect` asserted only at the retrieval phase; generation re-routes independently and this
  divergence is not checked (coverage: 2 cases total).
- `articles.py` and `resolve` — still zero coverage, unchanged since S3 began.
- pubg-mobile 13.6 cross-reference fixture — not encoded this iteration.
- A2 (seed) still unfixed — worked around via N-runs, not resolved.

## Findings

### Advisory (none blocking)

- **A-S4-1 (highest priority) — `conflict-a16-number-collision` (queries.yaml:229-251) passes
  VACUOUSLY on a non-answer.** Forbid-only assertion; unit-probed — a pure abstention passes the
  whole case. The pinned behaviour could regress to abstention undetected. One-line fix: add
  `require_citation` for cs2 3.2.3 (p.17). **The only material non-disclosure by the builder.**
- **A-S4-2 — hedge auto-check is pool-level, looser than "class-level."** "commonly" anywhere in
  any excerpt excuses "typically" in the answer; `global 2.2.1` (contains "usually"+"typically")
  is retrieved for most roster questions, so non-negotiable #4's no-softening rule is only weakly
  gated exactly where hedging is most likely. Disclosed by the builder; sentence-level check
  deferred to S5+.
- **A-S4-3 — `route_expect` asserted once (retrieval phase) but generation runs re-route
  independently;** a flaky router would silently change what the abstention checks measure.
  Coverage thin (2 cases).
- **A-S4-4 — `known_fail` is self-declaring with no ratchet.** Any assertion can be demoted by
  writing `status: known_fail` + free-text `finding`; nothing ties it to a human deferral; a
  consistently-passing known_fail (B4 citation half, 5/5 across sessions) stays non-blocking until
  manually promoted. **Process control adopted: the verifier must diff `queries.yaml` status
  fields on every future stage.** The global `verbatim_max_run` known_fail must flip to
  `must_pass` when S5 closes B7.
- **A-S4-5 — offline pins cannot run standalone** (`--bucket regression` → "no cases selected" →
  exit 2). Cosmetic.
- **A-S4-6 — housekeeping:** `.env` gained `LANGSMITH_*` variables during the S4 window
  (gitignored, no violation, recorded); `Result.ok` returns `True` on empty runs list (`all([])`)
  — unreachable currently, latent vacuity.
- **Slug-keys ruling: the distinction HOLDS** — per-book pin keys are expected data compared
  against runtime-derived values, not routing logic; CLAUDE.md's "don't hardcode the slug list"
  targets routing/ingest logic, which remains derived.

## Verifier rulings

1. **No-LLM-judge — RIGHT CALL at this stage.** What mechanical checks CANNOT catch, concretely: a
   factually inverted paraphrase with correct citations (e.g. "may NOT earn Points even if the
   majority is retained" would pass every check on the express-primacy cases); numeric
   substitution on facts not require-pinned; mis-scoped prose attribution. Mitigation is real:
   main fixtures pin the load-bearing numbers (4,000 / five years / 1% / 10/8/1.5/12/100% / three
   players). `run.py`'s docstring claim "every behaviour under test is mechanically checkable" is
   **OVERBROAD** — the enumerated invariants are, full faithfulness is not. Revisit with
   human-checked goldens at S5+.
2. **25-word verbatim threshold — JUSTIFIED as a tripwire, not as a definition of non-negotiable
   #6.** Catches transcription (the B7 defect); a ≤25-word unmarked run can still violate #6.
   Keep.
3. **N=2 — defensible but thin; recommend N=3 default.** A 30%-flaky behaviour slips both runs
   with p≈0.49; N=3 → ≈0.34 at ~$0.012 more per full run. B6's flip shows N=2 can also mislabel a
   deferred defect as NOW PASSING. Not blocking (`--runs` exists, documented, 5 clean samples
   accumulated).
4. **Missing pubg-mobile 13.6 — acceptable gap, should-add** (unique surface: a title book
   cross-referencing Global by section number; one retrieval-only + forbid case at next touch).
5. **Question-wording neutrality — MIXED; one wording flatters.** `conflict-media-fines` is
   natural. `conflict-publisher-bans` ("How are publisher bans AND VAC bans handled…") enumerates
   both concepts and invites dual-book coverage — the builder's own attribution admits it. **The
   natural discriminating question — 006's "is a player with a 6-year-old VAC ban eligible?", where
   the two books give DIFFERENT answers — is NOT in the set. Add it at next touch.** Because the
   flattered assertions are `known_fail` (non-gating), the gate is NOT gamed; but "B4's citation
   half now passes" must NOT be read as pipeline improvement. Express-primacy pair (failing
   natural wording + passing rephrase, both pinned) is good design.
6. **Overall — FIT to be the regression gate CLAUDE.md demands**, with advisories fixed at next
   touch. Gate fails when it should, refuses to spend when it should, pins match independently
   re-derived reality, musts stable at N=3, known_fail cannot suppress a must_pass (per-assertion
   statuses; auto-checks gate everywhere; verified live and by unit probe).

## Contract deltas

**No new deltas this iteration.** All still-open deltas carried forward unchanged:

2. `\d{1,2}` narrows CLAUDE.md's stated `\d{1,3}` (which matches `70.000 USD`) — verifier
   recommends amending CLAUDE.md rather than reverting code. (004)
3. `[A-Z]` heading-regex guard relaxed under multi-level numbers: +8 genuine, 0 junk. (004)
4. The ">80% of Global chunks have a non-empty article number" gate is gameable as written — needs
   a distinct-article floor. (003)
5. A3 — structured-output constraint gap: `route` uses free-form `str` + post-validation, not
   `Literal`/Enum. (005)
6. CLAUDE.md line 150 — "manifest of 26 docs" contradicts the confirmed 25 PDFs;
   version/effective_date present-as-null for 24/25 documents. (S1)
7. CLAUDE.md line 26 — Global has no `/rulebooks/<slug>` detail page. (S1)
8. CLAUDE.md lines 35-36 — no `<noscript>` fallback exists; outcome holds, named mechanism does
   not. (S1)
9. CLAUDE.md line 22 — "annexed to the Global Rulebook" is textually false for the EA/ALGS apex
   document. (S1)
10. `fitz` vs `pymupdf` — code imports the modern canonical `pymupdf` name; not yet ruled a
    deviation. (S0)
11. B7's verbatim quoting in tension with CLAUDE.md's don't on redistributing Esports Foundation
    content. (007)

**Note: A11 remains RESOLVED** (closed at 007 — CLAUDE.md non-negotiable #1's express-Global-primacy
exception).

## Carry-forward

### API spend

| party | detail | cost |
|---|---|---|
| **builder** | `eval/queries.yaml` + `eval/run.py`, live probes | **≈ $0.037** |
| **verifier** | negative gate tests, full harness re-run, stability probe, pin re-derivation | **≈ $0.050** |
| | **ITERATION TOTAL** | **≈ $0.087** |

**Project total ≈ $0.264 of $5 (~5.3%).** Corpus embedded exactly once, never re-embedded.

### Corpus and index state — do NOT redo

`data/pdfs/` (25 PDFs) and `data/manifest.json` cached. Chroma `ewc_rulebooks` holds **2381**
vectors; `chunks.pkl` holds the same **2381** Documents, sha256 `215c1862…`, **1,938,007 bytes**,
unchanged by this iteration. Re-running `index.py` re-embeds the whole corpus at $0.006057 — do it
**only** when `chunker.py` changes. This S4 build touched `eval/` only and required no re-index.

### For S5 (`articles.py` + `resolve`) — S5 is BOTH a build AND the repair scope for B4/B5/B6/B7

- **Ruling 4 from 007, carried and still binding:** hand the answer prompt FACTS, not derivation
  instructions; the prompt must SHRINK — remove DEFAULT CASE, the three-part test, and
  COMPLETENESS, replaced by a rendered precedence/completeness note computed in `resolve`.
- **Group on `article_id`, NOT `article`** — A16 (cs2 3.2.3 vs global 3.2.3, same number,
  unrelated articles) is the live counterexample.
- **The B5 relevance judgement belongs in `resolve`**, not a sibling-padding heuristic in the
  prompt.
- **B6 is INTERMITTENT** (CONFIRMED in one session, NOW-PASSING in another, same probes) — S5 must
  fix the class (the excerpt-framing exemption in `silence_violations()` that makes any "the
  excerpts do not state X" phrasing unfalsifiable), not chase this particular repro.
- **At S5's eval touch:** add the 6-year-VAC discriminator case (006's natural conflict wording,
  currently missing per ruling 5); add the pubg-mobile 13.6 case; fix A-S4-1 (require_citation on
  the A16 case so it can't pass vacuously on abstention); consider `--runs 3` default; flip
  `verbatim_max_run` from `known_fail` to `must_pass` when B7 closes.
- **Verifier process control, adopted this iteration:** diff `queries.yaml` status fields every
  stage, to catch any known_fail demotion that isn't a genuine human-authorized deferral.
- **Still open, unresolved:** mlbb's Global-copy at `authority=1` ruling; apex/ALGS authority
  ruling; OW2 corpus hole; A2 (seed); A5 (`index_stats.json` absolute paths); A6 (still not a git
  repo); honor-of-kings +6 printed-page offset; UA contact placeholder (`you@example.com`).

### Housekeeping

- Builder's honest self-reporting is noted for the record: it attributed the B4-citation-half
  surprise to its own question wordings **before** the verifier ruled on it — the verifier's
  ruling 5 subsequently confirmed and generalized that same concern (question-wording neutrality
  is mixed; the natural discriminating conflict case is still missing from the set).

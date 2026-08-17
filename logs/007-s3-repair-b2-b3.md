# Iteration 007 — S3 repair (B2 + B3)

- **Date:** 2026-08-13
- **Kind:** repair
- **Verdict:** FAIL
- **Next action:** **HALT FOR HUMAN INPUT.** The verifier's ruling 4 is now confirmed by live
  measurement (both prompt-only remedies shipped in the tree still dropped 2.8.3 on attempt 1 of
  4/4 B2 runs today) — further prompt clauses on this answer prompt are counter-productive. B5's,
  B6's, and B7's real fixes (a relevance judgement, a computed precedence/completeness fact, and a
  SHRINKING prompt) belong in `resolve`, which is **S5 scope**, out of bounds for this repair.
  CLAUDE.md's own build order additionally puts **S4 (`eval/`) before S5**. The human must choose
  the path: authorise S5 early, hold for S4 first, or something else.

> **B2 and B3, the two authorised targets of this repair, are GENUINELY FIXED and independently
> verified** — see *What was verified*. **The FAIL is entirely on new machinery this repair
> introduced** (B5, B6, B7) — the same shape as the 005→006 repair, where fixing B1 introduced
> B2/B3. B4 remains unmet, per human ruling, deferred to S5.
>
> **This iteration also corrects log 006 in place — the FOURTH verifier self-correction in this
> series** (A18 in 004, ruling 5 in 005, the precedence retraction in 006, and this one). The
> builder disputed the verifier's own B2 finding from 006 and the verifier **conceded**: two of
> three sub-claims were wrong, reasoned from an internally inconsistent original entry. See §B
> below and the annotations now embedded in `logs/006-s3-repair-b1.md`.

## What was built

**Human rulings received before this pass (not built by the builder — recorded here for the
record):**
- **B4 deferred to S5** — `resolve` is judged its right home.
- **CLAUDE.md non-negotiable #1 AMENDED by the human** — an express-Global-primacy exception was
  added: the confirmed case is `global 3.2.3` (p.17), which states precedence *"even if the
  respective game title rulebook allows bigger changes."* The logger's own diff check (not
  editing CLAUDE.md — confirming, per write boundary) shows exactly **6 lines added**, nothing
  else in CLAUDE.md changed. **This resolves A11.**

**Builder — `graph.py` the only file touched. Scope: B2 + B3 only.**

- **B3 fixed mechanically, as the verifier's 006 instruction required (checkable from `docs`
  metadata, not by prompt):** new `books_in_evidence()` computes which books are actually in the
  context window from `docs` metadata; new `silence_violations()` flags a sentence claiming a book
  that IS in evidence says nothing. Citations are stripped before the check runs. The DEFAULT CASE
  silent-title sentence (the source of B3) was **removed**.
- **B2 — builder reports two prompt-only remedies were tried and FAILED before going structural:**
  1. A COMPLETENESS clause — **4/4 failure** (still dropped 2.8.3 on attempt 1).
  2. A computed excerpt-index hoisted above the excerpts — **8/8 failure**.
  Only then did the builder add `unused_sibling_articles()` — a structural check, not a prompt
  clause.
- **Amendment implementation** — the minimal edit for the human's CLAUDE.md #1 exception: the
  prompt's blanket line *"Never write that the Global Rulebook governs over a title rulebook"*
  became *"...unless a Global excerpt's own text expressly says that it does."* One line changed.
- Builder spend ≈ **$0.053**.
- **Builder disputed the verifier's own 006 B2 finding.** See §B — the dispute was substantially
  upheld.

No re-index. `chunker.py`, `index.py`, `ingest.py` untouched. No `articles.py`, no `eval/`, no
`resolve`/`grade` node.

## What was verified

All numbers below were **measured** by `ewc-verifier`, independently re-derived from the
builder's claims. Spend: **$0.02685** (25 live runs, 138,474 tokens in / 10,126 out). **No
re-embed.**

**The three authorised fixes — GENUINELY FIXED and independently verified:**

- **B2 fixture 4/4** — list starts at item 1; 10-minute warning present; 1 pt / 5 min to **max 8**;
  1.5 pts / 2 min to 15 min, **max 12** (this cap was **omitted from the original task brief** and
  the verifier caught it anyway); `2.8.3` repeat-offender **+100% from match 3, cited**; `2.8.4`
  forfeit present. All verified against the CS2 PDF p.11/p.12. **0 orphan citations in 25 runs.**
- **B3 repro 3/3** — no false silence claim; `global 2.2.1` and `2.2.2` used **substantively**,
  including TA approval and *"without undue delay"* — **the exact rules dropped at 006**.
- **B1 regression 3/3** — still fixed (carried check, re-run).
- **Citation audit — 22/22 clean.** 22 distinct locators across the 25 runs; article present on
  the cited page 22/22.
- **Leakage — clean.** Valorant asked for CS2 map-veto rules → **0 cs2 chunks retrieved**,
  refused.
- **Abstention — clean 4/4, 0 hedge words.**
- **Scope compliance — fully verified.** Only `graph.py` touched; `chunks.pkl` sha256
  `215c1862f59a8f1a…`, **1,938,007 bytes**, unchanged; Chroma **2381**, pickle **2381** — **no
  re-index**; A1/A2/A3 untouched; no `eval/`, no `articles.py`, no `resolve`/`grade` node added.

## Checks not run

- **`resolve` / `grade` still absent — zero coverage, unchanged since S3 began.**
- **BLOCKED, zero live coverage — must not be recorded as passing:** the sibling-disclosure branch
  (`graph.py:790-794`) and the withhold branch (`graph.py:796-803`). 0/25 runs reached either (0
  attempt-2 failures this iteration). Read-only code review only, never executed live.
- **Amendments layer (`articles.py`) — still zero coverage.**
- **Still no `eval/` harness** — all evidence remains hand-run probes.
- **Determinism still not pinned** (A2, no `seed`) — carried, unchanged.
- **Builder's offline test files still do not exist in the tree** — same gap as 006; claims about
  them remain unverifiable as stated. The verifier re-derived behaviour independently instead.

## Findings

### BLOCKING — all three introduced by this repair's new machinery

**B5 — the sibling check systematically pads compliance answers with irrelevant articles. Fires
on 17/18 substantive answers (94%).** `graph.py:457-481`.

- `--game rocket-league` — *"How many players are on a Rocket League team?"* → **3/3** forced in
  `2.2.3 Roster Eligibility`, `2.2.4 Substitute Rules`, and **`2.2.2 Travel & Accommodation
  Coverage`** — a team-size question returns a hotel-coverage paragraph every run.
- Club Championship Points question → **2/2** forced in `3.2.1` and `3.2.5`, after which **the
  model itself wrote that they are irrelevant**: *"these two articles do not directly address the
  specific question."* The check compels content the answer then disavows.
- **Cost:** 22 sibling flags across 25 runs; **17/18 substantive answers cost 2 LLM calls** (≈2×
  spend), 4.6–14.1s latency.
- Builder called it "mild padding on one probe"; the verifier measured **7/7 non-ladder questions
  padded**.

**B6 — a false gap claim passes the silence check by using the permitted excerpt-framing. 2/2, on
the express-primacy article.** `graph.py:408-431`.

- `--game cs2` — *"If a team makes more roster changes than allowed, can it still earn Club
  Championship Points?"* → **global 3.2.3 retrieved at RANK 1**, yet **both runs** answer *"The
  retrieved excerpts do not state whether..."* — **false**; the rank-1 excerpt states the
  governing condition.
- **Not a corpus hole:** rephrased, the same pipeline answers correctly **2/2**, with the full
  3.2.3 rule and the express-primacy clause.
- `silence_violations()` cannot see this because excerpt-framed sentences are deliberately
  exempted from the check. **Any false gap claim phrased "the retrieved excerpts do not state X"
  is unfalsifiable by this check.**
- **The verifier owns part of this.** Its own 006 repair instruction #2 specified only *"no
  assertion that a book does not state its own rules unless no excerpt from that book is in
  context"* — the builder implemented that faithfully; the instruction was under-specified.

**B7 — quoting has crossed from advisory (A12) into a non-negotiable #6 violation.**

- Longest unbroken verbatim run in the B2 answer vs. the source chunk: **115 words from cs2
  2.8.4** (54% of a 212-word article), plus 32 words from 2.8.2 and 35 from 2.8.3, **all
  unmarked** — reads as paraphrase while being transcription.
- **Driver identified:** the COMPLETENESS clause plus the sibling correction's instruction "keep
  everything you already had."
- Also touches CLAUDE.md's don't on redistributing Esports Foundation content (rulebook text is
  copied, not paraphrased).

### B4 status (not failed, per human ruling — deferred to S5)

- Still unmet. **0/25 answers contain a precedence statement.** One probe co-retrieved
  `cs2 3.2.3` AND `global 3.2.3` and stated neither governs.

### Advisory

- **A13 (HIGH) — `silence_violations()` has a reproducible false-positive class that can WITHHOLD
  a correct answer.** `_SUBJECT_WINDOW = 60` flags any silence phrase within 60 chars after a book
  alias, regardless of subject. **3 of 6** adversarial compound sentences flagged, including the
  most natural partial-gap disclosure there is: *"Under the EWC Global Rulebook 2026 emergency
  substitutes need TA approval, but the excerpts do not state a notification deadline."* **The
  prompt's own SILENCE clause instructs the model to write that phrasing.** Compound path: 2 of 6
  natural phrasings of the SKIPPED_SIBLINGS remedy also trip it, so the sibling check's own
  correction can push a correct answer into the withhold branch. **0/25 live** — latent, not yet
  observed — but it destroys correct output when it fires.
- **A14 — the builder's "0 post-check rejections / 0 false positives across 26 live runs" claim is
  FALSIFIED as a general claim.** The verifier measured rejections in **17/25** runs. The claim
  holds **only** for the citation post-check (0 unsupported, 22/22 verified). The two NEW checks
  (sibling, silence) rejected 25 times combined.
- **A15 — the builder's "the DEFAULT CASE clause was REMOVED rather than another clause added"
  claim is INACCURATE.** DEFAULT CASE is still present at `graph.py:518-522`; only the
  silent-title sentence went. Net, the prompt **GAINED** three sections (SILENCE, COMPLETENESS,
  FORM) and now stands at **8 sections / 770 words** — it **grew**, against the verifier's own 006
  ruling 4 (don't add another clause).
- **A16 — `cs2 3.2.3` (Global Valve Regional Standings slots) and `global 3.2.3` (Team Roster
  Integrity) are unrelated articles sharing a number, and are co-retrieved together.** The answer
  correctly ignored the collision this time — a #1 pass on a hard input — but this is **a loaded
  gun for S5: `resolve` grouping on article number alone would fabricate a conflict here.**
- **A17 — answers open lowercase** (*"the retrieved excerpts do not state…"*), an artifact of "No
  preamble." Cosmetic.
- **Carried unchanged:** A1, A2, A3, A5, A6, A7, A8, A10; honor-of-kings +6 printed-page offset;
  UA contact still `you@example.com`.

## Verifier rulings

1. *(Reserved slot — see §B below for the B2-dispute ruling, the primary ruling this iteration.)*
2. **Sibling depth rule — DO NOT adopt `depth>=3`; it does not address the evidence.** Measured:
   the Rocket League padding is produced **entirely by depth-3 siblings** (`2.2.1` cited →
   `2.2.2`/`2.2.3`/`2.2.4` flagged, all parent `2.2`), so `depth>=3` leaves it **completely
   untouched**. Depth-2 firing observed once in 25 runs. **The defect is that sibling-hood is a
   poor proxy for relevance, not that the depth is wrong.** Recommends: fire only when the answer
   already cites **two or more** siblings of that parent (a ladder demonstrably in use), or gate
   on retrieval rank; make the remedy default to a one-clause disclosure rather than "add what it
   says"; best fix — move the relevance judgement into `resolve`.
3. **"A skipped sibling ships with the omission disclosed rather than withholding" — CONSISTENT
   with non-negotiable #4, ENDORSED but UNVERIFIED.** #4 targets inference, not partiality; it
   requires a gap be stated, not that the answer be suppressed. Log 005 ruling 2 already held
   partial answers are not per se violations. Disclosure converts silent partiality into stated
   partiality. **Caveat: 0/25 reached this branch — reasoning endorsed, code path BLOCKED.**
4. **006 ruling 4 (prompt at its complexity ceiling) STRENGTHENED on live evidence.** The verifier
   did not take the builder's word: **both** prompt-only remedies are shipped in the current tree
   and the model **still dropped 2.8.3 on attempt 1 of 4/4 B2 runs today**. **For S5 `resolve`:**
   (a) hand the prompt FACTS, not derivation instructions, and make the prompt **shrink** — remove
   DEFAULT CASE, the three-part test, and COMPLETENESS, replacing them with a rendered
   precedence/completeness note; (b) `resolve` MUST group on `article_id`, not `article` — A16 is
   today's live counterexample; (c) the relevance judgement B5 gets wrong belongs in `resolve`
   too.
5. **A12 promoted to blocking as B7.**
6. **B1 uncited-enumeration — NOT REPRODUCED, ruled on principle:** a numbered list drawn from ONE
   article under a stem that CARRIES the citation satisfies non-negotiable #3; a citation
   appearing only on the last item with an uncited stem is a #3 defect. The shipped FORM clause
   already mandates the safe form.

## §B — Correction to log 006 (the FOURTH verifier self-correction)

**The verifier CONCEDES the B2 dispute — the builder was substantially right.** Rulings on the
four sub-claims of 006's B2 finding:

| 006's original B2 sub-claim | 007 ruling |
|---|---|
| "all of cs2 2.8.2 is lost" | **WRONG, retracted.** |
| "jumps straight to list item 2 / item 1 never exists" | **WRONG, retracted.** |
| "citation printed on its own line with no rule text attached" | **retracted as a content finding; accepted as a layout reading.** |
| "all of cs2 2.8.3 is lost — repeat offender, +100%, rank 1, no gap stated" | **CORRECT, confirmed live today.** |

**Why the verifier ruled against itself:** 006's own text is **internally inconsistent** — it
states the answer printed `(Counter-Strike 2 — Article 2.8.2, p.11)`, which means 2.8.2 WAS being
cited, while simultaneously claiming all of 2.8.2 was lost. Both cannot be true. The builder's
explanation (2/4 baseline runs put the citation on its own indented line under its list item,
attached to the preceding paragraph but visually detached) reconciles the recorded evidence
better. **The verifier over-read a formatting artifact as content loss and propagated it into a
claim about item numbering.** It could not re-run the pre-repair prompt without modifying source
(forbidden), so it does **not** claim independent proof of the original 0/4 — it ruled on the
internal inconsistency, which is its own stronger evidence, and explicitly **declined to hide
behind run-to-run variance** (A2, no seed).

**The half it got right is the half that mattered, and it is confirmed today:** across 4/4 B2
runs, `unused_sibling_articles` fired on attempt 1 with exactly `Counter-Strike 2 Article 2.8.3 —
Repeated lateness (p.11)`.

**Note for the record:** the builder disputed the orphan-citation symptom yet shipped a FORM
clause forbidding standalone citations — both moves were correct; **0 orphan citations in 25
runs**.

**Correction applied:** `logs/006-s3-repair-b1.md` has been edited **in place** — the retracted
parts of the B2 finding are struck through and annotated `> **RETRACTED (see 007):** …` inline,
the original text is preserved (not deleted), and a summary blockquote is added near the top of
the entry. **This is the FOURTH verifier self-correction in this project** (A18 in 004; ruling 5
in 005; the precedence retraction in 006; B2 now). The log is deliberately self-revising.

## API spend

| party | detail | cost |
|---|---|---|
| **builder** | `graph.py` edits, live probes | **≈ $0.053** |
| **verifier** | 25 live runs, 138,474 in / 10,126 out | **$0.02685** |
| | **ITERATION TOTAL** | **≈ $0.080** |

**Project total ≈ $0.177 of $5 (~3.5%).** Corpus embedded exactly once, never re-embedded. Store
still 2381 vectors / 2381 pickled Documents.

**Separately:** this iteration's verification was interrupted once by the user's **Claude**
monthly spend limit (unrelated to the OpenAI budget tracked above) and was resumed from
transcript.

## Contract deltas

**CLAUDE.md is the source of truth and only the human may amend it. The logger has not touched
it.**

**RESOLVED this iteration:**

1. **A11 — CLOSED.** CLAUDE.md non-negotiable #1 was **AMENDED by the human** with an
   express-Global-primacy exception (confirmed case: `global 3.2.3`, p.17, *"even if the
   respective game title rulebook allows bigger changes"*). Diff-verified: **exactly 6 lines
   added**, nothing else in CLAUDE.md changed. **This is the first contract delta in this project
   to be closed.**

**Still open — carried forward unresolved:**

2. **`\d{1,2}` narrows CLAUDE.md's stated `\d{1,3}`**, and `\d{1,3}` **matches `70.000 USD`**.
   Verifier recommends amending CLAUDE.md rather than reverting the code. (004 delta 1.)
3. **The `[A-Z]` heading-regex guard is relaxed** under multi-level numbers: +8 genuine articles,
   0 junk. (004 delta 2.)
4. **The ">80% of Global chunks have a non-empty article number" gate is gameable as written** —
   needs a distinct-article floor. (003 delta 1.)
5. **A3 — structured-output constraint gap.** `route` uses a free-form `str` constrained by
   post-validation, not `Literal`/Enum as CLAUDE.md's LangGraph contract describes. (005 delta 1.)
6. **CLAUDE.md line 150** — "manifest of 26 docs" contradicts the confirmed 25 PDFs (OW2 ships a
   Google Doc); `version`/`effective_date` present-as-null for 24/25 documents. (S1 deltas 1–2.)
7. **CLAUDE.md line 26** — Global has no `/rulebooks/<slug>` detail page; true for the 25 titles,
   false for Global. (S1 delta 3.)
8. **CLAUDE.md lines 35-36** — there is no `<noscript>` fallback; the outcome the spec wants holds,
   the mechanism it names does not. (S1 delta 4.)
9. **CLAUDE.md line 22** — "annexed to the Global Rulebook" is textually false for the EA/ALGS
   apex document. (S1.)
10. **`fitz` vs `pymupdf`** — code imports the modern canonical `pymupdf` name. Not yet ruled a
    deviation. (S0 delta 1.)
11. **NEW — B7's verbatim quoting tension with CLAUDE.md's don't on redistributing Esports
    Foundation content.** 115 unmarked verbatim words from cs2 2.8.4 (54% of the article) plus 32
    and 35 words from 2.8.2/2.8.3 read as transcription, not paraphrase, in tension with both
    non-negotiable #6 and the redistribution don't.

## Carry-forward

### OPEN QUESTIONS FOR THE HUMAN — the loop is HALTED on these

1. **Does S5 scope reopen now?** Ruling 4 is confirmed by live measurement: further prompt clauses
   on the answer prompt are counter-productive. B5/B6/B7's real fix (relevance judgement +
   precedence fact + a shrinking prompt) is S5 (`resolve`) work.
2. **CLAUDE.md's build order puts S4 (`eval/`) before S5.** Does the human want S4 first (per the
   spec's own order), or authorise S5 early given the live evidence that the answer prompt is at
   its ceiling?
3. Still open from earlier: **apex/ALGS authority ruling** (since S1); **mlbb's 17-chunk Global
   copy at `authority=1`**, which outranks Global under #1; **OW2 corpus hole**.

### Corpus and index state — do NOT redo

`data/pdfs/` (25 PDFs) and `data/manifest.json` cached. Chroma `ewc_rulebooks` holds **2381**
vectors; `chunks.pkl` holds the same **2381** Documents, sha256 `215c1862f59a8f1a…`, **1,938,007
bytes**, unchanged by this repair. Re-running `index.py` re-embeds the whole corpus at $0.006057 —
do it **only** when `chunker.py` changes. **This repair touched `graph.py` only and required no
re-index.**

### For S4 (`eval/`) — carried and new

- The four real conflict/agreement fixtures from 006: `dota2 5.5` vs `global 5.1.19.4.1` (media
  fines); `cs2 4.8` vs `global 5.1.12` (publisher bans); `dota2 1.4.1.1` verbatim-identical to
  `global 5.1.2.1`; `pubg-mobile 13.6` cross-reference. **Synthesis is NOT needed.**
- **Hedge-detector constraint:** 44 "usually" / 12 "generally" / 8 "typically" / 2 "commonly"
  corpus chunks — key on excerpt text, not a flat regex.
- **B2 fixture, INCLUDING the max-12 cap** (the original task brief omitted it; the verifier caught
  it independently).
- **The lateness-abstention fixture** (general scope + lateness question must abstain — Global has
  no punctuality rule).
- **A2 — pin `seed`.**
- **The both-directions tokenizer fixture** (`"Article 5.1.19"` win vs `"Article 3.2"`
  regression).
- **Per-book chunk + distinct-article regression fixture.**
- **NEW — a verbatim-run-length check for B7** (flag unmarked runs above some word threshold
  against source chunk text).
- **NEW — a padding check for B5** (flag answers that cite ≥2 siblings of a parent article the
  question did not ask about).

### For S5 (`articles.py` + `resolve`)

- Ruling 4's three design constraints: hand the prompt **facts**, not derivation instructions;
  group on **`article_id`**, not `article` — A16 is the live counterexample; move the **relevance
  judgement** (B5's defect) into `resolve`.
- **mlbb's Global-copy at `authority=1`** — human ruling still needed.
- **apex/ALGS ruling** — still open.
- **OW2 corpus hole** — still open.
- **B4** — precedence statement generation, deferred here per human ruling.

### Housekeeping

- **Builder's offline test files (`test_postcheck.py`, `test_withhold.py` and equivalents) still
  do not exist in the tree** — same gap as 006. Claimed pass rates remain unverifiable as stated;
  the verifier keeps re-deriving behaviour independently instead.
- A1 (chroma/pickle drift unguarded), A5 (`index_stats.json` absolute paths), A6 (still not a git
  repo), honor-of-kings +6 page offset, UA contact `you@example.com` — all carried unchanged, no
  new movement this iteration.

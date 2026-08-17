# Iteration 004 — S2 chunker (repair)

- **Date:** 2026-08-11
- **Kind:** repair
- **Verdict:** PASS
- **Next action:** advance to S3 (`index.py` + a bare retrieve-and-answer path)

> **⚠ PARTIALLY RETRACTED BY ITERATION 005 (2026-08-13).** **Ruling 5** ("thin bodies … found by
> BM25 and essentially never by dense") and its derived Carry-forward bullet are **WRONG** and
> have been struck in place below — dense retrieval finds them **14/14**. The "do NOT widen `k`"
> constraint from that ruling **still stands**. See `005-s3-index-graph.md`. Everything else in
> this entry is unaffected.

> This iteration CLOSES iteration 003's **B1** (22 articles' rule text deleted) and **B2**
> (12 articles served under a neighbouring article's number and page). Both were re-tested
> against the PDFs, not against the builder's report. The Global coverage gate was held
> **exactly unchanged** at **158/159 = 99.37107%, 141 distinct articles** — the repair bought
> back deleted rule text and fixed citations without moving the gate at all.

## What was built

- `chunker.py` — **884 → 1033 lines** (growth is mostly docstring/comment recording the
  measurement that justifies each change). **Only file modified.** Five edits:
  1. `_NUM` / `RE_NUMBER_ONLY` sub-level component narrowed `\d{1,4}` → **`\d{1,2}`**.
  2. New `RE_ONLY_PARENTHETICAL` — rejects candidates whose heading is nothing but a
     parenthetical.
  3. `_plausible_heading_text` split into `_heading_shape` + the `[A-Z]` guard; new
     `_plausible_subarticle_text` (relaxes `[A-Z]` for **MULTI-LEVEL numbers only**) and new
     `_wraps_previous_line`.
  4. `enforce_sequence` — restores multi-level candidates **after** the LIS contest.
  5. New `_rescue_thin_segments` + a retention branch in `chunk_document`.

Nothing else was touched. `CLAUDE.md`, `logs/`, `ingest.py` untouched. No S3–S6 file created,
no OpenAI call attempted, no secret / URL / absolute path introduced. Verifier confirmed scope
compliance directly.

### B1 approach — the builder REJECTED the verifier's suggested heuristic

003's fix direction was a word-count / terminal-punctuation test (≥6 words, or ends `.`/`;`/`:`).
The builder rejected it because it would **not** have recovered
`honor-of-kings 7.6 "Compliance Obligations; Illegal Activity"` (4 words, no terminal
punctuation).

Chosen instead: **keep a thin segment exactly when no emitted descendant will repeat its
heading.** A bodyless *parent's* heading survives verbatim inside every child's `heading_path`,
so dropping it costs nothing; a thin *leaf* has nothing to carry it. **No word-count constant
was introduced.** Kept chunks get the heading promoted into the body, so the text is searchable
rather than metadata-only.

Measured: **447 thin segments** (body < 20 chars) → **43 kept / 404 dropped**.

### B2 approach — narrow, not a rewrite

- **B2(a):** the builder did **not** rewrite the LIS (003's verifier had judged it the right
  *global* algorithm). It restores multi-level candidates after the contest, having removed the
  two junk classes **at source**: prize amounts killed by `\d{1,2}`; the parenthetical killed by
  `RE_ONLY_PARENTHETICAL`.
- **B2(b):** the `[A-Z]` guard was **not deleted** — it still applies to single-level numbers,
  and is relaxed only under a multi-level number, paid for by `_wraps_previous_line`. The
  builder introduced and then fixed one new false positive itself
  (`ea-sports-fc 4.2.5.1 "of the Official Rules;"`, a line-wrap tail on p.2).

## What was verified

Everything below was **executed** by `ewc-verifier`.

**Headline numbers — all re-derived independently, all MATCHED:**

| metric | value |
|---|---|
| total chunks | **2381** |
| with an article | **2344 = 98.446%** |
| **Global gate** | **158/159 = 99.37107%**, **141 distinct — UNCHANGED from pre-repair** |
| split pieces / oversized segments | **427 / 173** |
| metadata violations | **0** |
| article-less chunks | **37** |
| duplicate `chunk_id`s | **0** |
| max body | **1200** chars |
| chunk-0 heading found literally on its recorded page | **2096 / 2096, 0 misses** |
| determinism | 3 runs identical, hash **`5c710095d60d0ac0`** |

**B1 — FIXED.** 447 thin segments, 43 kept / 404 dropped.
**The 404 boundary claim survives testing: 0 of the 404 lack an emitted descendant.**
Full-corpus absence sweep: **0 rule texts still missing.** All **22** originally-named articles
recovered. mlbb 6.2 **and** 6.2.1 / 6.2.2 / 6.2.3 / 6.2.4 all present at p.28;
honor-of-kings 7.6 present at p.24. Zero empty bodies, zero missing labels, zero thin
article-less chunks introduced.

**B2 — FIXED, verified against the PDFs (opened with PyMuPDF), not against the report:**

- lol **2.5.9** "Replacement Tiebreakers" p.6 ✓
- lol **2.5.10** "Replacement deadline" p.7 ✓ (was cited 2.5.1 p.6 — wrong on both fields)
- lol **5.10.5** printed **TWICE** on p.19 ("Terminal Situation" and "Remakes After GOR") —
  **both now exist with distinct ids** ✓
- mlbb-women **2.7** "Country Restrictions" p.11 ✓
- dota2 **7.2.3** "1v1 Tiebreakers" p.32 ✓
- mlbb **9.1.2–9.1.8** p.50 ✓
- warzone `8.1 (Behavior).` **still correctly rejected**, still inside `warzone:2.5:0`'s body,
  **no warzone 8.1 chunk exists** ✓ (003 already ruled this a non-loss)

**`\d{1,2}` claim verified exactly:** **24** three-digit-component candidates corpus-wide,
**all 24 are prize amounts** (`70.000 USD`), **zero genuine headings**. Emitted articles:
**1943 at component width 1, 401 at width 2, ZERO at 3+**.

**`[A-Z]` relaxation measured end-to-end by the verifier itself:**
strict **2088** → naive relaxation **+10 (2 junk)** → multi-level-only **+9 (1 junk)** →
**shipped +8, all 8 genuine, 0 junk.** `_wraps_previous_line` removes **exactly ONE line
corpus-wide** (the ea-sports-fc false positive) and nothing genuine.
Post-narrowing the LIS rejects **exactly 4** dotted candidates, **all 4 genuine, all restored,
zero junk restored.**

**Regression hunt — NONE FOUND.** The verifier reconstructed the pre-repair build
(**2335 / 2298 / 431** — matches 003's record exactly) and diffed against the repaired build:
**0 articles lost, 0 pages changed, 0 baseline body lines unaccounted for.** apex letter-prefixed
articles (**37**) and global `5.1.19.3.1` intact.

**Chroma re-run:** **2381/2381 loaded, no `None` crash.** Scope filters:
`{"$or":[{"game":"valorant"},{"scope":"global"}]}` → **264 docs, zero cs2 leakage**;
`{"scope":{"$in":["global","amendment"]}}` → **159**.

**Advisory findings from 003 confirmed still untouched, by execution not by reading:**
A10 still mis-nested (`chunker.py cs2` prints no GATE line, exits 0); A11 still present;
A12's slug literal now at **`chunker.py:1022-1023`**; A4 still uncorrected (the verifier watched
`- 7 -` land in honor-of-kings 4.3's body live); A9's tuned constants still unpinned, still no
test directory.

## Checks not run

- **No S3+ behaviour was verified** — `index.py`, `graph.py`, `articles.py`, `eval/` still do
  not exist. Retrieval-time leakage, precedence resolution, abstention and end-to-end citation
  rendering remain unverified at the *system* level; only their chunk-level prerequisites are
  green.
- **Still no `OPENAI_API_KEY`.** Unchanged S0 blocker. S2 never needed one; **S3 cannot be
  verified without it and will return BLOCKED.**
- **Still not a git repository.** `.gitignore` correctness remains proxy-tested only, unchanged
  since S0.
- **A10's `return 1` branch still never executed** — Global passes and the verifier again
  declined to modify source to force it. Carried over from 003 unchanged.
- **The `article_key` `ValueError` guard** — still not exercised.
- **Determinism hashes are not comparable across iterations.** The builder's own hash
  (`137471cf8f9bf0c7`) comes from a different function than the verifier's
  (`5c710095d60d0ac0`); 003's `36d9404b172e173e` is not a target either, since the repair
  legitimately moves the chunk set.

## Findings

**No blocking findings. All findings below are ADVISORY.**

### Verifier rulings on the repair

1. **The builder's rejection of the verifier's own suggested B1 heuristic was CORRECT — and
   more so than the builder claimed.** The verifier's word-count/punctuation heuristic would
   have missed **14 of the 43** kept segments, not just honor-of-kings 7.6 — including the
   entire mlbb 11.2.1.x penalty schedule (`Fine(s)`, `Suspension(s)`, `Match Forfeiture(s)`).
   The builder's alternative is sound but has a **constructible failure mode the verifier built
   and confirmed in code** — see A16. **Zero instances today.**
2. **`\d{1,2}` — SAFE, and it repairs a latent flaw in CLAUDE.md itself.** See Contract deltas.
3. **`[A-Z]` relaxation — the multi-level restriction genuinely eliminates the junk**
   (measured, not assumed). But **`_wraps_previous_line` is correct today and fragile**: it
   accepts mlbb 9.1.2–9.1.8 only because each predecessor line ends in `;`. **A list punctuated
   with `,` — common in legal drafting — would be rejected wholesale.** Add to A9's fixture set.
4. **The 3 label-only chunks kept** — `cod-mw3 3.2.2.1 "Example Bracket"`,
   `trackmania 4 "Schedule"`, `mlbb-women 4 "Schedule"` — are the **right trade**. Correctly
   cited, harmless, and the alternative re-deletes honor-of-kings 7.6.
5. ~~**6–8 char bodies (`drugs;`, `Fine(s)`, `alcohol;`) — REAL S3 RISK.** `alcohol;` is a
   near-null dense vector; only the context label carries signal. **These will be found by BM25
   and essentially never by dense retrieval. Flag for S3 hybrid weighting; do NOT "fix" by
   widening `k`** — CLAUDE.md forbids papering over a retrieval failure with a wider `k`.~~

   > **RETRACTED (see 005) — the dense-retrieval prediction above is WRONG.** The verifier has
   > retracted its own ruling. Measured at S3 against the built index: `mlbb:9.1.4` (`alcohol;`)
   > ranks **5** dense on a natural question, **1** on the bare word "alcohol", **2** on another
   > phrasing, and **5** even at k=100. Across **all 14** thin-body chunks queried by their own
   > heading+body: **dense top-12 hit 14/14, BM25 14/14.**
   > **Mechanism missed here:** CLAUDE.md's mandated context label
   > `[<game_title> · Article <n> — <heading>]` puts the heading into the **EMBEDDED TEXT**, and
   > for these chunks the heading **IS** the rule text — so the vector is not near-null. The
   > contract's label requirement is doing exactly the job it was specified to do.
   > **STILL STANDS on its own merits:** the "do NOT widen `k`" constraint — CLAUDE.md forbids
   > papering over a retrieval failure that way. Only the dense prediction is retracted.
   > This is the **second** verifier self-correction in this log series (A18 below was the first).
6. **The 2 segments still dropped — ACCEPTABLE; the builder was over-cautious.** Both are
   CONTAINERS with emitted children — honor-of-kings 4.3 has 4.3.1–4.3.5, mlbb 4 has 4.1.x —
   not rule text. **Correctly dropped.**

### Advisory findings

- **A14 — record correction.** The builder's "20 of 25 books byte-for-byte unchanged" is
  **WRONG: it is 16 of 25.** **Nine** books changed: the 7 with chunk-count deltas plus
  **`dota2`** and **`fortnite`**, which changed *content* at equal count. An arithmetic error,
  not concealment — the builder discussed both books explicitly.
- **A15 — record correction.** `chunker.py:743-744` docstring is **stale**: it says
  "440 thin … 36 kept"; the actual figures are **447 / 43**.
- **A16 — the rescue heuristic drops a thin one-line rule that has a numbered child.**
  Constructible; the verifier built and confirmed it in code. **Zero instances today** — no
  dropped thin segment has an 8+-word sentence heading. Revisit if a re-uploaded PDF changes
  drafting style.
- **A17 (for S3) — `heading_path` is metadata-only, NOT in `page_content`.** **27** parent
  section titles exist in **no chunk text at all** (e.g. cs2 2.7 "Penalties and consequences of
  leaving the event", warzone 3 "Tournament Structure."). They are invisible to **dense AND
  BM25**. This is **not** a contract breach — the label format is exactly what CLAUDE.md
  specifies — but S3 must know.
- **A18 — the verifier is CORRECTING ITS OWN earlier finding.** 003's B2 enumeration of **12**
  mis-cited articles was **NOT exhaustive**. `MAX_HEADING_LEN = 90` *also* rejects
  **warzone 7.1 / 8.1 / 10.1 / 11.1 / 12.1, fortnite 8.5.1, mlbb Appendix-A 1.5 / 1.6**, each
  served under its **PARENT's number on the SAME page**. Milder than B2 proper (same page,
  parent number — versus B2's wrong article on a wrong page), **pre-existing and byte-identical
  in the reconstructed baseline**, so correctly **out of repair scope**. **A future reader must
  not treat 003's list of 12 as complete.**
- **A19 — `_wraps_previous_line` is load-bearing on a single data point.** See ruling 3.
- **A11 update** — chunks over 1200 chars *after* the context label: **228 → 227**;
  max **1258 → 1335**.

### Builder's own disclosed gaps (recorded for completeness)

- The builder's own sweep found **25** silently-deleted segments — a **superset** of the
  verifier's 22 — of which **23 recovered**. The **2** left are
  `honor-of-kings 4.3 "Owners"` (body is literally `- 7 -`, i.e. advisory A4's page-marker leak,
  out of scope) and `mlbb 4` (body `Names`, a wrapped tail of its own heading). The verifier
  ruled both **correctly dropped as containers** (ruling 6).
- The builder itself flagged the `\d{1,2}` narrowing as needing a **human ruling**.
- Bonus: `RE_ONLY_PARENTHETICAL` stopped fortnite's `1 (Victory Royale)` being eaten as a
  heading, **restoring the top row of its placement-points table**.
- `mlbb 9.1.8`'s heading is a line-wrap fragment — number and page are right, but the heading
  reads awkwardly in a citation. **Pre-existing class, not introduced by this repair.**
- The builder's determinism hash `137471cf8f9bf0c7` is computed by a different function than
  the verifier's and **is not comparable**.

## Contract deltas

**CLAUDE.md is the source of truth and only the human may amend it. The logger has not touched
it.**

**NEW in this iteration:**

1. **`\d{1,2}` narrows CLAUDE.md's stated `\d{1,3}` sub-level component — and the spec's own
   regex has a LATENT FLAW.** The verifier established that **`\d{1,3}` MATCHES `70.000 USD`**,
   i.e. CLAUDE.md's literal regex admits prize amounts as article numbers. Measured: **24
   three-digit-component candidates corpus-wide, all 24 prize amounts, zero genuine headings**;
   emitted articles are **1943 at width 1, 401 at width 2, zero at 3+**.
   **The verifier recommends AMENDING CLAUDE.md rather than reverting the code.**
   **Human ruling needed.**
2. **The `[A-Z]` relaxation deviates from CLAUDE.md's literal heading regex.** The guard is
   relaxed **only under a multi-level number**, paid for by `_wraps_previous_line`. Measured
   end-to-end: **+8 genuine articles, 0 junk** (strict 2088 → naive +10/2 junk → multi-level-only
   +9/1 junk → shipped +8/0 junk). This is the direct repair of 003's contract delta 2, which had
   recorded the guard's cost as 8 genuine articles rejected. **Human ruling needed on whether the
   spec regex should be amended.**

**Still open from earlier iterations — carried forward UNRESOLVED:**

3. **The ">80% of Global chunks have non-empty article numbers" gate is GAMEABLE as written**
   (003 delta 1). The literal spec regex scores Global 98.9% while producing an **11-article**
   corpus. **Recommend the human add a distinct-article floor to the gate.** Unchanged.
4. **CLAUDE.md line 150 — "manifest of 26 docs" contradicts the confirmed 25 PDFs** (OW2 ships a
   Google Doc); same line's `version`/`effective_date` expectation is present-as-null for 24/25
   documents. (S1 deltas 1–2.)
5. **CLAUDE.md line 26 — Global has no `/rulebooks/<slug>` detail page.** True for the 25 titles,
   false for Global. (S1 delta 3.)
6. **CLAUDE.md lines 35-36 — there is no `<noscript>` fallback.** The 25 links are ordinary
   server-rendered anchors; the outcome the spec wants holds, the mechanism it names does not.
   (S1 delta 4.)
7. **CLAUDE.md line 22 — "annexed to the Global Rulebook" is textually false for the EA/ALGS
   apex document.** (S1.)
8. **`fitz` vs `pymupdf`** — CLAUDE.md says "PyMuPDF (`fitz`)"; `chunker.py` imports `pymupdf`,
   the modern canonical name. **Until the human rules, this is NOT a deviation.** (S0 delta 1.)

**Also note (A18):** the verifier **corrected its own earlier finding** — 003's B2 enumeration of
12 mis-cited articles was not exhaustive. The additional cases are pre-existing and were
correctly left out of repair scope, but the record of 003 must not be read as complete.

## Carry-forward

**Corpus state — do NOT re-crawl.** `data/pdfs/` (25 PDFs) and `data/manifest.json` are cached
on disk and open cleanly. Read from disk. No destructive step has been run yet — `index.py`
(which drops the Chroma collection) still does not exist.

**For S3 (`index.py` + bare retrieve-and-answer):**

- **`OPENAI_API_KEY` blocker is UNCHANGED and now live.** No key, no `.env`. **S3 cannot be
  verified without it and will return BLOCKED.** `OPENAI_CHAT_MODEL` default (S0 A1) must be
  settled too.
- ~~**Ruling 5 — thin-body dense-retrieval risk.** 6–8 char bodies (`drugs;`, `Fine(s)`,
  `alcohol;`) are near-null dense vectors; only the context label carries signal. They will be
  found by **BM25 and essentially never by dense**. Weight the hybrid accordingly.~~
  **Do NOT widen `k`** — CLAUDE.md explicitly forbids papering over a retrieval failure that way.

  > **RETRACTED (see 005):** the struck text above is the carry-forward derived from ruling 5
  > and is retracted with it. Measured at S3: dense top-12 hit **14/14** thin-body chunks
  > (`mlbb:9.1.4` ranks 5 / 1 / 2 by phrasing, and 5 at k=100); BM25 14/14. The context label
  > puts the heading into the embedded text, so these vectors are not near-null. **No hybrid
  > re-weighting was needed and none should be applied on the strength of this bullet.**
  > The final sentence ("do NOT widen `k`") is **NOT** retracted — it stands on CLAUDE.md.
- **A17 — `heading_path` is metadata-only, not in `page_content`.** **27** parent section titles
  appear in no chunk text at all and are invisible to both retrievers.
- **A11 — 227 chunks exceed 1200 chars after the context label is prepended, max 1335.** Bodies
  are all ≤ 1200; the label is added after splitting. Relevant to S3 sizing.
- **A4 — honor-of-kings printed-page offset is +6** on 44/60 pages. Citations rendered `p.N`
  will name a page the reader cannot find in that book. Still uncorrected.
- **Chroma null-metadata risk stays CLOSED** — `NULL_SENTINEL = ""`; **2381/2381** chunks load
  with no `None` crash.
- **Routing needs (slug, game_title) PAIRS from the manifest**, not the bare slug list —
  `cod-mw3` is stale ("Call of Duty: Black Ops 7"). (S1.)
- **apex/ALGS precedence — HUMAN RULING STILL OPEN since S1.** The chunker leaves apex at
  `authority=1` with `external_host=True`; correct neutral default, not a decision.

**For S4 (`eval/`):**

- **A9 — the regression fixture MUST pin per-book chunk count AND distinct-article count**, and
  must now **also** pin **`\d{1,2}`** and **`_wraps_previous_line`** — specifically ruling 3's
  comma-punctuated-list fragility (a `,`-punctuated sub-article list would be rejected
  wholesale). The tuned constants still have zero coverage and `drop_table_of_contents` deletes
  lines outright, so drift removes a section silently. PDF URLs are content-hashed; re-uploads
  **will** happen.
- **`eval/queries.yaml` must carry a `cod-mw3`↔`warzone` case and an `mlbb`↔`mlbb-women` case**
  (S1). Valorant-vs-cs2 will never expose realistic leakage.

**For S5 (`articles.py` + `resolve`):**

- **A2 — `resolve` MUST group on `article_id`, not `article`.** 13 bare Global article numbers
  collide between the main body and Appendices I/II.
- **A3 — mlbb ships a 17-chunk COPY of the Global Rulebook at `authority=1`**
  (`Appendix B - EWC26 Global Rules`), sharing Global's numbering and outranking it under
  CLAUDE.md's precedence rule. **Human ruling needed before S5.**
- **OW2 corpus hole — open, for the human.** No Overwatch 2 rules exist in the corpus; every OW2
  question will abstain. S5 is the plausible fix.

**Housekeeping:**

- **Still not a git repository.** Run `git status` before any first commit — `data/` (~29 MiB of
  redistributable PDFs owned by the Esports Foundation) must never be staged.
- **A real UA contact is still unset** (`ingest.py:47` / `.env.example:24` carry
  `you@example.com`). Set it before any further crawling.
- **A10 and A12 are still live in `chunker.py`** (metadata violations only fail the build when
  `global` is in the run; slug literal now at `:1022-1023`). Not repair scope; not fixed.

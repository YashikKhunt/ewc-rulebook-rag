# Iteration 006 — S3 repair (B1 citation/precedence)

- **Date:** 2026-08-13
- **Kind:** repair
- **Verdict:** FAIL
- **Next action:** **HALT FOR HUMAN INPUT.** B2 and B3 are repairable inside `graph.py`, but the
  verifier's ruling 4 judges the answer prompt to be **at its complexity ceiling** and recommends
  the structural fix — `resolve` computing the Global-vs-title relation from metadata — which is
  **S5 scope**. The human must decide whether to reopen scope. Separately, **A11 needs a human
  ruling** (CLAUDE.md #1's one-directional precedence vs `global 3.2.3`, which asserts primacy in
  the forbidden direction) before B4 can be fixed correctly rather than fixed wrongly.

> **⚠ PARTIALLY RETRACTED BY ITERATION 007 (2026-08-13).** The **B2** finding below is
> **PARTIALLY WRONG**. The builder disputed it during the 007 repair and the verifier
> **conceded**: "all of cs2 2.8.2 is lost," "jumps straight to list item 2 / item 1 never
> exists," and "citation printed on its own line with no rule text attached" (as a *content*
> claim) are **retracted** — the verifier's own text was internally inconsistent (it recorded
> the answer citing `(Counter-Strike 2 — Article 2.8.2, p.11)`, which means 2.8.2 WAS being
> cited, while also claiming all of 2.8.2 was lost). The layout observation about the citation's
> own-line placement is **kept as a formatting reading**. **What STANDS, reproduced live again
> at 007: all of `cs2 2.8.3` — repeat offender, +100% from match 3, retrieved rank 1 — was
> genuinely dropped with no gap stated.** This is the **FOURTH** verifier self-correction in
> this log series. See `logs/007-s3-repair-b2-b3.md` §B and the annotations inline in the B2
> finding below.
>
> **B1 IS CLOSED — 5/5.** The specific defect from 005 (fabricated CS2 article 5.1.7.3 / 4.8 and a
> false CS2-precedence assertion) no longer reproduces at all. But the repair introduced **two new
> reproducible regressions (B2, B3)**, and the verifier found **two genuine conflicts in the corpus
> that the builder said did not exist (B4)**.
>
> **This iteration RETRACTS a finding from log 005.** 005 recorded *"Precedence — works, but
> non-deterministically"*. That is now **retracted in full** — see *Findings → Retraction of 005's
> precedence finding* and the correction note embedded in `logs/005-s3-index-graph.md`.
> This is the **THIRD verifier self-correction** in this log series (A18 in 004 was the first,
> ruling 5 in 005 the second). **The log is deliberately self-revising: never trust an earlier
> entry's finding without checking the later ones.**

## What was built

- `graph.py` — **only file modified** (mtime 12:15). Repair of B1 only.
  - New **`citation_for(meta)`** — one canonical citation string used by **both** `render()` and
    the post-check, so the two cannot drift. This also fixed a latent false-positive source:
    article-less chunks previously rendered `(Game — Article n/a, p.N)` while the prompt asked for
    `(Game — p.N)`.
  - New **`_normalise` / `allowed_citations` / `cited_locators` / `unsupported_citations`** — the
    mechanical post-check. Zero API cost; pure string comparison against the `citation=` lines
    already in the context window.
  - **SYSTEM prompt:** CITATION tightened; PRECEDENCE rewritten with a one-directional statement, a
    **per-rule** (not per-topic) three-part test, an agreement branch, and an explicit **DEFAULT
    CASE** for the silent-title situation; ABSTAIN reworded to name the rulebooks searched.
  - New **RECITE** prompt; **`answer()` node rewritten**: generate → check → one bounded retry →
    check → withhold.
  - `State` gains `citation_errors`; the CLI prints rejections to stderr.

**No re-index.** `chunker.py`, `index.py`, `ingest.py` all unchanged. No `articles.py`, no `eval/`,
no `resolve`/`grade` node. Nodes are still `route → retrieve → answer`.

**Builder's offline test files `test_postcheck.py` and `test_withhold.py` DO NOT EXIST in the
tree.** Correctly kept out of source, but their claimed **16/16** and **4/4** pass rates are
therefore **unverifiable as stated**. The verifier re-derived the behaviour independently instead.

## What was verified

All numbers below were **measured** by `ewc-verifier`. Every builder claim was independently
re-derived.

**Builder claims verified TRUE:**

| claim | verifier's measurement |
|---|---|
| only `graph.py` modified | **TRUE** — mtime 12:15; chunker/index/ingest unchanged |
| no re-index | `chunks.pkl` sha256 `215c1862…` **exact match**, **1,938,007 bytes** |
| store unchanged | Chroma **2381** vectors, pickle **2381** |
| A1/A2/A3 untouched | grep for `seed`/`corpus_hash`/`Literal`/`Enum` returns **nothing**; router still free-form `str` |
| A4/A5/A6 untouched | `index_stats.json` still holds `/Users/yashik/…`; still **not a git repo** |
| no S4–S6 scope creep | no `eval/`, no `articles.py`, nodes still `route→retrieve→answer` |
| no hardcoded CDN URL or slug list | **confirmed** |
| no secrets or absolute paths in any `.py` | **confirmed** |
| withhold bounded at 1 retry | clean = **1 call**; bad→good = **2 calls, answer kept**; bad→bad = **2 calls, withheld**; no docs = **0 calls**. **No loop, no silent rewriting.** Withheld text names scope + bad locators + valid locators |
| post-check false-positive rate | **0 across all 28 live runs** |

**B1 repro ×5 — PASS 5/5.**
Pool identical every run: `cs2: 6.9.1, 6.2, 4.8, 6.9.4, 2.7.1, 2.8.3 | global: 5.1.7.3, 5.1.15.3`.
All 5 attribute the sanction to the **EWC Global Rulebook 2026** and cite
`(EWC Global Rulebook 2026 — Article 5.1.7.3, p.25)` **alone**. Zero *"The Counter-Strike 2
rulebook governs here"*. Zero CS2-attributed 5.1.7.3 or 4.8 citations. Post-check clean 5/5.
PyMuPDF confirms 5.1.7.3 and the "normally 5 years" text are **both on Global PDF p.25**.
**The specific defect is closed.**

**ONE DEVIATION from the builder's report:** the builder claimed **3/5** runs additionally state
the CS2 book is silent. The verifier measures **0/5** — the shipped DEFAULT CASE instruction is
simply **not followed**. (See A9.)

**Citation audit — 12/12 clean.** Every cited `(game, article, page)` triple resolves in the actual
PDF; article present on the cited page **12/12**; body text **11/12** (tekken-8 5.2.3 lands on
p.11 — the known page-span convention from 005 ruling 6, **not new**).

**Leakage — clean 2/2.** `cod-mw3` asked for Warzone loadouts → **refused**, pool **100%
cod-mw3+global**. `mlbb-women` asked for men's MLBB roster rules → **refused**, pool **100%
mlbb-women+global**.

**Over-abstention — NO suppression found.** **7 of 8** covered questions answered substantively.
The single abstention ("grace period before forfeit", routed `None`) is **CORRECT**: the verifier
grepped **all 159 Global chunks** — **Global has no punctuality/lateness/grace-period rule at
all**; that rule lives only in title books (`cs2 2.8.4`). Note this is **CLAUDE.md's own example
command** and it abstains — a **routing-scope artifact, not a corpus hole**. Worth an S4 fixture
pinning it as expected. (See Contract deltas.)

## Checks not run

- **Builder's offline suites not executable** — `test_postcheck.py` and `test_withhold.py` are not
  in the tree. "16/16" and "4/4" are **unverified claims**; the verifier re-derived the behaviour
  by independent means rather than accepting them.
- **`resolve` / `grade` nodes still not built, therefore still unverified.** The full LangGraph
  contract node list is not implemented. The precedence-note mechanism has **zero coverage because
  it is absent** — precedence still lives entirely in the answer prompt, which is exactly what B3
  and B4 exploit.
- **Amendments layer (contract #2) still untestable** — no `articles.py`, no amendment chunks.
  **Zero coverage.**
- **Still no `eval/` harness.** All S3 evidence remains hand-run probes. Nothing regression-pins
  any of it.
- **Determinism still not pinned** (A2 unchanged, no `seed`) — which is precisely why the verifier
  ran every case **≥3×**.
- **Still not a git repository.** `.gitignore` correctness remains proxy-tested only. Unchanged
  since S0. (A6)
- **honor-of-kings +6 printed-page offset (S2 A4) still uncorrected and still un-retested.**

## Findings

### BLOCKING

**B2 — CS2 punctuality answer silently drops the entire lateness penalty ladder and prints an
orphan citation. Reproducible 4/4. REGRESSION introduced by this repair.**

> **RETRACTED IN PART (see 007) — the FOURTH verifier self-correction.** During the 007 repair
> the builder disputed this finding and the verifier **conceded the builder was substantially
> right**. Reason: this entry's own text is internally inconsistent — it states the answer
> printed `(Counter-Strike 2 — Article 2.8.2, p.11)` (meaning 2.8.2 WAS being cited) while also
> claiming all of 2.8.2 was lost. Both cannot be true. The builder's explanation (2/4 baseline
> runs put the citation on its own indented line under its list item — attached to the preceding
> paragraph, but visually detached) reconciles the evidence better; the verifier over-read a
> formatting artifact as content loss and propagated it into a claim about item numbering. The
> verifier could not re-run the pre-repair prompt without modifying source (forbidden), so it does
> not claim independent proof of the original 0/4 — it rules on this entry's internal
> inconsistency instead. **The half that mattered is confirmed live, unretracted: across 4/4 B2
> runs at 007, `unused_sibling_articles` fired on attempt 1 with exactly
> `Counter-Strike 2 Article 2.8.3 — Repeated lateness (p.11)`.**

- **Input:** `--game cs2` — *"What happens if a Counter-Strike 2 team is late to a match?"*
- **Behaviour 4/4:** the answer opens *"…the following rules apply:"* then
  ~~**jumps straight to list item "2."** — item 1 **never exists**~~ **RETRACTED (see above) —
  WRONG.** In **2 of 4** runs the citation `(Counter-Strike 2 — Article 2.8.2, p.11)` is printed
  ~~**on its own line with no rule text attached at all**~~ **RETRACTED as a content claim (see
  above); kept only as a layout/formatting reading** — attached to the preceding paragraph but
  visually detached; in the other 2 it appears in a trailing `Citations:` line for content that is
  not in the answer.
- **What is lost:** ~~all of `cs2 2.8.2` (**retrieved at rank 2**) — the warning at 10 min, 1
  penalty point per 5 min to a max of 8, then 1.5 points per 2 min until 15 min after start —
  **and**~~ **RETRACTED (see above) — WRONG, 2.8.2 was not lost** all of `cs2 2.8.3`
  (**retrieved at rank 1**) — repeat offender, +100% from match 3. **CONFIRMED — this half
  stands and was reproduced live again at 007 (4/4).** Both verified present in the PDF at p.11.
- **Contract:** 005 ruling 2 named this exact case — *"a partial answer is not per se a violation;
  what would violate is SILENT partiality on a forfeit rule"*. **The answer states no gap** (true
  of the confirmed 2.8.3 drop). The **"inverts #3: a citation with no claim attached"** reading is
  covered by the layout-vs-content caveat above.
- **Attribution:** retrieval is unchanged (same pool, tokenizer untouched) and log 005 recorded the
  **previous** prompt returning the **COMPLETE** ladder. The only variable is the **new SYSTEM
  prompt** — most likely its closing *"Be brief. No preamble…"* pulling against the much heavier
  prompt body.
- **The post-check passed it clean 4/4** — it cannot see a dropped claim.

**B3 — the new DEFAULT CASE paragraph produces a confidently FALSE claim about the corpus.
Reproducible 3/3. NEW, introduced by this repair.** — `graph.py:346-350`

- **Input:** `--game valorant` — *"What are the roster registration and substitute rules for a
  Valorant team?"*
- **Behaviour 3/3:** the answer closes with *"The EWC Global Rulebook 2026 does not state its own
  rules on roster registration and substitutes for Valorant teams."*
- **This is FALSE, and contradicted by three excerpts in its own context window:**
  `global 2.2.1` *Definition of the two Types of Substitutes* (p.12, **rank 7**);
  `global 2.2.2` *Requirements for Emergency Substitutes* (p.12, **rank 8**);
  `global 3.2.7` *Official Club Affiliation and Roster* (p.18, **rank 6**).
  Global 2.2.2 states Emergency Substitute participation *"always requires explicit approval from
  the TA"* and that emergencies must be reported *"without any undue delay"* — a real, **retrieved**,
  **dropped** rule.
- **The builder's "mirror-image fixed" claim is HALF TRUE:** the backwards precedence sentence is
  gone, replaced by a **false silence assertion in the opposite direction**. The builder's regex
  sweep (`Global Rulebook…govern`) **structurally cannot detect this** — it only searched for the
  word "govern".

**B4 — non-negotiable #1 is UNMET on both genuine conflict pairs in the corpus. 2/2 each.**

The repair traded B1's **over-assertion** of precedence for **total suppression** of it:
**zero of the verifier's 28 live answers contain any precedence statement**, including on the two
real conflicts.

1. **Media obligations — `dota2 5.5` (pp.24-25) vs `global 5.1.19.4.1` (p.31).** Both open with the
   **identical** sentence *"Not fulfilling media obligations will result in fines. Their range
   depends on the situation."* Global then leaves the range to TA discretion; Dota 2 supplies a
   **binding numeric schedule** ($4,000 + 5% for media day; $600/$800/$1,000/$1,200/$2,000 tiers for
   signing sessions; $360…$1,200 for press conferences). **`global 5.1.19.4.1` retrieved at rank
   4.** Both runs give the Dota 2 schedule alone and **never mention the Global Rulebook**.
   (Figures verified against the PDF — the answer is **factually perfect**; only the precedence
   statement is missing.)
2. **Publisher bans — `cs2 4.8` (p.21) vs `global 5.1.12` (p.27).** Global: the TO *"reserves the
   right to refuse"* publisher-banned players, **no time limit**, plus *"Any ESIC bans will be
   honored"*. CS2: VAC bans honoured *"but only for five (5) years"*. **A 6-year-old VAC ban
   resolves differently under each.** **`global 5.1.12` retrieved at rank 4.** Both runs give CS2
   alone, **no precedence statement**, and **drop the ESIC-ban rule entirely**.

**Not repair-introduced** — but now **demonstrable on real inputs**, and must not ship as-is.

### Retraction of 005's precedence finding — the verifier has retracted its own S3 finding

**005 recorded: "Precedence (#1) — works, but NON-DETERMINISTICALLY", citing LoL roster
replacement, MLBB sponsorship, and CS2 punctuality. THAT IS WRONG, and the verifier says so
explicitly.** The **builder challenged it, and the builder is right.**

Retrieval-only pool dumps at 006:

- **MLBB sponsorship — 8/8 title, 0 global. There is no Global chunk in the pool at all.**
- **CS2 punctuality — 7 title + 1 global**, but the single Global chunk is **`5.1.7.1` Cheat
  Software**, **unrelated to lateness**.
- **LoL roster replacement — 7 title + 1 global**, where `global 2.2.1` **is** on substitutes but
  states **complementary** rules (substitute *types*) against LoL's **procedural** rule (swap
  between games, 5-min notice) — **no divergence**.

**In none of the three was there a Global rule differing on the same point.** 005's *"Precedence —
works"* rested on assertions that were **unfounded in exactly the B1 way**. `logs/005-s3-index-graph.md`
has been annotated in place; the original text is preserved, not deleted.

**This is the THIRD verifier self-correction in the project** — A18 in 004, ruling 5 in 005, and
this one.

### Verifier's six rulings

1. **The builder's challenge to 005's precedence finding — THE BUILDER IS RIGHT; RETRACTED.**
   See the dedicated section above.
2. **"No genuine conflict in the corpus" — SUBSTANTIALLY RIGHT but OVERSTATED. S4 does NOT need to
   synthesise.** Independent scan of **166 exact-heading Global/title pairs**: **68 at ≥0.9
   similarity** (near-verbatim restatements — confirms the builder), **71 at <0.3** which are
   heading collisions on generic words ("general", "purpose", "feedback") over unrelated subject
   matter. **Zero numeric-divergent same-heading pairs.**
   **But the builder MISSED one and MISCLASSIFIED another:**
   - `dota2 5.5` vs `global 5.1.19.4.1` (media obligations) is **a genuine conflict the builder did
     not find** — the **best natural conflict fixture in the corpus**.
   - `cs2 4.8` vs `global 5.1.12` (publisher bans) is **NOT "complementary"** — CS2 imposes a
     five-year limit Global does not have, and converts discretion into a mandatory honouring rule.
   **Bonus for S4:** `global 3.2.3` *Team Roster Integrity* asserts Global primacy **explicitly** —
   *"even if the respective game title rulebook allows bigger changes"*. Good **agreement**
   fixtures too: `dota2 1.4.1.1` is **verbatim-identical** to `global 5.1.2.1`, and
   `pubg-mobile 13.6` **cross-references Global by section number** — these test that the model
   says *"they agree"* rather than inventing precedence.
   **S4's conflict bucket should use these four real pairs. No synthesis, no waiting for S5.**
3. **The dota2 "usually" — builder CORRECT, verified in the PDF** (dota2 p.8 Art. 1.4.2 verbatim:
   *"Repeat offences will usually be punished more severely than listed in the appropriate section
   of these rules."*). Quoting it does **not** violate #4, whose target is the model softening its
   **own** claim.
   **But the problem is far larger than the builder reported:** a corpus-wide scan finds **44
   chunks containing "usually", 12 "generally", 8 "typically", 2 "commonly"** — including
   `global 2.2.1`, which contains **both** "usually" and "typically" and is retrieved for **every**
   roster/substitute question. A live run produced a second instance (`lol 2.5.1`: "brackets will
   usually not be reseeded").
   **S4's hedge detector must NOT be a flat regex over the answer** — it must flag a hedge only when
   **not attributable to retrieved excerpt text**, or it will fail faithful answers en masse.
   **One genuine edge:** the dota2 answer **paraphrased** "repeat offences will usually incur more
   severe punishments" **in the model's own voice** before quoting it — a detector keyed on
   quotation marks alone would miss that, so **key it on the excerpt text instead**.
4. **The two reverted prompt revisions — the shipped version is LESS-TESTED, not better, and the
   reverted failures were an accurate fragility signal.** The verifier measures the silence sentence
   at **0/5** where wanted (builder claimed 3/5) and **firing in the wrong direction 3/3** on
   valorant (B3). Both reverted failures and both live defects (B2 elision, B3 false silence) are
   **the same class** — **this prompt is at its complexity ceiling and each added clause is
   displacing an existing one. The fix for B2/B3 is NOT another clause. It should be structural:
   `resolve` (S5) computing the Global-vs-title relation from metadata and handing the answer
   prompt a FACT, rather than the prompt re-deriving it on every call.**
5. **The post-check's blind spots — residual risk is HIGH; it is NOT acceptable to close the stage
   on the post-check alone.** Both blocking regressions (B2, B3) passed the post-check **clean**,
   and B4's missing precedence statements likewise. **It is a LOCATOR check, not a FAITHFULNESS
   check. B1 specifically is closed by the PROMPT, not by the post-check** — which has **not yet
   caught anything live**. Fine as defence-in-depth; **must not be credited as the fix.**
6. **`page_end` coupling — real, and the builder has the direction WRONG.**
   `_CITATION_SHAPE = ^.+? — (?:Article \S+?, )?p\.\d+$` is anchored on `\d+$`. A rendered `p.6-7`
   would **not be rejected** — it would **not be recognised as a citation at all**, so
   `cited_locators()` returns empty and `unsupported_citations()` returns `[]` for **everything**.
   **The post-check silently degrades to a NO-OP** rather than producing false positives.
   Verified: `(… — Article 9.1.4, p.50-51)` → **detected = 0**. **A silent no-op is far more
   dangerous than a noisy rejection.**

### Advisory findings

- **A7 — the post-check is shape-fragile in BOTH directions; it validates FORMAT and only
  incidentally CONTENT.**
  **9 of 16 fabricated citations pass undetected** — all the B1 defect in a different surface form:
  `(Counter-Strike 2 — Art. 5.1.7.3, p.25)`; `(Counter-Strike 2, Article 5.1.7.3, p.25)` (comma for
  em-dash); `page 25`; `pp. 25-26`; `P.25`; `[square brackets]`; no parentheses at all;
  `…, p.25, as amended)`. **Also invisible: an entirely UNCITED rule statement.**
  **5 of 10 correct attributions are spuriously flagged** — markdown bold
  `(**EWC Global Rulebook 2026** — …)` (very plausible for gpt-4o-mini, which bolds freely and did
  so in live runs), a trailing dot after the article number, comma-separated multi-citations (the
  prompt mandates `;`), and an abbreviated book name. **Each would burn a retry and could withhold
  a correct answer.**
  Correctly handled: prose parentheticals ignored **4/4**; nested `(Citation: (…))`, line-wrapping,
  `p. 25`, en-dash and `;`-separation all tolerated as claimed.
- **A8 — `_PARENTHETICAL` caps at 500 chars**, so a citation inside a long parenthetical is
  **invisible**. Same silent-no-op class as ruling 6.
- **A9 — the DEFAULT CASE "silent book" sentence is unreliable in BOTH fire rate and direction**
  (**0/5** where wanted, **3/3** where wrong). Covered by B3.
- **A10 — chess answer did not correct a false premise.** Asked for fourth place *"in Euros"*; the
  corpus states **$100,000** (verified, chess PDF p.12). The answer gave $100,000 with a correct
  citation but **never flagged that the rulebook is denominated in USD**. A compliance tool should
  **reject the premise**.
- **A11 — NEW. `global 3.2.3` is a documented COUNTEREXAMPLE to CLAUDE.md #1's one-directional
  precedence, and the new prompt now FORBIDS stating it.** `graph.py:326-328` says *"Never write
  that the Global Rulebook governs over a title rulebook."* But **Global 3.2.3 asserts primacy in
  exactly that direction, in its own text**, for Club Championship Points eligibility (*"even if the
  respective game title rulebook allows bigger changes"*). **A faithful answer is now prohibited.**
  **HUMAN RULING NEEDED — either CLAUDE.md #1 gains an exception, or the prompt does.** See Contract
  deltas.
- **A12 — quoting is drifting long.** B1 run 3 **block-quotes four full sentences** of 5.1.7.3;
  CLAUDE.md #6 says paraphrase and quote only load-bearing phrases. **Trending the wrong way as the
  prompt grows.**
- **Carried unchanged and still open:** **A1** (no corpus hash guarding chroma/pickle drift);
  **A2** (no `seed` — which is why the verifier ran everything ≥3×); **A3** (free-form router
  schema); **A4**; **A5**; **A6**; **honor-of-kings +6 page offset**.

## API spend

| party | detail | cost |
|---|---|---|
| **builder** | repair of `graph.py`, live probes | **≈ $0.028** |
| **verifier** | 28 live answers + 3 router calls, gpt-4o-mini, **76,311 in / 4,678 out**; query embeddings ~$0.00002 | **$0.0143** |
| | **ITERATION TOTAL** | **≈ $0.042** |

**No re-embed.** Verifier's spend is **under the $0.30 ceiling by 20×**.

**Project total so far ≈ $0.097** against the **$5** credit (~1.9%).
**The corpus was embedded EXACTLY ONCE** (at 005, 302,864 tokens, $0.006057) and has **never been
re-embedded**. Store still holds **2381** vectors at exit.

## Contract deltas

**CLAUDE.md is the source of truth and only the human may amend it. The logger has not touched it.**

**NEW in this iteration:**

1. **A11 — `global 3.2.3` contradicts CLAUDE.md non-negotiable #1's one-directional precedence, and
   `graph.py:326-328` now FORBIDS a faithful answer.** CLAUDE.md #1 says the **game-title rule
   governs**, full stop. But **Global 3.2.3** *Team Roster Integrity* asserts Global primacy in its
   own text — *"even if the respective game title rulebook allows bigger changes"* — for Club
   Championship Points eligibility. The repaired prompt's blanket instruction *"Never write that the
   Global Rulebook governs over a title rulebook"* therefore **prohibits the faithful answer**.
   **HUMAN RULING NEEDED: either CLAUDE.md #1 gains a documented exception for articles that assert
   their own primacy, or the prompt gains one. B4 cannot be fixed correctly until this is decided.**
2. **CLAUDE.md's own example command abstains on the lateness question — a routing-scope artifact
   worth documenting.** `python -m graph "question here"` at general scope routes lateness questions
   to `None`; the verifier grepped **all 159 Global chunks** and confirmed **Global has no
   punctuality / lateness / grace-period rule at all** — it lives only in title books (`cs2 2.8.4`).
   The abstention is therefore **CORRECT behaviour, not a corpus hole**, but it means the spec's
   headline example produces an abstention. **Worth an S4 fixture pinning it as expected.**

**Still open from earlier iterations — carried forward UNRESOLVED:**

3. **A3 — structured-output constraint gap.** CLAUDE.md's LangGraph contract says `route` "uses
   structured output **constrained to the known slug list**"; the implementation declares a
   free-form `str` and constrains by **post-validation**. Untouched by this repair (verified).
   **Human ruling: bless post-validation, or require `Literal`/Enum.** (005 delta 1.)
4. **`\d{1,2}` narrows CLAUDE.md's stated `\d{1,3}` sub-level component**, and the spec's own regex
   has a latent flaw: `\d{1,3}` **MATCHES `70.000 USD`**. 24 three-digit-component candidates
   corpus-wide, all 24 prize amounts, zero genuine headings. **Verifier recommends AMENDING
   CLAUDE.md rather than reverting the code. Human ruling needed.** (004 delta 1.)
5. **The `[A-Z]` guard is RELAXED under multi-level numbers**, deviating from CLAUDE.md's literal
   heading regex. Measured: **+8 genuine articles, 0 junk. Human ruling needed.** (004 delta 2.)
6. **The ">80% of Global chunks have non-empty article numbers" gate is GAMEABLE as written** — the
   literal spec regex scores Global 98.9% while producing an **11-article** corpus.
   **Recommend the human add a distinct-article floor.** (003 delta 1.)
7. **CLAUDE.md line 150 — "manifest of 26 docs" contradicts the confirmed 25 PDFs** (OW2 ships a
   Google Doc); the same line's `version`/`effective_date` expectation is present-as-null for
   **24/25** documents. (S1 deltas 1–2.)
8. **CLAUDE.md line 26 — Global has no `/rulebooks/<slug>` detail page.** True for the 25 titles,
   false for Global. (S1 delta 3.)
9. **CLAUDE.md lines 35-36 — there is no `<noscript>` fallback.** The 25 links are ordinary
   server-rendered anchors; the outcome the spec wants holds, the mechanism it names does not.
   (S1 delta 4.)
10. **CLAUDE.md line 22 — "annexed to the Global Rulebook" is textually false for the EA/ALGS apex
    document.** (S1.)
11. **`fitz` vs `pymupdf`** — CLAUDE.md says "PyMuPDF (`fitz`)"; the code imports `pymupdf`, the
    modern canonical name. **Until the human rules, this is NOT a deviation.** (S0 delta 1.)

**Record-keeping note:** the verifier **corrected its own prior finding** this iteration (005's
"Precedence — works", retracted above). This is the **THIRD** such self-correction — A18 in 004 was
the first, ruling 5 in 005 the second. **The log is self-revising by design: do not treat an earlier
entry's finding as final without checking later entries.**

## Carry-forward

### OPEN QUESTIONS FOR THE HUMAN — the loop is HALTED on these

1. **A11 / CLAUDE.md #1 vs `global 3.2.3`.** Does non-negotiable #1's one-directional precedence
   gain an exception for articles that assert their own primacy, or does the prompt?
   **B4 cannot be fixed correctly until this is answered.**
2. **Does S5 scope reopen now?** The verifier's ruling 4 says the answer prompt is at its complexity
   ceiling and that B2/B3 should be fixed **structurally** by `resolve` — which is S5. The builder
   was explicitly told **not** to add `resolve` without the human reopening scope.
3. Still open from earlier: **apex/ALGS authority ruling** (since S1); **mlbb's 17-chunk Global copy
   at `authority=1`** which **outranks** Global under #1; **OW2 corpus hole**.

### Corpus and index state — do NOT redo

`data/pdfs/` (25 PDFs) and `data/manifest.json` cached. **Chroma `ewc_rulebooks` holds 2381
vectors**; `chunks.pkl` holds the same 2381 Documents — sha256 `215c1862…`, **1,938,007 bytes**,
**unchanged by this repair**. Re-running `index.py` re-embeds the whole corpus at $0.006057 — do it
**only** when `chunker.py` changes. **The B2/B3 repair touches `graph.py` only and MUST NOT require
a re-index.**

### If the human authorises a further S3 repair — the verifier's instructions

1. **B2** — the answer must not emit a **citation without a claim**, and must not **silently drop a
   retrieved rule from a numbered list**. **Fixture:** `--game cs2` *"What happens if a
   Counter-Strike 2 team is late to a match?"* must contain the 10-minute warning, 1 pt / 5 min to
   max 8, 1.5 pts / 2 min, **and** the +100% repeat-offender rule.
2. **B3** — no assertion that any book *"does not state its own rules"* unless **no excerpt from
   that book is in context**. **This is checkable mechanically from `docs` metadata, NOT by
   prompt.**
3. **B4** — precedence must be stated on the two real conflict pairs. **Verifier recommends
   deferring to `resolve` (S5) rather than adding another prompt clause; A11 needs a human ruling
   first.**
4. **Do NOT touch A1–A6. Do NOT re-index. Do NOT add `resolve` without the human reopening scope.**

### For S4 (`eval/`)

- **Conflict bucket: use the FOUR REAL PAIRS the verifier found. SYNTHESIS IS NOT NEEDED.**
  - **Conflict:** `dota2 5.5` (pp.24-25) vs `global 5.1.19.4.1` (p.31) — media obligations; identical
    opening sentence, Global leaves the range to TA discretion, Dota 2 supplies a binding numeric
    schedule. **The best natural conflict fixture in the corpus.**
  - **Conflict:** `cs2 4.8` (p.21) vs `global 5.1.12` (p.27) — publisher bans; CS2's five-year VAC
    limit vs Global's unlimited discretion + mandatory ESIC honouring. **A 6-year-old VAC ban
    resolves differently under each.**
  - **Agreement:** `dota2 1.4.1.1` is **verbatim-identical** to `global 5.1.2.1`.
  - **Agreement:** `pubg-mobile 13.6` **cross-references Global by section number**.
  The two agreement fixtures test that the model says *"they agree"* rather than **inventing**
  precedence. Also useful: `global 3.2.3` asserts Global primacy explicitly (see A11).
- **Hedge-detector design constraint (ruling 3): do NOT use a flat regex over the answer.** The
  corpus contains **44 chunks with "usually", 12 "generally", 8 "typically", 2 "commonly"** —
  including `global 2.2.1`, which has **both** "usually" and "typically" and is retrieved for
  **every** roster/substitute question. **Key detection on the retrieved excerpt text**, flagging a
  hedge only when **not attributable** to an excerpt. **A quotation-mark-keyed detector is
  insufficient** — a live dota2 answer paraphrased the hedge in the model's own voice before quoting
  it.
- **B2 fixture** — CS2 lateness must contain the full ladder (see above). Supersedes and sharpens
  005 ruling 2's no-show-threshold fixture.
- **Lateness-abstention fixture** — general scope + lateness question **must abstain**, and that is
  **expected, not a bug** (Global has no punctuality rule; verified across all 159 Global chunks).
- **A2 — pin `seed`.** Temperature 0 is not deterministic; regression detection is impossible
  without it. Still unset.
- **Ruling 3 (005) — pin the tokenizer in BOTH directions.** The win (`"Article 5.1.19"` 0/12 →
  5/12, 5.1.19.1 at rank 1) **and** the regression (`"Article 3.2"` BM25 rank 1 → out of the top 6).
- **A9 — per-book regression fixture** pinning per-book chunk count AND distinct-article count, plus
  `\d{1,2}` and `_wraps_previous_line`.
- **`_wraps_previous_line` comma-list fragility (004 ruling 3)** — accepts mlbb 9.1.2–9.1.8 only
  because each predecessor line ends in `;`; a `,`-punctuated list would be rejected wholesale.
- **Leakage fixtures `cod-mw3`↔`warzone` and `mlbb`↔`mlbb-women` are REGRESSION GUARDS, not known
  bugs** — 0 leaks at 005 (24 pools, 8 probes) and 2/2 clean again at 006.

### For S5 (`articles.py` + `resolve`)

- **`resolve` should COMPUTE the Global-vs-title relation from metadata and hand the answer prompt a
  FACT** — do not make the prompt re-derive it per call. This is the verifier's recommended
  structural fix for B2/B3/B4 (ruling 4).
- **`resolve` MUST group on `article_id`, NOT `article`** — **192 non-unique `(game, article)` pairs**
  corpus-wide (e.g. `global 1.2` twice); `chunk_id` is unique 2381/2381.
- **mlbb ships a 17-chunk COPY of the Global Rulebook at `authority=1`** (`Appendix B - EWC26 Global
  Rules`), sharing Global's numbering and **outranking** it under #1. **Human ruling needed.**
- **apex/ALGS precedence — HUMAN RULING STILL OPEN since S1.**
- **OW2 corpus hole — open, for the human.**
- **Contract #2 (amendments supersede) has ZERO coverage today.**

### Housekeeping — post-check hardening (all NEW this iteration)

- **A7 — the post-check validates FORMAT, not CONTENT. 9 of 16 fabricated citations pass
  undetected; 5 of 10 correct attributions are spuriously flagged** (markdown bold, trailing dot,
  comma-separated multi-citations, abbreviated book name). Each false flag burns a retry and can
  **withhold a correct answer**.
- **Ruling 6 — SILENT NO-OP RISK.** `_CITATION_SHAPE` is anchored on `p\.\d+$`. If `page_end`
  rendering ever lands (`p.6-7`), the post-check does not reject — it **stops recognising citations
  entirely** and returns `[]` for everything. Verified: `(… — Article 9.1.4, p.50-51)` → detected 0.
  **The builder has the direction of this coupling wrong.**
- **A8 — `_PARENTHETICAL` caps at 500 chars**; a citation inside a longer parenthetical is invisible.
  Same silent-no-op class.
- **Ruling 5 — do NOT credit the post-check as the B1 fix.** B1 is closed by the **prompt**. The
  post-check has **not caught anything live** and passed both new blocking regressions clean.
- **A12 — quoting is drifting long** against CLAUDE.md #6.
- **A10 — the system does not reject false premises** (chess "in Euros" → answered in USD without
  flagging).
- **A1** — chroma/pickle drift still unguarded; write a corpus hash into both and assert at load.
- **A5** — `data/index_stats.json` still contains absolute personal paths (`/Users/yashik/…`).
- **A6** — still not a git repository. Run `git status` before any first commit; `data/` (~29 MiB of
  redistributable PDFs owned by the Esports Foundation) must never be staged.
- **S2 A4** — honor-of-kings printed-page offset is **+6** on 44/60 pages; rendered `p.N` citations
  name a page the reader cannot find. **Still uncorrected.**
- **A real UA contact is still unset** (`ingest.py:47` / `.env.example:24` carry `you@example.com`).

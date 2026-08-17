# Iteration 003 — S2 chunker

- **Date:** 2026-08-11
- **Kind:** build
- **Verdict:** FAIL — 2 blocking findings
- **Next action:** repair S2 (`chunker.py`) — repair scope is **B1 and B2 only**

> The coverage gate passed and every headline number survived independent re-derivation.
> This is a FAIL anyway: 22 articles' rule text is **deleted** from the corpus and 12 more are
> served under a **neighbouring article's number and page**. Both are direct hits on
> non-negotiables #3 (citation on every claim) and #4 (abstain over infer).

## What was built

- `chunker.py` — new. Builder reported 878 lines; **verifier measured 884** (record corrected).
  Eight named single-responsibility passes:
  `extract → strip_boilerplate → find_heading_candidates → drop_table_of_contents →
  enforce_sequence → _find_parts → segment → chunk`.
- Public API for S3: `load_manifest()`, `chunk_document(record)`,
  `chunk_corpus(manifest_path, games=None)`, `validate(docs)`, `coverage(docs)`,
  `REQUIRED_METADATA`, `NULL_SENTINEL`.
- CLI: `__main__` prints coverage; `--dump GAME ARTICLE`; positional args limit to a subset;
  exit 1 on gate failure or metadata violation.

No other module was written. `index.py`, `graph.py`, `articles.py`, `eval/`,
`data/amendments.json`, any Chroma store and any `.pkl` all remain **ABSENT** — confirmed by
the verifier. No OpenAI call was attempted.

**Builder's own run:** `python chunker.py` → exit 0. 2335 chunks, 2298 with an article (98.4%),
431 pieces from the oversized splitter, 0 metadata violations, Global Rulebook 99.4%
(141 distinct articles). Claimed GATE PASS.

**Builder's claimed deviations from CLAUDE.md's stated heading regex**, with reasons:
U+200B zero-width spaces in Google-Docs exports are not matched by `\s`; `{0,3}` caps at four
levels but Global reaches `5.1.19.3.1`; apex uses letter-prefixed appendix numbering (`A1.`,
`C6.4.`); the number/heading separator is not always whitespace. Builder claimed the baseline
regex fails the gate at Global 66.7% / 8 articles.

**Builder claimed four silent bugs found and fixed mid-build:** appendix labels leaking
backwards; a cs2 body sentence relabelling the rest of the book; split pieces inheriting the
segment start page; cod-mw3 map-veto text being deleted by over-eager contents detection.

## What was verified

Everything below was **executed** by `ewc-verifier`, not read.

**Headline numbers — all independently re-derived, all MATCHED:**

- total chunks **2335** ✓
- with an article **2298 = 98.42%** ✓
- **Global gate 158/159 = 99.371%** ✓ (builder's "99.4%" is a round of this)
- Global distinct `article_id` **141** (128 bare) ✓
- split pieces **431 from 175 oversized segments** (builder said 174 — record corrected) ✓
- metadata violations **0** ✓
- All 25 per-book percentages match to the decimal. **apex 93.79% lowest, mlbb 99.60% highest.**
- Denominator is sane: 159 Global chunks / 141 distinct `article_id` over pp. 2–50 — this is
  **not** the "few huge chunks inflate the percentage" failure mode.

**U+200B claim CONFIRMED and load-bearing.** `re.match(r"\s", "​")` → `False`.
Global contains **483** ZWSPs, cs2 **307**, apex **517**. Global p.17 raw text is literally
`3.2.3.<ZWSP>\nTeam Roster Integrity`. Five-level `5.1.19.3.1` and letter-prefixed `A1.` /
`C6.4.` verified present and correctly captured. (The builder's docstring overstates the
number-on-its-own-line case — Global also has 10 same-line headings.)

**Metadata, all 2335 chunks (not a sample):** 11 required keys present; **ONE** distinct 22-key
metadata keyset; **0** `None`; **0** non-scalar; all `page` ints ≥ 1; all `chunk_id` unique.

**Chroma load re-run:** 2335/2335 loaded with real metadata, **no `None` crash** — S1's A4 risk
is closed by `NULL_SENTINEL = ""`. Scope filters:
`{"$or":[{"game":"valorant"},{"scope":"global"}]}` → **264 docs, games {global, valorant},
ZERO cs2 leakage**; `{"scope":{"$in":["global","amendment"]}}` → **159, all global**.

**Context label:** all 2298 article-carrying chunks match `[<game_title> · Article <n> —
<heading>]` with title and heading equal to metadata. **37 article-less chunks (1.6%)** use the
extension `[<game_title> · <heading>]` — necessary and documented.

**Article-first splitting:** **1904/2335 (81.5%)** are whole unsplit article segments; the
recursive splitter fires only on the 175 oversized; max body **1200** chars, zero over.

**Metadata truth hand-checked against the PDFs:** **2048/2048** article-carrying chunk-0
headings found literally on their recorded page, **0 misses**. Individually opened and
confirmed: global 3.2.3 p.17, global 5.1.19.3.1 p.30, cs2 2.8.1 p.11, cs2 5.1 p.22,
valorant 5.5.1 p.11, apex A1 p.22, apex C6.4 p.31, mlbb 6.5.1 p.30.

**Determinism:** two full CLI runs byte-identical; a third in-process run hashes identically
(`36d9404b172e173e`).

**Scope / authority:** 159 global/0, 2176 title/1, **zero violations**. apex authority untouched
at 1 with `external_host=True` on all 161 apex chunks. `version`/`effective_date` = `""` on all
2176 title chunks, `v1.0` / `2026-01-01` on all 159 global; `supersedes=""` everywhere.

**Other:** `import pymupdf` at `:35`. Pages 1-based physical and plausible (global 2–50 of
51 pp, mlbb 1–77 of 77 pp). No dot-leader body loss. Hygiene: no CDN URL, no URL of any kind,
no API key, no secret, no absolute personal path.

## Checks not run

- **The `pct <= GLOBAL_COVERAGE_GATE → return 1` branch was never executed** — Global passes,
  and the verifier declined to modify source to force it. **A10 below is from reading
  `chunker.py:873-880`, not from running it.**
- **The `article_key` `ValueError` guard at `chunker.py:149`** — not exercised.
- **Not applicable at S2** (no retriever, no graph exists yet): cross-title leakage at
  *retrieval* time, precedence resolution, abstention behaviour, end-to-end citation rendering.
  The chunk-level prerequisites for these are green **except B2 and A2/A3**.
- **Still no `OPENAI_API_KEY`** — unchanged S0 blocker, lands at S3.
- **Still not a git repository** — `.gitignore` correctness remains proxy-tested only,
  unchanged since S0.

## Findings

### BLOCKING

**B1 — `chunker.py:689-692` — 22 articles' entire rule text is silently DELETED from the
corpus. The builder's disclosure #2 ("bodyless parent headings emit no chunk … deliberate, no
actual rule text is lost") is FALSE.**

Segments whose body is shorter than `MIN_BODY_CHARS` (20) are dropped. **440 segments** are
dropped this way. For **22 of them the heading IS the whole rule**, so nothing survives — the
text appears nowhere in any chunk body, `heading`, or `heading_path`. Verified by full-corpus
substring search: **1,437 characters of rule text gone.** Distribution: **18 mlbb, 2 warzone,
1 cod-mw3, 1 honor-of-kings.**

Sharpest instance — mlbb "Game of Record", PDF p.28. Article 6.2 lists four conditions
6.2.1–6.2.4. **The corpus contains 6.2 and 6.2.3 only**; 6.2.1, 6.2.2 and 6.2.4 are deleted
(each is a single line, body length 0).
*Failure scenario:* "When does an MLBB game become a Game of Record?" → retrieval returns 6.2
plus one of the four conditions, **correctly cited**. The system states one quarter of a rule as
the rule — a confidently incomplete compliance answer, **not** an abstention. **Non-negotiable
#4's safety valve does not fire**, because from the retriever's point of view nothing is
missing.

Also deleted: mlbb 6.7.2.1 / 6.7.2.2 (grounds for a pause), 7.6.5.5 / 7.6.5.7 (prohibited
conduct), 4.1.5, 7.6.2, 11.2.4, Appendix-A 1.3, 9.2.1; warzone 4.1 and 4.4; honor-of-kings 7.6
("Compliance Obligations; Illegal Activity" — the article becomes **invisible**).

*Fix direction from the verifier:* when a segment has no body, keep the chunk if the heading is
itself sentence-like (≥ 6 words, or ends `.` / `;` / `:`), or fold the heading text into the
child/parent body. Genuinely-empty parents ("Introduction.", "Format.", "Side Selection.") are
**correctly** dropped and should stay dropped.

**B2 — 12 articles are served under a NEIGHBOURING article's number and page. Direct hit on
non-negotiable #3.** Two causes, one symptom.

*(a) `enforce_sequence`, `chunker.py:425-456`* — 4 genuine multi-level articles lose the
longest-increasing-subsequence contest and merge into the **preceding** article, inheriting that
article's number **and page**:

| true article | heading | true page | served as | served page | chars |
|---|---|---|---|---|---|
| lol **2.5.9** | Replacement Tiebreakers | p.6 | 2.5.1 | p.6 | 449 |
| lol **2.5.10** | Replacement deadline | **p.7** | 2.5.1 | **p.6** | 440 |
| lol 5.10.5 | Remakes After GOR | p.19 | 5.10.5.1 | — | 368 |
| mlbb-women **2.7** | Country Restrictions | p.11 | 2.11.5 | — | 175 |

The builder's diagnosis of the *cause* is right — the lol PDF genuinely numbers 2.5.1, 2.5.9,
2.5.10, 2.5.4, 2.5.5 out of order and prints `5.10.5.` twice — but the *consequence* is worse
than the builder's "advisory / cited under the wrong number" framing: **chunk `lol:2.5.1:1`
contains NOTHING BUT Article 2.5.10's text** and is labelled
`[League of Legends · Article 2.5.1 — Replacements]`, `article=2.5.1`, `page=6`.
*Failure scenario:* "What is the LoL replacement deadline?" → citation
`(League of Legends — Article 2.5.1, p.6)` is **wrong on both fields**; a compliance reader who
opens p.6 at 2.5.1 finds a different rule.

The builder listed warzone `8.1 (Behavior).` as a similar loss — **it is not.** The filter
**correctly** rejects it; it is a mid-sentence cross-reference, not a heading.

*(b) the `[A-Z]` guard, `chunker.py:241-243`* — mlbb **9.1.2–9.1.8** are genuine
lowercase-initial articles (prohibited-sponsor list: `9.1.4 alcohol;`, `9.1.5 drugs;`,
`9.1.7 web3, cryptocurrency, NFT and Blockchain;`) and dota2 **7.2.3 "1v1 Tiebreakers"** starts
with a digit. All rejected, all served under 9.1.1 / 7.2.2. **The text survives; the citation
does not.**

*Verifier's repairability note:* both are fixable narrowly and at low risk. Every **other**
multi-level candidate the sequence filter rejects is either a prize amount (`7.500 USD`,
`27.500 USD` — 25 of them) or a parenthetical, both trivially distinguishable.

### ADVISORY (not repair scope unless the human says otherwise)

- **A1 — the builder's `[A-Z]`-guard evidence is factually wrong; correcting the record.**
  Builder claimed "exactly 25 extra headings, all table fragments, zero genuine lowercase
  headings". Measured: **38 extras, and 8 of them are genuine articles** (see B2b). The guard
  still earns its place — the other 30 are `1 year`, `24 teams`, `4 matches`, `alcohol;`
  fragments — **but it is not free.**
- **A2 — S5 `resolve` MUST group on `article_id`, not `article`. Collision claim CONFIRMED.**
  **13** bare article numbers in the Global Rulebook appear under two different parts:
  `1.2 … 3.1` in both the main body and *Appendix I – Protest Rules*, and `2` in both the main
  body and *Appendix II – Prize Money Splits*. Grouping on `article` would conflate a protest
  deadline with a definitions clause.
- **A3 — precedence hazard: mlbb ships a COPY of the Global Rulebook at `authority=1`.**
  `Appendix B - EWC26 Global Rules` → **17 mlbb chunks** (`1.1 Rule changes`,
  `1.2 EWC Global Rulebook`, `3 Misconduct`, `5 Privacy and Data Protection`, …), all
  `scope=title, authority=1`. Under CLAUDE.md's precedence rule these **outrank the real Global
  Rulebook chunks** and share its article numbering. **Needs a human ruling before S5.**
- **A4 — honor-of-kings citations point to the wrong PRINTED page.** Physical-vs-printed offset
  surveyed across all 25 books: **24 are 0 or unnumbered; honor-of-kings is +6 on 44/60 pages**
  (physical p.11 is printed "- 5 -"). The builder's "spot-confirmed against printed page
  numbers" holds for cs2 and global, **not here**. Related: hok's `- N -` markers leak into
  chunk bodies because `RE_BARE_NUMBER` (`chunker.py:101`) doesn't match `- 5 -` — that is 10 of
  the 21 body-page misses.
- **A5 — disclosure #3 is benign, but the builder's stated MECHANISM is WRONG.** Verifier
  reproduced **2304/2335 (98.67%)** exact and **2314/2335 (99.10%)** within ±1 exactly. The
  cause is **not** "multi-column/table reflow": the heading sits at the bottom of page N and the
  body starts on N+1 (verified on hok 4.1.8, 6.3, 9.2, 11.1 — body found on p+1 in every case).
  `page` = heading page is the right choice and `page_end` captures the remainder.
  **This is not a wrong page.** A future reader must not inherit the reflow explanation.
- **A6 — disclosure #4 (chess loses 86 vocabulary words) CONFIRMED; the builder's judgement is
  CORRECT.** The builder explicitly asked the verifier to check this. Verifier opened the chess
  PDF: contents (pp.3–4) advertises `6.1 Sanctions … 6.20 Code of conduct`; the body (p.11)
  reads `6. Misconduct / 6.1 Punctuality Penalties / 6.1.1 Player punctuality`. A scan for
  `\b6\.\d{1,2}\b` across all 14 pages hits only pp. 3, 4 and 11 — **6.2–6.20 do not exist in
  the body.** The contents page is stale relative to the body. **Following the body is right.**
- **A7 — disclosure #6 (apex 93.79%) CONFIRMED, and `C6.3` is NOT a chunker miss.** The 10
  article-less apex chunks are the title page and 6 genuinely unnumbered appendix preambles
  including the eligible-countries table — all 10 read. **No `C6.3.` heading exists anywhere in
  apex's extracted text**; the string occurs only in cross-references, and its point table on
  p.31 is attributed to C6.2. **Source/extraction gap, not a chunker defect.**
- **A8 — disclosure #7 (the four self-fixed bugs) CONFIRMED FIXED.** cod-mw3's map veto is
  present and correct: `5.3.1 Map Veto Process in Bo5 matches` (p.12) and `5.3.2 … Bo7` (p.13)
  with sub-articles; both `"team a bans one map"` and `"team b bans one map"` present in output.
  Contents/body collision traced directly on dota2: p.4 contents entries for 2.8 / 2.9 / 2.9.1 /
  2.10 flagged and deleted, p.15 / p.16 body headings kept. Appendix labels do not leak
  backwards.
- **A9 — disclosure #5 (threshold fragility) is the real maintainability risk; the verifier
  AGREES S4 must pin it.** `TOC_RUN_MIN = 5` (`:51`), `dotted < 0.6 * len(head_run)` (`:381`),
  `hits >= 0.35 * len(head_run)` (`:386`) are fitted to today's 25 PDFs with **zero regression
  coverage**. Critically, **the `dead` set in `drop_table_of_contents` DELETES lines from the
  text stream** — so a threshold miss does not degrade a citation, it removes a section from the
  corpus outright. That is exactly how cod-mw3's map veto vanished pre-fix. Since PDF URLs are
  content-hashed and re-uploads are expected, **this will drift.** **S4 must pin per-book chunk
  count and distinct-article count as a regression fixture.**
- **A10 — `chunker.py:873-880` — metadata violations only fail the build when `global` is in the
  run.** The `return 1` for `problems` is nested inside `if "global" in stats`. `python
  chunker.py cs2` with violations exits **0**. Move the check out of the `global` branch.
  (Found by reading, not by execution — see *Checks not run*.)
- **A11 — 228 of 2335 chunks exceed 1200 chars AFTER the context label is prepended** (max
  **1258**, `global:1.11.2:0`). Bodies are all ≤ 1200 (`:704` splits before `:718` prepends).
  Harmless for embedding today; **worth knowing before S3 sizing.**
- **A12 — one slug literal:** `chunker.py:873-874` keys the gate on `stats["global"]`. It is the
  CLAUDE.md-named document rather than a game-slug list, so **not** the automatic FAIL the
  contract targets — but `scope == "global"` derives it cleanly.
- **A13 — handoff record corrections:** **884 lines, not 878; 175 oversized segments, not 174.**

### Complexity judgement (builder disclosure #8: "878 lines is large")

**JUSTIFIED, with one caveat.** 884 lines is defensible against 25 independent publishers, four
distinct heading conventions (same-line, number-on-own-line, run-in sentence, letter-prefixed
appendix), Google-Docs ZWSP exports, and contents pages mirroring body numbering. The module is
8 named single-responsibility passes, each independently callable — the verifier instrumented
each in isolation to trace defects, which is the practical maintainability test, and it passed.
The LIS approach in `enforce_sequence` is the right *global* algorithm, not a pile of special
cases. **The overfit risk is not the line count, it is the six untested tuned constants (A9).**

## Contract deltas

**CLAUDE.md is the source of truth and only the human may amend it. The logger has not touched
it.**

1. **NEW — CLAUDE.md's ">80% of chunks in the Global Rulebook have non-empty article numbers"
   gate (build order step 2) is GAMEABLE as written.** The verifier ran the baseline regex two
   ways:
   - as a **drop-in inside chunker.py's pipeline** (keeping the TOC detection and sequence
     enforcement) it reproduced the builder's numbers exactly: Global **66.7% / 8 articles**,
     cs2 98.3% / 2, apex 32.2% / 2, ea-sports-fc 73.3% / 1, warzone 48.1% / 5,
     pubg-mobile 80.9% / 14;
   - as a **faithful standalone reading of CLAUDE.md's spec** (literal regex, <100 line guard,
     require a following body, article-first split, **no** TOC detection, **no** sequence
     enforcement — neither of which appears in CLAUDE.md), **Global scores 98.9% with 11
     distinct articles**, and cs2 98.3% with **1** article.

   So read literally, **the baseline regex PASSES the >80% gate while producing an 11-article
   corpus.** The builder's deviation is still clearly justified — 11 vs 141 articles on Global,
   1 vs 97 on cs2 — **but the justification is the ARTICLE COUNT, not the percentage.** The
   builder's framing of this claim is wrong and should not be inherited.
   **Recommend the human add a distinct-article floor to the gate.**

2. **NEW — the `[A-Z]` guard in CLAUDE.md's stated heading regex has a real, measured cost.**
   It demonstrably rejects **8 genuine articles**: mlbb 9.1.2–9.1.8 (a lowercase-initial
   prohibited-sponsor list) and dota2 7.2.3 (starts with a digit). The guard is still worth
   keeping — it also rejects 30 table fragments — but the spec presents it as free and it is
   not. **The human should know before the regex is treated as settled.**

**Still open from earlier iterations — carried forward unresolved:**

3. **CLAUDE.md line 150 — "manifest of 26 docs" contradicts the confirmed site fact of 25
   PDFs** (OW2 ships a Google Doc), and the same line's `version`/`effective_date` expectation
   is present-as-null for 24/25 documents. (S1 deltas 1 and 2.)
4. **CLAUDE.md line 26 — Global has no `/rulebooks/<slug>` detail page.** True for the 25
   titles, false for Global. (S1 delta 3.)
5. **CLAUDE.md lines 35-36 — there is no `<noscript>` fallback.** The 25 links are ordinary
   server-rendered anchors; the outcome the spec wants holds, the mechanism it names does not.
   (S1 delta 4.)
6. **CLAUDE.md line 22 — "annexed to the Global Rulebook" is textually false for the EA/ALGS
   apex document** (zero occurrences of "Esports World Cup", "EWC" or "annex" in its first 6
   pages). (S1.)
7. **`fitz` vs `pymupdf`** — CLAUDE.md says "PyMuPDF (`fitz`)"; the builder wrote
   `import pymupdf` at `chunker.py:35`, the modern canonical name. **Until the human rules, this
   is NOT a deviation.** (S0 delta 1, now live and exercised at S2.)

## Carry-forward

**For the S2 repair (immediate next iteration):**

- **Repair scope is B1 and B2 ONLY**, per the loop contract. Advisory findings A1–A13 are **not**
  repair scope unless the human says otherwise.
- Re-verification after repair must re-derive the headline numbers, since any change to segment
  retention or sequence filtering moves the chunk count off **2335 / 2298 / 158-of-159 / 141
  distinct / 431 pieces from 175 segments**. Determinism hash to beat: `36d9404b172e173e`.
- Two beliefs must **not** be inherited: **disclosure #2 ("no actual rule text is lost") is
  FALSE** — 1,437 characters across 22 articles are gone; and **disclosure #3's mechanism is
  misdiagnosed** — it is heading-at-page-bottom / body-on-next-page, **not** multi-column or
  table reflow, and the recorded page is correct.

**For S3 (`index.py`):**

- **The corpus is cached — do NOT re-crawl.** `data/pdfs/` (25 PDFs, 30,436,220 bytes, 734 pp)
  and `data/manifest.json` are on disk and all open cleanly. Read from disk.
- **S1's A4 (Chroma rejects `None`) is CLOSED at the chunk layer.** `NULL_SENTINEL = ""`; all
  2335 chunks loaded into Chroma with real metadata, no crash.
- **A11 — the context label pushes 228 chunks over 1200 chars (max 1258).** Bodies are ≤ 1200;
  the label is prepended after splitting. Relevant to S3 sizing assumptions.
- **A4 — honor-of-kings printed-page offset is +6 on 44/60 pages.** Citations rendered as
  `p.N` will name a page the reader cannot find in that book.
- **Routing needs (slug, game_title) PAIRS from the manifest**, not the bare slug list — slugs
  are opaque and `cod-mw3` is stale ("Call of Duty: Black Ops 7"). (S1.)
- **`OPENAI_API_KEY` blocker is UNCHANGED and now imminent.** No key, no `.env`. S2 needed
  neither. **S3 cannot be verified without it and will return BLOCKED.**
- **`OPENAI_CHAT_MODEL` default (S0 A1) must be settled before S3.**
- **apex/ALGS precedence — HUMAN RULING NEEDED BEFORE S3.** Unchanged from S1; the chunker left
  apex at `authority=1` with `external_host=True` on all 161 apex chunks, which is the correct
  neutral default but not a decision.

**For S4 (`eval/`):**

- **A9 — S4 MUST pin per-book chunk count and distinct-article count as a regression fixture.**
  The six tuned constants have zero coverage and `drop_table_of_contents` deletes lines
  outright; a threshold drift removes a section from the corpus silently. PDF URLs are
  content-hashed, so re-uploads **will** happen.
- **`eval/queries.yaml` must carry a `cod-mw3`↔`warzone` case and an `mlbb`↔`mlbb-women` case**
  (S1). Valorant-vs-cs2 will never expose the realistic leakage.

**For S5 (`articles.py` + `resolve`):**

- **A2 — `resolve` MUST group on `article_id`, not `article`.** 13 bare Global article numbers
  collide between the main body and Appendices I/II.
- **A3 — mlbb ships a 17-chunk COPY of the Global Rulebook at `authority=1`** (`Appendix B -
  EWC26 Global Rules`), sharing Global's article numbering and outranking it under CLAUDE.md's
  precedence rule. **Human ruling needed before S5.**
- **OW2 corpus hole — open, for the human.** No Overwatch 2 rules exist in the corpus. Every
  OW2 question will abstain. S5 is the plausible fix.
- The Article 3.2.3 amendment is confirmed live and its body ships in the listing-page payload
  (S1 bonus intel). The `EWC_2026_TPA_Public` Tournament Participation Agreement remains a
  human decision.

**Housekeeping:**

- **Still not a git repository.** `.gitignore` correctness remains proxy-tested only. Run
  `git status` before any first commit — `data/` (29 MiB of redistributable PDFs owned by the
  Esports Foundation) must never be staged.
- **No destructive step has been run yet.** `index.py` (which drops the Chroma collection) does
  not exist.
- **A real UA contact is still unset** (`ingest.py:47` / `.env.example:24` carry
  `you@example.com`). Set it before any further crawling.

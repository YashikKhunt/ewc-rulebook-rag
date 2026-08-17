# Iteration 010 — S6 front-end (`frontend/` React+Redux + `server.py`)

- **Date:** 2026-08-14
- **Kind:** build
- **Verdict:** FAIL
- **Next action:** re-pin `chunks.pkl` sha256 and repair S6's B-2 (stale Chroma handle);
  S5's four findings remain open and unaddressed.

> **LOOP SHAPE CHANGED THIS STAGE.** The human created two new agents at `.claude/agents/`:
> `ewc-ux-designer` (stage 6a, design only) and `ewc-frontend-dev` (stage 6b, implementation).
> The loop for S6 was `ewc-ux-designer → ewc-frontend-dev → ewc-verifier → ewc-logger` —
> the three-agent `builder → verifier → logger` loop that ran S0-S5 gained a design stage in
> front of the builder. Record this as a structural change to the loop, not a one-off.

> **Both of the following are true and must not be blurred together:** the three
> human-required features (history, context display, click-through citations) are
> **DELIVERED and independently verified working in a real browser**, AND the stage
> **verdict is FAIL** on two blocking findings unrelated to those three features. Delivery
> of the UI does not clear the gate.

## What was built

### Stage 6a — design (ewc-ux-designer, $0 spend)
- `frontend/DESIGN.md` NEW — 12 sections, design spec only, not wired to any code.
- `frontend/mockup.html` NEW — static, banner-marked as a mockup, not wired.
- Organising principle: colour encodes authority (used ONLY for the three authority
  tiers); state (abstention/withholding/disclosure/title-mismatch) encoded via hairlines,
  hatching, letterspaced labels instead — `--alert` reserved for transport/config errors
  only, so an abstention can never visually read as a failure.
- 24 components, 18 states across lifecycle/result/overlay/shell categories.
- `TitleMismatchBanner` designed as a client-side, zero-cost mitigation for S5's B-2,
  computed from question+docs (not prose-sniffed), placed above the answer in DOM/focus
  order.
- `ScopeLedger` shows published titles, never slugs, on every turn.
- Flagged contentious calls: no token streaming, no regenerate button (would enable
  answer-shopping over a ~47% gate — S5 B-1), no conversational follow-ups (`graph.py` has
  no memory; treating a follow-up as new context would reproduce B-2's shape), no
  confidence score, context expanded by default, a `Search only` mode that fires zero chat
  completions.
- **Page-number finding, supersedes log 009's carried note (see Contract deltas below).**
- Corrected its own contrast tokens mid-spec: `--ink-3` measured 4.22-4.24:1, corrected to
  ≥4.5:1, measured table kept in the doc.
- Requested 11 API additions (none existed before this stage — `requirements.txt` had no
  web framework) and flagged 4 items needing human rulings (see below).

### Four human rulings made before stage 6b implementation
1. Alias map: ship the **derived** version; a small hand-checked supplement is allowed but
   the guard must degrade gracefully; no slug list hardcoded into routing logic.
2. Ship before B-2 (S5's cross-title misattribution) is repaired: **YES** — the
   mitigation's whole point is to make the defect visible, not to wait for it to be fixed.
3. Budget ceiling: server-side per-day and per-conversation caps, refusing BEFORE any
   model call.
4. Local PDF serving: **localhost only**, bind 127.0.0.1 explicitly — operator-local access
   only, given CLAUDE.md's content-ownership don't (PDFs are not to be redistributed).

### Stage 6b — implementation (ewc-frontend-dev, ≈$0.0064 spend)
- `server.py` NEW — starlette + uvicorn (both newly added to `requirements.txt`).
- `frontend/` NEW — Vite + React + Redux Toolkit, 12 components, `src/lib/claimText.js`,
  `src/lib/mismatch.js`, `src/lib/claimText.test.jsx`, 4 self-hosted woff2 fonts (166 KB).
- `data/aliases.json` NEW — 15 hand-checked colloquialisms (gitignored, see A-3).
- `data/page_labels.json` NEW, `data/history.db` NEW.
- `graph.py` — +86 lines, additive only (see Verifier rulings).
- `requirements.txt`, `.gitignore` modified.
- API surface: `POST /api/ask` (SSE phases → AskResponse), `POST /api/search`,
  `GET/POST /api/conversations`, `GET/PATCH/DELETE /api/conversations/:id`,
  `GET /api/catalog|corpus|budget`, `GET /api/source/:slug` (Range-capable),
  `GET /api/source/:slug/pages`. All 11 designer FLAGs answered.
- Builder found and fixed 3 bugs during its own verification pass: an `sr-only` text node
  that broke the byte-equality invariant (caught by the builder's own test), a footer scan
  that missed `​` (zero-width space) and "Page N of M" causing fabricated absences, and a
  budget refusal that was creating an empty conversation row.
- Builder corrected the designer's spec twice: `warzone` **is its own slug** ("Call of
  Duty: Warzone", distinct from `cod-mw3`) — all three B-2 reproductions fire on **derived**
  aliases with `data/aliases.json` deleted; and **6** books print physical-matching page
  numbers, not the designer's 5 (see page-number finding below).
- Builder's measured cost of one question: **$0.000756 – $0.001391**.

## What was verified

Verifier spend ≈$0.0057. Verified TRUE, executed not read:

- `graph.py`'s +86 lines are genuinely additive: exactly two new top-level names
  (`citation_spans`, `_outcome`); every S5-logged anchor shifts by exactly **+58** lines
  (`group_articles` 950→1008, `_coverage_lines` 1139→1197), proving nothing before or
  between the two insertion points changed in length. `SYSTEM` is still exactly **508
  words**, DEFAULT CASE / three-part test / COMPLETENESS still absent — S5's exact
  measurement, unchanged. `answer()`'s five exits gained only an `outcome` key. Routing,
  retrieval, and resolve proven byte-identical output on **28/28** retrieval cases.
- `citation_spans` reuses the existing citation parser — 326-case fuzz test, 0 mismatches,
  0 offset drift.
- Server binds 127.0.0.1; `--host` rejects any non-loopback value; `_is_local` is a second,
  independent gate.
- **`OPENAI_API_KEY` appears 0×** across `dist/*.js`, `*.css`, `*.js.map` (the one `sk-`
  string match is inside the word `tas`k``). `.env` is not served.
- Path traversal structurally impossible: `/api/source/{slug}` does a manifest lookup, never
  path concatenation — 7 static-path + 8 source-path traversal probes, all 404.
- Byte-equality invariant (rendered answer text === server-produced answer text) held under
  independent attack: 27/27 builder tests plus 15 hostile fixtures the verifier added
  (markdown, `<script>`, zero-width/bidi chars, emoji, CRLF, nested parens, lying spans),
  plus a live-DOM check (`textContent === server.answer`) at 1141 and 1557 chars, 0 diff.
- Budget guard returns HTTP 402 before any model call; turn/conversation counts unchanged,
  0 OpenAI calls made during the probe.
- No speculative model calls: page mount fires only corpus/catalog/conversations/budget
  requests; `run()` is reachable only from submit handlers. `Search only` mode measured
  `cost_usd 0.0`, empty usage.
- The B-2 mismatch banner fires on a run that **did misattribute live** — the builder's
  stored turn is genuine: *"The map veto procedure in CS2, as outlined in the VALORANT
  rulebook…"* citing VALORANT 5.5.1.1/5.5.1.2 with `outcome: answered`. The banner is
  computed from question+docs independent of the model's prose, so it fires whether the
  model misattributes or abstains.
- **All three required features verified working in real Chrome:**
  1. History — 34 threads listed, switchable, **survived a full server restart** (verifier's
     process read threads written by the builder's process). Rename works. DELETE → 204 then
     404. Stale-corpus detection fired correctly on all six pre-rebuild turns.
  2. Context — 8 cards per turn: book, article, page range, section trail, full excerpt,
     authority tier, rank star.
  3. Click-through — clicking `Counter-Strike 2 — Article 6.3.2, p.25` opened pdf.js at
     "Physical PDF page 25 of 32 — the page this citation points to / This page's printed
     footer reads 'Page 25 of 32'", cross-checked against the PDF with PyMuPDF.
- Four behaviours checked through the UI: cross-title leakage CLEAN (cs2-scoped ask inside
  a valorant-titled conversation returns only {cs2, global}; unknown slug → 400);
  abstention renders as a success state with context still shown; citations inseparable
  from prose (inline `<a>` inside the sentence; `copyPayload` carries answer+scope+
  fingerprint together) and the ⌀ uncited-paragraph marker fired on **5 of 6** paragraphs of
  a real live answer — the UI surfaced a genuine CLAUDE.md #3 defect instead of hiding it;
  precedence rendered as typed finding panels.

## Checks not run

- Nothing recorded as explicitly skipped by the verifier beyond what B-1/B-2 below already
  cover as "could not resolve attribution" — this section is otherwise empty because the
  verifier's own report does not flag additional untested surface. (Per logger rules: an
  empty section is itself a claim — noted here rather than omitted.)
- S5's four blocking findings (B-2 misattribution, B-1 coin-flip gate, B-3 resolve/amendment
  scope, B-4 false verbatim record) were **not in S6's repair scope** and were not
  re-checked this iteration; they are carried forward untouched, not re-verified as still
  present or absent.
- `grade` (retrieval-sufficiency loop) — still not built, still not exercised.

## Findings

### Blocking

- **B-1 — the eval gate is RED on the tree as it now stands, and the corpus was rebuilt
  mid-verification.** `eval/run.py --retrieval-only` → **EVAL FAIL, exit 1**;
  `regression-pins` 31/32; sole failure is `chunks.pkl` sha256: want
  `e5819299a1e72ab8…`, got `49c0a952d9421605…`.
  Timeline recovered from file mtimes: `data/manifest.json` 16:12:59 (`ingest.py`),
  `data/amendments.json` 16:13:19 (`articles.py`), `data/chunks.pkl` +
  `data/index_stats.json` 16:13:47 (`index.py`, destructive); Chroma collection UUID
  `56f539bc…` → `05300feb…`, sqlite 24.5 → 27 MB; then `python server.py` (PID 87398, :8000)
  at 16:13:59 and `vite` (PID 87432, :5173) at 16:14:04 — processes the verifier did not
  start.
  **Corpus content is UNAFFECTED:** the manifest is byte-identical to the S1 baseline except
  `generated_at`/`http_requests`; all 25 PDF sha256s and `downloaded_at` unchanged; 2382
  docs; all 31 retrieval pins still pass. Only the pickle serialisation differs.
  The verifier explicitly **refused to guess attribution**. It notes the builder's claim was
  TRUE at handoff (reproduced byte-for-byte at 16:06, `diff` clean) and false afterwards.
  **Resolution needed: re-pin `chunks.pkl` and record why.**
  *Logger note, not verifier claim:* the sequence ingest → articles → index → server → vite
  matches the handoff's own documented run commands, i.e. it is consistent with the human
  running the app themselves after handoff. Recording this as the most probable explanation
  while preserving the verifier's refusal to assert it as fact.
- **B-2 — a stale Chroma handle bricks retrieval for the process lifetime and reports it as
  an opaque bare 500.** Observed live: after the collection was recreated under a running
  server, every `POST /api/search` returned `HTTP/1.1 500`, `content-type: text/plain`, body
  `Internal Server Error`, from `chromadb.errors.NotFoundError: Error getting collection: …
  does not exist`. `graph.py:92` caches `_STORE` in a module global that is never
  re-acquired, so the process never recovers on its own. `server.py:1044` registers
  `exception_handlers={HTTPException: not_found}` only, so a non-`HTTPException` bypasses
  the JSON handler; `frontend/src/store/api.js:38` then receives `body = null` and surfaces
  an uninformative `HTTP 500` to the user. Availability/error-surfacing defect, not a
  correctness defect — but for a UI whose entire premise is a live index, "silently broken
  until someone restarts the process" is unacceptable. Stable across a 22-sample/6-minute
  poll once the store settled, so the trigger is a concurrent re-index event, not elapsed
  time.

### Advisory

- **A-1 — `server.py:629` states "8 books print nothing at all"; measured 12** (chess,
  cod-mw3, ea-sports-fc, fatal-fury, lol, r6-siege, rocket-league, street-fighter-6,
  tekken-8, tft, trackmania, valorant). `frontend/DESIGN.md:565` repeats the wrong number
  and names `crossfire`, which DOES print labels. The builder reported the correction in
  its own handoff and then shipped the wrong number in source anyway — **the same pattern
  as S5's B-4: the comment/finding text is what a future reader will trust, and it is
  wrong.**
- **A-2 — the budget estimate is below a real retry-triggering question.** `estimate_usd`
  defaults to `0.0015`; a live browser ask measured **$0.00152775**. `server.py:106` claims
  the estimate is "comfortably higher than the measured cost of a real question (~$0.0004)".
  It errs toward SPENDING, not refusing, whenever the post-check retry fires.
- **A-3 — `data/aliases.json` is hand-checked content living inside gitignored `data/`.**
  Not a slug-list contract violation, but uncommittable as written: a fresh clone loses it
  silently.
- **A-4 — every unscoped-conversation `POST /api/search` creates a conversation row.** A
  22-sample poll left 22 rail entries all titled "map veto." A free lookup should not
  pollute history.
- **A-5 — the `chunks.pkl` sha256 pin cannot distinguish "bytes differ, content identical"
  from real content drift.** It earned its keep this iteration (it is what caught B-1), but
  its failure message should say which case it is.
- **A-6 — the caveat/disclosure panel is only visible BEFORE the tool is used.**
  `App.jsx:105` renders `CorpusAtRest` and its "What this system does not yet do" list only
  when `chat.turns.length === 0`; after the first question the disclosure disappears, and
  the persistent `CorpusBar` shows only chunks/books/fingerprint. **Log 009's finding that
  the eval gate passes ≈47% at the shipped default is disclosed NOWHERE in the UI, at any
  point.**

## Contract deltas

- **`requirements.txt` gained a web framework** (starlette + uvicorn) — the first
  non-RAG-stack dependency in the project. Not a violation of anything in CLAUDE.md, but
  worth flagging since CLAUDE.md's stack line does not mention a web server.
- **CLAUDE.md's repo-layout section does not mention `server.py` or `frontend/`.** Both now
  exist as first-class parts of the repo; the human may want to update the layout listing.
  Flagging, not editing — per the logger's write boundary, only the human may change
  CLAUDE.md.
- **Page-number finding — supersedes log 009's carried "+6" note.** Log 009 (Carry-forward)
  recorded an unresolved "honor-of-kings +6 printed-page offset." The S6 designer measured
  this directly and found it **worse than previously recorded**: honor-of-kings is **two
  documents concatenated** — physical pp.2-6 print "- 1 -"…"- 5 -", then p.7 **restarts** at
  "- 1 -" through p.50, and pp.51-60 print nothing. The "+6" offset holds only for pp.7-50,
  is **+1** for pp.2-6, and is undefined after p.50 — printed labels 1-5 each land on two
  different physical pages. **Printed numbering is therefore NOT an invertible function**
  for this title; the design correctly never attempts to convert it, keeps the physical
  page as the locator, and reports observed footers as observations with an explicit
  ambiguity warning rather than a computed mapping.
  Corpus-wide, the verified figures are **6 books whose printed numbers match physical
  pages** and **12 books that print nothing at all** — NOT the "8 print nothing" figure
  shipped in `server.py:629` and `DESIGN.md:565` (see advisory A-1).
- No deltas from the pipeline itself (`ingest.py`/`chunker.py`/`index.py`/`graph.py`
  contract shape) beyond the additive `graph.py` change already covered under "What was
  verified."
- **All still-open deltas from prior stages carried forward unchanged**, per 009's list:
  scope-filter extension awaiting human ratification; the latent general-branch gap
  (CLAUDE.md's GENERAL scope filter has no game clause); `\d{1,2}` vs CLAUDE.md's `\d{1,3}`;
  the `[A-Z]` heading-guard relaxation; the >80% article-coverage gate's distinct-article
  floor; contract #2's `superseded` branch (A3) unproven end to end — structured-output
  constraint; the doc-count/version/effective_date question at (009's) line 150; the Global
  detail-page question at line 26; the noscript-fallback question at lines 35-36; "annexed"
  vs EA apex wording at line 22; fitz/pymupdf usage confirmation; B7 vs the PDF
  redistribution don't. **A11 remains RESOLVED** (closed at iteration 007, unaffected by
  S6).

## Verifier rulings

1. **`graph.py` changes — ACCEPTABLE, genuinely additive.** No contract line was crossed;
   see "What was verified."
2. **`data/aliases.json` — DATA, not a disguised slug list.** With the hand-checked
   supplement stripped, all three B-2 (S5) reproductions still fire (cs2, warzone, mlbb) and
   both negative controls stay silent. It never selects scope, never filters retrieval, and
   is validated against the derived slug set with ambiguous aliases auto-dropped. Builder's
   claim verified.
3. **Markdown-as-literal-text rendering — CORRECT CONSEQUENCE, not a defect.** The only
   rendering consistent with `textContent === answer`. If markdown emission is unwanted, the
   fix belongs in the PROMPT (stop emitting `**bold**`), never in the renderer.
4. **UI honesty — MOSTLY HONEST, one real gap.** Strong: B-2 and the missing `grade` node
   are both named in `known_gaps`; the mismatch banner states plainly that the displayed
   rules may not belong to the asked title regardless of the answer's own wording; the
   superseded-amendment branch prints an honest "unexercised path" note citing log 009;
   stale-corpus detection fired correctly live. **Gap: the disclosure panel disappears after
   the first question (A-6), and the ≈47% eval-gate figure is never surfaced anywhere in the
   UI.**
5. **Shipping a UI now — NOT SOUND as a general deliverable; DEFENSIBLE as an
   operator-local tool.** CLAUDE.md places UI at build-order step 6, and S5 (step 5) is
   FAIL. Against that: this is the first artifact in the project that makes S5's B-2 visible
   to a human at the moment of reading, deterministically and for free — something the CLI
   pipeline never did. Ruling: keep it loopback-only, and **do not let S6 be read as having
   advanced the project past S5's open findings.**
6. **Overall — the three required features are DELIVERED; the system is NOT fit for a
   compliance decision.** All three work end to end in real Chrome. But S5's B-2 is open and
   reproducible (the builder's own stored turn attributes VALORANT's veto ladder to CS2 with
   `outcome: answered`), a live answer stated roughly 25 rule steps with citations only on
   the final sentence, and the eval gate is currently red. The UI marks all of this
   honestly, which is the most a display layer can do — the pipeline underneath still has to
   be fixed.

## Carry-forward

### What this stage genuinely achieved (hold this alongside the FAIL)

- Loop gained a design stage (`ewc-ux-designer`) that produced a spec grounded in the
  contract (authority-as-colour, state-as-structure) and caught a real corpus defect
  (honor-of-kings page-number non-invertibility) before any code was written.
- Three human-required features (history, context, click-through citations) delivered and
  independently verified working in a real browser, including survival across a server
  restart.
- Builder self-corrected 3 bugs during its own pre-handoff verification, and self-corrected
  2 factual errors in the designer's spec (warzone slug identity, page-count figure) —
  though the corrected page-count figure did not make it into the shipped source (A-1).
- B-2 (S5's cross-title misattribution) is now visible to a human at read time via
  `TitleMismatchBanner`, deterministically and for $0 marginal cost, even though the
  underlying pipeline defect is unrepaired.
- Zero secret leakage across the entire built/shipped frontend bundle; zero path-traversal
  vectors found under active probing; budget guard verified to block spend before any model
  call.

### Immediate repair scope

1. Re-pin `chunks.pkl` sha256 to the current value and record in the pin file *why* it
   changed (pickle serialization only, corpus content proven identical) so a future reader
   does not mistake this for content drift.
2. Repair S6's B-2: re-acquire `_STORE` instead of caching it as a dead module global, and
   register a catch-all exception handler in `server.py` so a non-`HTTPException` failure
   still returns a JSON body instead of a bare opaque 500.
3. Advisory A-1 through A-6, in whatever order the next builder judges most efficient.

### S5's findings — still open, NOT addressed by S6, remain the project's real blockers

S6 was scoped to the front-end only; none of S5's four findings were in its repair scope,
and none were touched:

- **B-2 (S5)** — cross-title misattribution, 3/3 reproducible (VALORANT rules answered
  under a CS2 question with `outcome: answered`). The S6 banner makes this *visible*, it
  does not make it *not happen*.
- **B-1 (S5)** — `eval/run.py` is a coin-flip at the shipped default (`runs: 3`), ~47% pass
  probability on `conflict-vac-six-year`.
- **B-3 (S5)** — `resolve` silently drops the Global article from its own view for any
  amended article (`Group.scope` inherits from the amendment member).
- **B-4 (S5)** — the recorded fix for verbatim quoting ("≤34w") is false against the shipped
  tree; measured 90w.

Also still open, carried across multiple stages: `grade` (retrieval-sufficiency loop) never
built; contract #2's `superseded` branch unproven end to end; apex/ALGS authority and mlbb
Global-copy classification defaults unratified by a human; TPA PDF ingestion undecided; OW2
corpus hole (Google Doc, not PDF); UA contact placeholder (`you@example.com`); A2 (no
generation seed) still unresolved.

### Processes possibly still running

Two processes may still be live from the unattributed 16:13 rebuild: `server.py` (was PID
87398, :8000) and `vite` (was PID 87432, :5173). Check before starting new ones.

### API spend

| party | detail | cost |
|---|---|---|
| **designer (6a)** | `DESIGN.md` + `mockup.html`, no model calls beyond its own reasoning | **$0** |
| **builder (6b)** | `server.py`, `frontend/`, `graph.py` +86 lines, data files | **≈ $0.0064** |
| **verifier** | read-only checks + one live browser session, no re-index | **≈ $0.0057** |
| | **ITERATION TOTAL (metered)** | **≈ $0.012** |
| **unattributed** | re-embed from the unattributed 16:13 corpus rebuild (see B-1) | **≈ $0.006 (unmetered)** |

**Project total ≈ $0.586 of $5 (~11.7%).**

### Corpus and index state

Corpus was re-embedded once during this stage window by an unattributed process (see B-1).
Content proven unchanged (manifest byte-identical to S1 baseline except timestamps; all 25
PDF sha256s unchanged; 2382 docs; 31/32 pins pass). Chroma collection UUID changed
`56f539bc…` → `05300feb…`; sqlite grew 24.5 → 27 MB. `chunks.pkl` sha256 pin is stale and
must be updated (see Immediate repair scope, item 1).

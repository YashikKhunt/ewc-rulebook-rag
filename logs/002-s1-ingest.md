# Iteration 002 — S1 ingest

- **Date:** 2026-08-11
- **Kind:** build
- **Verdict:** PASS
- **Next action:** advance to S2 (`chunker.py`)

## What was built

- `ingest.py` — new, ~560 lines. Polite serial crawler → slug discovery from the listing page →
  per-detail-page PDF URL discovery → hash-cached download → `data/manifest.json`.
  The only `.py` file in the tree.
- `data/pdfs/*.pdf` — 25 PDFs, named `<slug>__<url_hash>.pdf`.
- `data/manifest.json` — 25 documents + 1 skipped entry.

No other module was written. `chunker.py`, `index.py`, `graph.py`, `articles.py`, `eval/`,
`data/amendments.json` all remain absent — confirmed by the verifier.

**Builder assertions (recorded as claims, then independently re-derived below):** nothing
hardcoded — slugs come from listing anchors, PDF URLs from detail pages; single
`requests.Session`, identifying UA, strictly serial; `_throttle()` guarantees >= 0.6 s and
`EWC_CRAWL_DELAY` cannot go below 0.6; one attempt per URL, no retries; cache key is the URL
content hash embedded in the filename, so a re-upload yields a new path and the superseded file
is logged stale, never deleted; `%PDF-` magic check rejects a corrupt cache entry; `.part` file
plus atomic rename; manifest carries 16 keys per document; a missing PDF is skipped and logged
with exit 0.

**Builder's own command runs:**

- Cold `python ingest.py` → exit 0, **25 slugs discovered, 25 PDFs saved, 1 skipped,
  51 requests in 36.3 s**.
- Re-run → exit 0, **25/25 cache hits, 0 PDF bytes fetched, 26 requests in 17.3 s**.
- Offline fixture tests of the discovery / date / hash helpers passed.
- Cached-path test with a stub raising on any network call → 25/25 succeeded.
- PyMuPDF opened all 25 → 734 pages; Global 51 pp containing `3.2.3` and "Team Roster".
- robots.txt permits the crawl.

## What was verified

The verifier (`ewc-verifier`) made **4 live requests only** — serial, 1.2 s apart, identifying
UA: `robots.txt`, the listing page, `/rulebooks/cs2`, `/rulebooks/overwatch-2` — and saved them
as offline fixtures. It did **not** re-run the crawl; crawl etiquette binds the verifier too.

Executed and re-derived, not taken on trust:

- **Manifest ↔ disk:** 25 documents, 1 skipped. 25 files on disk, 1:1 with the manifest,
  no extras, no `.part` leftovers. Every filename exactly `<game>__<url_hash>.pdf`.
- **Bytes:** all 25 sha256 and byte counts recomputed and matching; all 25 start `%PDF-`;
  total **30,436,220 bytes (29.0 MiB)**. `sha256`, `url_hash`, `game`, `path`, `source_url`
  all unique across the manifest.
- **Schema:** all 16 claimed keys present on **every** entry — one distinct keyset across all 25.
  `scope`/`authority` correct on all: **1 × global/0, 24 × title/1, zero violations**.
  `supersedes` null everywhere. `url_hash` independently re-derived from `source_url` for all 25
  — **zero mismatches**.
- **PDF integrity:** all 25 open in PyMuPDF, none encrypted. **734 pages total — confirmed.**
  Global **51 pp**; `3.2.3` occurs on pp. 3 (TOC) and 17; p. 17 reads
  "3.2.3. Team Roster Integrity / Clubs need to retain the majority of the roster…" — confirmed.
- **Etiquette, adversarial:** `EWC_CRAWL_DELAY` in {`0.0`, `0`, `-5`, `0.01`, `abc`, `""`,
  `0.5999999`} → **0.6 in every case**, with a warning; `1.5` honoured. Measured inter-request
  gaps against a stubbed session: **0.6016 / 0.6052 / 0.6038 s**. Greps for
  `thread|asyncio|async|await|Pool|concurrent|multiprocessing|aiohttp|httpx` → **0 hits**;
  `retry|backoff|while True|for attempt` → **0 hits**. robots.txt: Disallow only
  `/*/ewc26-paris/production-requests`, `Allow: /` — the crawl is permitted.
- **Cache behaviour:** all 25 served through `download()` with a crawler that raises on any
  network call → **zero network access**; reconstructed sha256 / bytes / path matched the
  manifest with `cached=True`. `--force` correctly attempts network. A planted non-PDF at a cache
  path → rejected, unlinked, re-downloaded, no `.part` residue. A non-PDF response body →
  Skipped, no `.pdf` written. A mid-download `ConnectionError` → Skipped, `.part` cleaned.
  Re-upload simulation → new hash, new path, old file reported stale and left on disk.
- **Hygiene:** no CDN URL and no slug literal in `ingest.py`. No secrets, no absolute personal
  paths. `.gitignore` proxy: only `.gitignore`, `ingest.py`, `logs/` staged; `data/` →
  `.gitignore:9`, `.env` → `:2`. **Still NOT a git repo**, so this remains a proxy exactly as at S0.
- **No running ahead:** S2–S6 files all absent.
- **S2 readiness: YES.** The manifest supplies `game`, `game_title`, `scope`, `authority`,
  `version`, `effective_date`, `source_url` plus `path`; `article`/`heading`/`page`/`chunk` are
  per-chunk derivations. Subject to A4 below.

## Checks not run

- **Full `python ingest.py` end-to-end was NOT re-executed by the verifier** — declined on
  etiquette grounds (a 26-request crawl). Cache behaviour was verified at function level instead.
  The builder's cold-run numbers above are therefore the builder's, not independently reproduced.
- **23 of the 25 detail pages were never fetched by the verifier.** Only `cs2` and `overwatch-2`
  were opened live; everything else about those 23 rests on the listing-page payload and the
  builder's run.
- **Local PDF integrity was verified; that the local bytes match upstream *today* was not.**
  No re-fetch and compare was performed.
- **Still not a git repository.** No `git init` has been run, so committability remains proxy-tested
  only, unchanged from S0.
- **No `OPENAI_API_KEY` and no `.env`.** S1 needs neither, so nothing was blocked — but the S0
  key blocker is untouched and still lands at S3.

## Findings

**BLOCKING: none.**

Advisory, ranked as the verifier ranked them:

- **A1 — `ingest.py:321-323`, `_is_official_host` suffix match has no dot boundary.**
  `host.endswith("esportsworldcup.com")` returns True for `evilesportsworldcup.com` (verified).
  `external_host` is a provenance/trust signal the precedence layer may lean on (see Contract
  delta 4). Impact today is nil — every URL comes from the official site's own markup — but the
  signal is wrong for a lookalike domain. Fix:
  `host == "esportsworldcup.com" or host.endswith(".esportsworldcup.com")`.
- **A2 — `ingest.py:171-183`, the apex cache key is not content-aware, so that document can go
  permanently stale.** `url_content_hash("https://algs.ea.com/year-6-rules.pdf")` →
  `ua3d9f11cd167a409`, a SHA-1 of the URL. EA can replace that file in place with amended ALGS
  rules and every future run will silently serve the 2026-08-11 copy — exactly the failure
  CLAUDE.md's hash-cache rule exists to prevent, for 1 of 25 documents. The docstring
  acknowledges it; nothing acts on it. Suggested: re-fetch `external_host` docs and compare
  sha256 (or conditional GET), or surface staleness in the manifest.
- **A3 — the builder's "manifest byte-stable across runs" claim is FALSE; correct the record.**
  `ingest.py:546` `generated_at` is `datetime.now()` and `:548` `http_requests` varies
  (51 cold vs 26 cached); two writes 1.1 s apart differed on exactly those two lines. The
  `documents` array **is** byte-identical (verified), because a cached `downloaded_at` is
  reconstructed from mtime — a good design. Not a defect, but **nobody should build a
  change-detector on the manifest file hash.**
- **A4 — S2/S3 carry-forward, and the sharpest one: 24/25 documents have `version: null` and
  `effective_date: null`, and Chroma rejects `None` metadata.** Verified:
  `col.add(metadatas=[{"version": None}])` → `TypeError: argument 'metadatas': Cannot convert
  Python object to MetadataValue`. CLAUDE.md requires `version` and `effective_date` on every
  chunk. `chunker.py` / `index.py` must coerce `None` → `""` or a sentinel, or indexing crashes
  on the first title chunk. Same applies to `doc_title` and `supersedes`.
- **A5 — `ingest.py:372`, `doc_title=None` for all 24 titles discards data the builder already
  parses.** The same payload carries `title:"EWC CS 2026 Rulebook"`,
  `title:"APEX LEGENDS™ GLOBAL SERIES YEAR SIX OFFICIAL RULES"`. Not a CLAUDE.md-required field,
  so **not a defect** — but free provenance for the citation layer, one regex group away.
- **A6 — `ingest.py:241-246`, `find_download_url` silently returns only the first match.**
  Verified all 25 `rulebookDocuments` arrays have length 1 today, so nothing is dropped. If a
  title ever publishes a rulebook plus an appendix, ingest takes one and never logs the other.
  A count-and-warn would make that visible.
- **A7 — `ingest.py:47` / `.env.example:24`, the UA contact is a placeholder**
  (`+contact: you@example.com`). It identifies the tool (satisfies the contract) but gives the
  Foundation nobody to reach. **Set a real contact before further crawling.**
- **A8 — `ingest.py:445-450`, truncation is undetectable.** `is_valid_pdf` reads 5 bytes; a body
  cut off after the header would land as a "valid" cached PDF. `Content-Length` is available and
  unchecked. Low probability (requests raises on `IncompleteRead`, which is caught), no instance
  observed — all 25 opened cleanly.
- **A9 — S2 carry-forward: the builder's page-1 note is CONFIRMED and generalises far beyond
  dota2.** Measured page-1 extracted text: dota2 **15** chars, global 41, free-fire 45,
  trackmania 46, fortnite 68, pubg 72, cs2 77, mlbb-women 84, warzone 97, tft 102, mlbb 108,
  honor-of-kings 107. **11 of 25 books yield under 110 characters on page 1.**
  The chunker must not assume page 1 carries the title or any article text.

## Contract deltas

**CLAUDE.md is the source of truth and only the human may amend it. The logger has not touched
it.** Four confirmed contradictions, each verified against the live site:

1. **25 PDFs, not 26 — CONFIRMED SITE FACT, a contract delta and not a defect.**
   Listing payload: `overwatch-2 → rulebookDocuments:[{externalUrl:"https://docs.google.com/
   document/d/1IaT…/edit?tab=t.0", fileUrl:void 0}]`. The detail page contains **zero** `.pdf`
   strings yet renders `<span data-slot="tag">PDF available</span>` and
   `<h2 id="rulebook-pdf-heading">Rulebook PDF</h2>` — **the badge does lie.**
   CLAUDE.md line 30 ("Not every title has a published PDF… skip and log, never crash") already
   anticipates this and **contradicts line 150** ("manifest of 26 docs"). Ingest followed the more
   specific rule. **Recommend amending line 150.**
   *For the human:* OW2 is a competing title and the corpus now contains **no OW2 rules at all**.
   The system will abstain on every OW2 question — correct under non-negotiable #4, but a real
   hole. S5 (`articles.py`) is the plausible home for non-PDF sources.

2. **`version` / `effective_date` present only for Global — CONFIRMED SITE FACT, NOT a parsing
   failure.** This is the one that would otherwise have been a FAIL. Three independent proofs:
   (a) the builder's own `PAYLOAD_DOC_RE` matches 25/25 documents on live listing HTML and every
   match is `version:void 0, publishDate:void 0` — the regex works, the data is absent;
   (b) an independent scan of the cs2 detail page for
   `version:` / `publishDate:` / `effectiveDate:` / `"version":` / `updatedAt:` / `\bv\d+\.\d+\b` /
   `[Ee]ffective\s+\w+` found only `version:void 0` and `publishDate:void 0`;
   (c) the rendered Rulebook PDF section on cs2 reads in full:
   "Rulebook PDF Download rulebook (opens in a new tab)".
   Global genuinely ships `version:"v1.0",effectiveDate:"2026-01-01"` and the rendered line
   "v1.0 · effective 1 Jan 2026 · English", and ingest captures both. The fields are
   present-as-null and will populate automatically if the Foundation starts publishing them.
   Contract delta on line 150 — **not a FAIL.**

3. **Global has no detail page — CONFIRMED.** `"/rulebooks/global"` does not occur anywhere in
   the listing HTML. The only "Download rulebook" anchor on the listing page is the hero card:
   "PDF 2026 Season EWC Global Rulebook 2026 … v1.0 · effective 1 Jan 2026 · English ↓ Download
   rulebook". **Contract delta on CLAUDE.md line 26** — that line is true for the 25 titles and
   false for Global.

4. **Zero `<noscript>` — CONFIRMED; the mechanism does not exist but the outcome does.**
   `soup.find_all("noscript")` → **0**. There are 25 ordinary server-rendered
   `<a href="/en/competitive-ops/rulebooks/…">`. `discover_title_urls` on the raw HTML returns
   25 slugs, set-identical to the manifest's 24 titles + `overwatch-2`. The outcome CLAUDE.md
   wanted holds exactly; only the filter buttons are JS-gated. A misreading of mechanism in the
   spec, **no code change needed. Recommend amending lines 35-36.**

**Additionally — the apex/ALGS precedence question, escalated to the human (verifier ruling 5):**
Downloading `apex → algs.ea.com` was **correct**: the site lists it as the Apex
`rulebookDocuments` entry, so it *is* the published Apex rulebook, and skipping it would create a
silent corpus hole. It is the only `external_host: true` entry. **But** the verifier opened it —
51 pp, "APEX LEGENDS™ GLOBAL SERIES YEAR SIX OFFICIAL RULES", sponsored by Electronic Arts Inc.,
and across its first 6 pages there are **zero** occurrences of "Esports World Cup", "EWC", or
"annex". CLAUDE.md line 22 asserts title rulebooks are *"annexed to the Global Rulebook"*; this
one textually is not. With `authority=1` it will **override the EWC Global Rulebook on any
conflicting point with no textual basis** — a compliance-grade wrong answer waiting to happen.
Options: (a) accept `authority=1`; (b) give `external_host` docs a distinct authority or a
mandatory answer-time provenance caveat; (c) exclude it.
**HUMAN RULING NEEDED BEFORE S3.** The manifest already carries `external_host`, so any option is cheap.

**And — slug/name drift, CONFIRMED, with an S3 risk worse than the builder framed it
(verifier ruling 6).** Live payload: `cod-mw3` → "Call of Duty: Black Ops 7"
(PDF `EWC_26_COD_BO_7_Rulebook`); `honor-of-kings` → "Honor of Kings and Arena of Valor"
(PDF `KWC_at_EWC_26_Rulebook`); `r6-siege` → "Rainbow 6 Siege X"
(PDF `TOM_CLANCY_S_RAINBOW_SIX_SIEGE…`). Further drift the builder missed:
`warzone` → "Call of Duty: Warzone" (PDF `COD_WRS_Championship`); `mlbb` → `MSC_at_EWC_26`;
`mlbb-women` → `MWI_at_EWC_26`; `apex` → `ALGS`. **`cod-mw3` is a stale slug** (MW3 → BO7) —
live proof that slugs are opaque identifiers. Two hazards follow:
(a) a `route` node given only the bare slug list **cannot** map "Black Ops 7" → `cod-mw3`; it must
receive the **(slug, game_title) pairs** from the manifest.
(b) More dangerous: there are Call-of-Duty-family entries (`cod-mw3`, `warzone`) and two MLBB
entries (`mlbb`, `mlbb-women`). Leakage between `mlbb`/`mlbb-women` or `cod-mw3`/`warzone` is the
most likely violation of non-negotiable #5, and a valorant-vs-cs2 test will **never** catch it.
**`eval/queries.yaml` (S4) MUST carry a `cod-mw3`↔`warzone` case and an `mlbb`↔`mlbb-women` case.**

## Carry-forward

The next iteration (S2, `chunker.py`) and everything after must know:

- **`data/pdfs/` and `data/manifest.json` now exist** — 25 PDFs, 30,436,220 bytes (29.0 MiB),
  734 pages, all opening cleanly in PyMuPDF. **Do NOT re-crawl.** Re-runs are cached by URL
  content hash and cost 0 PDF bytes; a crawl is 26+ live requests against a public official
  resource. Read from disk.
- **A4 — Chroma rejects `None` metadata, and 24/25 documents carry `version: null` /
  `effective_date: null`.** `chunker.py` / `index.py` MUST coerce `None` → `""` or a sentinel for
  `version`, `effective_date`, `doc_title`, `supersedes`, or **indexing crashes on the first title
  chunk**. This is the single most likely S2/S3 breakage.
- **A9 — page 1 is frequently near-empty.** 11 of 25 books yield under 110 characters of extracted
  text on page 1 (dota2: **15** chars). The chunker must not assume page 1 carries the title or
  any article text.
- **S3 routing needs (slug, game_title) PAIRS from the manifest**, not the bare slug list.
  Slugs are opaque and at least one (`cod-mw3` → "Call of Duty: Black Ops 7") is stale.
- **S4 eval is mandated to include a `cod-mw3`↔`warzone` case and an `mlbb`↔`mlbb-women` case.**
  These are the realistic cross-title-leakage failures; valorant-vs-cs2 will not expose them.
- **OW2 corpus hole — open, for the human.** No Overwatch 2 rules exist in the corpus (the source
  is a Google Doc, not a PDF). Every OW2 question will abstain. S5 is the plausible fix.
- **apex/ALGS precedence — HUMAN RULING NEEDED BEFORE S3.** See Contract deltas.
- **Still open from S0:**
  - **`OPENAI_API_KEY` blocker.** No key, no `.env`. S2 does not need one. **S3 (`index.py`)
    cannot be verified without it and will return BLOCKED.**
  - **`fitz` vs `pymupdf` CLAUDE.md amendment (S0 contract delta 1) — now live at S2.**
    Until the human rules, a builder using `import pymupdf` is NOT deviating.
  - **`OPENAI_CHAT_MODEL` default (S0 A1)** — must be settled before S3.
- **Still not a git repository.** `.gitignore` correctness remains proxy-tested only. Run
  `git status` and confirm before any first commit — `data/` (29 MB of redistributable PDFs owned
  by the Esports Foundation) must never be staged.
- **A3 — do not build a change-detector on the manifest file hash.** `generated_at` and
  `http_requests` vary run to run; only the `documents` array is byte-stable.
- No destructive step has been run yet. `index.py` (which drops the Chroma collection) does not exist.

## Bonus intel for S5, found in the listing payload

- **The amendment CLAUDE.md predicts is LIVE:** `href:"/competitive-ops/articles/article"`,
  `title:"Global Rulebook Update: Article 3.2.3 (Team Roster Integrity)"`, body opening
  `# Update to Art. 3.2.3 of the EWC 2026 Global Rulebook` — and **the article body is shipped in
  the listing page payload itself**, which may make `articles.py` cheaper than expected.
- The "Public Version Archive" is present as `kind:"placeholder"`, "Coming soon." — matching
  CLAUDE.md line 37. Do not build against it.
- Also present but correctly out of scope today: `EWC_2026_TPA_Public_1_…pdf`
  (Tournament Participation Agreement, `category:"agreement"`, `version:"2026 edition"`) — a
  governing document **not** in `rulebookDocuments`. **Worth a human decision at S5** whether it
  belongs in the corpus.

Project context for the EWC Rulebook RAG. Read this fully before touching code.

## What this is

A retrieval system over the **Esports World Cup 2026 competitive rulebooks** (PDFs).
Stack: Python 3.11+, LangChain (loaders/splitters/stores), LangGraph (orchestration),
Chroma (vectors), BM25 (lexical), OpenAI (embeddings + generation).

The output is a **compliance-grade** answering system, not a chatbot. A wrong answer
about a forfeit rule is worse than no answer. Abstention is a success state.

---

## Source of truth — verify before assuming

Root: `https://resources.esportsworldcup.com/en/competitive-ops`

These facts were confirmed by inspecting the live site. Do not "improve" the ingest
logic based on assumptions that contradict them:

- **Two-tier corpus.** One `EWC Global Rulebook 2026` (v1.0, effective 1 Jan 2026)
  plus **25 per-game-title rulebooks**. Title rulebooks are explicitly
  *"annexed to the Global Rulebook"* — they do not replace it.
- **Detail pages** live at `/en/competitive-ops/rulebooks/<slug>` (e.g. `cs2`,
  `dota2`, `valorant`, `mlbb-women`, `cod-mw3`, `honor-of-kings`, `tekken-8`).
  The PDF link is on the detail page, not the listing page.
- **PDF URLs are content-hashed** on `cdn.esportsworldcup.com`
  (e.g. `EWC_CS_2026_Rulebook_fe6e24ed0b.pdf`). They change on re-upload.
  → Never hardcode a PDF URL. Always rediscover. Use the URL hash as the cache key.
- **Not every title has a published PDF.** Ingest must skip and log, never crash.
- **The PDFs are not the whole truth.** Rulings and amendments are published as HTML
  articles under `/en/competitive-ops/articles/*` and can supersede a PDF article
  (confirmed example: an update to Global Rulebook **Article 3.2.3, Team Roster
  Integrity**). A PDF-only index will state superseded rules with full confidence.
- The listing page filters require JS. Parse the no-JS fallback list — it contains
  all 25 links.
- A "Public Version Archive" of prior editions is advertised as *coming soon*.
  Do not build against it yet; leave the `supersedes` metadata field in place for it.

**Scraping etiquette:** identifying User-Agent, `time.sleep(0.6)` between requests,
never parallelise the crawl. This is a public official resource — treat it gently.

---

## Repo layout

```
ingest.py       # discover + download PDFs -> data/pdfs/, writes data/manifest.json
articles.py     # scrape amendment/ruling HTML articles -> data/amendments.json
chunker.py      # PDF -> article-aware LangChain Documents
index.py        # build Chroma collection + pickle chunks for BM25
graph.py        # LangGraph app: route -> retrieve -> grade -> resolve -> answer
eval/queries.yaml
eval/run.py     # scores retrieval + faithfulness against the query set
data/           # gitignored
```

Keep these as separate modules. Do not collapse into one file.

---

## Commands

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

python ingest.py          # ~26 PDFs, polite crawl, safe to re-run (cached by hash)
python articles.py        # amendments layer
python index.py           # rebuild vector store (destructive: drops collection)
python -m graph "question here"
python eval/run.py        # must pass before any retrieval change is considered done
```

Requires `OPENAI_API_KEY` in `.env`. Never commit `.env` or anything under `data/`.

---

## Non-negotiable behaviours

These are the product. Do not relax them to make an answer look better.

1. **Precedence.** When Global and title rulebooks both address a point and they
   differ, **the game-title rule governs** and the answer must say so explicitly.
   Encoded as metadata `authority`: `global=0`, `title=1`, `amendment=2`.
   Higher authority wins; never silently blend the two.
   **Exception — express Global primacy.** Where the Global Rulebook's own text
   expressly asserts primacy on a point (confirmed case: Article 3.2.3, *Team Roster
   Integrity*, "even if the respective game title rulebook allows bigger changes"),
   **Global governs on that point** and the answer must say so. This is the only
   direction in which Global outranks a title book, and it must be grounded in the
   Global text itself — never inferred because a title book is silent.
2. **Amendments supersede.** If an amendment chunk shares an article number with a
   base PDF chunk, the base text is presented only as *"as amended"*. Never quote a
   superseded article as current.
3. **Citation on every claim.** Format: `(Game — Article X.Y.Z, p.N)`. An uncited
   rule statement is a bug.
4. **Abstain over infer.** If retrieved excerpts don't cover the question, say so and
   name what was searched. Never reason from esports general knowledge, never fill a
   gap from the model's priors, never soften with "typically" or "usually".
5. **No cross-title leakage.** A question routed to `valorant` must not retrieve
   `cs2` chunks. Filter at the store level, not in the prompt.
6. **Quote sparingly.** Paraphrase rule text; quote only short exact phrases where
   the precise wording is legally load-bearing.

---

## Chunking rules

- Split on **article boundaries first**, `RecursiveCharacterTextSplitter`
  (1200/150) only for oversized articles. Never split blindly by character count —
  it destroys the article numbering that makes answers verifiable.
- Heading detection: `^\s*(\d{1,2}(?:\.\d{1,3}){0,3})\.?\s+([A-Z][^\n]{2,90})\s*$`,
  line length < 100. Tables and headers/footers will produce false positives —
  guard on length and require a following body.
- Prepend a context label to every chunk's text:
  `[<game_title> · Article <n> — <heading>]`. The embedding must carry article
  context, not just metadata.
- Required metadata on every chunk:
  `game, game_title, scope, authority, article, heading, page, version,
   effective_date, source_url, chunk`.
- Use PyMuPDF (`fitz`) for extraction — page numbers must survive. Do **not** switch
  to `PyPDFLoader`; page fidelity and layout handling are worse on these files.

---

## Retrieval rules

- **Hybrid is mandatory.** Rule queries are token-exact ("Article 3.2.3", "forfeit",
  "10 minutes"). Dense-only retrieval measurably misses these. Merge dense + BM25
  with Reciprocal Rank Fusion (k=60), then sort by `authority` descending.
- Scope filter: title question → `{"$or": [{"game": slug}, {"scope": "global"}]}`.
  General question → `{"scope": {"$in": ["global", "amendment"]}}`.
- Retrieve 12 + 12, fuse, keep top 8.
- One grade-and-rewrite loop maximum. Do not build unbounded agent loops — latency
  and cost matter and a second rewrite almost never helps on this corpus.

---

## LangGraph contract

State: `question, query, game, docs, conflicts, answer, tries`.
Nodes: `route → retrieve → grade → (retrieve | resolve) → answer`.

- `route` uses structured output constrained to the known slug list; returns `None`
  for tournament-wide questions rather than guessing a title.
- `resolve` groups retrieved chunks by article number, detects same-article
  disagreement across authority levels, and writes an explicit precedence note into
  state for the answer prompt to consume.
- Every node returns a partial dict. No mutation of state in place.

---

## Build order

1. `ingest.py` — manifest of 26 docs with version/effective-date captured.
2. `chunker.py` — assert article numbers are non-empty for >80% of chunks in the
   Global Rulebook. If not, the heading regex is wrong; fix it before indexing.
3. `index.py` + a bare retrieve-and-answer path. Validate against 5 hand-checked
   questions with the PDFs open.
4. `eval/queries.yaml` — three buckets: **normal**, **cross-scope**, **conflict**.
   Conflict cases (a topic both Global and a title book address) are the ones that
   expose flat retrieval; write these first.
5. `articles.py` + `resolve` node.
6. Only then, any UI.

---

## Don'ts

- Don't hardcode CDN PDF URLs or the game slug list — derive both at runtime.
- Don't add a reranker, GraphRAG, or a multi-agent layer before `eval/run.py`
  shows the simple pipeline's actual failure modes.
- Don't cache LLM answers keyed on the question alone; the corpus is versioned.
- Don't let the answer prompt see raw chunks without their metadata header.
- Don't paper over a retrieval failure by widening `k`. Diagnose the routing first.
- Don't commit PDFs to the repo. They are redistributable content owned by the
  Esports Foundation; ingest them at build time.
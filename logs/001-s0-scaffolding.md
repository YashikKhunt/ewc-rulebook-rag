# Iteration 001 — S0 scaffolding

- **Date:** 2026-08-11
- **Kind:** build
- **Verdict:** PASS
- **Next action:** advance to S1 (`ingest.py`)

## What was built

- `requirements.txt` — 17 direct deps pinned, transitives left to float. langchain 1.3.14,
  langchain-core 1.5.3, langchain-community 0.4.2 (source of `BM25Retriever`),
  langchain-text-splitters 1.1.2, langgraph 1.2.10, chromadb 1.5.9, langchain-chroma 1.1.0,
  rank-bm25 0.2.2, langchain-openai 1.4.3, openai 2.53.0, pymupdf 1.28.2, requests 2.34.2,
  beautifulsoup4 4.15.0, lxml 6.1.1, python-dotenv 1.2.2, pyyaml 6.0.3, pydantic 2.13.4.
  Inline comments state why each dep is present.
- `.gitignore` — `.env` + `.env.*` with a `!.env.example` negation, `data/`, blanket `*.pdf`,
  `chroma/` and `chroma_db/`, `*.sqlite3`, `*.pkl`/`*.pickle`, venvs, Python caches, editor/OS files.
- `.env.example` — required `OPENAI_API_KEY`; optional with defaults
  `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`, `OPENAI_CHAT_MODEL=gpt-4o-mini`,
  `EWC_BASE_URL`, `EWC_USER_AGENT`, `EWC_CRAWL_DELAY=0.6`, `EWC_DATA_DIR=data`,
  `EWC_CHROMA_DIR=data/chroma`, `EWC_CHROMA_COLLECTION=ewc_rulebooks`.
  **These names are now the contract every later stage reads.**
- `.python-version` — `3.11`. Not one of the three named S0 deliverables; builder added it and
  flagged it for a ruling (see Findings A2 / Contract deltas).

No `git init` was run. **The project is still not a git repository.**

## What was verified

Verifier (`ewc-verifier`) re-derived everything independently and executed rather than read.

- uv 0.11.23 confirmed. Existing project `.venv` is CPython 3.11.15. `uv pip check` → 112
  packages, all compatible.
- **Cold reproduction** in a scratchpad dir: `uv venv --python 3.11` +
  `uv pip install --no-cache -r requirements.txt` → succeeded, 112 packages, check clean.
  The builder's install was reproduced, not taken on trust.
- Pins vs installed compared by script: **17 pinned direct deps, 0 mismatches.**
- Offline capability probe, **16/16 OK** — exercising what later stages actually need, not bare imports:
  - bs4 with the `lxml` parser.
  - Built a 3-page PDF and confirmed `page.number` survives PyMuPDF extraction →
    `[(0,'3.2.1 Team R'), (1,'3.2.2 …'), (2,'3.2.3 …')]`. Page fidelity requirement holds.
  - `RecursiveCharacterTextSplitter(1200, 150)` constructs and splits.
  - `Document` metadata roundtrip including `authority` and `article`.
  - `BM25Retriever.from_documents().invoke()` returns ranked docs on the rank_bm25 backend.
  - **Chroma scope filters, exactly as mandated, against an ephemeral collection:**
    `{"$or":[{"game":"valorant"},{"scope":"global"}]}` → `['global rule','valorant rule']`,
    **zero cs2 leakage**; `{"scope":{"$in":["global","amendment"]}}` → `['global rule']`.
    Store-level filtering (CLAUDE.md non-negotiable #5) is supported by this chromadb pin.
  - `ChatOpenAI.with_structured_output(pydantic_model)` returns a `RunnableSequence`.
  - `StateGraph`/`END` compiled and invoked with the full 7-field state; partial-dict returns
    merged correctly with no in-place mutation.
  - pyyaml parses a three-bucket `queries.yaml` shape.
- Key transitives confirmed present: tiktoken 0.13.0, numpy 2.4.6, httpx 0.28.1, tenacity 9.1.4,
  soupsieve 2.9.2, langgraph-checkpoint 4.2.0. Nothing CLAUDE.md implies is missing.
- Hygiene greps: hardcoded `cdn.esportsworldcup.com` / PDF URL → **0 hits** outside CLAUDE.md and
  agent definitions. Literal game-slug list → **0 hits**, same exclusions. Secret-shaped scan
  (`sk-…{16,}`, `AKIA…`, `api_key="…"`) → **0 hits**; `.env.example` carries only the literal
  placeholder. Absolute personal path scan → **0 hits** in builder-written files.
- **No running ahead:** none of `ingest.py`, `articles.py`, `chunker.py`, `index.py`, `graph.py`,
  `eval/` exist. S1–S6 files: NONE present.
- `.gitignore` **proxy** test: `git init` in a scratch dir with the project's real `.gitignore`,
  `git add -A` over a hostile fixture set → only `.env.example`, `.gitignore`, `ingest.py` staged.
  `git check-ignore` confirmed: `.env`→:2, `.env.local`→:3, `.env.example`→TRACKABLE (negation
  works), `data/manifest.json` + `data/pdfs/EWC_CS_2026_Rulebook_abc123.pdf` +
  `data/chroma/chroma.sqlite3`→:9 `data/`, `docs/loose_rulebook.pdf`→:12 `*.pdf`,
  `chunks.pkl`→:18, `.venv/lib/…`→:22. A file containing a realistic-looking key was not staged.

## Checks not run

- **Live OpenAI path — not exercised.** No `OPENAI_API_KEY` present, no `.env` file exists.
  `OpenAIEmbeddings`/`ChatOpenAI` were constructed with a dummy key and `with_structured_output`
  was exercised, but the key path, model availability and embedding dimensionality are unproven
  end to end. S0 needs no API call, so this does not block. See Finding A5 — it becomes a
  **BLOCKED verdict at S3** if a key is still absent.
- **In-place git committability — not checked, and the verifier explicitly declined to pass it
  as one.** The `.gitignore` evidence above is a *proxy* test in a scratch repo. It proves the
  rules are correct under real git semantics; it does **not** prove this project is safe, because
  this project has no index to be safe. **The first real `git init` here must be re-checked with
  `git status` before any commit.**
- No lockfile / transitive-resolution reproducibility check beyond the single cold install
  (see A3).
- No live crawl of `resources.esportsworldcup.com` — correctly out of scope at S0.

## Findings

**BLOCKING: none.**

Advisory, ranked as the verifier ranked them:

- **A1 — `.env.example:15`, `OPENAI_CHAT_MODEL=gpt-4o-mini` needs human ratification and is
  likely the wrong default.** The four non-negotiable behaviours (abstention, refusing to blend
  Global with title rules, no "typically"/"usually" hedging) are exactly the instruction-following
  behaviours that degrade first on a small model. For a spec whose premise is "a wrong answer
  about a forfeit rule is worse than no answer", a mini-tier default optimises the wrong axis.
  Set this deliberately before S3, and have `eval/run.py` report which model produced a run.
- **A2 — the `.python-version` rationale in the builder handoff is not reproducible as stated.**
  The artefact is fine and stays; the justification was wrong. See Contract deltas.
- **A3 — `requirements.txt` transitives float:** 95 of 112 packages unconstrained. This matches
  the builder's disclosed intent and no CLAUDE.md rule requires a lockfile, so it is **not a
  defect**. But once `eval/run.py` makes retrieval scores the regression signal, a floating
  transitive is a plausible source of unexplained score drift. Consider `uv.lock` /
  `uv pip compile` at S4.
- **A4 — `.gitignore:15-16` covers `chroma/` and `chroma_db/`, not `chroma*/`** as the handoff
  claimed. A store at e.g. `./chroma_store/` would be trackable. Low impact: the default
  `EWC_CHROMA_DIR=data/chroma` sits under the `data/` rule and `*.sqlite3` catches the payload.
  Recorded because the handoff described a broader pattern than the file contains.
- **A5 — coverage gap, not a defect: no live OpenAI call verified.** See Checks not run.
  **S3 cannot be verified without a key and will return BLOCKED, not FAIL, if one is still absent.**
- **A6 — note for whoever writes `eval/`: the BM25 probe returned the WRONG document for a
  token-exact query.** "forfeit 10 minutes" against a two-doc corpus returned the valorant doc,
  not the cs2 doc containing "forfeit after 10 minutes"; `BM25Okapi.get_scores` returned 0.000.
  This is rank_bm25's negative-IDF clamping on tiny corpora, **not** a bug in the pin, and it will
  not occur across thousands of real chunks. Recorded so nobody debugging S3/S4 mistakes it for a
  retrieval defect — **and so no eval fixture is ever built on a handful of synthetic documents.**
- **A7 — `requirements.txt:7`, umbrella `langchain==1.3.14` may be dead weight;** the pipeline
  uses the sub-packages directly. Defensible under CLAUDE.md's "LangChain (loaders/splitters/stores)"
  phrasing and harmless. Do not act now.

## Contract deltas

1. **`fitz` vs `pymupdf` — genuine contract delta, needs a human ruling.**
   CLAUDE.md line 116 says *"Use PyMuPDF (`fitz`) for extraction"*. At the pinned PyMuPDF 1.28.2,
   `import fitz` emits a deprecation warning: the alias is deprecated and **will be removed**.
   The substance of the rule is unaffected — PyMuPDF not `PyPDFLoader`, page numbers survive
   (verified above). Only the alias is stale, so a future PyMuPDF bump would break code written
   to the letter of the current spec.
   *Verifier's recommended ruling:* amend CLAUDE.md line 116 to
   "PyMuPDF (`import pymupdf`; the legacy `fitz` alias is deprecated at 1.28)" and have
   `chunker.py` use `import pymupdf`.
   **Until the human rules, a builder using `import pymupdf` at S2 is NOT deviating.**
   Only the human may change CLAUDE.md; the logger has not touched it.

2. **Corrected `.python-version` rationale — record this one, not the builder's.**
   The builder justified the file by claiming `uv venv` would otherwise silently select
   Python 3.14. The verifier measured it: **`uv venv` without `.python-version` selects
   CPython 3.12.13** (a uv-managed install), **not 3.14**. `requirements.txt` also resolves
   cleanly on 3.11, 3.12 and 3.14 alike (`--dry-run`). So the silent-3.14 failure the builder
   described **does not occur**, and 3.12 would have satisfied the "Python 3.11+" floor anyway.
   Verdict: **ACCEPTABLE SCOPE, KEEP** — but for **reproducibility**, not for the stated failure.
   It makes `uv venv` (the first command in CLAUDE.md's command block) deterministic across
   machines rather than dependent on each developer's uv python inventory.
   A future reader must not inherit the builder's false belief about this machine's toolchain.

3. **langchain-community sunset warning — advisory, carried to S3, not blocking.**
   The warning was reproduced verbatim. It is a `DeprecationWarning` at import, not a functional
   defect; `BM25Retriever` works. The decision (vendor a thin `rank_bm25` wrapper vs stay on
   langchain-community) belongs at **S3**, when `index.py` picks up the lexical half and
   `eval/run.py` is available to prove any swap is behaviour-neutral.

## Carry-forward

The next iteration (S1, `ingest.py`) must know:

- **`.venv` already exists at the project root**, CPython 3.11.15, 112 packages, `uv pip check`
  clean. Do not rebuild it. `source .venv/bin/activate`.
- **No `data/` directory yet.** Nothing ingested, nothing cached, no `manifest.json`.
  S1 creates `data/pdfs/` and `data/manifest.json` from scratch.
- **Not a git repository.** No `git init` has been run. The `.gitignore` is correct but untested
  in place — when someone does `git init`, run `git status` and confirm before the first commit.
- **Env var names S1 must read** (fixed by `.env.example`, do not invent new ones):
  `EWC_BASE_URL`, `EWC_USER_AGENT`, `EWC_CRAWL_DELAY` (default `0.6`, matching CLAUDE.md's
  `time.sleep(0.6)` etiquette rule), `EWC_DATA_DIR` (default `data`), plus
  `EWC_CHROMA_DIR`, `EWC_CHROMA_COLLECTION`, `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL`,
  `OPENAI_CHAT_MODEL` for later stages.
- **Open question awaiting the human — A5 key blocker looming at S3.** There is still no
  `OPENAI_API_KEY` and no `.env`. S1 and S2 do not need one. **S3 (`index.py`) cannot be verified
  without it and will return BLOCKED.** Get a key in place before S3 starts.
- **Open question awaiting the human — the `fitz`/`pymupdf` CLAUDE.md amendment** (Contract
  delta 1). Relevant at S2, not S1.
- **Open question awaiting the human — `OPENAI_CHAT_MODEL` default** (A1). Must be settled
  before S3.
- No destructive step has been run. `index.py` (which drops the Chroma collection) does not exist.

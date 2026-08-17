# EWC Rulebook RAG

A retrieval system over the **Esports World Cup 2026 competitive rulebooks** — one Global
Rulebook plus 24 per-game-title rulebooks, annexed to it, with a published amendments layer
on top.

The goal is a **compliance-grade** answering system, not a chatbot. A wrong answer about a
forfeit rule is worse than no answer, so **abstention is a success state** and every rule
claim carries a citation of the form `(Game — Article X.Y.Z, p.N)`.

`CLAUDE.md` is the project contract and the source of truth for how this is built. Read it
before changing anything.

---

## Status — read this before trusting an answer

This is a working system with **known, documented, open defects**. It is not fit for making
a real compliance decision today. The full history is in [`logs/`](logs/) — eleven verified
iterations, including four occasions where the verifier retracted its own earlier finding.

Currently open and blocking:

| | |
|---|---|
| **Cross-title misattribution** | Asked about one title while scoped to another, answers can present one book's rules under the other's name. Store-level filtering is clean — no foreign chunks are ever retrieved — but the *prose* mislabels them. The UI mitigates this with a banner computed independently of the answer text. |
| **Unstable eval gate** | The natural VAC-ban discriminator case passes ~7/9, so the gate passes roughly 47% of runs at the shipped default. |
| **`resolve` and amendments** | For an amended article, the group's scope is taken from the amendment, which hides the base Global article from precedence detection. |
| **Verbatim over-quoting** | Unmarked verbatim runs up to 90 words, against the "quote sparingly" rule. |
| **`grade` never built** | CLAUDE.md's LangGraph contract specifies a retrieval-sufficiency node that can route back to `retrieve`. It was deferred twice and does not exist; `tries` is dead state. |

---

## Architecture

```
ingest.py     discover + download rulebook PDFs      -> data/pdfs/, data/manifest.json
articles.py   scrape amendments / rulings            -> data/amendments.json
chunker.py    PDF -> article-aware Documents         (PyMuPDF; splits on article boundaries)
index.py      build Chroma collection + BM25 pickle  (destructive; re-embeds the corpus)
graph.py      LangGraph: route -> retrieve -> resolve -> answer
server.py     loopback HTTP API over graph.py
frontend/     React + Redux client
eval/         retrieval + faithfulness gate
```

Design decisions worth knowing:

- **Hybrid retrieval is mandatory.** Rule queries are token-exact ("Article 3.2.3",
  "forfeit", "10 minutes"), which dense-only retrieval measurably misses. Dense + BM25 are
  merged with Reciprocal Rank Fusion (k=60), then sorted by authority.
- **Article-aware chunking.** Splitting blindly by character count destroys the article
  numbering that makes an answer verifiable. Character splitting is a fallback for
  oversized articles only.
- **Authority is metadata, not prose.** `global=0`, `title=1`, `amendment=2`. Precedence is
  computed in `resolve` and handed to the answer prompt as a fact.
- **Scope filtering happens at the store**, never in the prompt.
- **The client never re-authors a claim.** A shipped test asserts the rendered answer's
  `textContent` equals the pipeline's output byte-for-byte; the only permitted transform is
  wrapping existing citation substrings in anchors.

## Corpus

Discovered at runtime — no CDN URL or game slug is ever hardcoded, because the PDF URLs are
content-hashed and change on re-upload. 25 rulebooks, 734 pages, 2,382 chunks. Overwatch 2
publishes its rulebook as a Google Doc rather than a PDF and is skipped and logged. One
title (`apex`) is a third-party EA document served from another host and flagged as such.

**PDFs are not committed.** They are the Esports Foundation's content; `ingest.py` fetches
them at build time with a polite serial crawl (identifying User-Agent, 0.6s delay).

## Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env          # add your OPENAI_API_KEY

python ingest.py              # ~25 PDFs, polite crawl, cached by content hash
python articles.py            # amendments layer
python index.py               # rebuild vector store (DESTRUCTIVE, re-embeds)

python -m graph "How long is a CS2 forfeit delay?" --game cs2
python eval/run.py --retrieval-only   # free; full run makes real API calls
```

Front-end:

```bash
cd frontend && npm install && npm run build && cd ..
python server.py              # 127.0.0.1:8000
```

The server binds loopback only and serves locally-cached PDFs. **Do not expose it beyond
localhost.**

## Cost

Every question is a real OpenAI call. Embedding the full corpus costs about $0.006; a single
question costs roughly $0.0008–$0.0014. `index.py` prints a cost estimate and refuses to
exceed `--max-usd`; the server enforces per-day and per-conversation ceilings that refuse
*before* any model call.

## How this was built

Via a sequential agent loop — builder → verifier → logger — where the verifier independently
re-derives every claim rather than accepting the builder's report, and the logger records
what actually happened including failures. Agent definitions are in
[`.claude/agents/`](.claude/agents/). Each iteration is logged in [`logs/`](logs/) with its
verdict, evidence, and open findings.

Several defects in this repo were caught only because the verifier disproved a builder's
claim; several findings were later retracted when re-measurement showed the verifier itself
was wrong. Both directions are preserved in the logs rather than edited away.

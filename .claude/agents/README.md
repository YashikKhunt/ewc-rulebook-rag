# EWC RAG build loop

Three agents, run strictly in order, one stage of `CLAUDE.md`'s build order per pass:

```
        ┌──────────────────────────────────────────────┐
        │                                              │
        ▼                                              │
  ewc-builder ──► ewc-verifier ──► ewc-logger ─────────┤
   writes code     PASS/FAIL        logs/NNN-*.md      │
                   evidence         + INDEX.md          │
                                                        │
   FAIL → repair the same stage ────────────────────────┘
   PASS → advance to the next stage
   BLOCKED → halt, surface to the human
```

## Stages (from `CLAUDE.md` § Build order)

| Stage | Deliverable |
|-------|-------------|
| S0 | `requirements.txt`, `.gitignore`, `.env.example` |
| S1 | `ingest.py` → `data/pdfs/`, `data/manifest.json` |
| S2 | `chunker.py` — article-aware chunks, >80% article coverage on Global |
| S3 | `index.py` + bare retrieve-and-answer path |
| S4 | `eval/queries.yaml` + `eval/run.py` — normal / cross-scope / conflict |
| S5 | `articles.py` + `resolve` node + full `graph.py` |
| S6 | UI — only after S4 passes |

## Running a pass

Invoke the agents by name in sequence, carrying each one's report into the next:

```
Use ewc-builder to implement S1.
Then use ewc-verifier to verify S1.
Then use ewc-logger to record the iteration.
```

Loop control lives with the orchestrator (main session or `/loop`), not inside the agents:
the builder never grades itself, the verifier never patches code, the logger never leaves
`logs/`.

## Invariants

- `CLAUDE.md` is the specification. Only the human changes it; a contradiction found during
  a pass gets logged under **Contract deltas**, not silently resolved.
- A stage advances only on an explicit `VERDICT: PASS`.
- A check that could not be executed is `BLOCKED`, never a `PASS`.
- Repairs touch only the findings named in the verdict.

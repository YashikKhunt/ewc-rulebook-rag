"""Build the retrieval index for the EWC rulebook corpus.

Two artefacts, both derived from ``chunker.chunk_corpus()`` in a single pass so the
dense and lexical halves of the hybrid retriever can never drift apart:

    data/chroma/            Chroma collection (dense vectors, OpenAI embeddings)
    data/chunks.pkl         the same Document list, pickled, for BM25 (lexical)

**This script is destructive.** It drops the Chroma collection named by
``EWC_CHROMA_COLLECTION`` before rebuilding it. Re-running it re-embeds the whole
corpus and therefore costs money.

Cost discipline
---------------
Embedding is the only large spend in this project. Before any network call the
script counts the exact tokens it is about to send with ``tiktoken`` and prints the
dollar figure at the model's published price. If the estimate exceeds ``--max-usd``
(default $0.50) it refuses to run. ``--estimate`` stops after the estimate and makes
no network call at all.

Usage
-----
    python index.py --estimate          # chunk + count tokens + price it, no network
    python index.py                     # destructive rebuild
    python index.py --max-usd 0.10      # tighter budget ceiling
    python index.py --games global cs2  # partial corpus (still drops the collection)
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from langchain_core.documents import Document

from articles import amendment_documents
from chunker import chunk_corpus, coverage, validate

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Prices, in USD per 1M tokens, as published by OpenAI. Used only for the
# estimate and the spend report -- never for a decision the human did not make.
# ---------------------------------------------------------------------------
EMBEDDING_PRICE_PER_1M = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}

DEFAULT_MAX_USD = 0.50
ADD_BATCH = 200          # documents per Chroma add_documents call
EMBED_BATCH = 256        # texts per OpenAI embeddings request


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


def chunks_pickle_path() -> Path:
    return ROOT / _env("EWC_DATA_DIR", "data") / "chunks.pkl"


def stats_path() -> Path:
    return ROOT / _env("EWC_DATA_DIR", "data") / "index_stats.json"


def chroma_dir() -> Path:
    return ROOT / _env("EWC_CHROMA_DIR", "data/chroma")


def collection_name() -> str:
    return _env("EWC_CHROMA_COLLECTION", "ewc_rulebooks")


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def count_tokens(texts: Sequence[str], model: str) -> list[int]:
    """Exact per-text token counts for the embedding model."""
    import tiktoken

    try:
        encoder = tiktoken.encoding_for_model(model)
    except KeyError:
        encoder = tiktoken.get_encoding("cl100k_base")
    return [len(encoder.encode(text)) for text in texts]


def estimate(docs: Sequence[Document], model: str) -> dict:
    """Token counts and dollar cost for embedding ``docs`` exactly once."""
    counts = count_tokens([d.page_content for d in docs], model)
    total = sum(counts)
    price = EMBEDDING_PRICE_PER_1M.get(model)
    return {
        "model": model,
        "documents": len(docs),
        "tokens": total,
        "tokens_max": max(counts) if counts else 0,
        "tokens_mean": round(total / len(counts), 1) if counts else 0.0,
        "price_per_1m_usd": price,
        "usd": None if price is None else round(price * total / 1_000_000, 6),
        "over_context": sum(1 for c in counts if c > 8191),
    }


def print_estimate(report: dict) -> None:
    print("\nEMBEDDING COST ESTIMATE (tiktoken, exact input tokens)")
    print(f"  model              {report['model']}")
    print(f"  documents          {report['documents']}")
    print(f"  input tokens       {report['tokens']:,}")
    print(f"  mean / max tokens  {report['tokens_mean']} / {report['tokens_max']}")
    if report["over_context"]:
        print(f"  !! {report['over_context']} chunks exceed the 8191-token input limit")
    if report["usd"] is None:
        print(f"  price              UNKNOWN for {report['model']} -- refusing to guess")
    else:
        print(f"  price              ${report['price_per_1m_usd']}/1M tokens")
        print(f"  ESTIMATED COST     ${report['usd']:.6f}")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def drop_collection(directory: Path, name: str) -> bool:
    """Delete the collection if it exists. Returns True if something was dropped."""
    import chromadb

    directory.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(directory))
    existing = {c.name for c in client.list_collections()}
    if name in existing:
        client.delete_collection(name)
        return True
    return False


def build(docs: Sequence[Document], embedding_model: str) -> dict:
    """Embed and persist. Assumes the caller has already approved the spend."""
    from langchain_chroma import Chroma
    from langchain_openai import OpenAIEmbeddings

    directory, name = chroma_dir(), collection_name()
    dropped = drop_collection(directory, name)
    print(f"  dropped existing collection: {dropped}")

    embeddings = OpenAIEmbeddings(model=embedding_model, chunk_size=EMBED_BATCH)
    store = Chroma(
        collection_name=name,
        embedding_function=embeddings,
        persist_directory=str(directory),
    )

    started = time.time()
    for start in range(0, len(docs), ADD_BATCH):
        batch = list(docs[start:start + ADD_BATCH])
        store.add_documents(batch, ids=[d.metadata["chunk_id"] for d in batch])
        print(f"  embedded {min(start + ADD_BATCH, len(docs)):5d}/{len(docs)}",
              flush=True)
    elapsed = time.time() - started

    count = store._collection.count()
    return {"collection": name, "directory": str(directory), "count": count,
            "seconds": round(elapsed, 1)}


def write_pickle(docs: Sequence[Document]) -> Path:
    """Persist the same Document list BM25 will score against."""
    path = chunks_pickle_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        pickle.dump(list(docs), handle, protocol=pickle.HIGHEST_PROTOCOL)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--estimate", action="store_true",
                        help="count tokens and price the build, then exit (no network)")
    parser.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD,
                        help=f"refuse to embed above this estimate (default {DEFAULT_MAX_USD})")
    parser.add_argument("--games", nargs="*", default=None,
                        help="limit to these manifest slugs (still drops the collection)")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    embedding_model = _env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    print("chunking corpus ...", flush=True)
    docs = chunk_corpus(games=args.games)
    pdf_chunks = len(docs)

    # The amendment layer (S5). CLAUDE.md: the PDFs are not the whole truth --
    # a published amendment can supersede a PDF article, and a PDF-only index
    # states the superseded rule with full confidence. Amendment documents are
    # built by articles.py from data/amendments.json and validated by the SAME
    # chunker.validate() as the PDF chunks, so a missing metadata key fails the
    # build rather than reaching the store. Absent that file the build proceeds
    # PDF-only and says so, rather than failing.
    amendments = [] if args.games else amendment_documents()
    if args.games and amendment_documents():
        print("  --games given: amendment documents are EXCLUDED from this partial build")
    docs = list(docs) + list(amendments)
    print(f"  {pdf_chunks} PDF chunks + {len(amendments)} amendment chunk(s)")

    problems = validate(docs)
    print(f"  {len(docs)} chunks, {len(problems)} metadata violations")
    if problems:
        for problem in problems[:10]:
            print("  !", problem)
        print("refusing to index a corpus that fails chunker.validate()")
        return 1

    stats = coverage(docs)
    with_article = sum(1 for d in docs if d.metadata["article"])
    print(f"  {len(stats)} books, {with_article} chunks with an article "
          f"({100.0 * with_article / len(docs):.1f}%)")

    report = estimate(docs, embedding_model)
    print_estimate(report)

    if args.estimate:
        print("\n--estimate: stopping before any network call.")
        return 0

    if report["usd"] is None:
        print("\nrefusing to spend against an unpriced model. Set OPENAI_EMBEDDING_MODEL "
              "to a model listed in EMBEDDING_PRICE_PER_1M, or add its price.")
        return 2
    if report["usd"] > args.max_usd:
        print(f"\nESTIMATE ${report['usd']:.4f} EXCEEDS --max-usd ${args.max_usd:.4f}. "
              "Refusing to embed. Re-run with a higher ceiling if this is intended.")
        return 2
    if not os.getenv("OPENAI_API_KEY"):
        print("\nOPENAI_API_KEY is not set. Cannot embed.")
        return 2

    print(f"\nDESTRUCTIVE: dropping collection {collection_name()!r} in {chroma_dir()} "
          "and re-embedding the corpus.")
    built = build(docs, embedding_model)
    print(f"  collection {built['collection']}: {built['count']} vectors "
          f"in {built['seconds']}s")

    pickle_path = write_pickle(docs)
    print(f"  BM25 corpus pickled: {pickle_path} ({pickle_path.stat().st_size:,} bytes)")

    payload = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "chunks": len(docs),
        "with_article": with_article,
        "books": len(stats),
        "embedding": report,
        "chroma": built,
        "chunks_pickle": str(pickle_path),
    }
    with open(stats_path(), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    print(f"  wrote {stats_path()}")

    if built["count"] != len(docs):
        print(f"  ! collection holds {built['count']} vectors for {len(docs)} chunks")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

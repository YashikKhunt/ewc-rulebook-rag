"""HTTP layer over the LangGraph pipeline -- the API `frontend/` talks to.

A separate module, per CLAUDE.md's repo layout. It **imports** `graph.py` and
calls its nodes; it never reshapes what the pipeline decides or says. Everything
here is either a read-only derivation over `graph`'s output, or plumbing the
pipeline has no opinion about (history, budget, PDF bytes, page labels).

    python server.py                 # http://127.0.0.1:8000
    python server.py --port 8123
    python server.py --budget-day 0.10

Design contract: `frontend/DESIGN.md` §7. The FLAGs it raises are answered here:

    7.1  outcome            graph.answer() now returns it        (graph.py change)
    7.2  citation_spans     graph.citation_spans()               (graph.py change)
    7.3  forced_scope       echoed from the request              (here)
    7.4  cost_usd           graph.CHAT_PRICE_PER_1M x state.usage (here, chat only)
    7.5  retried            derived from usage node names        (here)
    7.6  note               returned, for the developer drawer   (here)
    7.7  page labels        PyMuPDF scan, cached                 (here)
    7.8  corpus_fingerprint chunks.pkl sha256, first 8 hex       (here)
    7.9  aliases            derived from the corpus + manifest   (here)
    7.10 phase events       LangGraph .stream() wrapped as SSE   (here)
    7.11 books with no PDF  manifest.skipped                     (here)

Three things this module deliberately does NOT do
-------------------------------------------------
* **It never caches an answer against a question.** CLAUDE.md forbids it -- the
  corpus is versioned. History stores *records*; there is no question->answer
  lookup path anywhere in this file. A stored turn carries the corpus
  fingerprint it was produced under so a stale record can be MARKED rather than
  quietly reused.
* **It never re-indexes.** It reads `data/chunks.pkl` and the Chroma directory
  and writes to neither.
* **It never sends the OpenAI key anywhere near the browser.** Every model call
  happens in this process.

Cost discipline
---------------
A UI invites far more querying than a CLI does, so a spend ceiling is enforced
HERE, before any chat completion, in the same shape as `index.py --max-usd`:
count what the call could cost, compare against what has already been spent, and
refuse with an explanation rather than spending. Two independent ceilings, both
env-configurable: per calendar day and per conversation. `Search only` with a
forced scope makes ZERO chat completions and is not gated by them.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from dotenv import load_dotenv

import graph

ROOT = Path(__file__).resolve().parent
DATA = ROOT / graph._env("EWC_DATA_DIR", "data")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[server] {name}={raw!r} is not a number; using {default}", file=sys.stderr)
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ---------------------------------------------------------------------------
# Budget -- refuses BEFORE the model call, never after
# ---------------------------------------------------------------------------

class Budget:
    """Two ceilings, both checked before any chat completion is issued.

    `estimate_usd` is the figure a single question is *assumed* to cost when
    deciding whether to allow it. It is deliberately several times the measured
    cost of a real question (~$0.0004 on gpt-4o-mini) so the guard errs toward
    refusing. Refusing costs the user a message; spending past the ceiling costs
    real money that cannot be recovered.

    `prior_usd` is spend this database never saw -- the ~$0.57 the project spent
    at S0-S5, so the ledger reads against the true project total rather than
    pretending the meter starts at zero when the server does.
    """

    def __init__(self) -> None:
        self.day_usd = _env_float("EWC_BUDGET_DAY_USD", 0.50)
        self.conversation_usd = _env_float("EWC_BUDGET_CONVERSATION_USD", 0.25)
        self.estimate_usd = _env_float("EWC_BUDGET_ESTIMATE_USD", 0.0015)
        self.prior_usd = _env_float("EWC_BUDGET_PRIOR_USD", 0.5681)
        self.project_usd = _env_float("EWC_BUDGET_PROJECT_USD", 5.00)

    def check(self, conversation_id: str | None) -> dict | None:
        """None when the call may proceed; a refusal dict when it may not."""
        today = spend_on(_today())
        if today + self.estimate_usd > self.day_usd:
            return {
                "scope": "day",
                "ceiling_usd": self.day_usd,
                "spent_usd": round(today, 6),
                "estimate_usd": self.estimate_usd,
                "message": (
                    f"Refused before calling the model. Today's spend is "
                    f"${today:.4f} and this question is budgeted at "
                    f"${self.estimate_usd:.4f}, which would exceed the daily "
                    f"ceiling of ${self.day_usd:.4f}. Raise it with "
                    f"EWC_BUDGET_DAY_USD, or ask again tomorrow. Search only "
                    f"with a scope set is unaffected -- it makes no model call."
                ),
            }
        if conversation_id:
            spent = spend_in_conversation(conversation_id)
            if spent + self.estimate_usd > self.conversation_usd:
                return {
                    "scope": "conversation",
                    "ceiling_usd": self.conversation_usd,
                    "spent_usd": round(spent, 6),
                    "estimate_usd": self.estimate_usd,
                    "message": (
                        f"Refused before calling the model. This conversation has "
                        f"spent ${spent:.4f} against a ceiling of "
                        f"${self.conversation_usd:.4f}. Start a new conversation, "
                        f"or raise EWC_BUDGET_CONVERSATION_USD."
                    ),
                }
        return None

    def snapshot(self, conversation_id: str | None = None) -> dict:
        today = spend_on(_today())
        return {
            "day_usd": self.day_usd,
            "day_spent_usd": round(today, 6),
            "conversation_usd": self.conversation_usd,
            "conversation_spent_usd": (
                round(spend_in_conversation(conversation_id), 6)
                if conversation_id else None
            ),
            "estimate_usd": self.estimate_usd,
            "session_usd": round(spend_all(), 6),
            "prior_usd": self.prior_usd,
            "project_spent_usd": round(self.prior_usd + spend_all(), 6),
            "project_usd": self.project_usd,
            "refused": bool(self.check(conversation_id)),
        }


BUDGET = Budget()


# ---------------------------------------------------------------------------
# History -- server-side SQLite. A record store, never a cache.
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation (
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turn (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  asked_at TEXT NOT NULL,
  question TEXT NOT NULL,
  response_json TEXT NOT NULL,
  corpus_fingerprint TEXT NOT NULL,
  cost_usd REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS turn_seq ON turn(conversation_id, seq);
CREATE INDEX IF NOT EXISTS turn_asked_at ON turn(asked_at);
"""

_DB_LOCK = threading.Lock()


def db() -> sqlite3.Connection:
    path = DATA / graph._env("EWC_HISTORY_DB", "history.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _DB_LOCK, db() as conn:
        conn.executescript(SCHEMA)


def spend_on(day: str) -> float:
    with db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM turn WHERE substr(asked_at,1,10) = ?",
            (day,)).fetchone()
    return float(row["s"])


def spend_in_conversation(conversation_id: str) -> float:
    with db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM turn WHERE conversation_id = ?",
            (conversation_id,)).fetchone()
    return float(row["s"])


def spend_all() -> float:
    with db() as conn:
        row = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) AS s FROM turn").fetchone()
    return float(row["s"])


def create_conversation(title: str) -> dict:
    now = _now()
    cid = _id("c")
    with _DB_LOCK, db() as conn:
        conn.execute(
            "INSERT INTO conversation (id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (cid, title[:60] or "Untitled enquiry", now, now))
    return conversation_summary(cid)


def conversation_summary(cid: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM conversation WHERE id = ?", (cid,)).fetchone()
        if not row:
            return None
        turns = conn.execute(
            "SELECT response_json, corpus_fingerprint FROM turn "
            "WHERE conversation_id = ? ORDER BY seq", (cid,)).fetchall()
    scopes: list[str] = []
    stale = False
    live = corpus_fingerprint()
    for t in turns:
        if t["corpus_fingerprint"] != live:
            stale = True
        try:
            payload = json.loads(t["response_json"])
        except json.JSONDecodeError:
            continue
        for doc in payload.get("docs") or []:
            slug = doc.get("game")
            if slug and slug not in scopes:
                scopes.append(slug)
    return {
        "id": row["id"], "title": row["title"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "turn_count": len(turns), "scopes": scopes, "stale": stale,
    }


def list_conversations() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id FROM conversation ORDER BY updated_at DESC").fetchall()
    return [s for s in (conversation_summary(r["id"]) for r in rows) if s]


def load_conversation(cid: str) -> dict | None:
    """A pure read. Never invokes the pipeline; never spends."""
    summary = conversation_summary(cid)
    if not summary:
        return None
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM turn WHERE conversation_id = ? ORDER BY seq", (cid,)).fetchall()
    turns = []
    for row in rows:
        payload = json.loads(row["response_json"])
        payload["stale"] = row["corpus_fingerprint"] != corpus_fingerprint()
        turns.append(payload)
    return {**summary, "turns": turns}


def record_turn(cid: str, payload: dict) -> None:
    now = _now()
    with _DB_LOCK, db() as conn:
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM turn WHERE conversation_id = ?",
            (cid,)).fetchone()["n"]
        conn.execute(
            "INSERT INTO turn (id, conversation_id, seq, asked_at, question, "
            "response_json, corpus_fingerprint, cost_usd) VALUES (?,?,?,?,?,?,?,?)",
            (payload["turn_id"], cid, seq, payload["asked_at"], payload["question"],
             json.dumps(payload), payload["corpus_fingerprint"],
             float(payload.get("cost_usd") or 0.0)))
        conn.execute("UPDATE conversation SET updated_at = ? WHERE id = ?", (now, cid))


def rename_conversation(cid: str, title: str) -> dict | None:
    with _DB_LOCK, db() as conn:
        cur = conn.execute("UPDATE conversation SET title = ?, updated_at = ? WHERE id = ?",
                           (title[:60] or "Untitled enquiry", _now(), cid))
        if not cur.rowcount:
            return None
    return conversation_summary(cid)


def delete_conversation(cid: str) -> bool:
    with _DB_LOCK, db() as conn:
        cur = conn.execute("DELETE FROM conversation WHERE id = ?", (cid,))
        conn.execute("DELETE FROM turn WHERE conversation_id = ?", (cid,))
        return bool(cur.rowcount)


# ---------------------------------------------------------------------------
# Corpus, catalog, fingerprint
# ---------------------------------------------------------------------------

_FINGERPRINT: str | None = None
_MANIFEST: dict | None = None
_CATALOG: list[dict] | None = None


def corpus_fingerprint() -> str:
    """First 8 hex of the chunks.pkl sha256 (FLAG 7.8). Computed once: the file
    is an input to this process, and a change to it means the server should be
    restarted anyway."""
    global _FINGERPRINT
    if _FINGERPRINT is None:
        path = DATA / "chunks.pkl"
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        _FINGERPRINT = digest.hexdigest()[:8]
    return _FINGERPRINT


def manifest() -> dict:
    global _MANIFEST
    if _MANIFEST is None:
        path = DATA / "manifest.json"
        _MANIFEST = json.loads(path.read_text()) if path.exists() else {
            "documents": [], "skipped": []}
    return _MANIFEST


# Words that carry no discriminating power as a one-word book alias. Derived
# aliases that reduce to one of these are dropped: matching "fire" or "women"
# anywhere in a question would fire the mismatch banner constantly, and a guard
# that cries wolf is a guard the user learns to ignore.
_ALIAS_STOP = frozenset("""
free fire fatal fury kings honor arena valor women mobile legends world cup
sports the and pro open esports rulebook global bang tactics league siege
street fighter ops competitive
""".split())

# An alias shorter than this is not evidence that a question named a book --
# "ff" and "rl" occur inside ordinary prose far more often than they name Free
# Fire or Rocket League, and a guard that fires on noise is a guard the user
# stops reading.
_ALIAS_MIN = 3


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _derived_aliases(slug: str, game_title: str, doc_title: str,
                     detail_url: str, other_slugs: frozenset[str] = frozenset()) -> set[str]:
    """Everything the corpus and the manifest already say a book is called.

    Nothing here is a literal: the slug list, the published titles and the
    detail-page paths are all read at runtime from `graph.catalog()` and
    `data/manifest.json`, so a re-crawl that renames or adds a title is picked
    up with no code change (CLAUDE.md: don't hardcode the slug list)."""
    out: set[str] = set()
    for source in (slug, game_title, doc_title):
        flat = _slugify(source or "")
        if len(flat) >= _ALIAS_MIN:
            out.add(flat)
    # Only a detail page that actually addresses a book -- the Global Rulebook's
    # `detail_url` is the section listing page, whose tail names no title.
    if "/rulebooks/" in detail_url:
        tail = _slugify(detail_url.rstrip("/").rsplit("/", 1)[-1])
        if len(tail) >= _ALIAS_MIN:
            out.add(tail)
    # Hyphen/segment parts of the slug -- "tekken" from "tekken-8" -- but only
    # where the part is long enough to be a name, is not a generic word, and is
    # not ANOTHER book's whole slug. That last guard is what keeps "mlbb" a name
    # for `mlbb` rather than a word both `mlbb` and `mlbb-women` answer to, and
    # likewise "pubg" for `pubg` rather than `pubg-mobile`. Without it the two
    # cancel each other out as ambiguous and the guard goes quiet on exactly the
    # sibling-book pairs log 009's B-2 reproduces on.
    for part in re.split(r"[^a-z0-9]+", slug.lower()):
        if (len(part) >= _ALIAS_MIN and part not in _ALIAS_STOP
                and part not in other_slugs):
            out.add(part)
    return {a for a in out if a and not (len(a.split()) == 1 and a in _ALIAS_STOP)}


def _supplement() -> dict[str, list[str]]:
    """`data/aliases.json`, an optional hand-checked supplement (human ruling 1,
    S6b). It is DATA compared against runtime-derived slugs, never routing logic:
    every key is checked against `graph.catalog()` and a key naming a slug that
    does not exist is dropped with a warning rather than trusted. Absent file =>
    derived aliases only, and the mismatch guard degrades gracefully."""
    # `data/` is gitignored (it holds Esports Foundation PDFs), so a supplement
    # kept only there is operator-local and does not survive a fresh clone. That
    # is tolerable -- the guard degrades to derived aliases -- but the operator
    # should be able to version one if they want to, so a repo-root copy is also
    # honoured. `data/` wins where both exist.
    path = next((p for p in (DATA / "aliases.json", ROOT / "aliases.json") if p.exists()), None)
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[server] ignoring {path}: {exc}", file=sys.stderr)
        return {}
    known = {slug for slug, _ in graph.catalog()}
    aliases = raw.get("aliases") if isinstance(raw, dict) else None
    if not isinstance(aliases, dict):
        return {}
    out: dict[str, list[str]] = {}
    for slug, words in aliases.items():
        if slug not in known:
            print(f"[server] {path.name}: unknown slug {slug!r} -- ignored "
                  f"(it is not in the indexed corpus)", file=sys.stderr)
            continue
        if isinstance(words, list):
            kept = [_slugify(str(w)) for w in words if str(w).strip()]
            out[slug] = [w for w in kept if len(w) >= _ALIAS_MIN]
    return out


def catalog() -> list[dict]:
    """Every book the UI may name: the 24 indexed title books, the Global
    Rulebook, and the ones with no PDF (FLAG 7.11) marked `in_corpus: false`.

    Aliases that resolve to MORE THAN ONE book are dropped from all of them.
    "call of duty" is the live case: it prefixes both `cod-mw3` (Black Ops 7)
    and `warzone`, so it cannot discriminate between them and a banner fired on
    it would be noise. An alias only earns its place if it names one book."""
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG

    chunks = graph.load_chunks()
    counts: dict[str, int] = {}
    titles: dict[str, str] = {}
    for doc in chunks:
        meta = doc.metadata
        slug = meta.get("game")
        counts[slug] = counts.get(slug, 0) + 1
        if meta.get("scope") in ("global", "title"):
            titles.setdefault(slug, meta.get("game_title") or slug)

    by_slug = {d["game"]: d for d in manifest().get("documents", [])}
    supplement = _supplement()

    all_slugs = frozenset(titles) | {
        s.get("game") for s in manifest().get("skipped", []) if s.get("game")}

    books: list[dict] = []
    for slug, title in sorted(titles.items()):
        entry = by_slug.get(slug, {})
        aliases = _derived_aliases(slug, title, entry.get("doc_title") or "",
                                   entry.get("detail_url") or "",
                                   all_slugs - {slug})
        aliases |= set(supplement.get(slug, []))
        books.append({
            "slug": slug,
            "game_title": title,
            "scope": "global" if slug == "global" else "title",
            "authority": 0 if slug == "global" else 1,
            "in_corpus": True,
            "chunk_count": counts.get(slug, 0),
            "version": entry.get("version") or "",
            "effective_date": entry.get("effective_date") or "",
            "source_url": entry.get("source_url") or "",
            "detail_url": entry.get("detail_url") or "",
            "external_host": bool(entry.get("external_host")),
            "sha256": entry.get("sha256") or "",
            "downloaded_at": entry.get("downloaded_at") or "",
            "source_available": bool(pdf_path(slug)),
            "skip_reason": None,
            "aliases": sorted(aliases),
        })

    for skipped in manifest().get("skipped", []):
        books.append({
            "slug": skipped.get("game"),
            "game_title": skipped.get("game_title") or skipped.get("game"),
            "scope": "title", "authority": 1,
            "in_corpus": False, "chunk_count": 0,
            "version": "", "effective_date": "", "source_url": skipped.get("url") or "",
            "detail_url": skipped.get("detail_url") or "", "external_host": False,
            "sha256": "", "downloaded_at": "", "source_available": False,
            "skip_reason": skipped.get("reason") or "not published as a PDF",
            "aliases": sorted(_derived_aliases(
                skipped.get("game") or "", skipped.get("game_title") or "", "",
                skipped.get("detail_url") or "",
                all_slugs - {skipped.get("game")})),
        })

    # Drop aliases that name more than one book -- they cannot discriminate.
    seen: dict[str, int] = {}
    for book in books:
        for alias in book["aliases"]:
            seen[alias] = seen.get(alias, 0) + 1
    for book in books:
        book["aliases"] = [a for a in book["aliases"] if seen[a] == 1]

    _CATALOG = books
    return _CATALOG


def corpus_info() -> dict:
    chunks = graph.load_chunks()
    books = catalog()
    amendments = sum(1 for d in chunks if d.metadata.get("scope") == "amendment")
    return {
        "chunks": len(chunks),
        "books": sum(1 for b in books if b["in_corpus"]),
        "amendments": amendments,
        "fingerprint": corpus_fingerprint(),
        "chat_model": graph._env("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        "embedding_model": graph._env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        "catalog": books,
        # Stated so the UI can say it rather than imply otherwise: this pipeline
        # has no conversation memory and no retrieval-sufficiency grade.
        "pipeline_nodes": ["route", "retrieve", "resolve", "answer"],
        "known_gaps": [
            "grade (retrieval sufficiency) is not built -- log 009, verifier ruling 3",
            "B-2 cross-title misattribution is open -- the answer prose can name a "
            "title whose rulebook was not searched (log 009)",
        ],
    }


# ---------------------------------------------------------------------------
# Local PDFs -- OPERATOR-LOCAL ACCESS ONLY
# ---------------------------------------------------------------------------
#
# These PDFs are Esports Foundation content. CLAUDE.md declines to redistribute
# them: they are gitignored and ingested at build time, never committed. Serving
# the LOCALLY INDEXED copy to the operator's own browser, over loopback, is not
# redistribution -- it is the operator reading the file already on their disk,
# and it is the ONLY copy for which a cited page number is guaranteed correct
# (the publisher silently re-uploaded the Global Rulebook mid-project; see log
# 009). The publisher's own URL is offered alongside as a labelled external link
# so the user can always reach the canonical copy.
#
# THIS MUST NOT BE DEPLOYED BEYOND LOCALHOST. The server binds 127.0.0.1 and
# `_is_local` rejects any non-loopback client, so exposing it would take a
# deliberate change here plus a deliberate change to the bind address. If this
# ever needs to serve another machine, the content-ownership question has to be
# answered first -- it is not answered by this code.

_PAGE_LABELS: dict[str, list[dict]] | None = None
_PAGE_COUNTS: dict[str, int] = {}


def pdf_path(slug: str) -> Path | None:
    for entry in manifest().get("documents", []):
        if entry.get("game") == slug:
            path = ROOT / str(entry.get("path") or "")
            return path if path.is_file() else None
    return None


def page_count(slug: str) -> int | None:
    if slug in _PAGE_COUNTS:
        return _PAGE_COUNTS[slug]
    path = pdf_path(slug)
    if not path:
        return None
    import pymupdf

    with pymupdf.open(path) as doc:
        _PAGE_COUNTS[slug] = doc.page_count
    return _PAGE_COUNTS[slug]


# The shapes these 25 books actually print, measured against the PDFs:
#   "- 5 -"  "5"  "Page 11 of 32"  "Page 11"  "11 of 32"
# Anything else is not treated as a page number. Reporting "no printed page
# number appears on this page" for a page that plainly prints one is a
# fabricated absence, which is exactly what this UI must not do -- so the
# pattern is kept wide enough to cover the real footers and narrow enough that
# a stray figure in body text is not mistaken for one.
_FOOTER = re.compile(
    r"^[\s\-–—_.·|]*(?:page\s*)?(\d{1,4})(?:\s*(?:of|/)\s*\d{1,4})?[\s\-–—_.·|]*$", re.I)

# Zero-width and BOM characters. `honor-of-kings` prints its footers as
# "- 2 -​", and U+200B is category Cf, so `\s` does not match it -- without
# stripping these the footer scan reports "no printed page number appears on this
# page" for pages that plainly print one. Claiming an absence that is not there
# is exactly the fabrication this UI is supposed to avoid.
_INVISIBLE = str.maketrans("", "", "​‌‍⁠﻿")


def page_labels(slug: str) -> list[dict]:
    """Printed page numbers OBSERVED in each page's footer (FLAG 7.7).

    Reported as an observation of a page, never as a locator. DESIGN.md §6.1 is
    the reason: printed numbering across these books is not an invertible
    function -- 8 books print nothing at all, and `honor-of-kings` is two
    documents in one file where printed labels 1-5 each land on TWO different
    physical pages. So `ambiguous` is set for any label seen on more than one
    physical page, and the UI says so instead of offering a converter.

    Computed once per book with PyMuPDF and cached to data/page_labels.json. No
    network, no model call, no effect on the index."""
    global _PAGE_LABELS
    if _PAGE_LABELS is None:
        cache = DATA / "page_labels.json"
        try:
            _PAGE_LABELS = json.loads(cache.read_text()) if cache.exists() else {}
        except (OSError, json.JSONDecodeError):
            _PAGE_LABELS = {}
    if slug in _PAGE_LABELS:
        return _PAGE_LABELS[slug]

    path = pdf_path(slug)
    if not path:
        return []
    import pymupdf

    observed: list[dict] = []
    with pymupdf.open(path) as doc:
        _PAGE_COUNTS[slug] = doc.page_count
        for n in range(doc.page_count):
            text = doc[n].get_text("text").translate(_INVISIBLE)
            label = None
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            for line in reversed(lines[-3:]):
                if _FOOTER.match(line):
                    label = line
                    break
            observed.append({"physical": n + 1, "footer_label": label,
                             "ambiguous": False})

    counts: dict[str, int] = {}
    for row in observed:
        if row["footer_label"]:
            counts[row["footer_label"]] = counts.get(row["footer_label"], 0) + 1
    for row in observed:
        row["ambiguous"] = bool(row["footer_label"]) and counts[row["footer_label"]] > 1

    _PAGE_LABELS[slug] = observed
    try:
        (DATA / "page_labels.json").write_text(json.dumps(_PAGE_LABELS))
    except OSError as exc:
        print(f"[server] could not cache page labels: {exc}", file=sys.stderr)
    return observed


# ---------------------------------------------------------------------------
# Serialising what the pipeline produced
# ---------------------------------------------------------------------------

def doc_json(doc) -> dict:
    """A chunk's metadata VERBATIM plus its text, plus two server-computed
    fields. Nothing is defaulted or invented: an empty `version` stays empty and
    the UI renders it as `unstated`, which is the truth for 24 of 25 books."""
    meta = dict(doc.metadata)
    slug = meta.get("game")
    is_pdf = str(meta.get("source_path") or "").endswith(".pdf")
    return {
        **meta,
        "page_content": doc.page_content,
        "source_available": bool(is_pdf and pdf_path(slug)),
        "page_count": page_count(slug) if is_pdf else None,
    }


def chat_cost(usage: Iterable[dict]) -> float | None:
    """Chat spend only (FLAG 7.4). Embedding spend for the retrieval leg is not
    tracked by the pipeline, so it is NOT folded in and NOT guessed -- the figure
    is labelled `chat only` in the response so the ledger under-reports openly
    rather than silently."""
    model = graph._env("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    price = graph.CHAT_PRICE_PER_1M.get(model)
    if price is None:
        return None
    rate_in, rate_out = price
    rows = list(usage or [])
    tin = sum(int(u.get("input", 0)) for u in rows)
    tout = sum(int(u.get("output", 0)) for u in rows)
    return (rate_in * tin + rate_out * tout) / 1_000_000


def response_json(state: dict, *, question: str, forced_scope: bool,
                  generated: bool, duration_ms: int,
                  conversation_id: str, turn_id: str, asked_at: str) -> dict:
    docs = list(state.get("docs") or [])
    answer_text = state.get("answer")
    usage = list(state.get("usage") or [])
    return {
        "turn_id": turn_id,
        "conversation_id": conversation_id,
        "asked_at": asked_at,
        "question": question,
        "mode": "ask" if generated else "search",

        "outcome": state.get("outcome") if generated else None,
        "answer": answer_text if generated else None,
        "citation_spans": (graph.citation_spans(answer_text, docs)
                           if generated and answer_text else []),

        "game": state.get("game"),
        "forced_scope": forced_scope,
        "scope": state.get("scope"),
        "query": state.get("query"),

        "docs": [doc_json(d) for d in docs],
        "ranks": dict(state.get("ranks") or {}),
        "accountable": list(state.get("accountable") or []),
        "findings": list(state.get("conflicts") or []),
        "top_findings": list(state.get("top_findings") or []),
        "note": state.get("note") or "",
        "citation_errors": list(state.get("citation_errors") or []),

        "usage": usage,
        "cost_usd": chat_cost(usage),
        "cost_basis": "chat only; retrieval embeddings are not metered by the pipeline",
        "model": graph._env("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        "duration_ms": duration_ms,
        # FLAG 7.5 -- the pipeline's one bounded retry fired iff it logged a
        # second `answer.recite` usage row. Derived, not a pipeline change.
        "retried": any(u.get("node") == "answer.recite" for u in usage),
        "corpus_fingerprint": corpus_fingerprint(),
    }


# ---------------------------------------------------------------------------
# Running the pipeline
# ---------------------------------------------------------------------------

_APP = None
_APP_LOCK = threading.Lock()


def compiled():
    global _APP
    with _APP_LOCK:
        if _APP is None:
            _APP = graph.build_graph()
    return _APP


def run_ask(question: str, game: str | None, emit: Callable[[dict], None]) -> dict:
    """The full pipeline, streamed per node so the UI can name the phase it is in
    (FLAG 7.10).

    `.stream(stream_mode=["updates", "values"])` runs the SAME compiled graph
    `ask()` invokes -- same nodes, same order, same edges. `updates` drives the
    phase events; the final `values` payload is LangGraph's own accumulated
    state, so nothing here merges state by hand.

    PHASES ONLY. The answer text is never streamed: `answer` post-checks its own
    draft and can withhold it entirely, and showing a user text that is then
    retracted is the worst thing this product could do."""
    initial: dict = {"question": question, "tries": 0, "conflicts": []}
    if game:
        initial["game"] = game

    final: dict = {}
    for mode, chunk in compiled().stream(initial, stream_mode=["updates", "values"]):
        if mode == "values":
            final = chunk
            continue
        for node, update in (chunk or {}).items():
            emit({"phase": node, "scope": (update or {}).get("scope"),
                  "game": (update or {}).get("game")})
    return final


def run_search(question: str, game: str | None) -> dict:
    """`Search only`: route -> retrieve -> resolve, and STOP. No generation.

    The compiled graph cannot be halted before `answer`, so the same three node
    functions are called directly, in the graph's own order, each returning a
    partial dict that is merged into the state exactly as LangGraph merges it.
    Nothing is reimplemented -- these are `graph.route`, `graph.retrieve` and
    `graph.resolve` themselves.

    With a scope set this makes ZERO chat completions (`route` returns early when
    the caller forced a game), so the cheapest path through the system is also
    the one the UI puts a button on."""
    state: dict = {"question": question, "tries": 0, "conflicts": []}
    if game:
        state["game"] = game
    for node in (graph.route, graph.retrieve, graph.resolve):
        state.update(node(state))
    return state


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

from starlette.applications import Starlette                        # noqa: E402
from starlette.exceptions import HTTPException                      # noqa: E402
from starlette.middleware import Middleware                         # noqa: E402
from starlette.middleware.cors import CORSMiddleware                # noqa: E402
from starlette.requests import Request                              # noqa: E402
from starlette.responses import (FileResponse, JSONResponse,        # noqa: E402
                                 Response, StreamingResponse)
from starlette.routing import Route                                 # noqa: E402
from starlette.staticfiles import StaticFiles                       # noqa: E402


def _is_local(request: Request) -> bool:
    """Operator-local access only. The bind address already restricts this, but
    a second check here means loosening it takes two deliberate edits, not one."""
    host = (request.client.host if request.client else "") or ""
    return host in ("127.0.0.1", "::1", "localhost", "")


def _resolve_game(raw: str | None) -> str | None:
    """Validate a caller-forced scope against the slugs derived from the corpus.
    No slug list lives here; `graph.catalog()` is the only source."""
    if not raw or raw in ("auto", "none", "global"):
        return None
    known = {slug for slug, _ in graph.catalog()}
    if raw not in known:
        raise HTTPException(400, f"unknown game slug {raw!r}")
    return raw


async def _body(request: Request) -> dict:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(400, "expected a JSON body")
    return payload if isinstance(payload, dict) else {}


def _ensure_conversation(payload: dict, question: str) -> str:
    cid = payload.get("conversation_id")
    if cid and conversation_summary(cid):
        return cid
    return create_conversation(question.strip()[:60])["id"]


async def api_ask(request: Request) -> Response:
    """Full pipeline, streamed as SSE phase events, terminating with the whole
    AskResponse. Budget is checked BEFORE the first model call."""
    payload = await _body(request)
    question = str(payload.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question is required")
    game = _resolve_game(payload.get("game"))
    forced = bool(game)

    # Checked BEFORE the conversation is created as well as before the model is
    # called, so a refused request leaves nothing behind at all -- no spend, no
    # recorded turn, and no empty conversation row in the history rail.
    existing = payload.get("conversation_id")
    refusal = BUDGET.check(existing if existing and conversation_summary(existing) else None)
    if refusal:
        return JSONResponse({"error": "budget_refused", "budget_refusal": refusal,
                             "budget": BUDGET.snapshot(existing),
                             "conversation_id": existing}, status_code=402)

    conversation_id = _ensure_conversation(payload, question)

    if not os.getenv("OPENAI_API_KEY"):
        return JSONResponse({"error": "no_api_key",
                             "message": "OPENAI_API_KEY is not set in this process. "
                                        "Add it to .env and restart the server."},
                            status_code=503)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: dict | None) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def work() -> None:
        started = time.monotonic()
        turn_id, asked_at = _id("t"), _now()
        try:
            state = run_ask(question, game, emit)
            body = response_json(
                state, question=question, forced_scope=forced, generated=True,
                duration_ms=int((time.monotonic() - started) * 1000),
                conversation_id=conversation_id, turn_id=turn_id, asked_at=asked_at)
            record_turn(conversation_id, body)
            emit({"phase": "done", "response": body,
                  "budget": BUDGET.snapshot(conversation_id),
                  "conversation": conversation_summary(conversation_id)})
        except Exception as exc:                       # noqa: BLE001
            emit({"phase": "error", "error": type(exc).__name__, "message": str(exc)})
        finally:
            emit(None)

    threading.Thread(target=work, daemon=True).start()

    async def events():
        yield f"data: {json.dumps({'phase': 'start', 'conversation_id': conversation_id})}\n\n"
        while True:
            event = await queue.get()
            if event is None:
                return
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store",
                                      "X-Accel-Buffering": "no"})


async def api_search(request: Request) -> Response:
    """route -> retrieve -> resolve. `answer` is null and no generation happens."""
    payload = await _body(request)
    question = str(payload.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "question is required")
    game = _resolve_game(payload.get("game"))
    forced = bool(game)

    # With a forced scope `route` returns without calling a model, so this path
    # spends nothing on chat and is not gated. Without one, `route` is a real
    # completion and the same ceiling applies as to /api/ask.
    existing = payload.get("conversation_id")
    if not forced:
        refusal = BUDGET.check(existing if existing and conversation_summary(existing) else None)
        if refusal:
            return JSONResponse({"error": "budget_refused", "budget_refusal": refusal,
                                 "budget": BUDGET.snapshot(existing),
                                 "conversation_id": existing}, status_code=402)

    conversation_id = _ensure_conversation(payload, question)

    started = time.monotonic()
    turn_id, asked_at = _id("t"), _now()
    state = await asyncio.to_thread(run_search, question, game)
    body = response_json(state, question=question, forced_scope=forced, generated=False,
                         duration_ms=int((time.monotonic() - started) * 1000),
                         conversation_id=conversation_id, turn_id=turn_id,
                         asked_at=asked_at)
    record_turn(conversation_id, body)
    return JSONResponse({"response": body, "budget": BUDGET.snapshot(conversation_id),
                         "conversation": conversation_summary(conversation_id)})


async def api_conversations(request: Request) -> Response:
    if request.method == "POST":
        payload = await _body(request)
        return JSONResponse(create_conversation(str(payload.get("title") or "New enquiry")))
    return JSONResponse(list_conversations())


async def api_conversation(request: Request) -> Response:
    cid = request.path_params["cid"]
    if request.method == "DELETE":
        if not delete_conversation(cid):
            raise HTTPException(404, "no such conversation")
        return Response(status_code=204)
    if request.method == "PATCH":
        payload = await _body(request)
        summary = rename_conversation(cid, str(payload.get("title") or ""))
        if not summary:
            raise HTTPException(404, "no such conversation")
        return JSONResponse(summary)
    loaded = load_conversation(cid)
    if not loaded:
        raise HTTPException(404, "no such conversation")
    return JSONResponse(loaded)


async def api_catalog(request: Request) -> Response:
    return JSONResponse(catalog())


async def api_corpus(request: Request) -> Response:
    return JSONResponse(corpus_info())


async def api_budget(request: Request) -> Response:
    return JSONResponse(BUDGET.snapshot(request.query_params.get("conversation_id")))


async def api_source(request: Request) -> Response:
    """The LOCALLY INDEXED PDF -- the exact file the citations were computed
    against. Loopback clients only; see the block comment above."""
    if not _is_local(request):
        raise HTTPException(403, "local PDFs are served to loopback clients only")
    slug = request.path_params["slug"]
    path = pdf_path(slug)
    if not path:
        raise HTTPException(404, f"no local PDF for {slug!r} -- run `python ingest.py`")
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{slug}.pdf"'})


async def api_source_pages(request: Request) -> Response:
    slug = request.path_params["slug"]
    if not pdf_path(slug):
        raise HTTPException(404, f"no local PDF for {slug!r}")
    labels = await asyncio.to_thread(page_labels, slug)
    return JSONResponse({"slug": slug, "page_count": page_count(slug), "pages": labels})


async def not_found(request: Request, exc: HTTPException) -> Response:
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


def build_app(static: Path | None = None) -> Starlette:
    routes = [
        Route("/api/ask", api_ask, methods=["POST"]),
        Route("/api/search", api_search, methods=["POST"]),
        Route("/api/conversations", api_conversations, methods=["GET", "POST"]),
        Route("/api/conversations/{cid}", api_conversation,
              methods=["GET", "PATCH", "DELETE"]),
        Route("/api/catalog", api_catalog, methods=["GET"]),
        Route("/api/corpus", api_corpus, methods=["GET"]),
        Route("/api/budget", api_budget, methods=["GET"]),
        Route("/api/source/{slug}", api_source, methods=["GET"]),
        Route("/api/source/{slug}/pages", api_source_pages, methods=["GET"]),
    ]
    middleware = [
        # The Vite dev server runs on another port on this same machine. Origins
        # are loopback-only for the same reason the bind address is.
        Middleware(CORSMiddleware,
                   allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
                   allow_methods=["*"], allow_headers=["*"]),
    ]
    app = Starlette(routes=routes, middleware=middleware,
                    exception_handlers={HTTPException: not_found})
    if static and static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="static")
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1",
                        help="loopback only; see the local-PDF note in this module")
    parser.add_argument("--budget-day", type=float, default=None,
                        help="override EWC_BUDGET_DAY_USD for this run")
    parser.add_argument("--budget-conversation", type=float, default=None)
    parser.add_argument("--static", type=Path, default=ROOT / "frontend" / "dist",
                        help="built client to serve at / (optional)")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    if args.budget_day is not None:
        BUDGET.day_usd = args.budget_day
    if args.budget_conversation is not None:
        BUDGET.conversation_usd = args.budget_conversation

    if args.host not in ("127.0.0.1", "::1", "localhost"):
        # Not a hard block -- but it must never happen by accident.
        print(f"REFUSING to bind {args.host}: this server hands out locally indexed "
              f"Esports Foundation PDFs and is for operator-local use only. "
              f"Read the local-PDF note in server.py before changing this.",
              file=sys.stderr)
        return 2

    init_db()
    if not (DATA / "chunks.pkl").exists():
        print(f"{DATA/'chunks.pkl'} missing -- run `python index.py` first", file=sys.stderr)
        return 2
    if not os.getenv("OPENAI_API_KEY"):
        print("warning: OPENAI_API_KEY is not set; /api/ask will refuse.", file=sys.stderr)

    print(f"corpus  {corpus_fingerprint()} -- {len(graph.load_chunks())} chunks, "
          f"{sum(1 for b in catalog() if b['in_corpus'])} books")
    print(f"budget  ${BUDGET.day_usd:.2f}/day, ${BUDGET.conversation_usd:.2f}/conversation; "
          f"spent today ${spend_on(_today()):.4f}")
    print(f"serving http://{args.host}:{args.port}  (loopback only)")

    import uvicorn

    uvicorn.run(build_app(args.static), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())

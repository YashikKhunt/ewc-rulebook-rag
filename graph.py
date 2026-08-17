"""LangGraph app over the EWC rulebook corpus.

Stage S3 ships the **bare retrieve-and-answer path**:

    route -> retrieve -> answer

The full contract in CLAUDE.md is ``route -> retrieve -> grade -> (retrieve | resolve)
-> answer``. ``grade`` (the single rewrite loop, S4) and ``resolve`` (precedence /
amendment reconciliation, S5) are **not implemented here**. Their state keys
(``conflicts``, ``tries``) exist and are threaded through unchanged so adding the nodes
does not reshape the state.

What S3 does implement, because they are non-negotiable behaviours and not features:

* **Hybrid retrieval.** Dense (Chroma) + lexical (BM25) at 12 each, merged with
  Reciprocal Rank Fusion at k=60, truncated to the top 8, then ordered by ``authority``
  descending. Hybrid is mandatory: rule questions are token-exact ("Article 3.2.3",
  "forfeit"), and the corpus contains one-word sub-articles (``alcohol;``, ``Fine(s)``)
  whose dense vectors carry almost no signal -- BM25 is the only retriever that finds
  them. The fix for a retrieval miss is never a wider ``k``.
* **Scope filtering at the store level**, never in the prompt. A question routed to
  ``valorant`` cannot retrieve ``cs2`` chunks because ``cs2`` chunks are never fetched.
* **Precedence.** ``authority``: global=0, title=1, amendment=2. Higher wins and the
  answer must say so explicitly rather than blending the two.
* **Abstention.** If the excerpts do not cover the question the answer says so and names
  what was searched.
* **Mechanical post-checks.** A prompt is a hope; these are guards. Every
  ``(Game — Article X, p.N)`` the answer emits must match, verbatim, a ``citation=``
  line that was in the context window. No book may be called silent while its
  excerpts sit in the context window. No retrieved article may be dropped without a
  word once its siblings have been used. All three read facts already in ``docs``,
  so they cost no API call and cannot hallucinate. One bounded regeneration on
  failure, then the answer is withheld or the omission disclosed -- never silently
  corrected.

Answers are never cached: the corpus is versioned, so a question alone is not a key.

Usage
-----
    python -m graph "How long is the grace period before a forfeit?"
    python -m graph --show-docs "What is Article 3.2.3?"
    python -m graph --game cs2 "..."     # skip the routing LLM call, force a scope
"""

from __future__ import annotations

import argparse
import math
import os
import pickle
import re
import sys
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Optional, Sequence, TypedDict

from dotenv import load_dotenv
from langchain_core.documents import Document

ROOT = Path(__file__).resolve().parent

DENSE_K = 12
LEXICAL_K = 12
FUSED_K = 8
RRF_K = 60


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


# ---------------------------------------------------------------------------
# Corpus handles
# ---------------------------------------------------------------------------

_CHUNKS: list[Document] | None = None
_STORE: Any = None


def load_chunks() -> list[Document]:
    """The pickled Document list index.py wrote -- BM25's corpus."""
    global _CHUNKS
    if _CHUNKS is None:
        path = ROOT / _env("EWC_DATA_DIR", "data") / "chunks.pkl"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing -- run `python index.py` first")
        with open(path, "rb") as handle:
            _CHUNKS = pickle.load(handle)
    return _CHUNKS


def vector_store():
    """The persisted Chroma collection."""
    global _STORE
    if _STORE is None:
        from langchain_chroma import Chroma
        from langchain_openai import OpenAIEmbeddings

        _STORE = Chroma(
            collection_name=_env("EWC_CHROMA_COLLECTION", "ewc_rulebooks"),
            embedding_function=OpenAIEmbeddings(
                model=_env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
            ),
            persist_directory=str(ROOT / _env("EWC_CHROMA_DIR", "data/chroma")),
        )
    return _STORE


def catalog() -> list[tuple[str, str]]:
    """(slug, game_title) pairs for every *title* book, derived from the indexed
    corpus itself. Never hardcoded: a re-crawl that adds or renames a title is
    picked up with no code change. Title names are read from the corpus rather
    than from a literal because the manifest's own names drift (`cod-mw3` is
    published as "Call of Duty: Black Ops 7")."""
    seen: dict[str, str] = {}
    for doc in load_chunks():
        meta = doc.metadata
        if meta.get("scope") == "title":
            seen.setdefault(meta["game"], meta["game_title"])
    return sorted(seen.items())


# ---------------------------------------------------------------------------
# Scope filtering -- applied at the store, never in the prompt
# ---------------------------------------------------------------------------

def scope_filter(game: str | None) -> dict:
    """A title question sees that title plus Global; a tournament-wide question
    sees Global plus amendments and no title book.

    ONE DELIBERATE DEVIATION from CLAUDE.md's verbatim filter, reported rather
    than made quietly. The spec writes the title branch as
    ``{"$or": [{"game": slug}, {"scope": "global"}]}``. Taken literally an
    amendment chunk (``scope="amendment"``) is invisible to every title question,
    which makes non-negotiable #2 unreachable exactly where it bites: the one
    published amendment amends a **Global** article (3.2.3), and that article is
    retrieved by title-scoped roster questions, not by tournament-wide ones. So a
    third clause is added -- amendments to the GLOBAL book are visible wherever
    Global itself is. It is written as an explicit ``$and`` rather than a bare
    ``{"scope": "amendment"}`` so that an amendment to *another* title book still
    cannot leak across titles (#5). An amendment to the routed title is already
    covered by the first clause, because amendment chunks carry the ``game`` of
    the book they amend.
    """
    if game:
        return {"$or": [
            {"game": game},
            {"scope": "global"},
            {"$and": [{"scope": "amendment"}, {"game": "global"}]},
        ]}
    return {"scope": {"$in": ["global", "amendment"]}}


def _matches(meta: dict, where: dict) -> bool:
    """Evaluate the same filter dict against a pickled chunk, so BM25 searches
    exactly the subset Chroma searches. Supports only the operators used above."""
    if "$or" in where:
        return any(_matches(meta, clause) for clause in where["$or"])
    if "$and" in where:
        return all(_matches(meta, clause) for clause in where["$and"])
    for key, want in where.items():
        value = meta.get(key)
        if isinstance(want, dict):
            if "$in" in want and value not in want["$in"]:
                return False
        elif value != want:
            return False
    return True


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    """Keep dotted article numbers intact, and emit their dotted prefixes.

        "Article 3.2.3"  -> ["article", "3.2.3", "3.2"]

    Article numbers are the highest-precision signal in this corpus, so they must
    survive tokenization whole. But whole is not enough on its own: the Global
    Rulebook has no bare ``5.1.19`` chunk -- only ``5.1.19.1`` .. ``5.1.19.4.1`` --
    and an atomic token makes "Article 5.1.19" match none of them (measured: 0 of
    12 BM25 hits were 5.1.19.x before prefixes were added). Emitting prefixes of
    two or more components on BOTH the query and the corpus makes a parent-number
    query reach its children. Single components ("5") are deliberately not emitted:
    they are common numerals and would only add noise."""
    tokens: list[str] = []
    for token in _TOKEN.findall(text.lower()):
        tokens.append(token)
        if "." in token:
            bits = token.split(".")
            for depth in range(2, len(bits)):
                tokens.append(".".join(bits[:depth]))
    return tokens


def dense_search(query: str, where: dict, k: int = DENSE_K) -> list[Document]:
    return vector_store().similarity_search(query, k=k, filter=where)


def lexical_search(query: str, where: dict, k: int = LEXICAL_K) -> list[Document]:
    from langchain_community.retrievers import BM25Retriever

    pool = [d for d in load_chunks() if _matches(d.metadata, where)]
    if not pool:
        return []
    retriever = BM25Retriever.from_documents(
        pool, preprocess_func=tokenize, k=min(k, len(pool))
    )
    return retriever.invoke(query)


def rrf(rankings: Sequence[Sequence[Document]], k: int = RRF_K) -> list[Document]:
    """Reciprocal Rank Fusion. Score = sum over lists of 1/(k + rank)."""
    scores: dict[str, float] = {}
    docs: dict[str, Document] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            key = doc.metadata["chunk_id"]
            docs.setdefault(key, doc)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    order = sorted(scores, key=lambda key: (-scores[key], key))
    return [docs[key] for key in order]


def hybrid(query: str, where: dict) -> tuple[list[Document], dict[str, int]]:
    """12 dense + 12 lexical, fused, truncated to 8, then ordered by authority
    descending. Relevance decides *which* 8; precedence decides the order the
    answer prompt reads them in. Sorting is stable, so RRF order survives inside
    each authority level.

    Returns the ordered documents **and** the pre-sort fused rank of each, keyed
    by ``chunk_id``. The relevance rank is thrown away by the authority sort, and
    `resolve` needs it: "how strongly did retrieval want this excerpt" is a
    different question from "which book outranks which", and B5 was caused by
    conflating the two. The ranks are returned rather than written into metadata
    because BM25 hands back the very Document objects held in the module-level
    chunk cache -- mutating their metadata would poison every later query."""
    fused = rrf([dense_search(query, where), lexical_search(query, where)])[:FUSED_K]
    ranks = {doc.metadata["chunk_id"]: n for n, doc in enumerate(fused, start=1)}
    ordered = sorted(fused, key=lambda d: -int(d.metadata.get("authority", 0)))
    return ordered, ranks


# ---------------------------------------------------------------------------
# Prompt rendering -- a chunk never reaches the model without its metadata
# ---------------------------------------------------------------------------

def citation_for(meta: dict) -> str:
    """The one canonical citation string for a chunk.

    Used by BOTH `render()` (what the model is shown) and `unsupported_citations()`
    (what the model is held to), so the two can never drift apart. An article-less
    chunk renders as ``(Game — p.N)``, matching what the prompt asks for; the old
    ``Article n/a`` placeholder was a citation the model was told never to write."""
    article = (meta.get("article") or "").strip()
    if article:
        return f"({meta['game_title']} — Article {article}, p.{meta['page']})"
    return f"({meta['game_title']} — p.{meta['page']})"


def index_lines(docs: Iterable[Document]) -> str:
    """A one-line-per-excerpt contents list, shown above the excerpts themselves.

    The headings are already in each excerpt's header, but buried under two thousand
    tokens of rule text, and the model reliably answered from the first excerpt that
    fit the question while leaving a rank-1 excerpt unused (`cs2 2.8.3`, repeat-offender
    lateness, dropped 4/4). Hoisting the headings into a short list the model reads
    first turns "did I use everything?" into a checklist instead of a recall problem."""
    rows = []
    for n, doc in enumerate(docs, start=1):
        meta = doc.metadata
        article = meta.get("article")
        label = f"Article {article}" if article else "(no article number)"
        rows.append(f"  [{n}] {meta['game_title']} {label} — "
                    f"{meta.get('heading') or '(no heading)'}")
    return "\n".join(rows)


def render(docs: Iterable[Document]) -> str:
    blocks = []
    for n, doc in enumerate(docs, start=1):
        meta = doc.metadata
        tier = {0: "GLOBAL", 1: "TITLE", 2: "AMENDMENT"}.get(
            int(meta.get("authority", 0)), "?"
        )
        head = (
            f"[{n}] {meta['game_title']} | scope={meta['scope']} "
            f"authority={meta['authority']} ({tier})\n"
            f"    article={meta.get('article') or '(none)'} "
            f"| heading={meta.get('heading') or '(none)'}\n"
            f"    section={meta.get('heading_path') or '(none)'}\n"
            f"    page={meta['page']} | citation={citation_for(meta)}\n"
            f"    version={meta.get('version') or 'unstated'} "
            f"| effective={meta.get('effective_date') or 'unstated'}"
        )
        blocks.append(f"{head}\n{doc.page_content}")
    return "\n\n---\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Mechanical citation post-check
# ---------------------------------------------------------------------------
#
# The prompt asks the model to copy `citation=` verbatim. This checks that it did.
# It is a text comparison against the excerpts actually put in the context window --
# no API call, no model judgement. It catches the failure class this product exists
# to prevent: a citation that is PRESENT and WELL-FORMED but points at the wrong
# book, article or page, which a compliance reader would follow to unrelated text.

_PARENTHETICAL = re.compile(r"\(([^()]{0,500})\)")
_CITATION_SHAPE = re.compile(
    r"^.+? — (?:Article \S+?, )?p\.\d+$"
)


def _normalise(text: str) -> str:
    """Collapse cosmetic variation ONLY: whitespace, dash glyph, `p. 25` vs `p.25`.

    Deliberately does not touch the game name, the article number or the page --
    those are the locator, and a difference in any of them is exactly what this
    check exists to report."""
    text = text.replace("–", "—")
    text = re.sub(r"\s+-\s+", " — ", text)
    text = re.sub(r"\s*—\s*", " — ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip("()").strip().strip(".,;").strip()
    return re.sub(r"p\.\s+", "p.", text)


def allowed_citations(docs: Iterable[Document]) -> set[str]:
    """Normalised, parenthesis-free locators -- the same shape `cited_locators`
    produces, so the two are directly comparable."""
    return {_normalise(citation_for(d.metadata)) for d in docs}


def cited_locators(text: str) -> list[str]:
    """Every citation-shaped locator in the answer.

    Parentheticals that are not citation-shaped (ordinary prose asides) are ignored,
    and a parenthetical holding several citations separated by `;` -- the format the
    prompt itself produces -- is split into its parts."""
    found: list[str] = []
    for inner in _PARENTHETICAL.findall(text):
        for piece in inner.split(";"):
            piece = _normalise(piece)
            if _CITATION_SHAPE.match(piece):
                found.append(piece)
    return found


def citation_spans(text: str, docs: Iterable[Document]) -> list[dict]:
    """The same locators `cited_locators` finds, WITH their character offsets in
    `text` and the chunk each one is licensed by.

    Added at S6b for the HTTP layer (frontend/DESIGN.md FLAG 7.2). The front-end
    must weld each citation to its claim as a clickable anchor, which needs
    positions; `cited_locators` returns bare strings. Rather than let the client
    parse rule text -- which is the client re-authoring a claim, and which could
    silently disagree with the post-check that decides whether an answer ships --
    the offsets are computed HERE, from the SAME `_PARENTHETICAL` regex, the same
    `;` split, the same `_normalise` and the same `_CITATION_SHAPE` as
    `cited_locators`. The invariant

        [s["locator"] for s in citation_spans(t, docs)] == cited_locators(t)

    holds by construction and is asserted in the S6b tests.

    Read-only: it inspects `text` and `docs` and returns a new list. It cannot
    change what the pipeline retrieves, decides or says.

    `start`/`end` bound the locator itself, never the surrounding `(`, `)` or
    `;` -- those stay plain text so the sentence still reads correctly aloud.
    `chunk_id` is None when the locator matches no excerpt, which is exactly the
    set `unsupported_citations` rejects; the caller renders that as unresolved
    rather than as a working link.
    """
    by_locator: dict[str, list[str]] = {}
    for doc in docs:
        by_locator.setdefault(
            _normalise(citation_for(doc.metadata)), []
        ).append(doc.metadata["chunk_id"])

    spans: list[dict] = []
    for match in _PARENTHETICAL.finditer(text):
        inner, base = match.group(1), match.start(1)
        offset = 0
        for piece in inner.split(";"):
            start = base + offset
            offset += len(piece) + 1          # +1 for the ";" that was split out
            visible = piece.strip().rstrip(".,; ")
            if not visible:
                continue
            locator = _normalise(piece)
            if not _CITATION_SHAPE.match(locator):
                continue
            lead = start + (len(piece) - len(piece.lstrip()))
            chunk_ids = by_locator.get(locator, [])
            spans.append({
                "start": lead,
                "end": lead + len(visible),
                "text": text[lead:lead + len(visible)],
                "locator": locator,
                "chunk_id": chunk_ids[0] if chunk_ids else None,
                "chunk_ids": chunk_ids,
            })
    return spans


def unsupported_citations(text: str, allowed: set[str]) -> list[str]:
    """Locators in the answer that appear in no excerpt. Order-preserving, deduped."""
    bad: list[str] = []
    for locator in cited_locators(text):
        if locator not in allowed and locator not in bad:
            bad.append(locator)
    return bad


# ---------------------------------------------------------------------------
# Mechanical silence check
# ---------------------------------------------------------------------------
#
# Which books are in the context window is a FACT sitting in `docs` metadata. The
# model is not able to read it reliably: asked about Valorant rosters it asserted,
# three times out of three, that the Global Rulebook "does not cover" the point
# while three Global excerpts on exactly that point sat in its own prompt. So the
# fact is computed here and the answer is held to it, the same way citations are.
#
# The correct way to state a gap is about the *excerpts* -- "the retrieved excerpts
# do not state X" -- which is also the only honest claim available: eight chunks
# were searched, which is never enough to know what a whole rulebook contains.

_SILENCE = re.compile(
    r"\b(?:does|do|did)\s+not\s+(?:state|contain|address|cover|specify|provide"
    r"|mention|include|say|set\s+out|establish|impose|define)\b"
    r"|\b(?:is|are|was|were)\s+silent\b"
    r"|\b(?:has|have|contains?|includes?)\s+no\s+(?:rule|provision|article|text|specific)"
    r"|\bno\s+(?:rule|provision|article|text)s?\s+(?:on|for|about|regarding|covering)\b"
    r"|\bnothing\s+(?:on|about|regarding)\b"
    r"|\bnot\s+(?:stated|addressed|covered|mentioned|specified)\b",
    re.I,
)

# The other word order: "there is no relevant text IN the Global Rulebook on ...".
# Here the book follows the phrase, so it is matched separately -- direction matters,
# because "the excerpts do not state a deadline for VALORANT" names a book AFTER a
# silence phrase and is a perfectly good sentence.
_SILENCE_BEFORE_BOOK = re.compile(
    r"\bno\s+(?:\w+\s+){0,3}(?:rule|provision|article|text|mention|reference|guidance)s?"
    r"\s+(?:in|from|within)\s+(?:the\s+)?",
    re.I,
)

# How far before the silence phrase a book name still reads as its subject.
_SUBJECT_WINDOW = 60
# How far after "no text in ..." the book name must sit to be that phrase's object.
_OBJECT_WINDOW = 20


def books_in_evidence(docs: Iterable[Document]) -> list[tuple[str, int]]:
    """(book title, number of excerpts) for every book in the context window."""
    counts: dict[str, int] = {}
    for doc in docs:
        title = doc.metadata["game_title"]
        counts[title] = counts.get(title, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _book_aliases(docs: Iterable[Document]) -> set[str]:
    """Lowercased names a book in evidence might be called by in prose."""
    aliases: set[str] = set()
    for doc in docs:
        aliases.add(doc.metadata["game_title"].lower())
        if doc.metadata.get("scope") == "global":
            aliases.add("global rulebook")
    return aliases


def _strip_citations(text: str) -> str:
    """Drop citation parentheticals so a book name inside one is not mistaken for a
    prose mention of that book."""
    def drop(match: re.Match) -> str:
        inner = match.group(1)
        parts = [_normalise(p) for p in inner.split(";")]
        return "" if parts and all(_CITATION_SHAPE.match(p) for p in parts) else match.group(0)

    return _PARENTHETICAL.sub(drop, text)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


# A13: the words that make a silence phrase's subject the EXCERPTS rather than the
# book named earlier in the same sentence. Log 007 measured `_SUBJECT_WINDOW = 60`
# flagging 3 of 6 adversarial compound sentences, including the partial-gap
# disclosure the prompt itself instructs the model to write:
#   "Under the EWC Global Rulebook 2026 emergency substitutes need TA approval, but
#    the excerpts do not state a notification deadline."
# The book name is inside the window, but it is not the subject of "do not state".
# When one of these words sits BETWEEN the book alias and the silence phrase, the
# subject has changed and the sentence is an excerpt-framed claim, not a claim about
# the book. That is the phrasing the SILENCE clause asks for; flagging it can
# withhold a correct answer, which is worse than the defect it was guarding.
_SUBJECT_SHIFT = re.compile(
    r"\b(?:excerpts?|passages?|retrieved\s+text|text\s+provided|provided\s+text"
    r"|articles?|provisions?|sections?)\b",
    re.I,
)


def silence_violations(text: str, docs: Iterable[Document]) -> list[str]:
    """Sentences claiming a book that IS in evidence says nothing on the point.

    A book absent from the context window may be reported as absent -- that claim
    is true and useful. A book present in it may not, because the excerpts in front
    of the model contradict the claim."""
    docs = list(docs)
    aliases = _book_aliases(docs)
    bad: list[str] = []
    for sentence in _sentences(_strip_citations(text)):
        lowered = sentence.lower()
        flagged = any(
            (pos := lowered[: hit.start()].rfind(alias)) >= 0
            and hit.start() - (pos + len(alias)) <= _SUBJECT_WINDOW
            and not _SUBJECT_SHIFT.search(lowered, pos + len(alias), hit.start())
            for hit in _SILENCE.finditer(lowered)
            for alias in aliases
        ) or any(
            0 <= lowered.find(alias, hit.end()) - hit.end() <= _OBJECT_WINDOW
            for hit in _SILENCE_BEFORE_BOOK.finditer(lowered)
            for alias in aliases
        )
        if flagged:
            bad.append(" ".join(sentence.split()))
    return bad


# ---------------------------------------------------------------------------
# Mechanical false-gap check (B6)
# ---------------------------------------------------------------------------
#
# `silence_violations` deliberately exempts the excerpt-framed phrasing -- "the
# retrieved excerpts do not state X" -- because that is the honest way to report a
# gap. The cost, measured at 007, is that ANY false gap claim wearing that phrasing
# is unfalsifiable: with `global 3.2.3` sitting at retrieval RANK 1, the pipeline
# answered "the retrieved excerpts do not state whether..." 2/2, and no check could
# see it.
#
# This closes the class rather than the repro. The claim carries its own subject --
# whatever follows the silence phrase -- so the subject is extracted and matched
# against the excerpts. If one excerpt contains essentially all of the claim's
# distinguishing words, the claim is false about the evidence and is reported.
#
# It is deliberately narrow, because the opposite error is worse: a genuine
# abstention that gets suppressed is a correct answer destroyed. A claim is only
# flagged when a SINGLE excerpt covers at least `_GAP_COVERAGE` of at least
# `_GAP_MIN_TERMS` distinguishing words. Measured against the two abstention
# fixtures, whose subjects contain words that appear in no excerpt at all
# ("overwatch", "grace"), neither is flagged.

_EXCERPT_FRAMED = re.compile(
    r"\b(?:the\s+)?(?:retrieved\s+)?(?:excerpts?|passages?|retrieved\s+(?:rulebook\s+)?text"
    r"|provided\s+text|text\s+provided)\b[^.]{0,40}?"
    r"\b(?:do|does|did)\s+not\s+"
    r"(?:state|contain|address|cover|specify|provide|mention|include|say|indicate|answer)\b",
    re.I,
)

_GAP_COVERAGE = 0.80
_GAP_MIN_TERMS = 3
_GAP_SUBJECT_WORDS = 16

_DOC_FREQUENCY: dict[str, int] | None = None
_CORPUS_SIZE = 0


def _idf(word: str) -> float:
    """Inverse document frequency over the indexed corpus.

    Plain word-count coverage does not separate a false gap claim from a true
    one: the false claim's subject ("roster changes ... earn Club Championship
    Points") matched 6 of 10 words of the very excerpt that answers it, while a
    TRUE abstention about Overwatch 2 matched a similar fraction -- because the
    words that decide the case ("overwatch", "grace") are rare and the words that
    do not ("whether", "still", "makes") are everywhere. Weighting by rarity puts
    the decision on the terms that distinguish the claim."""
    global _DOC_FREQUENCY, _CORPUS_SIZE
    if _DOC_FREQUENCY is None:
        counts: dict[str, int] = {}
        chunks = load_chunks()
        for doc in chunks:
            for token in set(content_words(doc.page_content)):
                counts[token] = counts.get(token, 0) + 1
        _DOC_FREQUENCY, _CORPUS_SIZE = counts, len(chunks)
    return math.log((_CORPUS_SIZE + 1) / (_DOC_FREQUENCY.get(word, 0) + 1))


def false_gap_violations(text: str, docs: Iterable[Document],
                         top_findings: Sequence[str] = ()) -> list[str]:
    """Excerpt-framed gap claims the evidence contradicts. Two mechanisms.

    1. **Blanket abstention against a computed fact.** If the answer cites
       nothing at all -- it abstains outright -- while `resolve` reported a
       relation about the excerpt retrieval ranked FIRST, the abstention denies
       something the pipeline itself established from that excerpt's text. This
       is the live B6 shape exactly: `global 3.2.3` at rank 1, an amendment and
       an express-primacy finding computed from it, and an answer saying the
       excerpts do not state the point. Measured against all five abstention and
       cross-title-refusal fixtures: none of them has a rank-1 finding, so none
       is touched -- correct abstention stays a success state.

    2. **Subject-directed.** The claim carries its own subject, so it is matched
       against each excerpt, weighted by term rarity. Deliberately set at
       `_GAP_COVERAGE`, above anything measured today (the live B6 claim reaches
       0.68), so it adds no false positives now and stands as the general guard
       for claims mechanism 1 cannot see.

    Both are narrow on purpose: suppressing a correct abstention destroys a right
    answer, and abstention is a success state in this product.
    """
    docs = list(docs)
    bad: list[str] = []

    if top_findings and not cited_locators(text):
        for sentence in _sentences(_strip_citations(text)):
            if _EXCERPT_FRAMED.search(sentence) or _SILENCE.search(sentence):
                bad.append(
                    f"{' '.join(sentence.split())[:200]}  "
                    f"[the answer cites nothing, yet the top-ranked excerpt "
                    f"supports: {'; '.join(top_findings)}]")
                break

    for sentence in _sentences(_strip_citations(text)):
        hit = _EXCERPT_FRAMED.search(sentence)
        if not hit:
            continue
        wanted = set(content_words(sentence[hit.end():])[:_GAP_SUBJECT_WORDS])
        if len(wanted) < _GAP_MIN_TERMS:
            continue          # nothing specific enough to check the claim against
        total = sum(_idf(word) for word in wanted)
        if total <= 0:
            continue
        for doc in docs:
            have = set(content_words(doc.page_content))
            covered = sum(_idf(word) for word in wanted & have)
            if covered / total >= _GAP_COVERAGE:
                meta = doc.metadata
                bad.append(
                    f"{' '.join(sentence.split())[:200]}  "
                    f"[contradicted by {meta['game_title']} "
                    f"Article {meta.get('article') or '-'} p.{meta['page']}]")
                break
    return bad


# ---------------------------------------------------------------------------
# Mechanical verbatim-run check (B7)
# ---------------------------------------------------------------------------
#
# 007 measured unmarked verbatim runs of 115 / 105 / 104 / 71 / 60 / 28 words from
# the source chunks, the longest being 54% of a single article -- transcription
# reading as paraphrase, against non-negotiable #6 and against CLAUDE.md's don't on
# redistributing Esports Foundation content. The two drivers it identified (the
# COMPLETENESS clause and the sibling correction's "keep everything you already
# had") are both gone from this prompt, but a prompt is a hope; this is the guard.
#
# The pipeline threshold is deliberately TIGHTER than eval's 25-word tripwire, so a
# regeneration is triggered while there is still headroom under the gate.

VERBATIM_LIMIT = 20


def longest_verbatim_run(text: str, docs: Iterable[Document]) -> tuple[int, str]:
    """Longest common contiguous word run between the answer and any one excerpt.

    Punctuation- and case-insensitive: transcription does not stop being
    transcription when a comma moves. Quoted runs are NOT exempt -- a 100-word
    block quote is still redistribution, and #6 asks for short phrases only."""
    answer_words = _CONTENT.findall(text.lower())
    best, where, passage = 0, "", ""
    for doc in docs:
        chunk_words = _CONTENT.findall(doc.page_content.lower())
        previous = [0] * (len(chunk_words) + 1)
        for word in answer_words:
            current = [0] * (len(chunk_words) + 1)
            for j, chunk_word in enumerate(chunk_words, start=1):
                if word == chunk_word:
                    current[j] = previous[j - 1] + 1
                    if current[j] > best:
                        best = current[j]
                        meta = doc.metadata
                        where = (f"{meta['game_title']} "
                                 f"Article {meta.get('article') or '-'} p.{meta['page']}")
                        passage = " ".join(chunk_words[j - best:j])
            previous = current
    return best, (f"{where}: \"{passage}\"" if where else "")


def verbatim_violations(text: str, docs: Iterable[Document],
                        limit: int = VERBATIM_LIMIT) -> list[str]:
    """The correction quotes the copied passage back, not just its length.

    Measured: told only "28 consecutive words copied from cs2 2.8.3", the model
    left the passage where it was 3/3 -- it cannot act on a fault it cannot
    locate. Shown the words, it rewrites them."""
    run, where = longest_verbatim_run(text, list(docs))
    if run <= limit:
        return []
    return [f"{run} consecutive words, copied from {where} (limit {limit})"]


# ---------------------------------------------------------------------------
# Mechanical sibling-article check
# ---------------------------------------------------------------------------
#
# Neither prompt wording nor a hoisted contents list moved this: asked what happens
# when a CS2 team is late, the model answered from 2.8.2 and 2.8.4 and silently
# skipped 2.8.3 (repeat offender, +100%) in 8 of 8 runs, with 2.8.3 sitting at rank 1
# in its own context. So it is caught structurally instead.
#
# The signal is the article numbering the corpus already carries. Once an answer has
# used 2.8.2 and 2.8.4, article 2.8.3 is not an unrelated excerpt that happened to be
# retrieved -- it is a sibling rung of the same ladder, and dropping it without a word
# is the silent-partiality failure CLAUDE.md #4 forbids. Siblings are only ever
# compared within one book: a Global 2.2.x and a title 2.2.x are unrelated rules that
# merely share a number.

_LOCATOR = re.compile(r"^(?P<book>.+?) — Article (?P<article>\S+?), p\.\d+$")


def _parent(article: str) -> str | None:
    return article.rsplit(".", 1)[0] if "." in article else None


#: How many siblings of one parent the answer must already be using before a
#: skipped sibling counts as a dropped rung. B5, log 007 ruling 2: sibling-hood on
#: its own is a poor proxy for relevance -- it fired on 17 of 18 substantive
#: answers and pushed a hotel-coverage paragraph into a Rocket League team-size
#: answer 3/3. Requiring TWO already-cited siblings means the check only fires on a
#: ladder the answer is demonstrably climbing, which is the case it was built for
#: (cs2 2.8.2 + 2.8.4 cited, 2.8.3 dropped).
SIBLINGS_IN_USE = 2


def unused_sibling_articles(text: str, docs: Iterable[Document], allowed: set[str],
                            accountable: Iterable[str] | None = None) -> list[str]:
    """Retrieved articles the answer skipped while climbing their ladder.

    Two gates, both from log 007 ruling 2, and both needed:

    * the answer must already cite ``SIBLINGS_IN_USE`` siblings of that parent --
      a ladder in use, not merely a shared number prefix; and
    * the skipped article must be ``accountable``, i.e. inside the top of the
      FUSED RELEVANCE ranking that `resolve` computed. Relevance is `resolve`'s
      judgement to make (ruling 2's preferred fix), not this function's.

    ``accountable=None`` keeps the pre-S5 behaviour for direct callers and tests.
    """
    docs = list(docs)
    limit = None if accountable is None else set(accountable)
    cited: set[tuple[str, str]] = set()
    for locator in cited_locators(text):
        match = _LOCATOR.match(locator)
        if match and locator in allowed:
            cited.add((match["book"].strip(), match["article"].strip().rstrip(".")))

    skipped: list[str] = []
    seen: set[tuple[str, str]] = set()
    for doc in docs:
        meta = doc.metadata
        if limit is not None and meta["chunk_id"] not in limit:
            continue
        key = (meta["game_title"], (meta.get("article") or "").strip())
        if not key[1] or key in cited or key in seen:
            continue
        parent = _parent(key[1])
        if parent is None:
            continue
        in_use = {article for book, article in cited
                  if book == key[0] and _parent(article) == parent}
        if len(in_use) >= SIBLINGS_IN_USE:
            seen.add(key)
            skipped.append(f"{key[0]} Article {key[1]} — "
                           f"{meta.get('heading') or '(no heading)'} (p.{meta['page']})")
    return skipped


# ---------------------------------------------------------------------------
# Text relations -- the arithmetic `resolve` runs on
# ---------------------------------------------------------------------------
#
# Every function here reads text and metadata that are already in `docs`. None
# of them calls a model. That is the point: log 007 ruling 4 measured the answer
# prompt at its complexity ceiling, with each added clause displacing another,
# so the Global-vs-title relation is COMPUTED here and handed to the prompt as a
# fact instead of being re-derived by the model on every call.

_STOPWORDS = frozenset("""
a an the and or of to in for on at by with without from as is are was were be been
being that this these those it its their they them he she we you your our not no any
all each such same only own so very do does did doing have has had having but because
until while about against between into through during before after above below up down
out off over under again further once here there both few nor too per within upon shall
will may must can if then than which who whom what when where how also more most other
others said case cases participant participants team teams rule rules rulebook article
articles ewc global tournament
""".split())

_CONTENT = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*")

#: A Global article that asserts its own primacy over the title books. CLAUDE.md
#: non-negotiable #1's express-Global-primacy exception is grounded ONLY in text
#: like this -- never in a title book's silence. Measured corpus-wide: this fires
#: on exactly two chunks (global 3.2.3 p.17 and its amendment) and on zero title
#: chunks.
_EXPRESS_PRIMACY = re.compile(
    r"even if the (?:respective )?game[- ]title rulebook[^.]*\."
    r"|regardless of (?:what |any |the )?(?:respective )?game[- ](?:title|specific) rul\w+[^.]*\."
    r"|notwithstanding[^.]{0,80}game[- ](?:title|specific) rul\w+[^.]*\."
    r"|(?:shall |will )?(?:prevail|take[s]? precedence|govern[s]?) over "
    r"(?:the |any )?(?:respective )?game[- ](?:title|specific) rul\w+[^.]*\.",
    re.I,
)

#: A title book that declares a section to be a copy of the Global rules. mlbb
#: ships 17 such chunks ("Appendix B - EWC26 Global Rules") at authority=1,
#: sharing Global's numbering. Derived from the part name at runtime; no slug is
#: written down.
_RESTATES_GLOBAL = re.compile(r"global\s+rul", re.I)

#: "... as defined in Section 5.1.2.1 ... in the EWC Global Rulebook."
_XREF_ARTICLE = re.compile(r"(?:section|article|art\.)\s+(\d{1,2}(?:\.\d{1,3})+)", re.I)
_XREF_BOOK = re.compile(r"global\s+rulebook", re.I)

# Thresholds. Every one was set from measurement over the real pairs the 006
# verifier found, not chosen a priori; the measured values sit in wide gaps:
#   same point   headings 1.00 / 0.67 (real pairs)  vs  0.25 / 0.00 (non-pairs)
#   agreement    body 1.00 (dota2 1.4.1.1 = global 5.1.2.1)  vs  0.21 / 0.00
SAME_POINT_HEADING = 0.60
SAME_POINT_LEAD = 0.70
SAME_POINT_BODY = 0.35
AGREEMENT_BODY = 0.50
INCORPORATED_BODY = 0.70      # amendment text already present in the base article
#: A one-line opening ("Fines are as follows:") carries no subject; measured, a
#: 4-word lead scored 0.75 containment against an unrelated Global article and
#: fabricated a conflict between PUBG Mobile clothing rules and Global prize
#: deductions. Short leads are not evidence of anything.
MIN_LEAD_WORDS = 6
#: How far down the fused relevance ranking an excerpt still has to be accounted
#: for. B5: sibling-hood is a poor proxy for relevance, so a skipped sibling only
#: counts when retrieval actually wanted it.
ACCOUNTABLE_RANK = 4


def flat(text: str) -> str:
    """Collapse the hard line wraps PDF extraction leaves behind.

    Not cosmetic: `global 3.2.3` wraps as "game title\\nrulebook", and the
    express-primacy regex missed it entirely until this was applied."""
    return re.sub(r"\s+", " ", text).strip()


def body_text(doc: Document) -> str:
    """The chunk's text without the ``[Game · Article n — Heading]`` label."""
    text = doc.page_content
    if text.startswith("[") and "\n" in text:
        return text.split("\n", 1)[1]
    return text


def content_words(text: str) -> list[str]:
    return [w for w in _CONTENT.findall(text.lower())
            if w not in _STOPWORDS and len(w) > 1]


def _shingles(text: str, n: int = 3) -> set[tuple]:
    words = content_words(text)
    return {tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _containment(a: set, b: set) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def _lead(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", flat(text))
    return parts[0] if parts else text


def subject_score(a: "Group", b: "Group") -> float:
    """How strongly two article groups are about the SAME point, in [0, 1].

    A16 is why this is not article-number equality: ``cs2 3.2.3`` (Global Valve
    Regional Standings slots) and ``global 3.2.3`` (Team Roster Integrity) are
    unrelated articles that share a number and ARE co-retrieved -- 192
    (game, article) pairs are non-unique corpus-wide. And both genuine conflicts
    in this corpus (dota2 5.5 vs global 5.1.19.4.1; cs2 4.8 vs global 5.1.12)
    have DIFFERENT numbers, so number equality would simultaneously fabricate the
    collision and miss every real pair.

    Measured on those pairs: heading agreement is the load-bearing signal
    (1.00 and 0.67 for the real pairs, 0.25 and 0.00 for non-pairs)."""
    heading = _jaccard(set(content_words(a.heading)), set(content_words(b.heading)))
    lead_a = set(content_words(_lead(a.text)))
    lead_b = set(content_words(_lead(b.text)))
    lead = (_containment(lead_a, lead_b)
            if min(len(lead_a), len(lead_b)) >= MIN_LEAD_WORDS else 0.0)
    body = _jaccard(_shingles(a.text), _shingles(b.text))
    return max(heading if heading >= SAME_POINT_HEADING else 0.0,
               lead if lead >= SAME_POINT_LEAD else 0.0,
               body if body >= SAME_POINT_BODY else 0.0)


def agree(a: "Group", b: "Group") -> bool:
    """Do the two articles state the SAME rule?

    Jaccard, not containment: containment's denominator is the SHORTER text, so a
    long title article trivially "contains" a short Global one and every pairing
    with a one-line Global article would read as agreement. Measured: the genuine
    agreement (dota2 1.4.1.1 = global 5.1.2.1) scores 1.00 while the genuine
    media-fines conflict scores 0.13."""
    return _jaccard(_shingles(a.text), _shingles(b.text)) >= AGREEMENT_BODY


def restates_global(doc: Document) -> bool:
    """A title chunk sitting in a section the title book itself labels as a copy
    of the Global rules. Such a chunk must never be read as a title rule
    outranking the real Global Rulebook -- it IS the Global rule, reprinted."""
    meta = doc.metadata
    if meta.get("scope") != "title":
        return False
    return bool(_RESTATES_GLOBAL.search(str(meta.get("part") or ""))
                or _RESTATES_GLOBAL.search(str(meta.get("heading_path") or "")))


def express_primacy(doc: Document) -> str | None:
    """The Global text asserting its own primacy over the title books, if any."""
    if doc.metadata.get("scope") not in ("global", "amendment"):
        return None
    match = _EXPRESS_PRIMACY.search(flat(doc.page_content))
    return match.group(0).strip() if match else None


def cross_references(doc: Document) -> set[str]:
    """Global article numbers a title chunk defers to by name.

    ``pubg-mobile 13.6``: "...as defined in Section 5.1.2.1 Penalty Points in the
    EWC Global Rulebook." A cross-reference is agreement by incorporation, not a
    conflict. Self-references (a title 1.2 pointing at Global 1.2) are dropped as
    boilerplate."""
    if doc.metadata.get("scope") != "title":
        return set()
    own = (doc.metadata.get("article") or "").strip()
    found: set[str] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", flat(doc.page_content)):
        if _XREF_BOOK.search(sentence):
            found.update(a for a in _XREF_ARTICLE.findall(sentence) if a != own)
    return found


def _cite(doc: Document) -> str:
    meta = doc.metadata
    article = (meta.get("article") or "").strip()
    where = f"Article {article}, p.{meta['page']}" if article else f"p.{meta['page']}"
    return f"{meta['game_title']} ({where})"


class Group(NamedTuple):
    """All retrieved chunks of ONE article, treated as one rule.

    CLAUDE.md's contract for `resolve` is to "group retrieved chunks by article
    number". Grouping is on ``article_id`` -- ``part § article`` where the book
    has appendices -- not on the bare number, and the group is scoped to its
    book, so two books that merely share a number are never merged.

    Grouping matters beyond tidiness: ``dota2 5.5`` arrives as two chunks (p.24
    and p.25, the fine schedule continuing onto the next page). Compared
    separately, one read as a conflict with ``global 5.1.19.4.1`` and the other
    read as agreement with it -- the note would have told the model two opposite
    things about one pair of articles. Merged, the article is judged once."""
    game: str
    game_title: str
    scope: str
    article: str
    article_id: str
    heading: str
    text: str
    docs: list[Document]

    @property
    def cite(self) -> str:
        return _cite(self.docs[0])

    @property
    def chunk_ids(self) -> list[str]:
        return [d.metadata["chunk_id"] for d in self.docs]


def group_articles(docs: Iterable[Document]) -> list[Group]:
    """Retrieved chunks folded into one Group per (book, article_id)."""
    buckets: dict[tuple[str, str], list[Document]] = {}
    for doc in docs:
        meta = doc.metadata
        key = (meta["game"],
               str(meta.get("article_id") or meta.get("article") or
                   meta.get("heading") or meta["chunk_id"]))
        buckets.setdefault(key, []).append(doc)
    groups = []
    for (game, article_id), members in buckets.items():
        first = members[0].metadata
        groups.append(Group(
            game=game,
            game_title=first["game_title"],
            scope=first.get("scope", "?"),
            article=(first.get("article") or "").strip(),
            article_id=article_id,
            heading=str(first.get("heading") or ""),
            text=" ".join(body_text(d) for d in members),
            docs=members,
        ))
    return groups


# ---------------------------------------------------------------------------
# resolve -- the precedence / amendment node
# ---------------------------------------------------------------------------

def resolve(state: State) -> dict:
    """Group the retrieved excerpts, decide how the books relate, and write an
    explicit precedence note into state for the answer prompt to consume.

    Returns ``conflicts`` (the structured findings), ``note`` (the rendered text
    the prompt reads) and ``accountable`` (the chunk_ids relevant enough that
    dropping one silently is a defect). A partial dict, as every node returns;
    nothing in ``state`` is mutated.

    The relations it can find, in the order they are reported:

    ``amended``      an amendment in evidence targets an article in evidence.
                     Whether the base PDF text is stale is DECIDED, not assumed:
                     if the amendment's new wording is already present in the
                     base article the note says so, because claiming a current
                     article is superseded is its own compliance failure.
    ``primacy``      a Global excerpt's own text asserts primacy over the title
                     books (CLAUDE.md #1's express exception). Grounded in the
                     Global text, quoted in the note, never inferred from a title
                     book's silence.
    ``conflict``     a Global and a title excerpt state DIFFERENT rules on the
                     same point. The title rule governs (#1).
    ``agreement``    they state the SAME rule, verbatim or near enough.
    ``cross_ref``    the title excerpt defers to a Global article by number.
    ``restatement``  the title excerpt is a reprint of the Global rules.
    ``provenance``   an externally-hosted book would outrank the Global Rulebook.
    """
    docs: list[Document] = list(state.get("docs") or [])
    ranks: dict[str, int] = dict(state.get("ranks") or {})
    findings: list[dict] = []

    accountable = {d.metadata["chunk_id"] for d in docs
                   if ranks.get(d.metadata["chunk_id"], 99) <= ACCOUNTABLE_RANK}

    def relevant(*chunk_ids: str) -> bool:
        """Report a relation only when retrieval actually wanted one of its
        articles. Without this the note editorialises about whatever happened to
        land in the pool: `global 3.2.3` is retrieved at rank 5 for an Overwatch 2
        roster question, and an express-primacy note there would push a correct
        abstention into answering. Relevance is `resolve`'s judgement to make --
        007 ruling 2 -- so it is made once, here, and applied to every finding."""
        return not accountable or any(cid in accountable for cid in chunk_ids)

    by_scope: dict[str, list[Document]] = {}
    for doc in docs:
        by_scope.setdefault(doc.metadata.get("scope", "?"), []).append(doc)
    amendments = by_scope.get("amendment", [])

    groups = group_articles(docs)
    global_groups = [g for g in groups if g.scope == "global"]
    title_groups = [g for g in groups if g.scope == "title"]

    # --- amendments (contract #2) -----------------------------------------
    for amendment in amendments:
        meta = amendment.metadata
        target_game = meta.get("amends_game") or meta.get("game")
        target_article = (meta.get("amends_article") or meta.get("article") or "").strip()
        base = [d for d in docs
                if d.metadata.get("scope") != "amendment"
                and d.metadata.get("game") == target_game
                and (d.metadata.get("article") or "").strip() == target_article]
        new_text = str(meta.get("new_text") or "")
        incorporated = bool(new_text) and any(
            _containment(_shingles(new_text), _shingles(body_text(d))) >= INCORPORATED_BODY
            for d in base
        )
        chunk_ids = ([amendment.metadata["chunk_id"]]
                     + [d.metadata["chunk_id"] for d in base])
        if not relevant(*chunk_ids):
            continue
        findings.append({
            "kind": "amended",
            "article": f"{target_game} {target_article}",
            "amendment": _cite(amendment),
            "base": [_cite(d) for d in base],
            "effective": meta.get("effective_date") or "",
            "incorporated": incorporated,
            "base_in_evidence": bool(base),
            "caveat": str(meta.get("caveat") or ""),
            "chunk_ids": chunk_ids,
        })

    # --- express Global primacy (CLAUDE.md #1's exception) -----------------
    # One finding per amended article, not one per chunk: `global 3.2.3` and its
    # amendment BOTH carry the primacy sentence, and reporting each separately
    # printed the same instruction twice.
    seen_primacy: set[str] = set()
    for doc in by_scope.get("global", []) + amendments:
        quote = express_primacy(doc)
        meta = doc.metadata
        key = f"{meta.get('amends_game') or meta['game']} {meta.get('article') or ''}".strip()
        if not quote or key in seen_primacy or not relevant(meta["chunk_id"]):
            continue
        seen_primacy.add(key)
        findings.append({
            "kind": "primacy",
            "article": key,
            "cite": _cite(doc),
            "quote": quote,
            "chunk_ids": [meta["chunk_id"]],
        })

    # --- Global vs title, ONE relation per title article -------------------
    # Only the best-matching Global article is reported for each title article.
    # Reporting every Global article that brushes the same subject produced four
    # notes for one pair, two of which disagreed with each other.
    for title in title_groups:
        xrefs = cross_references(title.docs[0])
        crossed = next((g for g in global_groups if g.article and g.article in xrefs),
                       None)
        if crossed:
            if relevant(*title.chunk_ids, *crossed.chunk_ids):
                findings.append({
                    "kind": "cross_ref", "title": title.cite, "global": crossed.cite,
                    "chunk_ids": title.chunk_ids + crossed.chunk_ids,
                })
            continue

        scored = [(subject_score(title, g), g) for g in global_groups]
        best_score, best = max(scored, key=lambda pair: pair[0], default=(0.0, None))
        if best is None or best_score <= 0.0:
            continue
        if not relevant(*title.chunk_ids, *best.chunk_ids):
            continue

        if restates_global(title.docs[0]):
            kind = "restatement"
        elif agree(title, best):
            kind = "agreement"
        else:
            kind = "conflict"
        findings.append({
            "kind": kind, "title": title.cite, "global": best.cite,
            "subject": title.heading or best.heading, "score": round(best_score, 3),
            "chunk_ids": title.chunk_ids + best.chunk_ids,
        })

    # --- provenance of externally-hosted books -----------------------------
    # Default pending a human ruling on apex/ALGS: its authority is NOT changed,
    # but it may not silently outrank the Global Rulebook either.
    if global_groups:
        for doc in docs:
            meta = doc.metadata
            if meta.get("external_host") and int(meta.get("authority", 0)) > 0:
                findings.append({
                    "kind": "provenance",
                    "cite": _cite(doc),
                    "chunk_ids": [meta["chunk_id"]],
                })
                break

    rank_one = {cid for cid, rank in ranks.items() if rank == 1}
    return {"conflicts": findings,
            "note": render_note(findings, docs, accountable),
            "accountable": sorted(accountable),
            "top_findings": [f"{f['kind']} at {f.get('cite') or f.get('title') or f['article']}"
                             for f in findings
                             if any(c in rank_one for c in f["chunk_ids"])]}


def _coverage_lines(docs: Sequence[Document], accountable: set[str]) -> list[str]:
    """The COMPLETENESS half of the note, as data rather than exhortation.

    Log 007 ruling 4 asked for the prompt's DEFAULT CASE, three-part precedence
    test AND COMPLETENESS clause to be replaced by a rendered note. Shipping the
    precedence half alone was measured to be worse than the clause it replaced:
    with nothing telling the model which excerpts bear on the question, the CS2
    lateness fixture -- answered in full 4/4 at 007 -- came back as a flat "the
    retrieved excerpts do not state what happens", with the penalty ladder at
    ranks 1 and 2 of its own context. Naming the excerpts retrieval ranked
    highest turns "did I use everything?" from a judgement into a checklist, and
    which excerpts those are is a fact this node already has.
    """
    if not accountable:
        return []
    wanted = [(n, d) for n, d in enumerate(docs, start=1)
              if d.metadata["chunk_id"] in accountable]
    if not wanted:
        return []
    listed = "; ".join(
        f"[{n}] {d.metadata['game_title']} "
        f"Article {d.metadata.get('article') or '-'}" for n, d in wanted)
    out = [f"COVERAGE. Retrieval ranked these excerpts highest for this question: "
           f"{listed}. Each one either belongs in the answer, cited, or is set "
           f"aside in a clause saying why. Where one of them sets a number, "
           f"threshold, multiplier or deadline, that figure goes in the answer -- "
           f"it is the part a reader is asking for and the part a summary drops. "
           f"Do not stop at the first excerpt that answers the question, and do "
           f"not report the excerpts as silent while any of these speaks to it."]
    if not any(d.metadata.get("scope") == "title" for d in docs):
        # The router matched the question to no known title AND no title book was
        # retrieved. For a question that names a game title, that combination is
        # the corpus saying it holds no rulebook for it -- the Overwatch 2 case,
        # which has no published PDF at all. Answering such a question out of the
        # Global Rulebook presents tournament-wide text as if it were that game's
        # rules, which is the inference CLAUDE.md #4 forbids.
        out.append(
            "SCOPE. No game-title rulebook is in evidence -- only the Global "
            "Rulebook and published amendments, and the question was matched to "
            "no game title in the corpus. If the question asks about a particular "
            "game title, say plainly that the retrieved excerpts do not cover that "
            "title and that no rulebook for it was retrieved, and name what was "
            "searched. Do not answer for that title out of the Global Rulebook.")
    return out


def render_note(findings: Sequence[dict], docs: Sequence[Document],
                accountable: set[str] | None = None) -> str:
    """The precedence + completeness note the answer prompt consumes.

    It states facts and the one sentence each fact obliges. This is what replaced
    the prompt's DEFAULT CASE paragraph, its three-part precedence test and its
    COMPLETENESS clause -- the model is no longer asked to derive any of it."""
    lines: list[str] = []
    for f in findings:
        if f["kind"] == "amended":
            base = "; ".join(f["base"]) or "not among these excerpts"
            if f["incorporated"]:
                lines.append(
                    f"AMENDED. Article {f['article']} was amended by a published notice "
                    f"effective {f['effective']} ({f['amendment']}). The rulebook text in "
                    f"these excerpts ({base}) ALREADY CONTAINS the amended wording, so it "
                    f"is current AS AMENDED. Present it as amended, give its effective "
                    f"date, and cite the notice alongside the rulebook.")
            elif f["base_in_evidence"]:
                lines.append(
                    f"AMENDED. Article {f['article']} was amended by a published notice "
                    f"effective {f['effective']} ({f['amendment']}), and the rulebook text "
                    f"in these excerpts ({base}) PREDATES it. Quote the notice's wording as "
                    f"the current rule; the rulebook excerpt may be referred to only as the "
                    f"text as it stood before the amendment. Never state it as current.")
            else:
                lines.append(
                    f"AMENDED. Article {f['article']} was amended by a published notice "
                    f"effective {f['effective']} ({f['amendment']}). The rulebook article "
                    f"itself is not among these excerpts, so state the rule from the notice "
                    f"and say the underlying article was not retrieved.")
            if f["caveat"]:
                lines.append(
                    f"    The notice publishes its own caveat, which the answer must "
                    f"carry: \"{f['caveat']}\"")
        elif f["kind"] == "primacy":
            lines.append(
                f"GLOBAL PRIMACY. {f['cite']} asserts in its own text that it governs "
                f"over the game-title rulebooks on this point: \"{f['quote']}\" This is "
                f"the one direction in which Global outranks a title book. Say that the "
                f"Global Rulebook governs on this point, and cite it.")
        elif f["kind"] == "conflict":
            lines.append(
                f"CONFLICT. {f['title']} and {f['global']} both state a rule on the same "
                f"point ({f['subject']}) and they differ. The GAME-TITLE rule GOVERNS. "
                f"Give the title rule as the operative one and say in the answer that "
                f"the title rulebook governs here over the Global Rulebook. State what "
                f"the Global article provides too, and carry BOTH citations — "
                f"{f['title']} AND {f['global']} — because a reader cannot check a "
                f"precedence claim against a book the answer never cites.")
        elif f["kind"] == "agreement":
            lines.append(
                f"AGREEMENT. {f['title']} and {f['global']} state the SAME rule. Say they "
                f"agree and cite both. Do NOT assert precedence in either direction.")
        elif f["kind"] == "restatement":
            lines.append(
                f"RESTATEMENT. {f['title']} is the title book reprinting the Global rules, "
                f"not a title rule of its own. Treat it as agreeing with {f['global']}. It "
                f"does NOT outrank the Global Rulebook.")
        elif f["kind"] == "cross_ref":
            lines.append(
                f"CROSS-REFERENCE. {f['title']} defers to {f['global']} by section number. "
                f"They agree; the Global article supplies the detail. Cite both, and do "
                f"NOT assert precedence.")
        elif f["kind"] == "provenance":
            lines.append(
                f"PROVENANCE. {f['cite']} is published on a third-party host, not by the "
                f"Esports World Cup. If you rely on it against the Global Rulebook, say "
                f"that it is externally published.")
    scopes = {d.metadata.get("scope") for d in docs}
    if not lines:
        if "title" in scopes and "global" in scopes:
            lines.append("PRECEDENCE. No Global/title divergence was found among these "
                         "excerpts. State each rule from the book whose excerpt carries "
                         "its text, and do NOT assert precedence in either direction.")
        else:
            lines.append("PRECEDENCE. These excerpts come from a single tier of the "
                         "corpus, so no question of precedence arises. Do NOT assert "
                         "precedence.")
    lines += _coverage_lines(docs, accountable or set())
    return ("NOTE ON THIS EVIDENCE SET (computed from these excerpts' text and metadata "
            "before you were called -- follow it; do not re-derive it):\n"
            + "\n".join(f"  - {line}" for line in lines))


SYSTEM = """You answer questions about the Esports World Cup 2026 competitive rulebooks.
This is a compliance tool, not a chatbot. A confidently wrong answer about a forfeit
rule is worse than no answer.

Use ONLY the numbered excerpts provided. They are the entire evidence base.

CITATION. Every statement of a rule carries a citation, COPIED CHARACTER FOR CHARACTER
from the `citation=` line of the excerpt you took the rule from. Do not retype it from
memory and do not assemble one yourself. An uncited rule statement is a defect, and so
is a citation that names a book, article or page you were not shown: never pair one
rulebook's name with another rulebook's article number or page, and never cite a game
whose excerpt you did not actually use. Several citations may share one parenthetical,
separated by "; ".

PRECEDENCE. The PRECEDENCE NOTE below was computed from these excerpts' own text and
metadata, before you were called. It is a statement of fact, not a suggestion: follow
what it says, write the sentence it tells you to write, and assert no precedence it does
not state. Do not work precedence out for yourself — a rule appearing under a game's
name does not make it that game's rule; what decides is which excerpt carries the text.

ABSTAIN OVER INFER. If the excerpts do not answer the question, say plainly that the
retrieved rulebook text does not cover it, and name the rulebooks that were searched —
those are named on the "Retrieval scope searched" line below (name the BOOKS, never
restate the question). Abstain only when the excerpts really are silent: if an excerpt
does answer the question, answer it. Do not answer from general esports knowledge. Do not guess. Never write
"typically", "usually", "generally", "commonly", or "in most tournaments" — if you are
reaching for one of those words, the correct answer is that the corpus does not say.

SILENCE. A gap is a fact about what was retrieved, not about what a book contains: write
"the retrieved excerpts do not state ...". Never write that a book listed on the "Books
in evidence" line does not state, does not cover, or is silent on a point — you were
shown a handful of its articles and cannot know that. You may report a book as absent
only if it is not on that line.

QUOTING. State every rule the excerpts give you — this is about HOW, not whether. Put
each rule in your own words, keeping numbers, thresholds and conditions exact. Where the
precise wording is legally load-bearing, quote it, in quotation marks, and keep the
quotation to a phrase rather than a paragraph.

FORM. Put each citation inline, at the end of the sentence or list item it supports.
Never put a citation on a line of its own and never append a list of citations at the
end: a citation with no claim attached to it is a defect. No preamble, no restating the
question, no closing offer of further help; otherwise be concise."""

BAD_CITATIONS = """Your answer cited rulebook locations that appear in NO excerpt you were given:

{bad}

The only citations available in this evidence set are, exactly:

{allowed}

Rewrite using only those, copied exactly. Do not re-label a rule with a different
rulebook, article or page to make a citation fit, and do not attribute a rule to a game
title when the only excerpt carrying it is a Global Rulebook excerpt. If a claim cannot
be supported by one of the citations listed above, drop the claim."""

BAD_SILENCE = """Your answer claimed a rulebook says nothing on the point, but that rulebook
IS in your evidence — these excerpts came from it. The claim is false as written:

{bad}

Books in evidence: {books}

Either state what those excerpts actually do say on the point and cite them, or, if they
genuinely do not reach the point, say that "the retrieved excerpts do not state ..."
without naming a book as silent. Do not repeat the claim in other words."""

SKIPPED_SIBLINGS = """Your answer works through a section of a rulebook but passes over these
retrieved articles of that same section without a word:

{bad}

Account for each in ONE clause: either what it adds, cited — including any number,
threshold, multiplier or deadline it sets, which is the part a reader needs and the part
a summary loses — or that it was retrieved and does not bear on the question. A clause
is enough: do not expand the answer around them and do not copy their text in. Leave the
rest of your answer as it was: this is a targeted addition, not a rewrite, and nothing
you already said is in question."""

BAD_GAP = """Your answer says the excerpts do not cover something that an excerpt in front of
you does cover:

{bad}

That claim is false about this evidence set. Answer from the excerpt named in brackets
and cite it. If you believe it genuinely does not reach the point, say precisely which
narrower part is missing instead of the broad claim you made."""

TOO_VERBATIM = """Your answer reproduces a run of rulebook text word for word instead of
stating the rule in your own words:

{bad}

Find that passage in your answer and rewrite it. Keep every number, threshold, condition
and citation exactly as they are — only the sentence construction changes. If part of it
must stay word for word because the exact wording is legally load-bearing, keep only
that phrase and put it in quotation marks. Everything else in your answer stays as it
is."""

# Attached ONLY to a bad-citation correction. That correction can strip claims out of
# the answer, so it needs somewhere to land when everything goes. The other four cannot:
# they add a clause, rephrase a passage or correct a false claim about the evidence.
# Offering the abstention escape hatch to all of them was measured to destroy a correct
# answer -- the CS2 lateness fixture answered in full on attempt 1, was asked only to
# account for one skipped sibling, and came back 2/2 as "the retrieved excerpts do not
# state what happens if a Counter-Strike 2 team is late to a match", with the whole
# penalty ladder in its own context window.
REWRITE_TAIL = """
If nothing is left supported, say the retrieved rulebook text does not cover the question
and name the scope searched."""

USER = """Question: {question}

Retrieval scope searched: {scope}
Books in evidence (the only books whose text you were shown): {books}
Search query used: {query}

{note}

Excerpts retrieved, in order — use every one that bears on the question:

{index}

Excerpts:

{context}"""


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------

class State(TypedDict, total=False):
    """CLAUDE.md's contract keys plus the plumbing the nodes need.

    ``docs`` is and stays a FLAT ``list[Document]`` in retrieval order. `resolve`
    groups the excerpts, but its grouping lives in ``conflicts`` (the contract's
    own name for it) and in the rendered ``note`` -- reshaping ``docs`` would
    silently break every consumer that reads the retrieval pool, ``eval/run.py``
    among them.
    """
    # --- CLAUDE.md's contract ------------------------------------------------
    question: str
    query: str
    game: Optional[str]
    docs: list[Document]
    conflicts: list[dict]        # `resolve`'s structured findings
    answer: str
    tries: int                   # rewrite attempts; `grade` is not built (S5 report)
    # --- plumbing ------------------------------------------------------------
    scope: str
    ranks: dict                  # chunk_id -> fused relevance rank, pre-authority-sort
    note: str                    # `resolve`'s rendered precedence note for the prompt
    accountable: list[str]       # chunk_ids relevant enough to have to be accounted for
    top_findings: list[str]      # `resolve` findings about the rank-1 excerpt
    usage: list[dict]
    citation_errors: list[str]   # locators the post-check rejected; empty when clean
    outcome: str                 # which branch of `answer` produced the text (S6b)


def _chat(temperature: float = 0.0):
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=_env("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
                      temperature=temperature)


def _usage(message) -> dict:
    data = getattr(message, "usage_metadata", None) or {}
    return {"input": data.get("input_tokens", 0), "output": data.get("output_tokens", 0)}


# ---------------------------------------------------------------------------
# Nodes -- each returns a partial dict; state is never mutated in place
# ---------------------------------------------------------------------------

def route(state: State) -> dict:
    """Pick a game slug, or None for a tournament-wide question.

    Structured output constrained to the slug list derived from the corpus. The
    model may only return a slug that exists or the literal "none" -- it cannot
    invent a title, and it is told to prefer "none" over guessing."""
    from pydantic import BaseModel, Field

    pairs = catalog()
    slugs = [slug for slug, _ in pairs]

    if state.get("game") is not None:           # caller forced a scope
        game = state["game"]
        if game not in slugs:
            raise ValueError(f"unknown game slug {game!r}; known: {slugs}")
        return {"game": game, "query": state["question"], "tries": 0,
                "conflicts": [], "usage": []}

    class Route(BaseModel):
        """Which single game title's rulebook does this question concern?"""
        game: str = Field(
            description="the game slug, or 'none' if the question is tournament-wide "
                        "or names no single title"
        )

    listing = "\n".join(f"  {slug} = {title}" for slug, title in pairs)
    prompt = (
        "Route a question to at most ONE Esports World Cup game title.\n\n"
        f"Known slugs:\n{listing}\n\n"
        "Decide on the TITLE NAMED, not on the subject matter.\n"
        "- If the question names or unambiguously refers to one of the titles above "
        "(by name, common abbreviation, or its slug), return that slug. Do this even "
        "when the topic sounds tournament-wide -- sponsorship, conduct and eligibility "
        "are all also covered by individual title rulebooks, and the Global Rulebook "
        "is searched alongside the title either way, so naming the title costs nothing.\n"
        "- Return 'none' when the question names NO title above: it is tournament-wide, "
        "or it is about a game that is not in the list. Never substitute a title from "
        "the list for one that is not there.\n"
        "- If the question names more than one title, return the one it asks about; if "
        "it genuinely asks about both equally, return 'none'.\n\n"
        f"Question: {state['question']}"
    )
    result = _chat().with_structured_output(Route, include_raw=True).invoke(prompt)
    choice = (result["parsed"].game or "").strip().lower()
    game = choice if choice in slugs else None
    return {"game": game, "query": state["question"], "tries": 0, "conflicts": [],
            "usage": [{"node": "route", **_usage(result["raw"])}]}


def retrieve(state: State) -> dict:
    """Hybrid retrieval under the store-level scope filter."""
    game = state.get("game")
    where = scope_filter(game)
    docs, ranks = hybrid(state.get("query") or state["question"], where)
    if game:
        title = dict(catalog()).get(game, game)
        scope = f"the {title} rulebook and the EWC Global Rulebook 2026"
    else:
        scope = "the EWC Global Rulebook 2026 and published amendments (no title rulebook)"
    return {"docs": docs, "scope": scope, "ranks": ranks}


def _outcome(text: str) -> str:
    """Which of the two *shipping* outcomes a drafted answer is, decided
    mechanically (frontend/DESIGN.md FLAG 7.1).

    ``answered``  the text states rules and carries at least one citation.
    ``uncited``   the text carries NO citation at all.

    Non-negotiable #3 says every rule statement carries a citation. So a
    citation-free answer is either an abstention (the model saying the excerpts
    do not cover it) or a #3 defect -- and in BOTH cases it must not be
    presented as a rule statement. Which of the two it is cannot be decided
    mechanically, so it is not claimed: `uncited` is a fact about the text,
    `abstained` would be an interpretation of it.

    The other two outcomes are branches of `answer`, not properties of the text,
    so they are labelled where they are taken rather than pattern-matched back
    out of the prose afterwards. That is the whole point of returning this key:
    the sentinel wordings at the no-evidence and withheld returns are prompt
    copy, and a consumer that string-matched them would break silently the day
    someone edits a sentence."""
    return "answered" if cited_locators(text) else "uncited"


class Faults(NamedTuple):
    """Everything the mechanical post-checks found wrong with one draft."""
    cites: list[str]        # a locator cited that was in no excerpt
    silence: list[str]      # a book in evidence called silent
    gap: list[str]          # an excerpt-framed gap claim an excerpt contradicts
    skipped: list[str]      # a rung of a ladder in use, dropped without a word
    verbatim: list[str]     # rulebook text transcribed rather than stated

    def any(self) -> bool:
        return any(self)

    @property
    def untrustworthy(self) -> list[str]:
        """Faults that make the ANSWER false, not merely partial or badly written."""
        return self.cites + self.silence + self.gap

    def describe(self) -> str:
        parts = [f"unsupported citation ({b})" for b in self.cites]
        parts += [f"false silence claim: {s!r}" for s in self.silence]
        parts += [f"false gap claim: {g}" for g in self.gap]
        parts += [f"skipped sibling article: {s}" for s in self.skipped]
        parts += [f"over-quoting: {v}" for v in self.verbatim]
        return "; ".join(parts)


def answer(state: State) -> dict:
    """Generate, then hold the generated text to the evidence mechanically.

    Five checks run, none of them a second opinion from a model. Each compares the
    answer against facts already sitting in `docs`, so all five cost nothing and
    cannot themselves hallucinate:

    * `unsupported_citations` — a locator the answer cites was in no excerpt.
    * `silence_violations` — the answer says a book is silent that is in evidence.
    * `false_gap_violations` — the answer says the excerpts do not cover something
      an excerpt in front of it does cover (B6).
    * `unused_sibling_articles` — the answer worked through a ladder and dropped a
      relevant rung of it without a word (B5).
    * `verbatim_violations` — the answer transcribes rulebook text rather than
      stating the rule (B7).

    On any failure the answer is regenerated ONCE, with the specific faults named,
    and re-checked. This is bounded at one retry; there is no loop.

    What happens after a failed retry depends on what failed. A bad citation, a
    false claim about a book, or a false claim about the evidence makes the answer
    itself untrustworthy, so it is WITHHELD and replaced by an abstention naming
    the scope and the locators actually retrieved. A still-skipped sibling or an
    over-long quotation does not impeach the claims that ARE there, which have been
    checked; withholding would trade a true partial answer for none, so those ship
    -- the omission disclosed in the answer body, the over-quoting recorded in
    `citation_errors` for the operator. Either way nothing is silently rewritten:
    quietly swapping a bad article number for a plausible one would leave a wrong
    answer looking right, which is the failure this tool exists to prevent."""
    docs = state.get("docs") or []
    scope = state.get("scope", "the indexed corpus")
    if not docs:
        return {"answer": "The retrieved rulebook text does not cover this. Searched: "
                          f"{scope}. No excerpt matched.",
                "citation_errors": [], "outcome": "no_evidence"}

    allowed = allowed_citations(docs)
    accountable = state.get("accountable")
    books = "; ".join(f"{title} ({n} excerpt{'s' if n != 1 else ''})"
                      for title, n in books_in_evidence(docs))
    messages = [
        ("system", SYSTEM),
        ("human", USER.format(question=state["question"], scope=scope, books=books,
                              query=state.get("query") or state["question"],
                              note=state.get("note") or render_note([], docs),
                              index=index_lines(docs), context=render(docs))),
    ]
    usage = list(state.get("usage") or [])
    listing = "\n".join(f"  ({c})" for c in sorted(allowed))

    def faults(text: str) -> Faults:
        return Faults(
            cites=unsupported_citations(text, allowed),
            silence=silence_violations(text, docs),
            gap=false_gap_violations(text, docs, state.get("top_findings") or ()),
            skipped=unused_sibling_articles(text, docs, allowed, accountable),
            verbatim=verbatim_violations(text, docs),
        )

    def correction_for(found: Faults) -> str:
        blocks = []
        if found.cites:
            blocks.append(BAD_CITATIONS.format(
                bad="\n".join(f"  ({b})" for b in found.cites), allowed=listing))
        if found.silence:
            blocks.append(BAD_SILENCE.format(
                bad="\n".join(f"  {s}" for s in found.silence), books=books))
        if found.gap:
            blocks.append(BAD_GAP.format(bad="\n".join(f"  {g}" for g in found.gap)))
        if found.skipped:
            blocks.append(SKIPPED_SIBLINGS.format(
                bad="\n".join(f"  {s}" for s in found.skipped)))
        if found.verbatim:
            blocks.append(TOO_VERBATIM.format(
                bad="\n".join(f"  {v}" for v in found.verbatim)))
        text = "\n\n".join(blocks)
        return text + "\n" + REWRITE_TAIL if found.cites else text

    response = _chat().invoke(messages)
    usage.append({"node": "answer", **_usage(response)})
    text = response.content
    found = faults(text)
    if not found.any():
        return {"answer": text, "usage": usage, "citation_errors": [],
                "outcome": _outcome(text)}

    errors = [f"attempt 1: {found.describe()}"]
    retry = _chat().invoke(messages + [("ai", text), ("human", correction_for(found))])
    usage.append({"node": "answer.recite", **_usage(retry)})
    found = faults(retry.content)
    if not found.any():
        return {"answer": retry.content, "usage": usage, "citation_errors": errors,
                "outcome": _outcome(retry.content)}

    errors.append(f"attempt 2: {found.describe()}")

    if not found.untrustworthy:
        # Partial or verbose, but everything it claims was checked and stands.
        # Withholding it would trade a stated partial answer for none, which
        # CLAUDE.md does not ask for -- so it ships, with the omission disclosed
        # in the body rather than left silent.
        body = retry.content
        if found.skipped:
            body += ("\n\nAlso retrieved and not covered above: "
                     + "; ".join(found.skipped) + ".")
        return {"answer": body, "usage": usage, "citation_errors": errors,
                "outcome": _outcome(body)}

    withheld = (
        "The drafted answer could not be reconciled with the retrieved excerpts, so it "
        "has been withheld rather than shown.\n"
        f"Searched: {scope}.\n"
        f"Unreconciled: {found.describe()}\n"
        "The excerpts actually retrieved were:\n" + listing
    )
    return {"answer": withheld, "usage": usage, "citation_errors": errors,
            "outcome": "withheld"}


def build_graph():
    """route -> retrieve -> resolve -> answer.

    CLAUDE.md's full contract is ``route -> retrieve -> grade -> (retrieve |
    resolve) -> answer``. `grade` (the single rewrite loop) is deliberately NOT
    built at S5 and is reported as deferred rather than half-built -- see the S5
    handoff. Its state key ``tries`` is threaded through unchanged so adding the
    node later does not reshape the state.
    """
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(State)
    builder.add_node("route", route)
    builder.add_node("retrieve", retrieve)
    builder.add_node("resolve", resolve)
    builder.add_node("answer", answer)
    builder.add_edge(START, "route")
    builder.add_edge("route", "retrieve")
    builder.add_edge("retrieve", "resolve")
    builder.add_edge("resolve", "answer")
    builder.add_edge("answer", END)
    return builder.compile()


_APP = None


def ask(question: str, game: str | None = None) -> State:
    """Run the pipeline once. Never cached -- the corpus is versioned."""
    global _APP
    if _APP is None:
        _APP = build_graph()
    initial: State = {"question": question, "tries": 0, "conflicts": []}
    if game:
        initial["game"] = game
    return _APP.invoke(initial)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

CHAT_PRICE_PER_1M = {            # USD per 1M tokens
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask the EWC rulebook corpus.")
    parser.add_argument("question", nargs="+")
    parser.add_argument("--game", default=None, help="force a slug, skipping the router")
    parser.add_argument("--show-docs", action="store_true",
                        help="print the retrieved excerpts' metadata")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 2

    question = " ".join(args.question)
    state = ask(question, game=args.game)

    print(f"routed to: {state.get('game') or 'NONE (tournament-wide)'}")
    print(f"searched : {state.get('scope')}")
    if args.show_docs:
        print("retrieved:")
        for n, doc in enumerate(state.get("docs") or [], start=1):
            meta = doc.metadata
            print(f"  {n}. auth={meta['authority']} {meta['game']:16s} "
                  f"art={meta.get('article') or '-':10s} p.{meta['page']:<4d} "
                  f"{(meta.get('heading') or '')[:52]}")
    print()
    print(state.get("answer", ""))

    for note in state.get("citation_errors") or []:
        print(f"[citation post-check rejected] {note}", file=sys.stderr)

    usage = state.get("usage") or []
    if usage:
        model = _env("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        rate_in, rate_out = CHAT_PRICE_PER_1M.get(model, (0.0, 0.0))
        tin = sum(u["input"] for u in usage)
        tout = sum(u["output"] for u in usage)
        cost = (rate_in * tin + rate_out * tout) / 1_000_000
        print(f"\n[{model}: {tin} in / {tout} out tokens = ${cost:.6f}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

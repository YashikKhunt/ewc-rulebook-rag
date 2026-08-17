"""Scrape the published amendment / ruling articles into ``data/amendments.json``.

Stage S5, first half. CLAUDE.md: *"The PDFs are not the whole truth. Rulings and
amendments are published as HTML articles under ``/en/competitive-ops/articles/*``
and can supersede a PDF article."* A PDF-only index states superseded rules with
full confidence, so this module gives the amendment layer its own documents at
``scope="amendment"``, ``authority=2``.

What the crawl actually finds (measured 2026-08-14, 2 HTTP requests)
--------------------------------------------------------------------
The listing page ships every article record in its own server-rendered data
payload, **including the full article body**, so the amendment layer costs one
request. A second request to the article's own page was made once, to hand-check
that the payload body matches the rendered page verbatim -- it does.

Exactly **one** published article carries a body: *"Global Rulebook Update:
Article 3.2.3 (Team Roster Integrity)"*, effective 2026-07-17. The other three
records ("EWC 2026 Tournament Participation Agreement", "Participant Sponsorship
Guidelines", "EWC Title Defenders") are off-site links with no body in the
payload; they are recorded in the ``skipped`` list with their reason and are not
indexed. The "Public Version Archive" is still ``kind:"placeholder"`` / "Coming
soon" and is not built against; the ``supersedes`` field is carried for it.

One chunk per amendment, deliberately
-------------------------------------
An amendment notice is **not** split into sections. Its "Previous rule" section
quotes the text the amendment replaces; if that section could be retrieved on its
own, the pipeline could put a superseded rule in front of a reader as current --
precisely the failure CLAUDE.md #2 exists to prevent. Keeping the notice whole
means the superseding text and the text it supersedes are never separated. A
notice longer than ``MAX_NOTICE_CHARS`` is split with the CLAUDE.md splitter and
logged loudly, because that property is then no longer guaranteed.

Nothing here is hardcoded: the article URLs come from the listing payload, and
the book an amendment targets is matched against the *manifest's* own titles.

Usage::

    python articles.py                 # crawl, write data/amendments.json
    python articles.py --dry-run       # crawl and report, write nothing
    python articles.py --show          # print the parsed amendments
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urljoin

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ingest import Config, Crawler, load_config, normalise_date

log = logging.getLogger("articles")

ROOT = Path(__file__).resolve().parent

#: Authority level for an amendment, per CLAUDE.md's precedence contract.
AUTHORITY_AMENDMENT = 2

#: Above this a notice is split rather than kept whole (see the module docstring).
MAX_NOTICE_CHARS = 6000
SPLIT_CHARS = 1200          # CLAUDE.md's splitter settings, used only past the cap
SPLIT_OVERLAP = 150

#: One article record in the listing page's data payload.
_RECORD_START = re.compile(r'\{id:"(?P<id>[^"]{1,80})",badge:')

#: "Art. 3.2.3", "Article 3.2.3", "Rule 3.2.3", "Section 5.1.2.1".
_ARTICLE_REF = re.compile(
    r"\b(?:art\.?|article|rule|section)\s+(\d{1,2}(?:\.\d{1,3}){0,3})\b", re.I
)

#: "Effective date: July 17, 2026" / "effective 17 July 2026".
_EFFECTIVE = re.compile(
    r"effective(?:\s+date)?\s*[:\-]?\s*"
    r"([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4}|\d{4}-\d{2}-\d{2})",
    re.I,
)

#: A markdown section heading in a notice body.
_SECTION = re.compile(r"^#{1,6}\s*(.+?)\s*$", re.M)

#: Sections that state the text the amendment INSTALLS, and the text it REPLACES.
_NEW_SECTION = re.compile(r"what\s+is\s+changing|what\s+changed|new\s+(?:rule|wording)"
                          r"|amended\s+(?:rule|text)|updated\s+(?:rule|wording)", re.I)
_OLD_SECTION = re.compile(r"previous\s+(?:rule|version|wording)|former\s+(?:rule|wording)"
                          r"|old\s+(?:rule|wording)", re.I)

#: A block quote of rule text inside a notice.
_QUOTED = re.compile(r'"([^"]{40,2000})"')

#: The notice's own precedence caveat, if it publishes one.
_CAVEAT = re.compile(
    r"[^.]*\bdiscrepanc\w*\b[^.]*\b(?:prevail|govern|control)\w*\b[^.]*\.", re.I
)

_TOKEN = re.compile(r"[a-z0-9]+")
#: Tokens too generic to identify a book by.
_TITLE_STOP = frozenset({"the", "of", "and", "rulebook", "rules", "rule", "2026", "2025"})


# ---------------------------------------------------------------------------
# JS payload parsing
# ---------------------------------------------------------------------------

def _js_string_at(html: str, start: int) -> tuple[str, int]:
    """Read the double-quoted JS string literal beginning at ``start``.

    The payload is JavaScript, not JSON: bodies are long, contain escaped
    newlines and escaped quotes, and are not parseable with ``json.loads``
    without first finding their exact extent. Returns (decoded, end_index).
    """
    assert html[start] == '"'
    out: list[str] = []
    i = start + 1
    while i < len(html):
        ch = html[i]
        if ch == "\\":
            out.append(html[i:i + 2])
            i += 2
            continue
        if ch == '"':
            break
        out.append(ch)
        i += 1
    raw = "".join(out)
    try:
        text = raw.encode("utf-8", "surrogatepass").decode("unicode_escape")
        text = text.encode("latin-1", "ignore").decode("utf-8", "ignore") or raw
    except (UnicodeDecodeError, UnicodeEncodeError):
        text = raw
    return text, i + 1


def _field(html: str, start: int, end: int, name: str) -> str | None:
    """Value of ``name:"..."`` inside ``html[start:end]``, or None (incl. ``void 0``)."""
    pattern = re.compile(rf"\b{re.escape(name)}:")
    match = pattern.search(html, start, end)
    if not match:
        return None
    pos = match.end()
    while pos < end and html[pos] == " ":
        pos += 1
    if html.startswith("void 0", pos):
        return None
    if pos >= end or html[pos] != '"':
        return None
    value, _ = _js_string_at(html, pos)
    return value or None


def _absolute(href: str | None, listing_url: str) -> str | None:
    """Resolve a payload href against the listing page.

    The payload publishes root-relative hrefs *without* the locale segment
    (``/competitive-ops/articles/article``), so a plain ``urljoin`` against the
    listing URL drops ``/en`` and yields a 404. Root-relative hrefs are joined
    against the locale root instead -- the URL this resolves to was fetched and
    confirmed live (200) during the hand-check.
    """
    if not href:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        locale_root = listing_url.rstrip("/").rsplit("/", 1)[0]
        return urljoin(locale_root + "/", href.lstrip("/"))
    return urljoin(listing_url.rstrip("/") + "/", href)


@dataclass
class RawArticle:
    id: str
    title: str | None
    excerpt: str | None
    href: str | None
    published: str | None
    label: str | None
    body: str | None


def parse_articles(html: str, listing_url: str) -> list[RawArticle]:
    """Every article record the listing page ships, body included where present."""
    starts = [m.start() for m in _RECORD_START.finditer(html)]
    found: list[RawArticle] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(html)
        ident = _RECORD_START.match(html, start).group("id")
        href = _field(html, start, end, "href")
        found.append(
            RawArticle(
                id=ident,
                title=_field(html, start, end, "title"),
                excerpt=_field(html, start, end, "excerpt"),
                href=_absolute(href, listing_url),
                published=normalise_date((_field(html, start, end, "publishedDate")
                                          or "")[:10]),
                label=_field(html, start, end, "label"),
                body=_field(html, start, end, "body"),
            )
        )
    return found


# ---------------------------------------------------------------------------
# Interpreting one notice
# ---------------------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _TITLE_STOP}


def book_index(manifest: dict) -> list[tuple[str, str, set[str]]]:
    """(game, game_title, identifying tokens) for every book in the manifest.

    The slug list is never written down here: whichever books ingest found are
    the books an amendment can target.
    """
    out = []
    for record in manifest.get("documents", []):
        tokens = _tokens(record["game_title"]) | _tokens(record["game"].replace("-", " "))
        out.append((record["game"], record["game_title"], tokens))
    return out


def sections(body: str) -> list[tuple[str, str]]:
    """(heading, text) for each markdown section of a notice, in order."""
    marks = list(_SECTION.finditer(body))
    out: list[tuple[str, str]] = []
    if not marks:
        return [("", body.strip())]
    if marks[0].start() > 0:
        out.append(("", body[: marks[0].start()].strip()))
    for n, mark in enumerate(marks):
        end = marks[n + 1].start() if n + 1 < len(marks) else len(body)
        out.append((mark.group(1).strip(), body[mark.end():end].strip()))
    return out


def _quoted_rule_text(body: str, wanted: re.Pattern) -> str | None:
    """The quoted rule text under the first section whose heading matches."""
    for heading, text in sections(body):
        if heading and wanted.search(heading):
            quotes = _QUOTED.findall(text)
            if quotes:
                return " ".join(q.strip() for q in quotes)
    return None


def targets(article: RawArticle, books: Sequence[tuple[str, str, set[str]]]
            ) -> list[dict]:
    """Which (book, article number) pairs this notice amends.

    An article number is only accepted when the surrounding sentence also names
    a book from the manifest -- "Art. 3.2.3 of the EWC 2026 Global Rulebook".
    A bare number with no book named is ambiguous and is not indexed as a target.
    """
    text = " ".join(filter(None, [article.title, article.excerpt, article.body or ""]))
    hits: dict[tuple[str, str], dict] = {}
    for match in _ARTICLE_REF.finditer(text):
        number = match.group(1)
        window = text[max(0, match.start() - 120): match.end() + 160]
        window_tokens = _tokens(window)
        for game, game_title, ident in books:
            if ident and ident <= window_tokens:
                hits.setdefault((game, number),
                                {"game": game, "game_title": game_title,
                                 "article": number})
    return sorted(hits.values(), key=lambda t: (t["game"], t["article"]))


@dataclass
class Amendment:
    id: str
    title: str
    excerpt: str | None
    source_url: str
    published: str | None
    effective_date: str | None
    label: str | None
    targets: list[dict]
    heading: str
    body: str
    new_text: str | None
    previous_text: str | None
    caveat: str | None


@dataclass
class SkippedArticle:
    id: str
    title: str | None
    href: str | None
    reason: str


@dataclass
class ArticleCrawl:
    amendments: list[Amendment] = field(default_factory=list)
    skipped: list[SkippedArticle] = field(default_factory=list)
    requests: int = 0


def interpret(article: RawArticle, books: Sequence[tuple[str, str, set[str]]],
              listing_url: str) -> Amendment | SkippedArticle:
    if not article.body:
        return SkippedArticle(article.id, article.title, article.href,
                              "no body in the listing payload (external link)")
    found = targets(article, books)
    if not found:
        return SkippedArticle(article.id, article.title, article.href,
                              "no rulebook article number tied to a known book")
    effective = _EFFECTIVE.search(article.body)
    heading = next((h for h, _ in sections(article.body) if h), article.title or "")
    caveat = _CAVEAT.search(article.body)
    return Amendment(
        id=article.id,
        title=article.title or heading,
        excerpt=article.excerpt,
        source_url=article.href or listing_url,
        published=article.published,
        effective_date=(normalise_date(_clean_date(effective.group(1)))
                        if effective else article.published),
        label=article.label,
        targets=found,
        heading=heading,
        body=article.body.strip(),
        new_text=_quoted_rule_text(article.body, _NEW_SECTION),
        previous_text=_quoted_rule_text(article.body, _OLD_SECTION),
        caveat=" ".join(caveat.group(0).split()) if caveat else None,
    )


_MONTHS = {m: n for n, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
    start=1)}


def _clean_date(raw: str) -> str:
    """Turn 'July 17, 2026' into a shape ingest.normalise_date() understands."""
    raw = raw.strip().rstrip(".")
    match = re.fullmatch(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", raw)
    if match:
        month = _MONTHS.get(match.group(1)[:3].lower())
        if month:
            return f"{int(match.group(3)):04d}-{month:02d}-{int(match.group(2)):02d}"
    return re.sub(r"(\d),\s*(\d{4})", r"\1 \2", raw)


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------

def crawl(crawler: Crawler, cfg: Config, manifest: dict) -> ArticleCrawl:
    """One request: the listing page carries every article record and its body."""
    log.info("fetching listing page %s", cfg.base_url)
    _soup, html = crawler.get_soup(cfg.base_url)
    books = book_index(manifest)

    result = ArticleCrawl()
    for raw in parse_articles(html, cfg.base_url):
        outcome = interpret(raw, books, cfg.base_url)
        if isinstance(outcome, SkippedArticle):
            log.info("skip  %-46s | %s", (raw.title or raw.id)[:46], outcome.reason)
            result.skipped.append(outcome)
        else:
            log.info("found %-46s | targets %s | effective %s",
                     outcome.title[:46],
                     ", ".join(f"{t['game']} {t['article']}" for t in outcome.targets),
                     outcome.effective_date or "unstated")
            result.amendments.append(outcome)
    result.requests = crawler.request_count
    return result


def amendments_path(cfg: Config) -> Path:
    return cfg.data_dir / "amendments.json"


def write_amendments(cfg: Config, result: ArticleCrawl) -> dict:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": cfg.base_url,
        "http_requests": result.requests,
        "counts": {"amendments": len(result.amendments),
                   "skipped": len(result.skipped)},
        "amendments": [
            {
                "id": a.id,
                "title": a.title,
                "excerpt": a.excerpt,
                "label": a.label,
                "source_url": a.source_url,
                "published": a.published,
                "effective_date": a.effective_date,
                "scope": "amendment",
                "authority": AUTHORITY_AMENDMENT,
                "targets": a.targets,
                "heading": a.heading,
                "new_text": a.new_text,
                "previous_text": a.previous_text,
                "caveat": a.caveat,
                "supersedes": [f"{t['game']}:{t['article']}" for t in a.targets],
                "body": a.body,
            }
            for a in result.amendments
        ],
        "skipped": [
            {"id": s.id, "title": s.title, "href": s.href, "reason": s.reason}
            for s in result.skipped
        ],
    }
    path = amendments_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return payload


# ---------------------------------------------------------------------------
# Documents for the index
# ---------------------------------------------------------------------------

def _context_label(game_title: str, article: str, heading: str) -> str:
    """Same shape chunker.context_label() produces, so the embedding of an
    amendment carries its article context exactly as a rulebook chunk's does."""
    bits = [game_title]
    if article:
        bits.append(f"Article {article}")
    if heading:
        bits.append(f"— {heading}")
    return "[" + " · ".join(bits[:2]) + (f" {bits[2]}" if len(bits) > 2 else "") + "]"


def amendment_documents(path: Path | None = None) -> list[Document]:
    """``data/amendments.json`` -> LangChain Documents, one per (notice, target).

    Metadata mirrors chunker.py's exactly -- ``chunker.validate()`` is run over
    these alongside the PDF chunks by index.py, so a missing or None-valued key
    fails the build rather than reaching the store.
    """
    path = path or (ROOT / "data" / "amendments.json")
    if not path.exists():
        log.warning("%s missing -- run `python articles.py` first; "
                    "indexing without the amendment layer", path)
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=SPLIT_CHARS, chunk_overlap=SPLIT_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    docs: list[Document] = []
    for entry in payload.get("amendments", []):
        body = entry["body"]
        pieces = [body]
        if len(body) > MAX_NOTICE_CHARS:
            log.warning(
                "notice %s is %d chars (> %d): splitting it, so a 'previous rule' "
                "section can now be retrieved without its superseding text",
                entry["id"], len(body), MAX_NOTICE_CHARS)
            pieces = splitter.split_text(body)

        for target in entry["targets"]:
            title = f"{target['game_title']} Amendment {entry['effective_date'] or entry['id']}"
            for n, piece in enumerate(pieces):
                label = _context_label(title, target["article"], entry["heading"])
                meta = {
                    "game": target["game"],
                    "game_title": title,
                    "scope": "amendment",
                    "authority": AUTHORITY_AMENDMENT,
                    "article": target["article"],
                    "article_id": target["article"],
                    "heading": entry["heading"],
                    "heading_path": entry["heading"],
                    "part": "",
                    "page": 1,
                    "page_end": 1,
                    "chunk": n,
                    "chunk_of": len(pieces),
                    "chunk_id": f"amendment:{entry['id']}:{target['game']}:"
                                f"{target['article']}:{n}",
                    "n_chars": len(piece),
                    "version": entry["effective_date"] or "",
                    "effective_date": entry["effective_date"] or "",
                    "source_url": entry["source_url"],
                    "doc_title": entry["title"],
                    "supersedes": f"{target['game']}:{target['article']}",
                    "external_host": False,
                    "source_path": str(path.name),
                    "amends_game": target["game"],
                    "amends_article": target["article"],
                    "amends_title": target["game_title"],
                    "new_text": entry.get("new_text") or "",
                    "previous_text": entry.get("previous_text") or "",
                    "caveat": entry.get("caveat") or "",
                }
                docs.append(Document(page_content=f"{label}\n{piece}", metadata=meta))
    return docs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="crawl, write nothing")
    parser.add_argument("--show", action="store_true", help="print each amendment")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)-7s %(message)s", stream=sys.stdout)

    cfg = load_config()
    manifest_path = cfg.data_dir / "manifest.json"
    if not manifest_path.exists():
        log.error("%s missing -- run `python ingest.py` first", manifest_path)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    crawler = Crawler(cfg.user_agent, cfg.crawl_delay)
    import requests
    try:
        result = crawl(crawler, cfg, manifest)
    except requests.RequestException as exc:
        log.error("could not fetch the listing page: %s", exc)
        return 1

    if args.show:
        for amendment in result.amendments:
            print("\n" + "=" * 78)
            print(amendment.title)
            print(f"  targets   : {amendment.targets}")
            print(f"  effective : {amendment.effective_date}")
            print(f"  new_text  : {(amendment.new_text or '')[:200]}")
            print(f"  previous  : {(amendment.previous_text or '')[:200]}")
            print(f"  caveat    : {amendment.caveat}")

    if args.dry_run:
        log.info("dry run: %d amendments, %d skipped, %d requests",
                 len(result.amendments), len(result.skipped), result.requests)
        return 0

    payload = write_amendments(cfg, result)
    log.info("wrote %s | %d amendments, %d skipped, %d requests",
             amendments_path(cfg), payload["counts"]["amendments"],
             payload["counts"]["skipped"], result.requests)

    docs = amendment_documents(amendments_path(cfg))
    log.info("%d amendment chunk(s) ready for index.py", len(docs))
    for doc in docs:
        meta = doc.metadata
        log.info("  %s | %s Article %s | %d chars",
                 meta["chunk_id"], meta["game_title"], meta["article"],
                 meta["n_chars"])
    if not result.amendments:
        log.warning("no amendments found -- the index will be PDF-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

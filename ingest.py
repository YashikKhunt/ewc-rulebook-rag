"""Discover and download the EWC 2026 competitive rulebook PDFs.

Stage S1 of the pipeline. Crawls the official Competitive Operations resource,
discovers the Global Rulebook plus every per-game-title rulebook, downloads the
PDFs into ``data/pdfs/`` and writes ``data/manifest.json`` for the chunker.

Nothing about the corpus is hardcoded: the game slug list comes from the listing
page's server-rendered links, and every PDF URL comes from the corresponding
detail page. CDN URLs are content-hashed and change on re-upload, so the hash
embedded in the URL is used as the cache key -- a re-run re-crawls the (cheap)
HTML to detect re-uploads but does not re-download PDF bytes it already holds.

The crawl is deliberately slow, serial and identified. This is a public official
resource owned by the Esports Foundation; treat it gently.

Usage::

    python ingest.py
    python ingest.py --dry-run    # discovery only, downloads nothing
    python ingest.py --force      # ignore the cache, re-download everything
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

log = logging.getLogger("ingest")

# --- Configuration -----------------------------------------------------------

DEFAULT_BASE_URL = "https://resources.esportsworldcup.com/en/competitive-ops"
DEFAULT_USER_AGENT = "ewc-rulebook-rag/0.1 (+contact: you@example.com)"
DEFAULT_CRAWL_DELAY = 0.6
DEFAULT_DATA_DIR = "data"

# Authority levels, per the precedence contract: higher wins.
AUTHORITY_GLOBAL = 0
AUTHORITY_TITLE = 1

# Detail pages hang off the listing page as /.../rulebooks/<slug>.
RULEBOOK_HREF_RE = re.compile(r"/rulebooks/(?P<slug>[a-z0-9][a-z0-9-]*)/?$", re.I)

# The download control on both the listing hero and each detail page.
DOWNLOAD_TEXT_RE = re.compile(r"download\s+rulebook", re.I)

# "v1.0 . effective 1 Jan 2026 . English"
VERSION_RE = re.compile(r"\bv(\d+(?:\.\d+)*)\b", re.I)
EFFECTIVE_RE = re.compile(
    r"effective\s+(\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4})", re.I
)

# The page ships its server-rendered data alongside the markup. Rendered HTML is
# the primary source; these narrow patterns only recover version / effective-date
# fields, which have no rendered equivalent on the title detail pages. Both are
# optional -- a miss yields None and never fails the run.
PAYLOAD_GLOBAL_RE = re.compile(r'version:"([^"]*)",effectiveDate:"([^"]*)"')
PAYLOAD_DOC_RE = re.compile(
    r'version:(void 0|"[^"]*"),publishDate:(void 0|"[^"]*"),'
    r'highlighted:(?:!0|!1),externalUrl:(void 0|"[^"]*"),fileUrl:(void 0|"[^"]*")'
)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


@dataclass
class Config:
    base_url: str
    user_agent: str
    crawl_delay: float
    data_dir: Path

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdfs"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"


def load_config() -> Config:
    load_dotenv()
    try:
        delay = float(os.getenv("EWC_CRAWL_DELAY", DEFAULT_CRAWL_DELAY))
    except ValueError:
        log.warning("EWC_CRAWL_DELAY is not a number; falling back to %s", DEFAULT_CRAWL_DELAY)
        delay = DEFAULT_CRAWL_DELAY
    # Etiquette floor: never crawl faster than the documented delay, whatever the
    # environment says.
    if delay < DEFAULT_CRAWL_DELAY:
        log.warning("EWC_CRAWL_DELAY=%s is below the %ss floor; using the floor", delay, DEFAULT_CRAWL_DELAY)
        delay = DEFAULT_CRAWL_DELAY
    return Config(
        base_url=os.getenv("EWC_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        user_agent=os.getenv("EWC_USER_AGENT", DEFAULT_USER_AGENT),
        crawl_delay=delay,
        data_dir=Path(os.getenv("EWC_DATA_DIR", DEFAULT_DATA_DIR)),
    )


# --- Polite serial crawler ---------------------------------------------------


class Crawler:
    """Strictly serial fetcher that keeps a minimum gap between requests.

    One attempt per URL. Failures are reported to the caller, which logs and
    skips -- this crawler never retries a public resource in a loop.
    """

    def __init__(self, user_agent: str, delay: float):
        self.delay = delay
        self._last_request_at = 0.0
        self.request_count = 0
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        )

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_request_at
        if self._last_request_at and gap < self.delay:
            time.sleep(self.delay - gap)

    def get(self, url: str, *, stream: bool = False, timeout: int = 60):
        self._throttle()
        try:
            response = self.session.get(url, stream=stream, timeout=timeout)
        finally:
            self._last_request_at = time.monotonic()
            self.request_count += 1
        response.raise_for_status()
        return response

    def get_soup(self, url: str) -> tuple[BeautifulSoup, str]:
        response = self.get(url)
        html = response.text
        return BeautifulSoup(html, "lxml"), html


# --- Small parsing helpers ---------------------------------------------------


def normalise_text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split())


def looks_like_pdf(url: str) -> bool:
    """True when the URL path names a PDF. Query strings are ignored."""
    return urlparse(url).path.lower().endswith(".pdf")


def url_content_hash(url: str) -> str:
    """Cache key for a rulebook URL.

    CDN uploads carry a content hash in the filename
    (``EWC_CS_2026_Rulebook_fe6e24ed0b.pdf``), so a re-upload changes the key and
    forces a fresh download. Externally hosted PDFs carry no such hash, so fall
    back to a digest of the URL itself -- still stable, just not content-aware.
    """
    stem = Path(urlparse(url).path).stem
    tokens = [t for t in stem.split("_") if re.fullmatch(r"[0-9a-f]{8,}", t)]
    if tokens:
        return "".join(tokens)
    return "u" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def normalise_date(raw: str | None) -> str | None:
    """Normalise a published date to ISO ``YYYY-MM-DD``, or None."""
    if not raw:
        return None
    raw = raw.strip().rstrip(".")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})", raw)
    if match:
        day, month_name, year = match.groups()
        month = MONTHS.get(month_name[:3].lower())
        if month:
            return f"{int(year):04d}-{month:02d}-{int(day):02d}"
    log.debug("could not normalise date %r", raw)
    return None


def parse_meta_line(text: str) -> tuple[str | None, str | None]:
    """Pull ``version`` and ISO ``effective_date`` out of rendered card text."""
    version_match = VERSION_RE.search(text)
    effective_match = EFFECTIVE_RE.search(text)
    version = f"v{version_match.group(1)}" if version_match else None
    effective = normalise_date(effective_match.group(1)) if effective_match else None
    return version, effective


def _unquote(js_value: str) -> str | None:
    """Turn a captured JS literal into a string, mapping ``void 0`` to None."""
    if js_value == "void 0":
        return None
    return js_value[1:-1] or None


def payload_global_meta(html: str) -> tuple[str | None, str | None]:
    """Version / effective date for the Global Rulebook, if the page ships them."""
    match = PAYLOAD_GLOBAL_RE.search(html)
    if not match:
        return None, None
    return match.group(1) or None, normalise_date(match.group(2))


def payload_doc_meta(html: str, url: str) -> tuple[str | None, str | None]:
    """Version / publish date for the document whose URL is ``url``, if published.

    Every title rulebook currently ships these as absent, so this normally
    returns ``(None, None)``. It is kept so the manifest picks the fields up
    automatically if the Foundation starts publishing them.
    """
    for match in PAYLOAD_DOC_RE.finditer(html):
        version, published, external_url, file_url = match.groups()
        if url in (_unquote(external_url), _unquote(file_url)):
            return _unquote(version), normalise_date(_unquote(published))
    return None, None


def find_download_url(scope_node, page_url: str) -> str | None:
    """Href of the 'Download rulebook' control within ``scope_node``."""
    for anchor in scope_node.find_all("a", href=True):
        if DOWNLOAD_TEXT_RE.search(normalise_text(anchor)):
            return urljoin(page_url, anchor["href"])
    return None


# --- Discovery ---------------------------------------------------------------


@dataclass
class Document:
    """A rulebook the crawler decided to fetch."""

    game: str
    game_title: str
    scope: str
    authority: int
    doc_title: str | None
    version: str | None
    effective_date: str | None
    source_url: str
    detail_url: str
    url_hash: str
    supersedes: None = None  # reserved for the Public Version Archive
    path: str | None = None
    bytes: int | None = None
    sha256: str | None = None
    downloaded_at: str | None = None
    cached: bool = False
    external_host: bool = False


@dataclass
class Skipped:
    game: str
    game_title: str | None
    detail_url: str
    reason: str
    url: str | None = None


@dataclass
class Discovery:
    documents: list[Document] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)


def discover_global(soup: BeautifulSoup, html: str, listing_url: str) -> Document | None:
    """The Global Rulebook is presented on the listing page itself, not under
    /rulebooks/<slug>. Find its download control and read the card around it."""
    for anchor in soup.find_all("a", href=True):
        if not DOWNLOAD_TEXT_RE.search(normalise_text(anchor)):
            continue
        url = urljoin(listing_url, anchor["href"])
        if not looks_like_pdf(url):
            continue
        card = anchor.find_parent("article") or anchor.parent
        heading = card.find(re.compile(r"^h[1-6]$"))
        title = normalise_text(heading) if heading else "EWC Global Rulebook"
        version, effective = parse_meta_line(normalise_text(card))
        payload_version, payload_effective = payload_global_meta(html)
        return Document(
            game="global",
            game_title=title,
            scope="global",
            authority=AUTHORITY_GLOBAL,
            doc_title=title,
            # Prefer the ISO date the page ships; fall back to the rendered line.
            version=payload_version or version,
            effective_date=payload_effective or effective,
            source_url=url,
            detail_url=listing_url,
            url_hash=url_content_hash(url),
            external_host=not _is_official_host(url),
        )
    return None


def _is_official_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("esportsworldcup.com")


def discover_title_urls(soup: BeautifulSoup, listing_url: str) -> list[tuple[str, str]]:
    """(slug, detail_url) for every title rulebook linked from the listing page.

    The listing page's filter controls need JS, but the links themselves are
    server-rendered, so a plain parse sees the complete list.
    """
    found: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        match = RULEBOOK_HREF_RE.search(urlparse(anchor["href"]).path)
        if match:
            slug = match.group("slug").lower()
            found.setdefault(slug, urljoin(listing_url, anchor["href"]))
    return sorted(found.items())


def title_name(soup: BeautifulSoup, slug: str) -> str:
    """Human-readable game name, e.g. 'Counter-Strike 2' for slug 'cs2'."""
    if soup.title:
        head = normalise_text(soup.title).split("·")[0].strip()
        head = re.sub(r"\s+Rulebook\s*(\d{4})?$", "", head).strip()
        if head:
            return head
    heading = soup.find("h1")
    if heading:
        return re.sub(r"\s+Rulebook\s*(\d{4})?$", "", normalise_text(heading)).strip()
    return slug


def discover_title(crawler: Crawler, slug: str, detail_url: str) -> Document | Skipped:
    """Visit one detail page and resolve its rulebook PDF, or explain the skip."""
    soup, html = crawler.get_soup(detail_url)
    name = title_name(soup, slug)

    section = soup.find("article", attrs={"aria-labelledby": "rulebook-pdf-heading"}) or soup
    url = find_download_url(section, detail_url)
    if not url:
        return Skipped(slug, name, detail_url, "no rulebook download link on the detail page")
    if not looks_like_pdf(url):
        return Skipped(slug, name, detail_url, "published rulebook is not a PDF", url)

    version, effective = payload_doc_meta(html, url)
    return Document(
        game=slug,
        game_title=name,
        scope="title",
        authority=AUTHORITY_TITLE,
        doc_title=None,
        version=version,
        effective_date=effective,
        source_url=url,
        detail_url=detail_url,
        url_hash=url_content_hash(url),
        external_host=not _is_official_host(url),
    )


def discover(crawler: Crawler, cfg: Config) -> Discovery:
    listing_url = cfg.base_url
    log.info("fetching listing page %s", listing_url)
    soup, html = crawler.get_soup(listing_url)

    result = Discovery()

    global_doc = discover_global(soup, html, listing_url)
    if global_doc:
        log.info(
            "global   | %s | %s | effective %s",
            global_doc.game_title, global_doc.version or "no version",
            global_doc.effective_date or "unknown",
        )
        result.documents.append(global_doc)
    else:
        log.error("no Global Rulebook download link found on the listing page")
        result.skipped.append(
            Skipped("global", None, listing_url, "no Global Rulebook link on the listing page")
        )

    titles = discover_title_urls(soup, listing_url)
    log.info("discovered %d title rulebook slugs", len(titles))

    for slug, detail_url in titles:
        try:
            outcome = discover_title(crawler, slug, detail_url)
        except requests.RequestException as exc:
            log.warning("skip %-18s | detail page unreachable: %s", slug, exc)
            result.skipped.append(Skipped(slug, None, detail_url, f"detail page unreachable: {exc}"))
            continue
        except Exception as exc:  # a malformed page must not end the crawl
            log.warning("skip %-18s | could not parse detail page: %s", slug, exc)
            result.skipped.append(Skipped(slug, None, detail_url, f"could not parse detail page: {exc}"))
            continue

        if isinstance(outcome, Skipped):
            log.warning("skip %-18s | %s", slug, outcome.reason)
            result.skipped.append(outcome)
        else:
            log.info("found %-18s | %s", slug, Path(urlparse(outcome.source_url).path).name)
            result.documents.append(outcome)

    return result


# --- Download ----------------------------------------------------------------


def local_path(cfg: Config, doc: Document) -> Path:
    """Cache path. The URL hash is in the filename, so a re-upload lands beside
    the old file rather than silently overwriting it."""
    return cfg.pdf_dir / f"{doc.game}__{doc.url_hash}.pdf"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_valid_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def download(crawler: Crawler, cfg: Config, doc: Document, *, force: bool) -> Skipped | None:
    """Fetch one PDF, or reuse the cached copy. Returns a Skipped on failure."""
    target = local_path(cfg, doc)

    if target.exists() and not force:
        if is_valid_pdf(target):
            stat = target.stat()
            doc.path = str(target)
            doc.bytes = stat.st_size
            doc.sha256 = sha256_of(target)
            # Keep the original fetch time rather than dropping it on a re-run.
            doc.downloaded_at = datetime.fromtimestamp(
                stat.st_mtime, timezone.utc
            ).isoformat(timespec="seconds")
            doc.cached = True
            log.info("cached %-18s | %s (%d KB)", doc.game, target.name, doc.bytes // 1024)
            return None
        log.warning("cached file for %s is not a PDF; re-downloading", doc.game)
        target.unlink(missing_ok=True)

    tmp = target.with_suffix(".pdf.part")
    try:
        response = crawler.get(doc.source_url, stream=True)
        tmp.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with tmp.open("wb") as handle:
            for block in response.iter_content(1 << 16):
                handle.write(block)
                size += len(block)
    except requests.RequestException as exc:
        tmp.unlink(missing_ok=True)
        log.warning("skip %-18s | download failed: %s", doc.game, exc)
        return Skipped(doc.game, doc.game_title, doc.detail_url, f"download failed: {exc}", doc.source_url)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        log.warning("skip %-18s | could not write file: %s", doc.game, exc)
        return Skipped(doc.game, doc.game_title, doc.detail_url, f"could not write file: {exc}", doc.source_url)

    if not is_valid_pdf(tmp):
        tmp.unlink(missing_ok=True)
        log.warning("skip %-18s | response was not a PDF", doc.game)
        return Skipped(
            doc.game, doc.game_title, doc.detail_url, "response body was not a PDF", doc.source_url
        )

    tmp.replace(target)
    doc.path = str(target)
    doc.bytes = size
    doc.sha256 = sha256_of(target)
    doc.downloaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log.info("saved  %-18s | %s (%d KB)", doc.game, target.name, size // 1024)
    return None


def report_orphans(cfg: Config, kept: list[Document]) -> list[str]:
    """Cached PDFs no longer referenced by any current URL -- most likely the
    previous edition of a re-uploaded rulebook. Reported, never deleted."""
    if not cfg.pdf_dir.exists():
        return []
    current = {Path(doc.path).name for doc in kept if doc.path}
    orphans = sorted(p.name for p in cfg.pdf_dir.glob("*.pdf") if p.name not in current)
    for name in orphans:
        log.warning("stale cached PDF (superseded upload?): %s", name)
    return orphans


# --- Manifest ----------------------------------------------------------------


def write_manifest(cfg: Config, discovery: Discovery, orphans: list[str], crawler: Crawler) -> dict:
    documents = [
        {
            "game": doc.game,
            "game_title": doc.game_title,
            "scope": doc.scope,
            "authority": doc.authority,
            "doc_title": doc.doc_title,
            "version": doc.version,
            "effective_date": doc.effective_date,
            "supersedes": doc.supersedes,
            "source_url": doc.source_url,
            "detail_url": doc.detail_url,
            "url_hash": doc.url_hash,
            "external_host": doc.external_host,
            "path": doc.path,
            "bytes": doc.bytes,
            "sha256": doc.sha256,
            "downloaded_at": doc.downloaded_at,
        }
        for doc in discovery.documents
        if doc.path
    ]
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": cfg.base_url,
        "http_requests": crawler.request_count,
        "counts": {
            "documents": len(documents),
            "global": sum(1 for d in documents if d["scope"] == "global"),
            "titles": sum(1 for d in documents if d["scope"] == "title"),
            "skipped": len(discovery.skipped),
        },
        "documents": documents,
        "skipped": [
            {
                "game": s.game,
                "game_title": s.game_title,
                "detail_url": s.detail_url,
                "url": s.url,
                "reason": s.reason,
            }
            for s in discovery.skipped
        ],
        "stale_cached_files": orphans,
    }
    cfg.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


# --- Entry point -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="discover only; download nothing")
    parser.add_argument("--force", action="store_true", help="re-download even if cached")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
        stream=sys.stdout,
    )

    cfg = load_config()
    log.info("base=%s delay=%ss data=%s", cfg.base_url, cfg.crawl_delay, cfg.data_dir)
    crawler = Crawler(cfg.user_agent, cfg.crawl_delay)

    started = time.monotonic()
    try:
        discovery = discover(crawler, cfg)
    except requests.RequestException as exc:
        log.error("could not fetch the listing page: %s", exc)
        return 1

    if args.dry_run:
        log.info(
            "dry run: %d documents discovered, %d skipped, %d requests in %.1fs",
            len(discovery.documents), len(discovery.skipped),
            crawler.request_count, time.monotonic() - started,
        )
        for doc in discovery.documents:
            log.info("  %-18s %-8s %s", doc.game, doc.scope, doc.source_url)
        return 0

    cfg.pdf_dir.mkdir(parents=True, exist_ok=True)
    for doc in list(discovery.documents):
        failure = download(crawler, cfg, doc, force=args.force)
        if failure:
            discovery.documents.remove(doc)
            discovery.skipped.append(failure)

    orphans = report_orphans(cfg, discovery.documents)
    manifest = write_manifest(cfg, discovery, orphans, crawler)

    counts = manifest["counts"]
    cached = sum(1 for d in discovery.documents if d.cached)
    log.info(
        "manifest %s | %d documents (%d global, %d title), %d cached, %d skipped, "
        "%d requests, %.1fs",
        cfg.manifest_path, counts["documents"], counts["global"], counts["titles"],
        cached, counts["skipped"], crawler.request_count, time.monotonic() - started,
    )
    for entry in manifest["skipped"]:
        log.info("  skipped %-18s %s", entry["game"], entry["reason"])

    missing_dates = [d["game"] for d in manifest["documents"] if not d["effective_date"]]
    if missing_dates:
        log.warning(
            "%d/%d documents publish no effective date: %s",
            len(missing_dates), counts["documents"], ", ".join(missing_dates),
        )

    return 0 if counts["documents"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

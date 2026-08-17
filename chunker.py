"""chunker.py — PDF -> article-aware LangChain Documents.

Stage S2 of the EWC Rulebook RAG build.

Reads ``data/manifest.json`` (written by ``ingest.py``) and turns each cached PDF
into a list of ``langchain_core.documents.Document`` objects that are split on
**article boundaries first**.  ``RecursiveCharacterTextSplitter(1200, 150)`` is
used only to break up an article whose body is too large to embed in one piece.

Extraction is PyMuPDF so that page numbers survive: every chunk records the
physical PDF page its text starts on, which is what the citation format
``(Game — Article X.Y.Z, p.N)`` needs.

No network access, no OpenAI calls.  Run it directly for the coverage report::

    python chunker.py            # all 25 documents
    python chunker.py global cs2 # a subset
    python chunker.py --dump global 3.2.3
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# PyMuPDF.  `import fitz` is deprecated at the pinned 1.28.x in favour of
# `import pymupdf`; it is the same library, so CLAUDE.md's "use PyMuPDF (fitz),
# never PyPDFLoader" is satisfied.
import pymupdf
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

MAX_CHARS = 1200          # oversized-article threshold == splitter chunk_size
CHUNK_OVERLAP = 150
MIN_BODY_CHARS = 20       # below this an "article" is a bare heading, not content
MAX_HEADING_LEN = 90      # heading text length guard (CLAUDE.md)
MAX_LINE_LEN = 100        # heading *line* length guard (CLAUDE.md)
TOC_RUN_MIN = 5           # a run of >= N headings with no body between them is a TOC

#: Value written wherever the manifest (or the PDF) supplies nothing.
#: Chroma rejects ``None`` in metadata -- verified at S1:
#: ``col.add(metadatas=[{"version": None}])`` raises
#: ``TypeError: argument 'metadatas': Cannot convert Python object to
#: MetadataValue``.  24 of the 25 manifest entries carry ``version: null`` and
#: ``effective_date: null``, so this sentinel is load-bearing for S3.
NULL_SENTINEL = ""

# Invisible characters Google-Docs PDF exports sprinkle through headings.
# U+200B is *not* matched by ``\s`` in Python, which is why the stock heading
# regex fails on those books; strip them before anything else looks at a line.
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_SPACEY = {ord(" "): " ", ord(" "): " ", ord(" "): " ", ord("\t"): " "}

# ---------------------------------------------------------------------------
# Heading regexes
# ---------------------------------------------------------------------------
# CLAUDE.md's starting point:
#   ^\s*(\d{1,2}(?:\.\d{1,3}){0,3})\.?\s+([A-Z][^\n]{2,90})\s*$
# Two measured problems with it on this corpus (see the S2 handoff for numbers):
#   1. It only matches "number and heading on one line".  Every Google-Docs
#      export in the corpus -- the Global Rulebook included -- puts the number
#      on its own line: "3.2.3.​\nTeam Roster Integrity".
#   2. {0,3} caps the number at four levels; the Global Rulebook reaches five
#      (e.g. 5.1.19.3.1).
#   3. Appendix articles in the third-party Apex book are letter-prefixed
#      ("A1. Competitor and Coach Behavior", "C6.4. Pro League Points").
#      Without the prefix those 30 pages get swallowed by the last numeric
#      article and mis-attributed.
#   4. `\s+` after the number is not always present: the Global Rulebook's
#      Appendix II opens `1.“Versus” GTTs` with no space at all.
# So the number pattern is widened and split into two forms.
#
# Sub-levels are capped at TWO digits (CLAUDE.md says three).  Measured over all
# 25 books: every genuine heading's widest article component is 1 or 2 digits
# (2095 headings at 1, 393 at 2, **zero** at 3+).  Three-digit components only
# ever came from European-format prize amounts -- `70.000 USD`, `7.500 USD` --
# which the four fighting-game books print one per line, and which then compete
# with real articles for the numbering sequence.  Narrowing the sub-level here
# removes all 24 of them at the regex, which is what makes it safe to trust a
# multi-level number later on (see `enforce_sequence`).
_NUM = r"[A-Z]?\d{1,2}(?:\.\d{1,2}){0,4}"

#: "1.1 Heading" / "1.1. Heading" / "1.“Versus” GTTs" -- number and heading on
#: the same line.  The heading text is validated separately, which is what stops
#: a table row like "1 $600,000" from being read as an article.  The lookahead
#: keeps a bare "1.1" from being re-read as article "1" with heading "1".  The
#: separator must be a dot or real whitespace, never nothing: "1st" in a prize
#: table would otherwise become article 1, heading "st".
RE_INLINE = re.compile(rf"^({_NUM})(?:\.[ ]*|[ ]+)(?![\d.])(\S.*)$")

#: "1.1." alone on a line; the heading is the next non-empty line.  A trailing
#: dot or at least one sub-level is required so that a bare page number ("17")
#: in a table of contents is not read as an article number.
RE_NUMBER_ONLY = re.compile(rf"^({_NUM})\.$|^([A-Z]?\d{{1,2}}(?:\.\d{{1,2}}){{1,4}})$")

RE_BARE_NUMBER = re.compile(r"^\d{1,4}$")
RE_DOT_LEADER = re.compile(r"\.{4,}")
#: "Appendix I - Protest Rules", "APPENDIX A: CODE OF CONDUCT".  Deliberately
#: strict: an unguarded version matched the cs2 body sentence
#: "Appendix 6.1). If no majority exists due to a tie, ..." and relabelled the
#: rest of that rulebook as an appendix.
#: A title after the number is mandatory: a bare "Appendix B" on its own line is
#: almost always a cross-reference that happened to wrap ("...the countries
#: listed in / Appendix B"), and treating it as a part boundary relabelled 15
#: pages of the Apex main body.
RE_APPENDIX = re.compile(
    r"^(Appendix|Annex|Schedule|Exhibit)\s+([IVXLC]+|[A-Z]|\d{1,2})\b[\s:.–—-]+"
    r"([A-Z“\"'(].{0,60})$",
    re.I,
)
#: "Appendix A" alone on a line, its title on the next -- how mlbb writes it.
RE_APPENDIX_BARE = re.compile(
    r"^(Appendix|Annex|Schedule|Exhibit)\s+([IVXLC]+|[A-Z]|\d{1,2})\.?$", re.I
)
MAX_PART_LABEL_LEN = 80
MAX_PART_TITLE_LEN = 60
#: Run-in heading: "Purpose. Activision Publishing, Inc. created ..." -- the
#: heading is the leading sentence.  Used only when the candidate heading line
#: is too long to be a heading on its own.
RE_RUN_IN = re.compile(r"^([A-Z][^.;:]{1,88})\.\s+(\S.*)$", re.S)


def _normalize(text: str) -> str:
    """Strip invisible characters and collapse odd spaces. Never reflows lines."""
    return text.translate(_INVISIBLE).translate(_SPACEY)


def _tidy(line: str) -> str:
    return re.sub(r"[ ]{2,}", " ", line).strip()


def article_key(article: str) -> tuple:
    """``"2.10.1"`` -> ``(0, "", 2, 10, 1)``; ``"C6.4"`` -> ``(1, "C", 6, 4)``.

    Used only for "does this sequence increase?" comparisons during table-of-
    contents detection, so the letter prefix is ordered ahead of the digits.
    """
    prefix = ""
    body = article
    if body[:1].isalpha():
        prefix, body = body[0], body[1:]
    try:
        digits = tuple(int(p) for p in body.split("."))
    except ValueError:  # pragma: no cover - article is regex-constrained
        digits = ()
    return (1 if prefix else 0, prefix) + digits


# ---------------------------------------------------------------------------
# Page / line model
# ---------------------------------------------------------------------------


@dataclass
class Line:
    text: str
    page: int          # 1-based physical PDF page
    pos_in_page: int   # index among that page's non-empty lines
    n_in_page: int     # count of non-empty lines on that page


def extract_lines(pdf_path: Path) -> tuple[list[Line], int]:
    """PyMuPDF text extraction, flattened to normalized lines that know their page."""
    lines: list[Line] = []
    with pymupdf.open(pdf_path) as doc:
        page_count = doc.page_count
        for index in range(page_count):
            raw = _normalize(doc[index].get_text())
            page_lines = [_tidy(ln) for ln in raw.splitlines()]
            page_lines = [ln for ln in page_lines if ln]
            total = len(page_lines)
            for pos, text in enumerate(page_lines):
                lines.append(Line(text, index + 1, pos, total))
    return lines, page_count


def strip_boilerplate(lines: Sequence[Line], page_count: int) -> list[Line]:
    """Drop running headers/footers and standalone page numbers.

    Only the top-3 / bottom-3 band of each page is eligible, and a line has to
    repeat on at least half the pages (minimum 4) to be considered furniture.
    Page 1 is frequently near-empty in this corpus (11 of 25 books yield under
    110 characters on page 1), so nothing here may assume page 1 has content.
    """
    band_counts: dict[str, set[int]] = {}
    for line in lines:
        if line.pos_in_page < 3 or line.pos_in_page >= line.n_in_page - 3:
            band_counts.setdefault(line.text.lower(), set()).add(line.page)

    threshold = max(4, int(0.5 * page_count))
    furniture = {text for text, pages in band_counts.items() if len(pages) >= threshold}

    kept: list[Line] = []
    for line in lines:
        in_band = line.pos_in_page < 3 or line.pos_in_page >= line.n_in_page - 3
        if in_band and line.text.lower() in furniture:
            continue
        # A bare number in the top/bottom two lines of a page is a page number.
        if RE_BARE_NUMBER.match(line.text) and (
            line.pos_in_page < 2 or line.pos_in_page >= line.n_in_page - 2
        ):
            continue
        # Dot leaders only ever occur in a contents listing. Ten of the 25 books
        # use that style; left in, the listing becomes a wall of article-less
        # front-matter chunks that pollute retrieval.
        if RE_DOT_LEADER.search(line.text):
            continue
        if line.text.lower() in {"table of contents", "table of content", "contents"}:
            continue
        kept.append(line)
    return kept


# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------


@dataclass
class Heading:
    index: int          # index into the line list where the heading starts
    consumed: int       # how many lines the heading itself occupies (1 or 2)
    article: str
    heading: str
    inline_body: str    # leftover text on the heading line (run-in headings)


#: A heading that is nothing but a parenthetical is never a heading; it is a
#: wrapped cross-reference that happened to start a line ("...in violation of
#: Section / 8.1 (Behavior)." in the Warzone book).  Zero genuine headings in
#: the corpus begin with "(", so this only ever removes noise -- but it is
#: written narrowly so that "(Optional) Tiebreakers" would still be accepted.
RE_ONLY_PARENTHETICAL = re.compile(r"^\([^)]*\)[\s.;:,]*$")


def _plausible_heading_text(text: str) -> bool:
    """CLAUDE.md's heading-text test, including its ``[A-Z]`` initial guard."""
    if not _heading_shape(text):
        return False
    # CLAUDE.md's [A-Z] guard.  It earns its place: every lowercase/digit-initial
    # candidate it rejects under a *bare* number is a table fragment ("1 year",
    # "24 teams", "4 matches").  See `_plausible_subarticle_text` for where it
    # does not.
    first = text[0]
    return first.isupper() or first in "“\"'("


def _heading_shape(text: str) -> bool:
    """Length / punctuation / letter-density tests, independent of case."""
    if not (2 <= len(text) <= MAX_HEADING_LEN):
        return False
    if RE_DOT_LEADER.search(text):
        return False
    if RE_ONLY_PARENTHETICAL.match(text):
        return False
    letters = sum(ch.isalpha() for ch in text)
    return letters >= 2 and letters >= 0.4 * len(text)


def _wraps_previous_line(previous: str) -> bool:
    """Does ``previous`` end mid-sentence, so that the next line continues it?

    This is the only thing separating a lowercase sub-article from a wrapped
    cross-reference.  ``ea-sports-fc`` p.2 breaks the sentence
    "...as noted in Section / 4.2.5.1. of the Official Rules;" across two lines;
    ``mlbb`` p.50 lists "9.1.3 firearms...providers; / 9.1.4 alcohol;".  The
    lines look identical; their predecessors do not.
    """
    if not previous:
        return False
    return previous[-1] not in ".;:!?”\"'"


def _plausible_subarticle_text(text: str, article: str, previous: str) -> bool:
    """Heading test for a *multi-level* number, where ``[A-Z]`` is too strict.

    A rulebook's ordered lists and table rows are numbered 1., 2., 3. -- nothing
    in this corpus numbers a list item 9.1.4 -- so a dotted number is already
    strong evidence of a real sub-article and the initial-capital requirement
    costs more than it earns there.  Measured cost of applying it: 8 genuine
    articles rejected and served under the preceding article's number -- mlbb
    9.1.2-9.1.8, a lowercase-initial prohibited-sponsor list ("9.1.4 alcohol;",
    "9.1.7 web3, cryptocurrency, NFT and Blockchain;"), and dota2 7.2.3
    "1v1 Tiebreakers", which starts with a digit.  Their text survived; their
    citation did not.

    Dropping the guard outright is not safe either: it admits
    "4.2.5.1. of the Official Rules;", the tail of a sentence that wrapped across
    a line break in the EA SPORTS FC book.  So the relaxation is paid for with
    the line-wrap test -- a heading never continues an unfinished sentence.

    This is a DELIBERATE narrowing of CLAUDE.md's stated regex; see the S2
    repair handoff.
    """
    if "." not in article:
        return False
    if not _heading_shape(text):
        return False
    return not _wraps_previous_line(previous)


def _as_heading(text: str) -> tuple[str, str] | None:
    """Split a too-long candidate into (run-in heading, remaining body)."""
    match = RE_RUN_IN.match(text)
    if not match:
        return None
    head, rest = match.group(1).strip(), match.group(2).strip()
    if not _plausible_heading_text(head) or len(head.split()) > 12:
        return None
    return head, rest


def find_heading_candidates(lines: Sequence[Line]) -> list[Heading]:
    candidates: list[Heading] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        text = line.text
        previous = lines[i - 1].text if i else ""
        if len(text) >= MAX_LINE_LEN or RE_DOT_LEADER.search(text):
            i += 1
            continue

        inline = RE_INLINE.match(text)
        if inline:
            article, rest = inline.group(1), inline.group(2).strip()
            if _plausible_heading_text(rest) or _plausible_subarticle_text(
                rest, article, previous
            ):
                candidates.append(Heading(i, 1, article, rest, ""))
                i += 1
                continue
            split = _as_heading(rest)
            if split:
                candidates.append(Heading(i, 1, article, split[0], split[1]))
                i += 1
                continue
            # Not a heading after all -- fall through, the line may still be a
            # number-only heading whose text sits on the next line.

        number_only = RE_NUMBER_ONLY.match(text)
        if number_only and i + 1 < len(lines):
            article = number_only.group(1) or number_only.group(2)
            nxt = lines[i + 1].text
            # For the two-line form the wrap test looks at the line before the
            # *number*, which is where the unfinished sentence would be.
            if _plausible_heading_text(nxt) or _plausible_subarticle_text(
                nxt, article, previous
            ):
                candidates.append(Heading(i, 2, article, nxt, ""))
                i += 2
                continue
            split = _as_heading(nxt)
            if split:
                candidates.append(Heading(i, 2, article, split[0], split[1]))
                i += 2
                continue
        i += 1
    return candidates


def drop_table_of_contents(
    lines: Sequence[Line], candidates: Sequence[Heading]
) -> tuple[list[Heading], set[int]]:
    """Remove contents-listing entries, which look exactly like real headings.

    Three signals, in increasing order of cleverness:

    1. Dot leaders ("1.1 Rule Changes......4") -- already rejected upstream.
    2. The entry is immediately followed by a bare page number.
    3. A *run* of >= TOC_RUN_MIN heading candidates with no body text between
       them.  Bodyless runs that long only occur in a contents list.  A contents
       list is strictly increasing, so where the numbering restarts inside the
       run (9. -> 1.) the tail after the last restart is real body and is kept.
    """
    if not candidates:
        return [], set()

    starts = {c.index: c for c in candidates}
    covered: set[int] = set()
    for c in candidates:
        covered.update(range(c.index, c.index + c.consumed))

    flagged: set[int] = set()

    # Signal 2: followed by a bare page number.
    for c in candidates:
        after = c.index + c.consumed
        if after < len(lines) and RE_BARE_NUMBER.match(lines[after].text):
            flagged.add(c.index)

    # Signal 3: bodyless runs.
    runs: list[list[Heading]] = []
    current: list[Heading] = []
    i = 0
    while i < len(lines):
        if i in starts:
            head = starts[i]
            current.append(head)
            i += head.consumed
            continue
        if i in covered:
            i += 1
            continue
        # A real body line (or a page number line inside a contents list).
        if not RE_BARE_NUMBER.match(lines[i].text):
            if current:
                runs.append(current)
                current = []
        i += 1
    if current:
        runs.append(current)

    for run in runs:
        if len(run) < TOC_RUN_MIN:
            continue
        # A contents listing is strictly increasing; where the numbering
        # restarts inside the run, the tail is real body (rocket-league's
        # contents list runs straight into "1. General" with nothing between).
        restart = 0
        for j in range(1, len(run)):
            if article_key(run[j].article) <= article_key(run[j - 1].article):
                restart = j
        head_run = run[:restart] if restart and len(run) - restart < TOC_RUN_MIN else run
        if len(head_run) < TOC_RUN_MIN:
            continue
        # Decisive test: a contents entry points forward, so its article number
        # occurs again later in the document.  A genuine bodyless run of sibling
        # headings ("5.3.1.1 Hardpoint / 5.3.1.2 Search and Destroy / 5.3.1.3
        # Overload") never does.  Without this, 13 real cod-mw3 articles and 2
        # valorant ones were deleted as contents entries.
        # And a contents listing is multi-level.  An ordered procedure list
        # ("1. Team A bans one map / 2. Team B bans one map / ...") is a bodyless
        # run of single-level numbers whose values do recur later; without this
        # guard cod-mw3's map-veto steps were deleted from the corpus outright.
        # Measured over all 25 books: every real contents run scores >= 0.79 on
        # "fraction of multi-level numbers", every mid-document ordered list
        # scores <= 0.29.  And a contents entry points forward, so its number
        # recurs later (>= 0.42 measured); the one genuine bodyless run of
        # dotted sibling headings in the corpus (mlbb p.58) scores 0.00.
        dotted = sum(1 for h in head_run if "." in h.article)
        if dotted < 0.6 * len(head_run):
            continue
        boundary = head_run[-1].index
        later = {c.article for c in candidates if c.index > boundary}
        hits = sum(1 for h in head_run if h.article in later)
        if hits >= 0.35 * len(head_run):
            flagged.update(h.index for h in head_run)

    # The flagged entries' own lines (and the page number that trails each of
    # them) must leave the text stream too, or the contents listing reappears as
    # article-less front matter.
    dead: set[int] = set()
    for c in candidates:
        if c.index in flagged:
            dead.update(range(c.index, c.index + c.consumed))
            after = c.index + c.consumed
            if after < len(lines) and RE_BARE_NUMBER.match(lines[after].text):
                dead.add(after)

    return [c for c in candidates if c.index not in flagged], dead


def _longest_increasing(keys: Sequence[tuple]) -> list[int]:
    """Indices of a longest strictly increasing subsequence of ``keys``."""
    tails: list[tuple] = []
    tails_at: list[int] = []
    previous = [-1] * len(keys)
    for i, key in enumerate(keys):
        pos = bisect.bisect_left(tails, key)
        if pos == len(tails):
            tails.append(key)
            tails_at.append(i)
        else:
            tails[pos] = key
            tails_at[pos] = i
        previous[i] = tails_at[pos - 1] if pos else -1
    chain: list[int] = []
    cursor = tails_at[-1] if tails_at else -1
    while cursor != -1:
        chain.append(cursor)
        cursor = previous[cursor]
    return sorted(chain)


def enforce_sequence(headings: Sequence[Heading], part_starts: Sequence[int]) -> list[Heading]:
    """Keep the headings that form a consistently advancing numbering.

    Ordered lists inside a rule are indistinguishable from headings line by line
    -- "1. Team A bans one map" and "3. Team Coach" match every heading pattern
    there is.  They are distinguishable *in sequence*: real article numbers rise
    monotonically through a part, list numbering restarts and collides.

    A running "must be greater than the last accepted" test is not enough,
    because one wrong accept poisons everything after it: an incrementing list
    (1., 2., 3., 4., 5.) walked the cursor past section 5 on page 5 of the
    VALORANT book and rejected the remaining 100 real articles.  Taking the
    *longest* increasing subsequence instead makes the decision globally, so a
    short spurious chain loses to the long real one no matter where it appears.

    Rejected candidates keep their text -- only their promotion to a heading is
    refused, so list items stay in the body of the article that owns them.  That
    is exactly why the contest must only ever be run between *single-level*
    numbers: a rejected heading's text is absorbed into the preceding article and
    is then served under that article's number and page, which is a wrong
    citation, not a lost list marker.  Multi-level numbers are therefore
    restored after the contest -- see below.
    """
    if not headings:
        return []
    boundaries = sorted(part_starts)

    groups: dict[int, list[int]] = {}
    for n, head in enumerate(headings):
        group = bisect.bisect_right(boundaries, head.index)
        groups.setdefault(group, []).append(n)

    keep: set[int] = set()
    for members in groups.values():
        keys = [article_key(headings[n].article) for n in members]
        keep.update(members[i] for i in _longest_increasing(keys))

    # A multi-level number is never an ordered-list marker.  Lists inside a rule
    # are written "1.", "2.", "3."; nothing in this corpus numbers a list item
    # "2.5.10".  So a dotted candidate that merely lost the contest is a genuine
    # article that the publisher printed out of order, and dropping it produces a
    # wrong citation rather than a tidy body.  Measured: the LIS rejects 29
    # dotted candidates across the 25 books -- 24 European-format prize amounts
    # ("70.000 USD"), now removed at the regex; one wrapped cross-reference
    # ("8.1 (Behavior)."), now removed by RE_ONLY_PARENTHETICAL; and 4 genuine
    # articles: lol 2.5.9 / 2.5.10 (the book numbers 2.5.1, 2.5.9, 2.5.10, 2.5.4,
    # 2.5.5 out of order), lol 5.10.5 (printed twice) and mlbb-women 2.7.  Every
    # rejection left is one of those 4, so restore them all.
    keep.update(n for n, head in enumerate(headings) if "." in head.article)
    return [head for n, head in enumerate(headings) if n in keep]


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------


@dataclass
class Segment:
    article: str
    heading: str
    part: str
    body: str
    page: int
    page_end: int
    #: (character offset into ``body``, PDF page) for each body line, so that a
    #: piece of an oversized article is cited on the page it actually starts on
    #: rather than on the page the article started on.
    offsets: list[tuple[int, int]]


def _find_parts(lines: Sequence[Line], first_heading: int) -> dict[int, tuple[str, int]]:
    """Line index -> appendix/annex label starting at that line.

    Appendices restart their numbering (the Global Rulebook has a main body
    1..7 *and* an Appendix I numbered 1..4), so the part label is what makes an
    article number unique inside a document.

    Markers before the first real article heading are ignored: everything there
    is title page and contents listing, and the contents listing names every
    appendix in the book, which would otherwise label the whole main body with
    the *last* appendix in the table.
    """
    parts: dict[int, tuple[str, int]] = {}
    for i in range(first_heading, len(lines)):
        text = lines[i].text
        if len(text) > MAX_PART_LABEL_LEN or ". " in text or text.endswith((",", ";")):
            continue
        if RE_APPENDIX.match(text):
            parts[i] = (_tidy(text).rstrip("."), 1)
            continue
        # Two-line form: "Appendix A" / "MSC Penalty Index".  The title line is
        # required and must look like a title, which is what separates a real
        # part boundary from a wrapped cross-reference ("... described in /
        # APPENDIX B. / Competitors invited to a Live Event may be required...")
        # and from a contents entry ("Appendix A" / "61").
        if RE_APPENDIX_BARE.match(text) and i + 1 < len(lines):
            title = lines[i + 1].text
            if (
                3 <= len(title) <= MAX_PART_TITLE_LEN
                and (title[0].isupper() or title[0] in "“\"'(")
                and not RE_BARE_NUMBER.match(title)
                and not RE_INLINE.match(title)
                and not RE_NUMBER_ONLY.match(title)
                and not title.endswith((",", ";", "."))
            ):
                parts[i] = (f"{_tidy(text).rstrip('.')} - {title}", 2)
    return parts


def segment(lines: Sequence[Line], headings: Sequence[Heading]) -> list[Segment]:
    first = headings[0].index if headings else len(lines)
    parts = _find_parts(lines, first)

    # The part label in force at each line index.
    part_at: list[str] = []
    label = ""
    for i in range(len(lines)):
        if i in parts:
            label = parts[i][0]
        part_at.append(label)

    segments: list[Segment] = []

    # Boundaries are article headings *and* appendix markers.  An appendix that
    # carries no numbered headings of its own (Apex's Appendix B is four pages
    # of eligible countries) would otherwise be swallowed by the last article of
    # the previous appendix and cited under its number.
    marker_starts = {
        i: consumed for i, (_, consumed) in parts.items()
        if not any(h.index <= i < h.index + h.consumed for h in headings)
    }
    boundaries: list[tuple[Heading | None, int, int]] = [(h, h.index, 0) for h in headings]
    boundaries += [(None, i, consumed) for i, consumed in marker_starts.items()]
    boundaries.sort(key=lambda triple: triple[1])

    first_boundary = boundaries[0][1] if boundaries else len(lines)
    bounds: list[tuple[Heading | None, int, int, int]] = [(None, 0, first_boundary, 0)]
    for n, (head, start, consumed) in enumerate(boundaries):
        end = boundaries[n + 1][1] if n + 1 < len(boundaries) else len(lines)
        bounds.append((head, start, end, consumed))

    for head, start, end, consumed in bounds:
        part_label = part_at[start] if start < len(part_at) else ""
        if head is None:
            # Front matter (consumed == 0), or an appendix preamble whose part
            # marker is not itself a numbered heading.
            is_front = consumed == 0
            body_lines = lines[start + consumed:end]
            body, offsets = _join(None, body_lines)
            if body.strip():
                label = "Front matter" if is_front else lines[start].text
                segments.append(
                    Segment("", label, "" if is_front else part_label, body,
                            lines[start].page, body_lines[-1].page, offsets)
                )
            continue

        body_lines = list(lines[start + head.consumed:end])
        body, offsets = _join(head.inline_body, body_lines, lines[start].page)
        page = lines[start].page
        page_end = body_lines[-1].page if body_lines else page
        segments.append(
            Segment(head.article, head.heading, part_label, body, page, page_end, offsets)
        )
    return segments


def _join(
    inline_body: str | None, body_lines: Sequence[Line], inline_page: int = 0
) -> tuple[str, list[tuple[int, int]]]:
    """Join body lines, recording the (offset, page) of each one."""
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    cursor = 0
    if inline_body:
        parts.append(inline_body)
        offsets.append((cursor, inline_page))
        cursor += len(inline_body) + 1
    for line in body_lines:
        if not line.text:
            continue
        parts.append(line.text)
        offsets.append((cursor, line.page))
        cursor += len(line.text) + 1
    return "\n".join(parts), offsets


# ---------------------------------------------------------------------------
# Document construction
# ---------------------------------------------------------------------------


def _s(value) -> str:
    """Coerce a manifest value for Chroma: ``None`` is not a legal metadata value."""
    if value is None:
        return NULL_SENTINEL
    return value if isinstance(value, str) else str(value)


def context_label(game_title: str, part: str, article: str, heading: str) -> str:
    """``[<game_title> · Article <n> — <heading>]`` (CLAUDE.md).

    The embedding has to carry article context, not only the metadata.  The
    appendix label is folded into the article number when there is one, because
    otherwise ``Article 1.1`` is ambiguous within a single rulebook.
    """
    if article:
        number = f"{part} § {article}" if part else article
        return f"[{game_title} · Article {number} — {heading}]"
    return f"[{game_title} · {heading}]"


def _page_for_offset(seg: Segment, offset: int) -> int:
    """Map a character offset inside a segment body back to a PDF page."""
    page = seg.page
    for start_offset, page_no in seg.offsets:
        if start_offset <= offset:
            page = page_no
        else:
            break
    return page


def _rescue_thin_segments(segments: Sequence[Segment]) -> set[int]:
    """Indices of body-less segments that must still be emitted.

    A segment whose body is under ``MIN_BODY_CHARS`` is usually a parent heading
    ("6. Introduction.", "5.4 Format.") whose children carry the rule text; its
    heading is repeated in every child's ``heading_path``, so dropping it costs
    nothing.  But this corpus also numbers *one-line rules*, where the heading is
    the entire article and there is no child to carry it -- mlbb's Game-of-Record
    conditions, "6.2.4 Game timer reaches 35 seconds (00:00:35).", are four such
    lines.  Dropping those deletes the rule from the corpus outright: the text
    then appears in no chunk body, no ``heading`` and no ``heading_path``, so
    retrieval returns article 6.2 plus whichever condition happened to have a
    body and the system states a quarter of a rule as the rule -- with a correct
    citation, so nothing looks missing and the abstention path never fires.

    The distinction is therefore not "how sentence-like is the heading" but
    "does anything else in this document still carry it": keep a thin segment
    exactly when no emitted descendant will repeat its heading.  Deepest first,
    so a chain of thin parents resolves in one pass.

    Measured over the 25 books: 440 thin segments, 404 dropped (all of them have
    an emitted descendant), 36 kept.
    """
    substantive = [len(seg.body.strip()) >= MIN_BODY_CHARS for seg in segments]
    emitted = {
        (seg.part, seg.article)
        for seg, ok in zip(segments, substantive)
        if ok and seg.article
    }

    rescued: set[int] = set()
    thin = sorted(
        (n for n, ok in enumerate(substantive) if not ok),
        key=lambda n: -len(segments[n].article.split(".")),
    )
    for n in thin:
        seg = segments[n]
        if not seg.article:
            # Front matter and appendix preambles have no citation anchor, so a
            # near-empty one is genuinely uncitable. Keep dropping those.
            continue
        prefix = seg.article + "."
        if any(part == seg.part and art.startswith(prefix) for part, art in emitted):
            continue
        rescued.add(n)
        emitted.add((seg.part, seg.article))
    return rescued


def chunk_document(record: dict, root: Path = ROOT) -> list[Document]:
    """Turn one manifest entry into article-aware ``Document`` objects."""
    pdf_path = root / record["path"]
    lines, page_count = extract_lines(pdf_path)
    lines = strip_boilerplate(lines, page_count)
    candidates = find_heading_candidates(lines)
    headings, dead = drop_table_of_contents(lines, candidates)

    if dead:
        remap: dict[int, int] = {}
        live: list[Line] = []
        for old, line in enumerate(lines):
            if old in dead:
                continue
            remap[old] = len(live)
            live.append(line)
        lines = live
        headings = [
            Heading(remap[h.index], h.consumed, h.article, h.heading, h.inline_body)
            for h in headings
            if h.index in remap
        ]

    first = headings[0].index if headings else len(lines)
    headings = enforce_sequence(headings, list(_find_parts(lines, first)))
    segments = segment(lines, headings)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=MAX_CHARS,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    base_meta = {
        "game": _s(record["game"]),
        "game_title": _s(record["game_title"]),
        "scope": _s(record["scope"]),
        "authority": int(record["authority"]),
        "version": _s(record.get("version")),
        "effective_date": _s(record.get("effective_date")),
        "source_url": _s(record.get("source_url")),
        "doc_title": _s(record.get("doc_title")) or _s(record["game_title"]),
        "supersedes": _s(record.get("supersedes")),
        "external_host": bool(record.get("external_host", False)),
        "source_path": _s(record["path"]),
    }

    # Breadcrumbs: 2.2.1 inherits the headings of 2.2 and 2.
    heading_by_key: dict[tuple[str, str], str] = {}
    for seg in segments:
        if seg.article:
            heading_by_key[(seg.part, seg.article)] = seg.heading

    rescued = _rescue_thin_segments(segments)

    docs: list[Document] = []
    used_ids: set[str] = set()

    for n_seg, seg in enumerate(segments):
        body = seg.body.strip()
        if len(body) < MIN_BODY_CHARS:
            if n_seg not in rescued:
                # A parent heading whose children carry the text.  Its heading
                # survives in every child's ``heading_path``, so emitting it
                # would only add an empty, uncitable chunk.
                continue
            # The heading IS the rule ("6.2.4 Game timer reaches 35 seconds
            # (00:00:35)."). Promote it into the body so the text is searchable
            # and not merely a metadata field.
            body = f"{seg.heading}\n{body}".strip() if body else seg.heading

        parts_of_path = []
        if seg.article:
            bits = seg.article.split(".")
            for depth in range(1, len(bits) + 1):
                key = ".".join(bits[:depth])
                title = heading_by_key.get((seg.part, key))
                if title:
                    parts_of_path.append(f"{key} {title}")
        heading_path = " > ".join(parts_of_path) or seg.heading

        pieces = [body] if len(body) <= MAX_CHARS else splitter.split_text(body)
        article_id = f"{seg.part} § {seg.article}" if seg.part and seg.article else seg.article

        cursor = 0
        for n, piece in enumerate(pieces):
            probe = piece.strip()[:40]
            found = seg.body.find(probe, cursor) if probe else -1
            if found >= 0:
                cursor = found
            # The first piece is cited on the page the *heading* sits on -- that
            # is where a reader opens the PDF to find the article. Later pieces
            # are cited on the page their own text starts on.
            page = seg.page if n == 0 else _page_for_offset(seg, cursor)
            label = context_label(base_meta["game_title"], seg.part, seg.article, seg.heading)
            text = f"{label}\n{piece}"

            chunk_id = f"{base_meta['game']}:{article_id or 'front'}:{n}"
            if chunk_id in used_ids:
                chunk_id = f"{chunk_id}:{len(used_ids)}"
            used_ids.add(chunk_id)

            meta = dict(base_meta)
            meta.update(
                {
                    "article": seg.article,
                    "article_id": article_id,
                    "heading": seg.heading,
                    "heading_path": heading_path,
                    "part": seg.part,
                    "page": int(page),
                    "page_end": int(seg.page_end),
                    "chunk": n,
                    "chunk_of": len(pieces),
                    "chunk_id": chunk_id,
                    "n_chars": len(piece),
                }
            )
            docs.append(Document(page_content=text, metadata=meta))
    return docs


# ---------------------------------------------------------------------------
# Corpus-level API (this is what index.py should call)
# ---------------------------------------------------------------------------

REQUIRED_METADATA = (
    "game", "game_title", "scope", "authority", "article", "heading",
    "page", "version", "effective_date", "source_url", "chunk",
)


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def chunk_corpus(
    manifest_path: Path = MANIFEST_PATH,
    games: Iterable[str] | None = None,
) -> list[Document]:
    """Chunk every document in the manifest (or the named subset)."""
    manifest = load_manifest(manifest_path)
    wanted = set(games) if games else None
    root = Path(manifest_path).resolve().parent.parent
    docs: list[Document] = []
    for record in manifest["documents"]:
        if wanted and record["game"] not in wanted:
            continue
        docs.extend(chunk_document(record, root=root))
    return docs


def validate(docs: Sequence[Document]) -> list[str]:
    """Return a list of contract violations; empty means the chunk set is sane."""
    problems: list[str] = []
    seen_ids: set[str] = set()
    for doc in docs:
        meta = doc.metadata
        missing = [k for k in REQUIRED_METADATA if k not in meta]
        if missing:
            problems.append(f"{meta.get('chunk_id', '?')}: missing {missing}")
        none_valued = sorted(k for k, v in meta.items() if v is None)
        if none_valued:
            problems.append(f"{meta.get('chunk_id', '?')}: None-valued {none_valued}")
        bad_types = sorted(
            k for k, v in meta.items() if not isinstance(v, (str, int, float, bool))
        )
        if bad_types:
            problems.append(f"{meta.get('chunk_id', '?')}: non-scalar {bad_types}")
        if not isinstance(meta.get("page"), int) or meta["page"] < 1:
            problems.append(f"{meta.get('chunk_id', '?')}: bad page {meta.get('page')!r}")
        if meta.get("chunk_id") in seen_ids:
            problems.append(f"duplicate chunk_id {meta['chunk_id']}")
        seen_ids.add(meta.get("chunk_id"))
        if not doc.page_content.startswith("["):
            problems.append(f"{meta.get('chunk_id', '?')}: missing context label")
    return problems


def coverage(docs: Sequence[Document]) -> dict[str, dict]:
    """Per-game article coverage: fraction of chunks carrying an article number."""
    stats: dict[str, dict] = {}
    for doc in docs:
        meta = doc.metadata
        row = stats.setdefault(
            meta["game"],
            {"chunks": 0, "with_article": 0, "split": 0, "articles": set(),
             "pages": set(), "game_title": meta["game_title"]},
        )
        row["chunks"] += 1
        if meta["article"]:
            row["with_article"] += 1
            row["articles"].add(meta["article_id"])
        if meta["chunk_of"] > 1:
            row["split"] += 1
        row["pages"].add(meta["page"])
    for row in stats.values():
        row["pct"] = 100.0 * row["with_article"] / row["chunks"] if row["chunks"] else 0.0
        row["n_articles"] = len(row["articles"])
        row["page_min"] = min(row["pages"])
        row["page_max"] = max(row["pages"])
        del row["articles"]
        del row["pages"]
    return stats


GLOBAL_COVERAGE_GATE = 80.0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chunk the EWC rulebook corpus.")
    parser.add_argument("games", nargs="*", help="limit to these manifest slugs")
    parser.add_argument("--dump", nargs=2, metavar=("GAME", "ARTICLE"),
                        help="print the chunks for one article and exit")
    args = parser.parse_args(argv)

    if args.dump:
        game, article = args.dump
        for doc in chunk_corpus(games=[game]):
            if doc.metadata["article"] == article:
                print("-" * 70)
                print({k: doc.metadata[k] for k in
                       ("game", "article_id", "heading", "page", "page_end", "chunk_id")})
                print(doc.page_content)
        return 0

    docs = chunk_corpus(games=args.games or None)
    stats = coverage(docs)

    print(f"{'game':18s} {'chunks':>7s} {'articles':>9s} {'w/article':>10s} "
          f"{'cov%':>7s} {'split':>6s}  pages")
    print("-" * 78)
    for game in sorted(stats, key=lambda g: stats[g]["pct"]):
        row = stats[game]
        print(f"{game:18s} {row['chunks']:7d} {row['n_articles']:9d} "
              f"{row['with_article']:10d} {row['pct']:6.1f}% {row['split']:6d}  "
              f"{row['page_min']}-{row['page_max']}")
    print("-" * 78)
    total = len(docs)
    with_article = sum(1 for d in docs if d.metadata["article"])
    split = sum(1 for d in docs if d.metadata["chunk_of"] > 1)
    print(f"TOTAL chunks={total}  with_article={with_article} "
          f"({100.0 * with_article / total:.1f}%)  split_by_recursive={split}")

    problems = validate(docs)
    print(f"metadata violations: {len(problems)}")
    for problem in problems[:10]:
        print("  ", problem)

    if "global" in stats:
        pct = stats["global"]["pct"]
        gate = "PASS" if pct > GLOBAL_COVERAGE_GATE else "FAIL"
        print(f"\nGATE  Global Rulebook article coverage {pct:.1f}% "
              f"(> {GLOBAL_COVERAGE_GATE:.0f}% required): {gate}")
        if pct <= GLOBAL_COVERAGE_GATE or problems:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

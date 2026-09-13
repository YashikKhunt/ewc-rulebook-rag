"""Unit tests for the pure helper functions in chunker.py.

These exercise the text-normalization, heading-detection, sequence-repair and
segment-assembly helpers directly -- no PDF extraction, no manifest, no
network access, and no OpenAI calls (chunk_document / build_corpus are out of
scope here; they need a real PDF on disk).
"""

from __future__ import annotations

import chunker
from chunker import (
    Heading,
    Line,
    Segment,
    _as_heading,
    _heading_shape,
    _join,
    _longest_increasing,
    _normalize,
    _page_for_offset,
    _plausible_heading_text,
    _plausible_subarticle_text,
    _rescue_thin_segments,
    _tidy,
    _wraps_previous_line,
    article_key,
    context_label,
    drop_table_of_contents,
    enforce_sequence,
    find_heading_candidates,
)


# ---------------------------------------------------------------------------
# _normalize / _tidy
# ---------------------------------------------------------------------------


def test_normalize_strips_invisible_characters():
    # U+200B (zero width space) inside a heading number, as seen in the
    # Google-Docs exports the module's docstring calls out.
    assert _normalize("3.2.3.\u200b") == "3.2.3."


def test_normalize_collapses_odd_spaces_to_ascii():
    # U+00A0 (nbsp) and U+202F (narrow nbsp) both appear in _SPACEY.
    assert _normalize("Team\u00a0Roster") == "Team Roster"
    assert _normalize("A\u202fB") == "A B"


def test_tidy_collapses_runs_of_spaces_and_trims():
    assert _tidy("  Team    Roster   Integrity  ") == "Team Roster Integrity"


def test_tidy_leaves_single_spaces_alone():
    assert _tidy("Team Roster Integrity") == "Team Roster Integrity"


# ---------------------------------------------------------------------------
# article_key
# ---------------------------------------------------------------------------


def test_article_key_orders_numeric_articles():
    assert article_key("2.10.1") == (0, "", 2, 10, 1)
    assert article_key("2.9") < article_key("2.10.1")


def test_article_key_letter_prefixed_sorts_after_numeric():
    # Letter-prefixed appendix articles ("C6.4") get prefix=1, plain numeric
    # articles get prefix=0, so a plain article always sorts first.
    assert article_key("2.1")[0] == 0
    assert article_key("C6.4")[0] == 1
    assert article_key("2.1") < article_key("C6.4")


def test_article_key_single_level():
    assert article_key("7") == (0, "", 7)


# ---------------------------------------------------------------------------
# _heading_shape / _plausible_heading_text
# ---------------------------------------------------------------------------


def test_heading_shape_rejects_too_short_or_too_long():
    assert not _heading_shape("A")
    assert not _heading_shape("x" * 91)


def test_heading_shape_rejects_dot_leaders():
    assert not _heading_shape("Rule Changes......4")


def test_heading_shape_rejects_bare_parenthetical():
    assert not _heading_shape("(Behavior)")


def test_heading_shape_rejects_low_letter_density():
    assert not _heading_shape("12345 67890")


def test_heading_shape_accepts_normal_heading():
    assert _heading_shape("Team Roster Integrity")


def test_plausible_heading_text_requires_capital_initial():
    assert _plausible_heading_text("Team Roster Integrity")
    assert not _plausible_heading_text("team roster integrity")


def test_plausible_heading_text_rejects_table_fragment():
    # A bare-number table row ("1 year", "24 teams") is not a heading.
    assert not _plausible_heading_text("24 teams")


def test_plausible_heading_text_accepts_leading_quote():
    assert _plausible_heading_text('"Versus" GTTs')


# ---------------------------------------------------------------------------
# _wraps_previous_line / _plausible_subarticle_text
# ---------------------------------------------------------------------------


def test_wraps_previous_line_true_when_sentence_unfinished():
    assert _wraps_previous_line("as noted in Section /")


def test_wraps_previous_line_false_when_sentence_ends():
    assert not _wraps_previous_line("The previous rule applies.")


def test_wraps_previous_line_false_when_no_previous_line():
    assert not _wraps_previous_line("")


def test_plausible_subarticle_text_requires_dotted_article():
    # A single-level article number is not eligible for the relaxed test.
    assert not _plausible_subarticle_text("alcohol;", "9", "")


def test_plausible_subarticle_text_accepts_lowercase_dotted_heading():
    assert _plausible_subarticle_text("alcohol;", "9.1.4", "")


def test_plausible_subarticle_text_rejects_line_wrap_continuation():
    # "...4.2.5.1. of the Official Rules;" is a wrapped cross-reference, not a
    # sub-article, because the previous line ends mid-sentence.
    assert not _plausible_subarticle_text(
        "of the Official Rules;", "4.2.5.1", "as noted in Section /"
    )


# ---------------------------------------------------------------------------
# _as_heading (run-in heading split)
# ---------------------------------------------------------------------------


def test_as_heading_splits_run_in_sentence():
    result = _as_heading("Purpose. Activision Publishing, Inc. created this rulebook.")
    assert result == ("Purpose", "Activision Publishing, Inc. created this rulebook.")


def test_as_heading_returns_none_when_no_period_break():
    assert _as_heading("A heading with no full stop at all") is None


def test_as_heading_returns_none_when_head_too_long():
    long_head = " ".join(["word"] * 13)  # 13 words, > the 12-word cap
    assert _as_heading(f"{long_head}. Body text follows.") is None


# ---------------------------------------------------------------------------
# find_heading_candidates
# ---------------------------------------------------------------------------


def _line(text: str, page: int = 1, pos: int = 0, n: int = 10) -> Line:
    return Line(text=text, page=page, pos_in_page=pos, n_in_page=n)


def test_find_heading_candidates_inline_form():
    lines = [
        _line("1.1 Team Roster Integrity"),
        _line("Body text describing the rule."),
    ]
    candidates = find_heading_candidates(lines)
    assert len(candidates) == 1
    head = candidates[0]
    assert head.article == "1.1"
    assert head.heading == "Team Roster Integrity"
    assert head.consumed == 1


def test_find_heading_candidates_two_line_form():
    lines = [
        _line("3.2.3."),
        _line("Team Roster Integrity"),
        _line("Body text describing the rule."),
    ]
    candidates = find_heading_candidates(lines)
    assert len(candidates) == 1
    head = candidates[0]
    assert head.article == "3.2.3"
    assert head.heading == "Team Roster Integrity"
    assert head.consumed == 2


def test_find_heading_candidates_ignores_table_row():
    lines = [_line("1 year"), _line("24 teams")]
    assert find_heading_candidates(lines) == []


def test_find_heading_candidates_ignores_dot_leader_lines():
    lines = [_line("1.1 Rule Changes......4")]
    assert find_heading_candidates(lines) == []


# ---------------------------------------------------------------------------
# drop_table_of_contents
# ---------------------------------------------------------------------------


def test_drop_table_of_contents_removes_run_followed_by_page_numbers():
    lines = []
    headings_text = []
    for n in range(1, 7):
        lines.append(_line(f"{n}. Heading {n}"))
        lines.append(_line(str(n * 10)))
        headings_text.append(f"Heading {n}")
    # The same article numbers recur later as real headings.
    for n in range(1, 7):
        lines.append(_line(f"{n}. Heading {n}"))
        lines.append(_line("Real body text for this article, long enough."))

    candidates = find_heading_candidates(lines)
    kept, dead = drop_table_of_contents(lines, candidates)

    kept_articles = [c.article for c in kept]
    # Only the second (real) occurrence of each article should survive.
    assert kept_articles.count("1") == 1
    assert dead  # some lines were dropped as contents-listing noise


def test_drop_table_of_contents_keeps_short_runs():
    # A run shorter than TOC_RUN_MIN is never treated as a contents listing.
    lines = [
        _line("1. Heading One"),
        _line("Body text for heading one, long enough to count as content."),
        _line("2. Heading Two"),
        _line("Body text for heading two, long enough to count as content."),
    ]
    candidates = find_heading_candidates(lines)
    kept, dead = drop_table_of_contents(lines, candidates)
    assert len(kept) == len(candidates)
    assert dead == set()


# ---------------------------------------------------------------------------
# _longest_increasing / enforce_sequence
# ---------------------------------------------------------------------------


def test_longest_increasing_picks_best_subsequence():
    keys = [(1,), (2,), (1,), (2,), (3,), (4,), (5,)]
    idx = _longest_increasing(keys)
    assert [keys[i] for i in idx] == [(1,), (2,), (3,), (4,), (5,)]


def test_longest_increasing_empty_input():
    assert _longest_increasing([]) == []


def test_enforce_sequence_drops_restarting_list_numbers():
    headings = [
        Heading(0, 1, "1", "Team A bans one map", ""),
        Heading(1, 1, "2", "Team B bans one map", ""),
        Heading(2, 1, "3", "Team A picks", ""),
        # The article numbering restarts here with a lower number -- a list,
        # not a real heading -- so it should be rejected.
        Heading(3, 1, "1", "Not a real article", ""),
    ]
    kept = enforce_sequence(headings, [])
    kept_articles = [h.article for h in kept]
    assert kept_articles == ["1", "2", "3"]


def test_enforce_sequence_restores_dotted_articles_out_of_order():
    # Multi-level (dotted) numbers are never list markers, so even if they lose
    # the longest-increasing-subsequence contest they must be restored.
    headings = [
        Heading(0, 1, "2.5.1", "First", ""),
        Heading(1, 1, "2.5.9", "Ninth", ""),
        Heading(2, 1, "2.5.10", "Tenth", ""),
        Heading(3, 1, "2.5.4", "Fourth, printed out of order", ""),
    ]
    kept = enforce_sequence(headings, [])
    kept_articles = {h.article for h in kept}
    assert kept_articles == {"2.5.1", "2.5.9", "2.5.10", "2.5.4"}


def test_enforce_sequence_empty_input():
    assert enforce_sequence([], []) == []


# ---------------------------------------------------------------------------
# context_label
# ---------------------------------------------------------------------------


def test_context_label_with_article_and_no_part():
    label = context_label("CS2", "", "1.1", "Team Roster Integrity")
    assert label == "[CS2 · Article 1.1 — Team Roster Integrity]"


def test_context_label_with_part_folds_appendix_into_number():
    label = context_label("Global", "Appendix I", "1", "Versus GTTs")
    assert label == "[Global · Article Appendix I § 1 — Versus GTTs]"


def test_context_label_without_article_uses_heading_only():
    label = context_label("Global", "", "", "Front matter")
    assert label == "[Global · Front matter]"


# ---------------------------------------------------------------------------
# _join / _page_for_offset
# ---------------------------------------------------------------------------


def test_join_records_offsets_for_each_line():
    body_lines = [_line("First line.", page=5), _line("Second line.", page=6)]
    body, offsets = _join(None, body_lines)
    assert body == "First line.\nSecond line."
    assert offsets == [(0, 5), (12, 6)]


def test_join_includes_inline_body_at_offset_zero():
    body_lines = [_line("Second line.", page=6)]
    body, offsets = _join("Inline heading text", body_lines, inline_page=4)
    assert body.startswith("Inline heading text\n")
    assert offsets[0] == (0, 4)
    assert offsets[1][1] == 6


def test_page_for_offset_maps_offset_to_correct_page():
    seg = Segment(
        article="1.1",
        heading="Heading",
        part="",
        body="First line.\nSecond line.",
        page=5,
        page_end=6,
        offsets=[(0, 5), (12, 6)],
    )
    assert _page_for_offset(seg, 0) == 5
    assert _page_for_offset(seg, 5) == 5
    assert _page_for_offset(seg, 12) == 6
    assert _page_for_offset(seg, 20) == 6


def test_page_for_offset_defaults_to_segment_page_when_no_offsets():
    seg = Segment(
        article="1", heading="H", part="", body="text", page=3, page_end=3, offsets=[]
    )
    assert _page_for_offset(seg, 0) == 3


# ---------------------------------------------------------------------------
# _rescue_thin_segments
# ---------------------------------------------------------------------------


def _seg(article: str, body: str, part: str = "") -> Segment:
    return Segment(article=article, heading=f"Heading {article}", part=part,
                    body=body, page=1, page_end=1, offsets=[])


def test_rescue_thin_segments_drops_parent_with_substantive_child():
    long_body = "x" * (chunker.MIN_BODY_CHARS + 5)
    segments = [
        _seg("6", "short"),           # thin parent heading
        _seg("6.1", long_body),       # substantive child carries the heading
    ]
    rescued = _rescue_thin_segments(segments)
    assert rescued == set()


def test_rescue_thin_segments_keeps_one_line_rule_with_no_children():
    segments = [_seg("6.2.4", "short")]
    rescued = _rescue_thin_segments(segments)
    assert rescued == {0}


def test_rescue_thin_segments_drops_thin_front_matter():
    segments = [_seg("", "short")]
    rescued = _rescue_thin_segments(segments)
    assert rescued == set()

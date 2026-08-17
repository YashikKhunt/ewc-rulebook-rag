/**
 * The render invariant (frontend/DESIGN.md §4.1).
 *
 *   render(<ClaimText answer={A} citationSpans={S} />).textContent === A
 *
 * BYTE FOR BYTE, for every fixture including the withheld and abstention texts.
 * The client is a display surface: it never authors, rewrites, softens,
 * summarises, truncates or re-flows a rule claim. The ONLY transformation
 * permitted anywhere in this file is wrapping a substring that is ALREADY
 * PRESENT in the answer with an anchor element.
 *
 * Everything here is therefore expressed as index ranges over the original
 * string, never as new strings. Nothing is trimmed, joined, normalised,
 * markdown-rendered, smart-quoted or ellipsised. If a citation span cannot be
 * trusted -- out of bounds, overlapping, or not matching the text at its own
 * offsets -- it is DROPPED and that stretch renders as plain text, because
 * losing a link is recoverable and mangling a rule claim is not.
 */

/**
 * Validate and order the server's citation spans against the answer string.
 * Returns only spans that are in bounds, non-overlapping, and whose recorded
 * `text` matches the answer at its own offsets.
 */
export function usableSpans(answer, spans) {
  if (typeof answer !== 'string' || !Array.isArray(spans)) return []
  const sorted = spans
    .filter((s) => s && Number.isInteger(s.start) && Number.isInteger(s.end))
    .filter((s) => s.start >= 0 && s.end <= answer.length && s.end > s.start)
    // The server sends the exact substring it measured. If it does not match
    // what we hold, the two disagree about the answer and we do not guess.
    .filter((s) => typeof s.text !== 'string' || answer.slice(s.start, s.end) === s.text)
    .sort((a, b) => a.start - b.start || a.end - b.end)

  const kept = []
  let cursor = 0
  for (const span of sorted) {
    if (span.start < cursor) continue // overlaps one we already accepted
    kept.push(span)
    cursor = span.end
  }
  return kept
}

/**
 * Paragraph ranges covering [0, answer.length) with no gaps and no overlaps.
 * The blank-line separator is kept at the END of the paragraph it follows, so
 * concatenating every range reproduces the answer exactly -- including its
 * line breaks, which `white-space: pre-wrap` then renders.
 */
export function paragraphRanges(answer) {
  if (typeof answer !== 'string') return []
  const ranges = []
  const breaks = /\n{2,}/g
  let last = 0
  let match
  while ((match = breaks.exec(answer)) !== null) {
    ranges.push({ start: last, end: match.index + match[0].length })
    last = match.index + match[0].length
  }
  ranges.push({ start: last, end: answer.length })
  return ranges.filter((r) => r.end > r.start)
}

/**
 * Split the answer into a flat list of segments that concatenate back to it.
 *
 *   [{ kind: 'text', start, end }, { kind: 'cite', start, end, span }, ...]
 *
 * Grouped by paragraph so an uncited paragraph can carry its `⌀` marker. The
 * marker is rendered as an EMPTY element with the glyph supplied by CSS
 * `content: attr(data-mark)`, so it contributes nothing to `textContent` and
 * cannot break the invariant above.
 */
export function claimSegments(answer, spans) {
  const usable = usableSpans(answer, spans)
  return paragraphRanges(answer).map((range) => {
    const inside = usable.filter((s) => s.start >= range.start && s.end <= range.end)
    const segments = []
    let cursor = range.start
    for (const span of inside) {
      if (span.start > cursor) {
        segments.push({ kind: 'text', start: cursor, end: span.start })
      }
      segments.push({ kind: 'cite', start: span.start, end: span.end, span })
      cursor = span.end
    }
    if (cursor < range.end) segments.push({ kind: 'text', start: cursor, end: range.end })
    return {
      start: range.start,
      end: range.end,
      segments,
      cited: inside.length > 0,
      // A paragraph that is only whitespace is a separator, not a claim: it
      // gets no "no citation on this passage" marker.
      blank: answer.slice(range.start, range.end).trim() === '',
    }
  })
}

/**
 * What Copy puts on the clipboard. A claim must not be able to leave this UI
 * naked, so the answer goes out WITH its citations (they are already inline in
 * the string), plus the scope it was produced under and the corpus fingerprint
 * it was produced against. The answer text itself is copied verbatim.
 */
export function copyPayload(turn) {
  const lines = [turn.answer ?? '']
  lines.push('')
  lines.push(`Searched: ${turn.scope ?? 'unstated'}`)
  lines.push(`Corpus: ${turn.corpus_fingerprint ?? 'unstated'} · asked ${turn.asked_at ?? 'unstated'}`)
  if (turn.citation_errors?.length) {
    lines.push(`Post-check recorded: ${turn.citation_errors.join(' | ')}`)
  }
  return lines.join('\n')
}

import { claimSegments } from '../lib/claimText'

/**
 * ClaimText — the render invariant made a component (DESIGN.md §4.1).
 *
 *   render(<ClaimText answer={A} citationSpans={S} />).textContent === A
 *
 * byte for byte, for every fixture including the withheld and abstention texts.
 * Enforced by src/lib/claimText.test.jsx, which fails the build if this file
 * ever starts editing what the pipeline said.
 *
 * No markdown rendering, no smart quotes, no trim, no truncation, no "read
 * more", no ellipsis, no sentence re-flow, no highlight injection. Line breaks
 * are preserved by `white-space: pre-wrap` on `.answer`, not by inserting <br>.
 */
export function ClaimText({
  answer, citationSpans, outcome, docs, onOpenSource, activeChunkId, className = 'answer',
}) {
  const text = answer ?? ''
  const paragraphs = claimSegments(text, citationSpans ?? [])
  const byChunk = new Map((docs ?? []).map((d) => [d.chunk_id, d]))

  return (
    <div className={className}>
      {paragraphs.map((para) => (
        <span key={para.start}>
          {para.segments.map((segment) =>
            segment.kind === 'text' ? (
              // A bare string child: it contributes exactly these characters.
              text.slice(segment.start, segment.end)
            ) : (
              <CitationChip
                key={segment.start}
                text={text.slice(segment.start, segment.end)}
                span={segment.span}
                doc={byChunk.get(segment.span.chunk_id)}
                active={activeChunkId && activeChunkId === segment.span.chunk_id}
                onOpen={onOpenSource}
              />
            ),
          )}
          {/* Uncited-passage marker. Presentational ONLY: the element is empty
              and the glyph comes from CSS `content: attr(data-mark)`, so it adds
              no characters to the textContent the invariant test measures. By
              non-negotiable #3 an uncited rule statement is a defect, and the
              UI's job is to surface defects, not to make the page look clean. */}
          {outcome === 'answered' && !para.cited && !para.blank && (
            <span
              className="uncited-mark"
              data-mark=" ⌀"
              role="img"
              aria-label="no citation on this passage"
            />
          )}
        </span>
      ))}
    </div>
  )
}

/**
 * CitationChip — an inline anchor INSIDE the sentence. Never absolutely
 * positioned, never floated, never a superscript marker with a footnote
 * elsewhere. A rule claim and its citation are inseparable: there is no
 * arrangement in which this can be read aloud, copied, or laid out without the
 * claim it belongs to.
 *
 * The visible text is exactly what the pipeline wrote. `aria-label` expands the
 * abbreviations so the locator is unambiguous aloud, without changing a
 * character of the visible string.
 */
export function CitationChip({ text, span, doc, active, onOpen }) {
  // The post-check is itself a thing that can be wrong, so a span the server
  // could not match to a retrieved excerpt is shown as unresolved rather than
  // silently unstyled or quietly dropped.
  if (!span.chunk_id || !doc) {
    return (
      <>
        <span className="citation unresolved" title="not matched to a retrieved excerpt">
          {text}
        </span>
        {/* The warning is an EMPTY element whose glyph comes from CSS
            `content: attr(data-mark)` and whose accessible name comes from
            aria-label. Putting the words in the DOM here would add characters
            to the answer's textContent and break the §4.1 render invariant --
            the claim must read back byte for byte even when we are flagging a
            problem with it. */}
        <span
          className="unresolved-mark"
          data-mark=" ⚠"
          role="img"
          aria-label="not matched to a retrieved excerpt"
        />
      </>
    )
  }

  const tier = Number(doc.authority) || 0
  const spanned = doc.page_end > doc.page
  const label =
    `Citation: ${doc.game_title}, ` +
    (doc.article ? `Article ${doc.article}, ` : 'no article number, ') +
    `physical PDF page ${doc.page}${spanned ? ` to ${doc.page_end}` : ''}. ` +
    `Opens the source page.`

  return (
    <a
      className={`citation t-${tier} ${active ? 'active' : ''}`}
      href={`/api/source/${doc.game}#page=${doc.page}`}
      aria-label={label}
      onClick={(event) => {
        event.preventDefault()
        onOpen?.(doc)
      }}
    >
      {text}
    </a>
  )
}

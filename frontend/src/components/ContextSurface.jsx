import { useDispatch, useSelector } from 'react-redux'
import { AuthorityBadge, Locator, Unstated } from './Primitives'
import { setContextOrder, toggleExpanded } from '../store'

/**
 * Feature 2: the retrieved chunks, shown as context under EVERY answer.
 *
 * Expanded by default. It is a mandatory feature and the evidence base for a
 * compliance decision; hiding it behind a "Sources ▸" accordion would be a dark
 * pattern here. Cards are never collapsed to header-only — the point is to show
 * the text.
 *
 * Every field below comes straight from chunk metadata. Nothing is invented, and
 * an empty `version` or `effective_date` renders as `unstated` (true for 24 of
 * 25 books) rather than being defaulted to something plausible.
 */
export function ContextSurface({ turn, onOpenSource, activeChunkId }) {
  const dispatch = useDispatch()
  const order = useSelector((s) => s.ui.contextOrder)
  const expanded = useSelector((s) => s.ui.expanded)

  const docs = turn.docs ?? []
  const ranks = turn.ranks ?? {}
  const accountable = new Set(turn.accountable ?? [])

  // Chunks resolve stamped SUPERSEDED — an `amended` finding whose base text
  // predates the amendment. No live instance exists in this corpus (log 009).
  const superseded = new Set(
    (turn.findings ?? [])
      .filter((f) => f.kind === 'amended' && !f.incorporated && f.base_in_evidence)
      .flatMap((f) => (f.chunk_ids ?? []).slice(1)),
  )

  const readOrder = new Map(docs.map((d, i) => [d.chunk_id, i + 1]))
  const shown =
    order === 'relevance'
      ? [...docs].sort(
          (a, b) => (ranks[a.chunk_id] ?? 99) - (ranks[b.chunk_id] ?? 99),
        )
      : docs

  if (docs.length === 0) {
    return (
      <>
        <div className="ctx-head">
          <div className="eyebrow">Retrieved context · 0 excerpts</div>
        </div>
        <p className="mono" style={{ color: 'var(--ink-3)' }}>
          The store returned no excerpt for this query under the scope above.
        </p>
      </>
    )
  }

  return (
    <>
      <div className="ctx-head">
        <div className="eyebrow">
          Retrieved context · {docs.length} excerpt{docs.length === 1 ? '' : 's'}
        </div>
        {/* Both orders are already in the response. Neither fires a request. */}
        <div className="seg" role="group" aria-label="Excerpt order">
          <button
            aria-pressed={order === 'read'}
            onClick={() => dispatch(setContextOrder('read'))}
            title="Authority-descending, RRF order stable within each tier — what actually happened"
          >
            As the model read them
          </button>
          <button
            aria-pressed={order === 'relevance'}
            onClick={() => dispatch(setContextOrder('relevance'))}
            title="The pre-authority-sort fused relevance rank"
          >
            By relevance
          </button>
        </div>
      </div>

      {shown.map((doc, index) => (
        <ContextCard
          key={doc.chunk_id}
          doc={doc}
          readOrder={readOrder.get(doc.chunk_id)}
          fusedRank={ranks[doc.chunk_id]}
          accountable={accountable.has(doc.chunk_id)}
          superseded={superseded.has(doc.chunk_id)}
          // `accountable` chunks are auto-expanded: resolve judged them relevant
          // enough that dropping one silently is a defect.
          expanded={expanded[doc.chunk_id] ?? accountable.has(doc.chunk_id)}
          active={activeChunkId === doc.chunk_id}
          onToggle={() => dispatch(toggleExpanded(doc.chunk_id))}
          onOpen={() => onOpenSource?.(doc)}
          style={{ animationDelay: `${Math.min(index, 8) * 40}ms` }}
        />
      ))}
    </>
  )
}

const TIER_CLASS = { 0: 'g', 1: 't', 2: 'a' }

export function ContextCard({
  doc, readOrder, fusedRank, accountable, superseded, expanded, active,
  onToggle, onOpen, style,
}) {
  const tier = TIER_CLASS[Number(doc.authority) || 0] ?? 'g'
  const spanned = doc.page_end > doc.page
  const host = (() => {
    try {
      return new URL(doc.source_url).host
    } catch {
      return null
    }
  })()

  return (
    <article
      className={[
        'card', tier,
        doc.external_host ? 'external' : '',
        active ? 'active' : '',
        superseded ? 'superseded' : '',
      ].filter(Boolean).join(' ')}
      style={style}
      aria-label={`Excerpt ${readOrder}: ${doc.game_title}`}
    >
      <header className="card-h">
        <AuthorityBadge authority={doc.authority} />
        <div className="grow">
          <div className="bk">{doc.game_title}</div>
          <div className="lc mono">
            <Locator
              gameTitle=""
              article={doc.article}
              page={doc.page}
              pageEnd={doc.page_end}
            />
          </div>
          <div className="tr" title={doc.heading_path || undefined}>
            {doc.part ? `Appendix ${doc.part} § ` : ''}
            {doc.heading_path || <span className="absent">no section trail</span>}
          </div>
        </div>
        <div className="rk">
          <div>
            READ #{readOrder}
            {typeof fusedRank === 'number' ? ` · RANK ${fusedRank}` : ''}
          </div>
          {accountable && (
            <div
              className="star"
              title="Retrieval ranked this excerpt highly enough that the answer must either use it or say why not."
            >
              ★ ACCOUNTABLE
            </div>
          )}
          {superseded && <div className="star">SUPERSEDED</div>}
        </div>
      </header>

      {/* page_content VERBATIM, including the [game · Article n — heading]
          context label the chunker prepends. Not stripped: it is what was
          embedded, and it is what the model read. */}
      <div className={`card-b ${expanded ? '' : 'clamped'}`}>{doc.page_content}</div>
      <button className="card-more" onClick={onToggle} aria-expanded={expanded}>
        {expanded ? '▴ less' : '▾ more'}
      </button>

      <footer className="card-f">
        <span>
          v {doc.version || <Unstated />} · effective {doc.effective_date || <Unstated />} ·{' '}
          {Number(doc.n_chars ?? 0).toLocaleString()} chars · chunk {Number(doc.chunk) + 1} of{' '}
          {doc.chunk_of}
          {doc.external_host && host && (
            <>
              {' '}
              <span className="tag hatched">THIRD-PARTY HOST · {host}</span>
            </>
          )}
        </span>

        {doc.source_available ? (
          <button className="open-btn" onClick={onOpen}>
            ▸ OPEN PDF PAGE{spanned ? `S ${doc.page}–${doc.page_end}` : ` ${doc.page}`}
          </button>
        ) : (
          <span className="unopenable">
            {doc.scope === 'amendment'
              ? 'Published as an HTML notice — no PDF page'
              : <>Local PDF not available — run <code>python ingest.py</code></>}
            {doc.source_url && (
              <>
                {' · '}
                <a href={doc.source_url} target="_blank" rel="noreferrer noopener">
                  publisher copy ↗
                </a>
              </>
            )}
          </span>
        )}
      </footer>
    </article>
  )
}

import { useEffect, useRef, useState } from 'react'
import { useDispatch } from 'react-redux'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { closeSource, setViewerPage } from '../store'
import { getPageLabels, sourceUrl } from '../store/api'
import { AuthorityBadge } from './Primitives'

// Self-hosted pdf.js: the worker is bundled from node_modules by Vite, not
// fetched from a CDN. CLAUDE.md's don'ts, and the viewer works offline.
pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

/**
 * Feature 3: opening the exact source page, honestly.
 *
 * A DRAWER, not a modal. This is load-bearing: the whole point is to check a
 * claim against its page, which requires seeing both at once. The conversation
 * narrows; it does not dim, blur or become inert.
 *
 * THE PAGE IN A CITATION IS THE PHYSICAL PDF PAGE, AND THE VIEWER OPENS AT THE
 * PHYSICAL PAGE. The UI never converts to a printed page number in either
 * direction — printed numbering across these 25 books is not an invertible
 * function (8 books print nothing; `honor-of-kings` is two documents in one file
 * where printed labels 1–5 each land on TWO different physical pages). A
 * converter would send a compliance user to the wrong page half the time, so
 * there isn't one.
 */
export function SourceViewer({ doc, page, onOpenPage }) {
  const dispatch = useDispatch()
  const canvasRef = useRef(null)
  const closeRef = useRef(null)
  const [state, setState] = useState('loading')
  const [pdf, setPdf] = useState(null)
  const [labels, setLabels] = useState(null)
  const [error, setError] = useState(null)

  const slug = doc?.game

  useEffect(() => {
    if (!slug || !doc?.source_available) {
      setState('unavailable')
      return undefined
    }
    let cancelled = false
    setState('loading')
    const task = pdfjs.getDocument({ url: sourceUrl(slug), isEvalSupported: false })
    task.promise.then(
      (loaded) => {
        if (cancelled) return
        setPdf(loaded)
        setState('ready')
      },
      (cause) => {
        if (cancelled) return
        setError(cause?.message ?? String(cause))
        setState('error')
      },
    )
    // Printed footer labels are an OBSERVATION of each page, never a locator.
    getPageLabels(slug).then(
      (data) => !cancelled && setLabels(data),
      () => !cancelled && setLabels(null),
    )
    return () => {
      cancelled = true
      task.destroy?.()
    }
  }, [slug, doc?.source_available])

  useEffect(() => {
    if (!pdf || state !== 'ready') return undefined
    if (page < 1 || page > pdf.numPages) {
      setState('page-out-of-range')
      return undefined
    }
    let cancelled = false
    let task = null
    pdf.getPage(page).then((rendered) => {
      if (cancelled) return
      const canvas = canvasRef.current
      if (!canvas) return
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      const base = rendered.getViewport({ scale: 1 })
      const width = Math.min(canvas.parentElement?.clientWidth ?? 460, 620)
      const viewport = rendered.getViewport({ scale: (width / base.width) * ratio })
      canvas.width = viewport.width
      canvas.height = viewport.height
      canvas.style.width = `${viewport.width / ratio}px`
      canvas.style.height = `${viewport.height / ratio}px`
      task = rendered.render({ canvasContext: canvas.getContext('2d'), viewport })
      task.promise.catch(() => {})
    })
    return () => {
      cancelled = true
      task?.cancel?.()
    }
  }, [pdf, page, state])

  useEffect(() => {
    closeRef.current?.focus()
  }, [doc?.chunk_id])

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') dispatch(closeSource())
      if (event.target.matches?.('input, textarea, select')) return
      if (event.key === '[') onOpenPage(page - 1)
      if (event.key === ']') onOpenPage(page + 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [dispatch, onOpenPage, page])

  if (!doc) return null

  const observed = labels?.pages?.find((p) => p.physical === page) ?? null
  const spanned = doc.page_end > doc.page
  const tier = Number(doc.authority) || 0
  const total = labels?.page_count ?? pdf?.numPages ?? doc.page_count

  return (
    <aside className="viewer" aria-label={`Source page ${page} of ${doc.game_title}`}>
      <header className="v-head">
        <div>
          <div className="bk">
            <AuthorityBadge authority={doc.authority} size="sm" /> {doc.game_title}
          </div>
          <div className="lc mono">
            {doc.article ? `Art. ${doc.article}` : 'no article number'}
            {' · '}
            {spanned ? `pp.${doc.page}–${doc.page_end}` : `p.${doc.page}`}
          </div>
        </div>
        <button
          className="x"
          ref={closeRef}
          onClick={() => dispatch(closeSource())}
          aria-label="Close the source viewer"
        >
          ✕
        </button>
      </header>

      <PageProvenanceStrip
        physicalPage={page}
        pageCount={total}
        observed={observed}
        hasLabels={Boolean(labels)}
        cited={page === doc.page || (doc.page_end > doc.page && page <= doc.page_end && page >= doc.page)}
      />

      <div className="v-body">
        {state === 'loading' && <p className="v-state">Loading the locally indexed PDF…</p>}
        {state === 'unavailable' && (
          <p className="v-state">
            {doc.scope === 'amendment'
              ? 'This excerpt is a published HTML notice, not a PDF page. Its source is linked below.'
              : <>No local PDF for this book. Run <code>python ingest.py</code> to fetch it, or
                open the publisher copy linked below.</>}
          </p>
        )}
        {state === 'error' && (
          <p className="v-state">
            The PDF could not be rendered: {error}. The publisher copy is linked below.
          </p>
        )}
        {state === 'page-out-of-range' && (
          <p className="v-state">
            This citation points at physical page {page}, but the local PDF has{' '}
            {pdf?.numPages} pages. The citation and the file disagree — do not assume either is
            right without checking the publisher copy.
          </p>
        )}
        {state === 'ready' && (
          <div className="stage">
            <canvas ref={canvasRef} />
            {/* An attention cue in the margin, NOT a text highlight: chunk text
                is PyMuPDF-extracted and reflowed, so a match would be
                approximate, and an approximate highlight on a compliance
                document asserts precision the system does not have. The page is
                the unit of evidence. */}
            {page === doc.page && <div className={`bracket t-${tier}`} />}
          </div>
        )}
      </div>

      {spanned && (
        <div className="v-span">
          <span>This excerpt continues onto page {doc.page_end}.</span>
          {/* Paging within an open viewer is free and fires nothing. */}
          <button className="open-btn" onClick={() => onOpenPage(doc.page_end)}>
            ▸ page {doc.page_end}
          </button>
        </div>
      )}

      <SourceOriginNote doc={doc} page={page} total={total} onOpenPage={onOpenPage} />
    </aside>
  )
}

/**
 * The honest page-numbering disclosure. Always present, never dismissible.
 * Line 1 always shows. Line 2 only where a footer label was actually OBSERVED
 * on that page. Line 3 only where that label is ambiguous within the document.
 */
export function PageProvenanceStrip({ physicalPage, pageCount, observed, hasLabels, cited }) {
  return (
    <div className="prov">
      <div className="eyebrow">
        Physical PDF page {physicalPage}
        {pageCount ? ` of ${pageCount}` : ''}
        {/* Only claim this IS the cited page while it actually is. Once the
            reader pages away, saying so would mislabel the evidence. */}
        {cited ? ' — the page this citation points to' : ' — paged away from the citation'}
      </div>
      {hasLabels ? (
        observed?.footer_label ? (
          <>
            <p>This page’s printed footer reads “{observed.footer_label}”.</p>
            {observed.ambiguous && (
              <p className="warn">
                ⚠ This document’s printed numbering is not unique: “{observed.footer_label}”
                also appears on another physical page. Citations use the physical page.
              </p>
            )}
          </>
        ) : (
          // Stated, not left blank.
          <p>No printed page number appears on this page.</p>
        )
      ) : (
        <p>Printed footer labels for this book have not been read.</p>
      )}
    </div>
  )
}

/**
 * Which copy of the PDF you are reading. Two different files can answer "the
 * source PDF", and log 009 documents that the distinction is real: the publisher
 * silently re-uploaded the Global Rulebook mid-project so the amended paragraph
 * moved to p.18. So the viewer names its copy.
 */
export function SourceOriginNote({ doc, page, total, onOpenPage }) {
  let host = null
  try {
    host = new URL(doc.source_url).host
  } catch {
    host = null
  }
  return (
    <footer className="v-foot">
      <span>
        indexed copy · {doc.source_path ?? 'unstated path'}
        {doc.external_host && host && (
          <>
            {' · '}
            <span className="tag hatched">THIRD-PARTY HOST · {host}</span>
          </>
        )}
      </span>

      <span className="v-pager">
        <button disabled={page <= 1} onClick={() => onOpenPage(page - 1)} aria-label="Previous page">
          [
        </button>
        <span>
          {page}
          {total ? ` / ${total}` : ''}
        </span>
        <button
          disabled={Boolean(total) && page >= total}
          onClick={() => onOpenPage(page + 1)}
          aria-label="Next page"
        >
          ]
        </button>
      </span>

      {doc.source_url && (
        <a href={doc.source_url} target="_blank" rel="noreferrer noopener">
          Publisher copy on {host ?? 'the publisher site'} ↗ — may have been re-uploaded since
          it was indexed; page numbers may differ.
        </a>
      )}
    </footer>
  )
}

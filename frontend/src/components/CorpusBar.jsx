import { useDispatch, useSelector } from 'react-redux'
import { setTheme, setCatalogOpen, toggleRail } from '../store'
import { AuthorityBadge, Unstated } from './Primitives'

export function CorpusBar() {
  const dispatch = useDispatch()
  const { info, catalog } = useSelector((s) => s.corpus)
  const theme = useSelector((s) => s.ui.theme)
  const open = useSelector((s) => s.ui.catalogOpen)

  const next = { system: 'light', light: 'dark', dark: 'system' }

  return (
    <div className="corpusbar">
      <button className="btn-ghost rail-toggle" onClick={() => dispatch(toggleRail())}>
        ☰
      </button>
      <span className="wordmark">EWC Rulebook RAG</span>

      {info ? (
        <button
          className="fp"
          onClick={() => dispatch(setCatalogOpen(!open))}
          aria-expanded={open}
          title="Every book in the index, with its chunk count, version and effective date"
        >
          {info.chunks} chunks · {info.books} books · {info.amendments} amendment
          {info.amendments === 1 ? '' : 's'} · {info.fingerprint}
        </button>
      ) : (
        <span className="mono">corpus not loaded</span>
      )}

      <div className="corpusbar-right">
        <button className="btn-ghost" onClick={() => dispatch(setTheme(next[theme]))}>
          {theme}
        </button>
      </div>

      {open && <CatalogPopover catalog={catalog} onClose={() => dispatch(setCatalogOpen(false))} />}
    </div>
  )
}

/**
 * The corpus inventory. Renders `unstated` — not a guess, not blank — where a
 * version or effective date is empty, which is the case for 24 of 25 books. Do
 * not invent a version.
 */
function CatalogPopover({ catalog, onClose }) {
  return (
    <div className="popover" role="dialog" aria-label="Corpus inventory">
      <h3>
        Every book in the index{' '}
        <button className="btn-ghost" style={{ float: 'right' }} onClick={onClose}>
          close
        </button>
      </h3>
      <table>
        <thead>
          <tr>
            <th></th>
            <th>book</th>
            <th>chunks</th>
            <th>version</th>
            <th>effective</th>
          </tr>
        </thead>
        <tbody>
          {catalog.map((book) => (
            <tr key={book.slug}>
              <td>
                <AuthorityBadge authority={book.authority} size="sm" />
              </td>
              <td>
                {book.game_title}
                {!book.in_corpus && (
                  <div className="absent" style={{ fontSize: 10 }}>
                    not in the corpus — {book.skip_reason}
                  </div>
                )}
              </td>
              <td>{book.in_corpus ? book.chunk_count : '—'}</td>
              <td className={book.version ? '' : 'absent'}>{book.version || 'unstated'}</td>
              <td className={book.effective_date ? '' : 'absent'}>
                {book.effective_date || 'unstated'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * The conversation-empty state: the corpus at rest. This doubles as an
 * inventory, which is genuinely useful and costs nothing.
 *
 * It also states the pipeline's known gaps, because a UI over a system with an
 * open blocking finding should say so rather than look authoritative.
 */
export function CorpusAtRest() {
  const { info, catalog } = useSelector((s) => s.corpus)
  if (!info) return null
  return (
    <div className="at-rest">
      <h1 className="headline">Ask about a rule.</h1>
      <p className="lead">
        Answers cite the rulebook, article and PDF page they came from. Each question is an
        independent lookup — the system carries no context between them, so a conversation here
        is a folder of related enquiries rather than a thread.
      </p>

      <div className="inventory">
        {catalog.map((book) => (
          <div key={book.slug} className={book.in_corpus ? '' : 'absent'}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {book.game_title}
            </span>
            <span>{book.in_corpus ? `${book.chunk_count}` : 'no PDF'}</span>
          </div>
        ))}
      </div>

      <div className="gaps">
        <div className="eyebrow">What this system does not yet do</div>
        <ul>
          {info.known_gaps.map((gap) => (
            <li key={gap}>— {gap}</li>
          ))}
          <li>
            — pipeline: {info.pipeline_nodes.join(' → ')} · corpus {info.fingerprint} ·{' '}
            {info.chat_model}
          </li>
        </ul>
      </div>
    </div>
  )
}

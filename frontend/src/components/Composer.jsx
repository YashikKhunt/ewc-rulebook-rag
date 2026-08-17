import { useEffect, useRef, useState } from 'react'
import { useSelector } from 'react-redux'
import { formatUsd } from './Primitives'

/**
 * The composer.
 *
 * COST DISCIPLINE, structurally: there is no autocomplete, no suggested
 * question, no "related rules", no prefetch, no poll and no query on typing,
 * focus or mount. The ONLY things that reach a model are the two buttons below,
 * both of which require a click or an explicit keyboard shortcut.
 *
 * Two submit controls, deliberately:
 *   Ask         — the full pipeline.
 *   Search only — route → retrieve → resolve, no generation. With a scope set
 *                 this fires ZERO chat completions. For a compliance user who
 *                 wants to read the articles themselves this is often the better
 *                 tool, and it makes the cheap path the VISIBLE path rather than
 *                 a hidden flag.
 */
export function Composer({ onAsk, onSearch, disabled, blockedReason }) {
  const catalog = useSelector((s) => s.corpus.catalog)
  const [question, setQuestion] = useState('')
  const [game, setGame] = useState('auto')
  const textareaRef = useRef(null)

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === '/' && !event.target.matches('input, textarea, select')) {
        event.preventDefault()
        textareaRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const scope = game === 'auto' ? null : game === 'global' ? null : game
  const forced = game !== 'auto'
  const ready = question.trim().length > 0 && !disabled

  const submit = (mode) => {
    if (!ready) return
    const payload = { question: question.trim(), game: scope }
    mode === 'ask' ? onAsk(payload) : onSearch(payload)
    setQuestion('')
  }

  const onKeyDown = (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault()
      submit(event.shiftKey ? 'search' : 'ask')
    }
  }

  // Estimated WITHOUT any network call: the router is one completion, the
  // answer node one more, plus one retry only if a post-check fails.
  const calls = forced ? 1 : 2
  const estimate = calls * 0.0002

  const searchedLabel = forced
    ? game === 'global'
      ? 'the EWC Global Rulebook 2026 and published amendments'
      : `${catalog.find((b) => b.slug === game)?.game_title ?? game} + Global`
    : 'whichever book the router picks, + Global'

  return (
    <div className="composer">
      <div className="wrap">
        {blockedReason && <div className="blocked">{blockedReason}</div>}

        <textarea
          ref={textareaRef}
          className="ta"
          rows={2}
          value={question}
          disabled={disabled}
          placeholder="Ask about a rule — e.g. “How long is the grace period before a forfeit?”"
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={onKeyDown}
          aria-label="Your question"
        />

        <div className="crow">
          <ScopeSelector value={game} onChange={setGame} catalog={catalog} />

          <span className="pre mono">
            ≈ {calls} model call{calls === 1 ? '' : 's'} · ≈ {formatUsd(estimate, 4)} · searches{' '}
            {searchedLabel}
          </span>

          <button className="btn btn-2" disabled={!ready} onClick={() => submit('search')}>
            Search only
          </button>
          <button className="btn btn-1" disabled={!ready} onClick={() => submit('ask')}>
            Ask
          </button>
        </div>

        <div className="hint mono">
          {forced
            ? 'Setting a scope skips the router — one fewer model call, and no chance of a routing error.'
            : 'Auto routes with one model call. Setting a scope skips it.'}
          {'  ·  ⌘/Ctrl+Enter to ask · ⌘/Ctrl+Shift+Enter to search only · / to focus'}
        </div>
      </div>
    </div>
  )
}

/**
 * Books with no published PDF are listed and DISABLED, with the reason. Silently
 * omitting `overwatch-2` would let a user believe they searched a book that does
 * not exist in the index.
 */
function ScopeSelector({ value, onChange, catalog }) {
  return (
    <select
      className="sel"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      aria-label="Which rulebook to search"
    >
      <option value="auto">Auto (router decides)</option>
      <option value="global">Global only</option>
      {catalog
        .filter((b) => b.slug !== 'global')
        .map((book) => (
          <option key={book.slug} value={book.slug} disabled={!book.in_corpus}>
            {book.game_title}
            {book.in_corpus ? '' : ` — no PDF published, not in the corpus`}
          </option>
        ))}
    </select>
  )
}

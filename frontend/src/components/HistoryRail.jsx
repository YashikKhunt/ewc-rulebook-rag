import { useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import {
  openConversation, startConversation, renameConversation, removeConversation,
} from '../store'
import { formatDay, formatUsd } from './Primitives'

/**
 * Feature 1: past chat history — persisted, listable, switchable, deletable.
 *
 * Records live in SQLite on the server, so they survive a reload, a browser
 * change, and a machine the compliance user may not own. Loading one is a PURE
 * READ: it never invokes the pipeline and never spends.
 */
export function HistoryRail() {
  const dispatch = useDispatch()
  const { conversations, activeId, listStatus } = useSelector((s) => s.chat)
  const railOpen = useSelector((s) => s.ui.railOpen)

  return (
    <aside className={`rail ${railOpen ? 'open' : ''}`} aria-label="Saved enquiries">
      <div className="rail-head">
        <span className="eyebrow">Enquiries</span>
        <button className="btn-ghost" onClick={() => dispatch(startConversation())}>
          New
        </button>
      </div>

      <div className="rail-list">
        {listStatus === 'loading' && <div className="rail-empty">Loading…</div>}

        {listStatus === 'ready' && conversations.length === 0 && (
          <p className="rail-empty">
            No saved enquiries. Each conversation is a folder of independent lookups — the
            system does not carry context between questions.
          </p>
        )}

        {conversations.map((conversation) => (
          <HistoryEntry
            key={conversation.id}
            conversation={conversation}
            active={conversation.id === activeId}
            onSelect={() => dispatch(openConversation(conversation.id))}
            onRename={(title) => dispatch(renameConversation({ id: conversation.id, title }))}
            onDelete={() => dispatch(removeConversation(conversation.id))}
          />
        ))}
      </div>

      <BudgetLedger />
    </aside>
  )
}

function HistoryEntry({ conversation, active, onSelect, onRename, onDelete }) {
  const [mode, setMode] = useState(null) // null | 'renaming' | 'confirming'
  const [draft, setDraft] = useState(conversation.title)

  if (mode === 'renaming') {
    return (
      <div className="entry-row">
        <input
          className="entry-rename"
          value={draft}
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              onRename(draft)
              setMode(null)
            }
            if (event.key === 'Escape') setMode(null)
          }}
          onBlur={() => {
            onRename(draft)
            setMode(null)
          }}
          aria-label="Rename this enquiry"
        />
      </div>
    )
  }

  return (
    <div className="entry-row">
      <button className="entry" aria-current={active} onClick={onSelect}>
        <span className="t">{conversation.title}</span>
        <span className="m mono">
          {conversation.stale && 'Δ '}
          {conversation.turn_count} turn{conversation.turn_count === 1 ? '' : 's'} ·{' '}
          {formatDay(conversation.updated_at)}
          {conversation.scopes.length > 0 && ` · ${conversation.scopes.join(', ')}`}
        </span>
      </button>

      <div className="entry-tools">
        <button onClick={() => setMode('renaming')} aria-label="Rename">
          ren
        </button>
        <button onClick={() => setMode('confirming')} aria-label="Delete">
          del
        </button>
      </div>

      {/* Confirm INSIDE the row — no modal for a destructive-but-scoped action,
          and the row states exactly what is lost. */}
      {mode === 'confirming' && (
        <div className="entry-confirm">
          <p>
            Deletes {conversation.turn_count} recorded{' '}
            {conversation.turn_count === 1 ? 'answer' : 'answers'}. Not recoverable.
          </p>
          <button className="btn-ghost" onClick={onDelete}>
            Delete
          </button>{' '}
          <button className="btn-ghost" onClick={() => setMode(null)}>
            Keep
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * The spend meter. Colour is never used here: --alert is reserved for genuine
 * errors, and running low on budget is a condition, not a fault. At 80% the
 * meter thickens instead.
 */
export function BudgetLedger() {
  const budget = useSelector((s) => s.corpus.budget)
  const turns = useSelector((s) => s.chat.turns)
  if (!budget) return null

  const lastTurn = turns.length ? turns[turns.length - 1].cost_usd : null
  const fraction = Math.min(1, budget.day_spent_usd / (budget.day_usd || 1))
  const warn = fraction >= 0.8

  return (
    <div className={`ledger ${warn ? 'warn' : ''} ${budget.refused ? 'refused' : ''}`}>
      <div className="eyebrow">Budget · today</div>
      <div className="meter">
        <i style={{ width: `${fraction * 100}%` }} />
      </div>
      <div className="mono lead">
        {/* 4 dp, not 2: a ceiling set to $0.002 must not read as "$0.00". */}
        {formatUsd(budget.day_spent_usd, 4)} / {formatUsd(budget.day_usd, 4)}
      </div>
      <div className="mono sub">
        project {formatUsd(budget.project_spent_usd, 4)} / {formatUsd(budget.project_usd, 2)}
      </div>
      {typeof lastTurn === 'number' && (
        <div className="mono sub" title="chat tokens only; retrieval embeddings are not metered">
          this turn {formatUsd(lastTurn)} (chat only)
        </div>
      )}
      {budget.refused && (
        <div className="mono sub">
          Ceiling reached — the server will refuse before calling the model.
        </div>
      )}
    </div>
  )
}

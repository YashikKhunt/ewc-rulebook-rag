import { useMemo } from 'react'
import { useSelector } from 'react-redux'
import { ScopeLedger } from './ScopeLedger'
import { ContextSurface } from './ContextSurface'
import { AnswerSurface, AbstentionPanel, WithheldPanel } from './AnswerSurface'
import { TitleMismatchBanner } from './TitleMismatchBanner'
import { formatWhen, formatUsd } from './Primitives'
import { detectTitleMismatch } from '../lib/mismatch'

/**
 * One question → result record. NOT a chat bubble.
 *
 * graph.py has no conversation memory: `ask()` builds a fresh state from a
 * single question every time. So turns are INDEPENDENT RECORDS, rendered as
 * stacked documents. There is no "continue the thread" affordance, no
 * pronoun-resolving follow-up, and nothing anywhere says "based on your last
 * question" — a UI that accepted "and what about CS2?" would silently drop the
 * referent and produce exactly B-2's failure shape.
 */
export function TurnCard({ turn, corpusFingerprint, catalog, onOpenSource, onRescope }) {
  const viewer = useSelector((s) => s.ui.viewer)
  const activeChunkId = viewer?.turnId === turn.turn_id ? viewer.chunkId : null

  const stale = turn.stale ?? turn.corpus_fingerprint !== corpusFingerprint
  const mismatch = useMemo(
    () => detectTitleMismatch(turn.question, turn, catalog),
    [turn, catalog],
  )

  return (
    <article className={`turn ${stale ? 'stale' : ''}`} aria-label={`Enquiry: ${turn.question}`}>
      {stale && (
        <div className="eyebrow stale-stamp">
          Recorded against an earlier corpus — {turn.corpus_fingerprint} · never re-run
        </div>
      )}

      <QuestionBlock turn={turn} />
      <ScopeLedger turn={turn} catalog={catalog} />

      {/* Before the answer in the DOM as well as visually, so a screen-reader
          user meets the caveat before the claim. */}
      {mismatch.mentioned.length > 0 && (
        <TitleMismatchBanner
          mentioned={mismatch.mentioned}
          routed={mismatch.routed}
          turn={turn}
          onRescope={onRescope}
        />
      )}

      <Result turn={turn} onOpenSource={onOpenSource} activeChunkId={activeChunkId} />

      {/* The excerpts are trustworthy even where the prose built from them was
          not, so context renders in EVERY result state — and seeing what WAS
          found is often the most useful part of an abstention. */}
      <ContextSurface turn={turn} onOpenSource={onOpenSource} activeChunkId={activeChunkId} />

      {turn.note && <DeveloperNote note={turn.note} />}
    </article>
  )
}

/**
 * Result states are derived from `response.outcome`, which the SERVER computes
 * mechanically — never by the client pattern-matching answer prose. Regex over
 * rule text is exactly the "re-render a claim" this client forbids, and it is
 * fragile against a model-authored abstention.
 */
function Result({ turn, onOpenSource, activeChunkId }) {
  if (turn.mode === 'search') {
    return (
      <section className="panel" role="region" aria-label="Search only">
        <div className="eyebrow">Search only — no answer was generated</div>
        <p className="gloss">
          This was a retrieval-only lookup: route, retrieve and resolve ran; the answer node did
          not. No rule statement has been written, by the model or by this interface. Read the
          excerpts below and draw your own conclusion.
        </p>
      </section>
    )
  }
  if (turn.outcome === 'withheld') return <WithheldPanel turn={turn} />
  if (turn.outcome === 'uncited' || turn.outcome === 'no_evidence') {
    return <AbstentionPanel turn={turn} />
  }
  return (
    <AnswerSurface
      turn={turn}
      docs={turn.docs ?? []}
      onOpenSource={onOpenSource}
      activeChunkId={activeChunkId}
    />
  )
}

function QuestionBlock({ turn }) {
  const cost =
    typeof turn.cost_usd === 'number'
      ? formatUsd(turn.cost_usd)
      : null
  return (
    <>
      <div className="qmeta mono">
        {formatWhen(turn.asked_at)}
        {' · '}
        {turn.model}
        {' · '}
        {cost ? <span title={turn.cost_basis}>{cost} (chat only)</span>
              : <span className="absent">cost not priced for this model</span>}
        {' · '}
        {(turn.duration_ms / 1000).toFixed(1)}s
        {turn.retried && ' · one correction attempt fired'}
      </div>
      <h2 className="question">{turn.question}</h2>
      {turn.forced_scope && (
        <div className="forced-tag">Scope set manually: {turn.game}</div>
      )}
    </>
  )
}

/**
 * `note` is PROMPT TEXT, written in imperatives to the model ("Say that the
 * Global Rulebook governs"). Shown in the answer flow it would read as the
 * system's own assertion to the user, so it lives behind a developer disclosure
 * and nowhere else.
 */
function DeveloperNote({ note }) {
  return (
    <details className="devnote">
      <summary>Show the note sent to the model</summary>
      <p className="caution">
        This is instruction text the pipeline computed and sent to the model, not a statement to
        you. It is written in imperatives and is shown here for debugging only.
      </p>
      <pre>{note}</pre>
    </details>
  )
}

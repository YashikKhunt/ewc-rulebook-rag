import { useState } from 'react'
import { ClaimText } from './ClaimText'
import { Locator } from './Primitives'
import { copyPayload } from '../lib/claimText'

/**
 * The answer surface. Visual rank, top to bottom:
 *
 *     precedence notices → answer prose → provenance → disclosure
 *
 * Notices come FIRST because a precedence relationship changes how you must read
 * every sentence that follows.
 */
export function AnswerSurface({ turn, docs, onOpenSource, activeChunkId }) {
  return (
    <>
      <PrecedenceNotices findings={turn.findings} docs={docs} onOpenSource={onOpenSource} />
      <ClaimText
        answer={turn.answer}
        citationSpans={turn.citation_spans}
        outcome={turn.outcome}
        docs={docs}
        onOpenSource={onOpenSource}
        activeChunkId={activeChunkId}
      />
      <ProvenanceCaveat docs={docs} />
      {turn.citation_errors?.length > 0 && <DisclosureStrip errors={turn.citation_errors} />}
      <AnswerTools turn={turn} />
    </>
  )
}

/**
 * Copy carries the answer WITH its citations, plus the scope line and the corpus
 * fingerprint. A claim must not be able to leave this UI naked.
 *
 * There is deliberately no regenerate, retry, shorten, summarise or translate
 * control anywhere on a completed answer: each would fire a speculative model
 * call against a $5 budget, and would invite shopping for a nicer answer over a
 * compliance system.
 */
function AnswerTools({ turn }) {
  const [said, setSaid] = useState(null)
  return (
    <div className="answer-tools">
      <button
        className="btn-ghost"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(copyPayload(turn))
            setSaid('Copied with its citations, scope and corpus fingerprint.')
          } catch {
            setSaid('The browser refused clipboard access.')
          }
        }}
      >
        Copy answer with citations
      </button>
      {said && <span className="said" role="status">{said}</span>}
    </div>
  )
}

/* ── precedence notices ─────────────────────────────────────────────────── */

const CITE = /^(.*?) \((?:Article (.+?), )?p\.(\d+)\)$/

/** Split `resolve`'s "Book (Article X, p.N)" cite string for the locator button. */
function parseCite(text) {
  const match = CITE.exec(String(text ?? '').trim())
  if (!match) return null
  return { gameTitle: match[1], article: match[2] ?? '', page: Number(match[3]) }
}

function LocatorButton({ cite, docs, onOpenSource }) {
  const parsed = parseCite(cite)
  if (!parsed) return <span className="loc">{cite}</span>
  const doc = (docs ?? []).find(
    (d) =>
      d.game_title === parsed.gameTitle &&
      String(d.article ?? '') === String(parsed.article ?? '') &&
      Number(d.page) === parsed.page,
  )
  return (
    <button
      className="loc"
      disabled={!doc}
      title={doc ? 'Open this page' : 'This excerpt is not among the retrieved context'}
      onClick={() => doc && onOpenSource?.(doc)}
    >
      {cite}
    </button>
  )
}

/**
 * One notice per `resolve` finding. The UI RESTATES the relation from structured
 * fields; it does not re-render the `note` (which is prompt text written in
 * imperatives to the model) and it does not paraphrase the answer.
 */
function PrecedenceNotices({ findings, docs, onOpenSource }) {
  const list = findings ?? []

  // The ABSENCE of a precedence finding is itself information a compliance
  // reader needs. Silence would leave them guessing.
  if (list.length === 0) {
    return (
      <div className="notice n-none">
        <div className="eyebrow">No divergence found</div>
        <p>
          No divergence was found between the retrieved excerpts. Each rule below is stated
          from the book whose excerpt carries its text.
        </p>
      </div>
    )
  }

  return list.map((finding, index) => (
    <PrecedenceNotice
      key={`${finding.kind}-${index}`}
      finding={finding}
      docs={docs}
      onOpenSource={onOpenSource}
    />
  ))
}

export function PrecedenceNotice({ finding, docs, onOpenSource }) {
  const locs = (cites) => (
    <div className="locs">
      {cites.filter(Boolean).map((cite) => (
        <LocatorButton key={cite} cite={cite} docs={docs} onOpenSource={onOpenSource} />
      ))}
    </div>
  )

  switch (finding.kind) {
    case 'conflict':
      return (
        <div className="notice n-title">
          <div className="eyebrow">Game-title rule governs</div>
          <p>
            {finding.title} and {finding.global} state different rules on{' '}
            {finding.subject || 'this point'}. Under the precedence rule the game-title book
            governs.
          </p>
          {locs([finding.title, finding.global])}
        </div>
      )

    case 'primacy':
      return (
        <div className="notice n-global">
          <div className="eyebrow">Global Rulebook governs — express primacy</div>
          <p>The Global Rulebook asserts primacy in its own text on this point.</p>
          {/* Never asserted without the grounding text. */}
          <blockquote>“{finding.quote}”</blockquote>
          {locs([finding.cite])}
        </div>
      )

    case 'amended': {
      if (finding.incorporated) {
        return (
          <div className="notice n-amend">
            <div className="eyebrow">Current as amended</div>
            <p>
              Article {finding.article} was amended effective {finding.effective || 'an unstated date'}.
              The rulebook text below already contains the amended wording.
            </p>
            {finding.caveat && (
              <div className="caveat">
                <div className="eyebrow">The notice publishes its own caveat:</div>
                <q>{finding.caveat}</q>
              </div>
            )}
            {locs([finding.amendment, ...(finding.base ?? [])])}
          </div>
        )
      }
      if (finding.base_in_evidence) {
        return (
          <div className="notice n-amend">
            <div className="eyebrow">Superseded — base text predates the amendment</div>
            <p>The rulebook excerpt below predates this amendment and is not current.</p>
            {finding.caveat && (
              <div className="caveat">
                <div className="eyebrow">The notice publishes its own caveat:</div>
                <q>{finding.caveat}</q>
              </div>
            )}
            {locs([finding.amendment, ...(finding.base ?? [])])}
            {/* Log 009, verifier ruling 5: this path has NO LIVE INSTANCE. The
                one published amendment is `incorporated`, so this branch is
                unit-tested only and has never rendered against real data. It is
                marked here so a reader does not mistake it for exercised code. */}
            <p className="unexercised">
              Unexercised path: no live superseded amendment exists in this corpus (log 009,
              ruling 5). This rendering has not been proven end to end.
            </p>
          </div>
        )
      }
      return (
        <div className="notice n-amend">
          <div className="eyebrow">Amended — base article not retrieved</div>
          <p>The underlying article was not among the retrieved excerpts.</p>
          {locs([finding.amendment])}
        </div>
      )
    }

    case 'agreement':
      // Deliberately UNCOLOURED: agreement is the absence of a precedence
      // relation, and colouring it would inflate it.
      return (
        <div className="notice n-none">
          <div className="eyebrow">Books agree</div>
          <p>Both books state the same rule. No precedence question arises.</p>
          {locs([finding.title, finding.global])}
        </div>
      )

    case 'restatement':
      return (
        <div className="notice n-none">
          <div className="eyebrow">Title book reprints the Global rule</div>
          <p>
            This is the Global rule reprinted in the title book, not a title rule. It does not
            outrank the Global Rulebook.
          </p>
          {locs([finding.title, finding.global])}
        </div>
      )

    case 'cross_ref':
      return (
        <div className="notice n-global">
          <div className="eyebrow">Title book defers to Global by section number</div>
          <p>{finding.title} refers to {finding.global}; the Global article supplies the detail.</p>
          {locs([finding.title, finding.global])}
        </div>
      )

    case 'provenance':
      return (
        <div className="notice n-hatch">
          <div className="eyebrow">Externally published source</div>
          <p>
            {finding.cite} is published on a third-party host, not by the Esports World Cup.
          </p>
          {locs([finding.cite])}
        </div>
      )

    default:
      return null
  }
}

/**
 * Stricter and cheaper than `resolve`'s provenance finding: ANY doc marked
 * `external_host` is reported, whether or not the finding fired. That is a
 * metadata field being displayed, not an inference.
 */
function ProvenanceCaveat({ docs }) {
  const hosts = new Set()
  for (const doc of docs ?? []) {
    if (doc.external_host) {
      try {
        hosts.add(new URL(doc.source_url).host)
      } catch {
        hosts.add('a third-party host')
      }
    }
  }
  if (hosts.size === 0) return null
  return (
    <div className="notice n-hatch" style={{ marginTop: 18 }}>
      <div className="eyebrow">Third-party host</div>
      <p>
        {[...hosts].join(', ')} publishes some of the excerpts below. They are not published by
        the Esports World Cup, and their marked excerpts carry a hatched border.
      </p>
    </div>
  )
}

/**
 * The answer shipped despite a failed post-check (over-quoting, or a skipped
 * sibling article). Operator-grade detail, and the compliance user is exactly
 * the audience for it. Mono, hairline-boxed — NOT the alert hue: a disclosed
 * defect is the system being honest, not an error.
 */
export function DisclosureStrip({ errors }) {
  return (
    <div className="disclose" role="region" aria-label="Post-check disclosure">
      <div className="eyebrow">Shipped with a recorded defect</div>
      <p>This answer shipped with a known defect recorded by the post-check:</p>
      <ul>
        {errors.map((error) => (
          <li key={error}>— {error}</li>
        ))}
      </ul>
    </div>
  )
}

/* ── abstention and withholding ─────────────────────────────────────────── */

const ABSTENTION_EYEBROW = {
  uncited: 'No coverage in the retrieved text',
  no_evidence: 'No excerpt matched this query',
}

/**
 * AbstentionPanel — a SUCCESS state, designed as one.
 *
 * No colour, no icon, no red, no apology, no empty-state illustration. Structure
 * only. It sits at the same visual weight as an answered turn — same type size,
 * same rhythm, same margins — so a user scrolling the history cannot tell "did
 * not answer" from "failed" by silhouette, because one of those did not happen.
 *
 * The pipeline cannot tell you it abstained; a model abstention is prose. What
 * it CAN tell you mechanically is that the answer carries zero citations, which
 * by non-negotiable #3 means it is either an abstention or a defect — and in
 * both cases it must not be presented as a rule statement.
 */
export function AbstentionPanel({ turn }) {
  const eyebrowId = `abstain-${turn.turn_id}`
  return (
    <section className="panel" role="region" aria-labelledby={eyebrowId}>
      <div className="eyebrow" id={eyebrowId}>
        {ABSTENTION_EYEBROW[turn.outcome] ?? ABSTENTION_EYEBROW.uncited}
      </div>
      {/* Verbatim, via the same invariant-bound renderer as an answered turn. */}
      <ClaimText answer={turn.answer} citationSpans={[]} outcome={turn.outcome} docs={[]}
        className="body" />
      <div className="searched">
        Searched · {turn.scope}
        <br />
        {(turn.docs ?? []).length} excerpt{(turn.docs ?? []).length === 1 ? '' : 's'} retrieved
        and reviewed — they are listed below.
      </div>
    </section>
  )
}

/**
 * WithheldPanel — a THIRD state, distinct from both answered and abstained.
 *
 * Same structural family as AbstentionPanel so it does not read as an error, but
 * marked with a hatched left edge — the only place pattern is used in this
 * design, so it is unambiguous. The unvalidated draft is NEVER shown.
 */
export function WithheldPanel({ turn }) {
  const eyebrowId = `withheld-${turn.turn_id}`
  return (
    <section className="panel withheld" role="region" aria-labelledby={eyebrowId}>
      <div className="eyebrow" id={eyebrowId}>
        Answer withheld — failed the citation check
      </div>
      <ClaimText answer={turn.answer} citationSpans={[]} outcome="withheld" docs={[]}
        className="body" />
      {/* UI chrome, not pipeline output — visually distinguished from the
          verbatim answer text above it. */}
      <p className="gloss">
        Two drafts were produced. Both failed a mechanical check against the retrieved text, so
        neither is shown. This is the system refusing to show you something it could not verify.
      </p>
      {turn.citation_errors?.length > 0 && (
        <div className="failed">
          <div className="eyebrow">What failed</div>
          <ul>
            {turn.citation_errors.map((error) => (
              <li key={error}>— {error}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

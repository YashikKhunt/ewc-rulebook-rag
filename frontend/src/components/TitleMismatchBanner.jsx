/**
 * TitleMismatchBanner — this design's direct answer to log 009's open blocking
 * finding (B-2).
 *
 * B-2: asked about CS2 map veto while scoped to Valorant, the pipeline answers
 * "The map veto rules for CS2 are as follows…" citing VALORANT articles, 3/3
 * runs. The store filter is clean and the citations are correct; the PROSE
 * mislabels. The eval harness is structurally blind to it because every
 * cross-scope case is `generate: false`.
 *
 * This banner is client-side, deterministic, and costs nothing. It renders ABOVE
 * the answer and BEFORE it in the DOM, is `aria-live="assertive"` — the one
 * thing here worth interrupting for — and is visually heavier than any notice,
 * because it contradicts the answer.
 *
 * The last sentence is deliberate. B-2 is a PROSE defect, so the banner tells
 * the user not to trust the sentence over the citation.
 *
 * A UI mitigation is NOT a pipeline fix. This ships while B-2 is open, and the
 * point is to make the defect visible rather than to hide it.
 */
export function TitleMismatchBanner({ mentioned, routed, turn, onRescope }) {
  const names = mentioned.map((b) => b.game_title)
  const list =
    names.length === 1
      ? names[0]
      : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`

  const searchedTitles = [
    ...new Set((turn.docs ?? []).map((d) => d.game_title).filter(Boolean)),
  ]
  const target = mentioned[0]
  const unavailable = target && target.in_corpus === false

  return (
    <section
      className="mismatch"
      role="region"
      aria-live="assertive"
      aria-label="Warning: your question names a rulebook that was not searched"
    >
      <div className="eyebrow">Your question names a rulebook that was not searched</div>

      <p>
        You mentioned {list}. This answer was produced from{' '}
        {searchedTitles.length ? searchedTitles.join(' and ') : 'no rulebook at all'}.
      </p>

      <p>
        Rules stated below are not {list}’s, whatever the wording of the answer says.
      </p>

      {unavailable ? (
        <p className="mono" style={{ fontSize: 12 }}>
          {target.game_title} has no rulebook in this corpus
          {target.skip_reason ? ` — ${target.skip_reason}` : ''}. It cannot be searched.
        </p>
      ) : (
        // An explicit user action with its cost printed on it. Nothing here
        // fires automatically.
        <button
          className="btn-rescope"
          onClick={() => onRescope?.(turn.question, target.slug)}
          disabled={!target}
        >
          Ask again, scoped to {target?.game_title} — 1 model call, about $0.0004
        </button>
      )}
    </section>
  )
}

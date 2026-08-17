import { AuthorityBadge } from './Primitives'

/**
 * ScopeLedger — the most important component in this design.
 *
 * Which books were searched is a permanent element of every turn: in the
 * composer before the call, and here after it. It is the user's only defence
 * against log 009's B-2 (the answer prose can name a title whose rulebook was
 * not searched), so it is never collapsible, never truncated, and present in
 * EVERY result state including abstention and withholding.
 *
 * Each chip carries the book's PUBLISHED TITLE, never the slug. That matters
 * concretely: the slug `cod-mw3` publishes as "Call of Duty: Black Ops 7", and a
 * Warzone question routed there is one of B-2's reproductions. Showing the
 * published title makes that visible at a glance; showing the slug hides it.
 */
export function ScopeLedger({ turn, catalog }) {
  const docs = turn.docs ?? []

  const books = []
  for (const doc of docs) {
    const key = `${doc.game}:${doc.scope}`
    let entry = books.find((b) => b.key === key)
    if (!entry) {
      entry = {
        key,
        slug: doc.game,
        title: doc.game_title,
        authority: Number(doc.authority) || 0,
        scope: doc.scope,
        count: 0,
      }
      books.push(entry)
    }
    entry.count += 1
  }
  books.sort((a, b) => b.authority - a.authority || a.title.localeCompare(b.title))

  const routedBook = catalog?.find((b) => b.slug === turn.game)

  return (
    <section className="scope" aria-label="Rulebooks searched for this question">
      <div className="eyebrow">Searched</div>

      {books.length > 0 ? (
        <div className="books">
          {books.map((book) => (
            <span className="book" key={book.key}>
              <AuthorityBadge authority={book.authority} />
              <span>
                <span className="n">{book.title}</span>
                <span className="c mono"> · {book.count} excerpt{book.count === 1 ? '' : 's'}</span>
              </span>
            </span>
          ))}
        </div>
      ) : (
        <div className="mono negative">
          No excerpt was returned by the store for this query.
        </div>
      )}

      <div className="routed mono">
        {turn.forced_scope ? 'Scope set manually' : 'Routed automatically'}
        {turn.game ? (
          <> · {routedBook?.game_title ?? turn.game} ({turn.game})</>
        ) : (
          // The negative is STATED, not left to inference.
          <> · <span className="negative">no title rulebook — the EWC Global Rulebook 2026
            and published amendments only</span></>
        )}
      </div>
    </section>
  )
}

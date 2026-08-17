/**
 * The B-2 guard (frontend/DESIGN.md §4.4).
 *
 * Log 009's blocking finding: asked about CS2 map veto while scoped to Valorant,
 * the pipeline answers "The map veto rules for CS2 are as follows…" citing
 * VALORANT articles. The store filter is clean; the PROSE mislabels. This
 * detection is client-side, deterministic and costs nothing -- it compares the
 * question's own words against the aliases the SERVER derived from the corpus
 * and the manifest, and warns when the question names a book that was not
 * searched.
 *
 * It never re-routes, never re-runs anything, and never edits the answer. It
 * says, above the answer and before it in the DOM, that the sentence below may
 * be attributing one book's rules to another.
 */

/** Same normalisation the server applies when it derives aliases. */
export function normalise(text) {
  return String(text ?? '')
    .normalize('NFKD')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

/**
 * Every alias occurrence in the question, longest-match-wins.
 *
 * Longest-match matters concretely: "MLBB Women" contains "mlbb". Without the
 * containment rule a question about the Women's book would be read as naming
 * the men's book as well, and the banner would fire on a correct answer.
 */
export function alias_matches(question, catalog) {
  const haystack = ` ${normalise(question)} `
  const hits = []
  for (const book of catalog ?? []) {
    for (const alias of book.aliases ?? []) {
      if (!alias) continue
      const needle = ` ${alias} `
      let from = 0
      let at
      while ((at = haystack.indexOf(needle, from)) !== -1) {
        hits.push({ slug: book.slug, book, start: at, end: at + needle.length })
        from = at + 1
      }
    }
  }
  // Drop any hit strictly contained in a longer hit for a DIFFERENT book.
  return hits.filter(
    (hit) =>
      !hits.some(
        (other) =>
          other.slug !== hit.slug &&
          other.end - other.start > hit.end - hit.start &&
          other.start <= hit.start &&
          other.end >= hit.end,
      ),
  )
}

/**
 * Books the question names that were NOT searched for this turn.
 *
 * `searchedSlugs` comes from the turn's own `docs` -- what the store actually
 * returned -- not from the routed slug alone, so a book that WAS in evidence
 * never triggers the banner even if the router labelled the turn differently.
 *
 * The Global Rulebook is excluded: it is searched on every query, so it can
 * never be the book that was missed.
 */
export function detectTitleMismatch(question, turn, catalog) {
  if (!question || !catalog?.length) return { mentioned: [], routed: null }

  const searched = new Set((turn?.docs ?? []).map((d) => d.game).filter(Boolean))
  if (turn?.game) searched.add(turn.game)

  const seen = new Map()
  for (const hit of alias_matches(question, catalog)) {
    if (hit.slug === 'global') continue
    if (searched.has(hit.slug)) continue
    seen.set(hit.slug, hit.book)
  }

  const routed = catalog.find((b) => b.slug === turn?.game) ?? null
  return { mentioned: [...seen.values()], routed }
}

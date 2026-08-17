/**
 * Marks used everywhere a tier or a locator appears.
 *
 * COLOUR IS NEVER THE SOLE CARRIER. Every tier appearance pairs its colour with
 * a glyph (G / T / A) and a distinct border treatment, so the design survives
 * greyscale printing and all three common colour-vision deficiencies.
 */

const TIER = {
  0: { glyph: 'G', cls: 'b-g', name: 'Global Rulebook' },
  1: { glyph: 'T', cls: 'b-t', name: 'game-title rulebook' },
  2: { glyph: 'A', cls: 'b-a', name: 'published amendment' },
}

export function AuthorityBadge({ authority, size = 'md' }) {
  const tier = TIER[Number(authority) || 0] ?? TIER[0]
  return (
    <span
      className={`badge ${tier.cls} ${size === 'sm' ? 'sm' : ''}`}
      role="img"
      aria-label={`Authority: ${tier.name}`}
      title={tier.name}
    >
      {tier.glyph}
    </span>
  )
}

/**
 * The canonical mono locator. `page` is the PHYSICAL PDF page -- the UI never
 * converts to a printed page number, in either direction (DESIGN.md §6.1).
 * Where a chunk spans pages it reads `pp.11–12`.
 *
 * Renders absence AS ABSENCE: a chunk with no article number says so rather
 * than borrowing a plausible one.
 */
export function Locator({ gameTitle, article, page, pageEnd }) {
  const pages = pageEnd && pageEnd > page ? `pp.${page}–${pageEnd}` : `p.${page}`
  return (
    <span className="mono">
      {gameTitle}
      {' · '}
      {article ? `Art. ${article}` : <span className="absent">no article number</span>}
      {' · '}
      {pages}
    </span>
  )
}

export function Eyebrow({ children, id, className = '' }) {
  return (
    <div className={`eyebrow ${className}`} id={id}>
      {children}
    </div>
  )
}

/** A metadata value that is genuinely empty. Never defaulted, never guessed. */
export function Unstated() {
  return <span className="absent">unstated</span>
}

export function formatUsd(value, digits = 6) {
  return typeof value === 'number' ? `$${value.toFixed(digits)}` : '—'
}

export function formatWhen(iso) {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function formatDay(iso) {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

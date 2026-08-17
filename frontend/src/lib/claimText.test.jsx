/**
 * THE RENDER INVARIANT (frontend/DESIGN.md §4.1, MUST).
 *
 *   render(<ClaimText answer={A} citationSpans={S} />).textContent === A
 *
 * Byte for byte, for every fixture including the withheld and abstention texts.
 * The only transformation this client may make to a rule claim is wrapping a
 * substring ALREADY PRESENT in the answer with an anchor. If anyone ever adds
 * markdown rendering, smart quotes, a trim(), a truncation, a "read more", an
 * ellipsis or a highlight injection to ClaimText, this file fails.
 *
 * The fixtures below are real pipeline output shapes, including the two sentinel
 * texts from graph.py (the no-evidence return at the top of `answer`, and the
 * withheld return at the bottom).
 */

import { describe, it, expect } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'
import { ClaimText } from '../components/ClaimText'
import { usableSpans, paragraphRanges, claimSegments, copyPayload } from './claimText'
import { detectTitleMismatch, alias_matches } from './mismatch'

afterEach(cleanup)

const doc = (over = {}) => ({
  chunk_id: 'valorant:5.5.1:0',
  game: 'valorant',
  game_title: 'VALORANT',
  article: '5.5.1',
  page: 11,
  page_end: 11,
  authority: 1,
  scope: 'title',
  ...over,
})

/** Build spans the way server.py's graph.citation_spans does: real offsets. */
function spansFor(answer, locators) {
  return locators.map(({ text, chunk_id }) => {
    const start = answer.indexOf(text)
    if (start === -1) throw new Error(`fixture bug: ${text} not in answer`)
    return { start, end: start + text.length, text, locator: text, chunk_id }
  })
}

const FIXTURES = [
  {
    name: 'answered, one citation',
    answer:
      'Teams must complete the map veto no later than fifteen minutes before the ' +
      'scheduled start (VALORANT — Article 5.5.1, p.11).',
    cites: [{ text: 'VALORANT — Article 5.5.1, p.11', chunk_id: 'valorant:5.5.1:0' }],
  },
  {
    name: 'answered, several locators in one parenthetical',
    answer:
      'The higher seed elects first (VALORANT — Article 5.5.1, p.11; ' +
      'EWC Global Rulebook 2026 — Article 5.1.19, p.31). This governs.',
    cites: [
      { text: 'VALORANT — Article 5.5.1, p.11', chunk_id: 'valorant:5.5.1:0' },
      { text: 'EWC Global Rulebook 2026 — Article 5.1.19, p.31', chunk_id: 'global:5.1.19:0' },
    ],
  },
  {
    name: 'multi-paragraph with a blank line and a trailing newline',
    answer:
      'First paragraph, uncited.\n\nSecond paragraph (VALORANT — Article 5.5.1, p.11).\n',
    cites: [{ text: 'VALORANT — Article 5.5.1, p.11', chunk_id: 'valorant:5.5.1:0' }],
  },
  {
    name: 'graph.py no-evidence sentinel (abstention)',
    answer:
      'The retrieved rulebook text does not cover this. Searched: the VALORANT ' +
      'rulebook and the EWC Global Rulebook 2026. No excerpt matched.',
    cites: [],
  },
  {
    name: 'graph.py withheld sentinel, with its locator listing',
    answer:
      'The drafted answer could not be reconciled with the retrieved excerpts, so it ' +
      'has been withheld rather than shown.\n' +
      'Searched: the VALORANT rulebook and the EWC Global Rulebook 2026.\n' +
      'Unreconciled: unsupported citation (VALORANT — Article 9.9.9, p.99)\n' +
      'The excerpts actually retrieved were:\n' +
      '  (VALORANT — Article 5.5.1, p.11)\n  (EWC Global Rulebook 2026 — Article 3.2.3, p.17)',
    cites: [],
  },
  {
    name: 'em dashes, curly quotes and unicode preserved exactly',
    answer:
      'The rule reads “no later than fifteen (15) minutes” — and no rewording is ' +
      'permitted here (VALORANT — Article 5.5.1, p.11). Fees may be 5–10% of the prize.',
    cites: [{ text: 'VALORANT — Article 5.5.1, p.11', chunk_id: 'valorant:5.5.1:0' }],
  },
  {
    name: 'empty answer',
    answer: '',
    cites: [],
  },
  {
    name: 'whitespace-only answer',
    answer: '   \n\n  ',
    cites: [],
  },
  {
    name: 'answer that is only a citation',
    answer: '(VALORANT — Article 5.5.1, p.11)',
    cites: [{ text: 'VALORANT — Article 5.5.1, p.11', chunk_id: 'valorant:5.5.1:0' }],
  },
]

describe('render invariant: textContent === answer, byte for byte', () => {
  for (const fixture of FIXTURES) {
    it(fixture.name, () => {
      const spans = spansFor(fixture.answer, fixture.cites)
      const docs = [doc(), doc({ chunk_id: 'global:5.1.19:0', game: 'global',
        game_title: 'EWC Global Rulebook 2026', article: '5.1.19', page: 31, authority: 0,
        scope: 'global' })]
      const { container } = render(
        <ClaimText answer={fixture.answer} citationSpans={spans} outcome="answered" docs={docs} />,
      )
      expect(container.textContent).toBe(fixture.answer)
    })
  }

  it('holds when the outcome is uncited (no ⌀ markers are emitted at all)', () => {
    const answer = 'Paragraph one.\n\nParagraph two.'
    const { container } = render(
      <ClaimText answer={answer} citationSpans={[]} outcome="uncited" docs={[]} />,
    )
    expect(container.textContent).toBe(answer)
  })

  it('the ⌀ marker never adds characters even when it renders', () => {
    const answer = 'An uncited paragraph.\n\nA cited one (VALORANT — Article 5.5.1, p.11).'
    const spans = spansFor(answer, [
      { text: 'VALORANT — Article 5.5.1, p.11', chunk_id: 'valorant:5.5.1:0' },
    ])
    const { container } = render(
      <ClaimText answer={answer} citationSpans={spans} outcome="answered" docs={[doc()]} />,
    )
    expect(container.querySelectorAll('.uncited-mark').length).toBe(1)
    expect(container.textContent).toBe(answer)
  })

  it('holds when a span cannot be matched to a retrieved excerpt', () => {
    const answer = 'A claim (VALORANT — Article 9.9.9, p.99) with no backing excerpt.'
    const spans = spansFor(answer, [
      { text: 'VALORANT — Article 9.9.9, p.99', chunk_id: null },
    ])
    const { container } = render(
      <ClaimText answer={answer} citationSpans={spans} outcome="answered" docs={[]} />,
    )
    expect(container.querySelector('.citation.unresolved')).toBeTruthy()
    // The "not matched" warning is an EMPTY element labelled by aria-label, so
    // even while flagging a problem with the claim we do not alter one byte of
    // it. This assertion is the reason that marker is not plain sr-only text.
    expect(container.querySelector('.unresolved-mark').textContent).toBe('')
    expect(container.textContent).toBe(answer)
  })

  it('drops a span whose recorded text disagrees with the answer, rather than mangling it', () => {
    const answer = 'A claim (VALORANT — Article 5.5.1, p.11).'
    const bogus = [{ start: 9, end: 38, text: 'SOMETHING ELSE ENTIRELY', chunk_id: 'x' }]
    const { container } = render(
      <ClaimText answer={answer} citationSpans={bogus} outcome="answered" docs={[doc()]} />,
    )
    expect(container.textContent).toBe(answer)
    expect(container.querySelectorAll('.citation').length).toBe(0)
  })

  it('drops out-of-bounds and overlapping spans without losing a character', () => {
    const answer = 'Alpha bravo charlie delta.'
    const spans = [
      { start: -3, end: 5, chunk_id: 'a' },
      { start: 0, end: 5, chunk_id: 'b' },
      { start: 2, end: 8, chunk_id: 'c' }, // overlaps the one above
      { start: 20, end: 999, chunk_id: 'd' },
    ]
    const { container } = render(
      <ClaimText answer={answer} citationSpans={spans} outcome="answered"
        docs={[doc({ chunk_id: 'b' })]} />,
    )
    expect(container.textContent).toBe(answer)
  })
})

describe('paragraphRanges', () => {
  it('covers the whole string with no gaps and no overlaps', () => {
    for (const text of ['', 'a', 'a\n\nb', 'a\n\n\n\nb\n', '\n\n', 'a\nb\nc']) {
      const ranges = paragraphRanges(text)
      const rebuilt = ranges.map((r) => text.slice(r.start, r.end)).join('')
      expect(rebuilt).toBe(text)
      for (let i = 1; i < ranges.length; i += 1) {
        expect(ranges[i].start).toBe(ranges[i - 1].end)
      }
    }
  })
})

describe('claimSegments', () => {
  it('segments always concatenate back to the answer', () => {
    const answer = 'One (VALORANT — Article 5.5.1, p.11).\n\nTwo (EWC Global Rulebook 2026 — Article 3.2.3, p.17).'
    const spans = spansFor(answer, [
      { text: 'VALORANT — Article 5.5.1, p.11', chunk_id: 'a' },
      { text: 'EWC Global Rulebook 2026 — Article 3.2.3, p.17', chunk_id: 'b' },
    ])
    const rebuilt = claimSegments(answer, spans)
      .flatMap((p) => p.segments)
      .map((s) => answer.slice(s.start, s.end))
      .join('')
    expect(rebuilt).toBe(answer)
  })
})

describe('usableSpans', () => {
  it('returns [] for non-string answers and non-array spans', () => {
    expect(usableSpans(null, [])).toEqual([])
    expect(usableSpans('x', null)).toEqual([])
  })
})

describe('copyPayload — a claim must not leave this UI naked', () => {
  it('carries the answer verbatim plus scope and corpus fingerprint', () => {
    const turn = {
      answer: 'A rule (VALORANT — Article 5.5.1, p.11).',
      scope: 'the VALORANT rulebook and the EWC Global Rulebook 2026',
      corpus_fingerprint: 'e5819299',
      asked_at: '2026-08-14T10:52:04Z',
      citation_errors: [],
    }
    const out = copyPayload(turn)
    expect(out.startsWith(turn.answer)).toBe(true)
    expect(out).toContain('the VALORANT rulebook')
    expect(out).toContain('e5819299')
  })
})

/* ── the B-2 guard ───────────────────────────────────────────────────────── */

const CATALOG = [
  { slug: 'valorant', game_title: 'VALORANT', aliases: ['valorant'] },
  { slug: 'cs2', game_title: 'Counter-Strike 2',
    aliases: ['counter strike', 'counter strike 2', 'cs2', 'csgo'] },
  { slug: 'cod-mw3', game_title: 'Call of Duty: Black Ops 7',
    aliases: ['black ops', 'call of duty black ops 7', 'cod', 'mw3'] },
  { slug: 'warzone', game_title: 'Call of Duty: Warzone',
    aliases: ['call of duty warzone', 'warzone'] },
  { slug: 'mlbb', game_title: 'Mobile Legends: Bang Bang',
    aliases: ['mlbb', 'mobile legends', 'mobile legends bang bang'] },
  { slug: 'mlbb-women', game_title: 'Mobile Legends: Bang Bang Women',
    aliases: ['mlbb women', 'mobile legends bang bang women'] },
  { slug: 'global', game_title: 'EWC Global Rulebook 2026',
    aliases: ['ewc global rulebook 2026'] },
]

describe('TitleMismatchBanner detection — log 009 B-2, all three reproductions', () => {
  it('CS2 question scoped to Valorant', () => {
    const turn = { game: 'valorant', docs: [{ game: 'valorant' }, { game: 'global' }] }
    const { mentioned } = detectTitleMismatch('What are the CS2 map veto rules?', turn, CATALOG)
    expect(mentioned.map((b) => b.slug)).toEqual(['cs2'])
  })

  it('Warzone question scoped to cod-mw3 — warzone is its OWN book, so this is derivable', () => {
    const turn = { game: 'cod-mw3', docs: [{ game: 'cod-mw3' }, { game: 'global' }] }
    const { mentioned } = detectTitleMismatch('What are the Warzone loadout rules?', turn, CATALOG)
    expect(mentioned.map((b) => b.slug)).toEqual(['warzone'])
  })

  it("men's MLBB question scoped to mlbb-women", () => {
    const turn = { game: 'mlbb-women', docs: [{ game: 'mlbb-women' }, { game: 'global' }] }
    const { mentioned } = detectTitleMismatch("What are the men's MLBB roster rules?", turn, CATALOG)
    expect(mentioned.map((b) => b.slug)).toEqual(['mlbb'])
  })

  it('does NOT fire when the named book was actually searched', () => {
    const turn = { game: 'cs2', docs: [{ game: 'cs2' }, { game: 'global' }] }
    const { mentioned } = detectTitleMismatch('What are the CS2 map veto rules?', turn, CATALOG)
    expect(mentioned).toEqual([])
  })

  it('does NOT fire on the Global Rulebook, which is always searched', () => {
    const turn = { game: 'valorant', docs: [{ game: 'valorant' }, { game: 'global' }] }
    const { mentioned } = detectTitleMismatch(
      'What does the EWC Global Rulebook 2026 say about rosters?', turn, CATALOG)
    expect(mentioned).toEqual([])
  })

  it('longest match wins: "MLBB Women" does not also report the men\'s book', () => {
    const turn = { game: 'valorant', docs: [{ game: 'valorant' }] }
    const { mentioned } = detectTitleMismatch('MLBB Women roster rules?', turn, CATALOG)
    expect(mentioned.map((b) => b.slug)).toEqual(['mlbb-women'])
  })

  it('matches on word boundaries, not substrings', () => {
    const turn = { game: 'valorant', docs: [{ game: 'valorant' }] }
    // "codify" must not match the alias "cod".
    const { mentioned } = detectTitleMismatch('Does the rulebook codify penalties?', turn, CATALOG)
    expect(mentioned).toEqual([])
  })

  it('degrades gracefully when a book carries no aliases at all', () => {
    const bare = [{ slug: 'cs2', game_title: 'Counter-Strike 2', aliases: [] }]
    const turn = { game: 'valorant', docs: [{ game: 'valorant' }] }
    expect(detectTitleMismatch('CS2 veto?', turn, bare).mentioned).toEqual([])
    expect(alias_matches('anything', bare)).toEqual([])
  })

  it('returns nothing when the catalog has not loaded yet', () => {
    expect(detectTitleMismatch('CS2 veto?', { game: 'valorant', docs: [] }, []).mentioned)
      .toEqual([])
  })
})

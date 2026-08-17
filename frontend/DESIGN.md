# EWC Rulebook RAG — Front-end Design Specification

**Stage:** S6a (design). **Author:** `ewc-ux-designer`. **Implements:** `ewc-frontend-dev`.
**Designed against:** `graph.py` @ 1739 lines, `State` at `graph.py:1403`, logs `008`, `009`.
**Corpus state at time of writing:** 2,382 chunks / 25 books / 1 amendment / Chroma `ewc_rulebooks`.

This is a contract, not a mood board. Where it says MUST, it is implementable as written and
`ewc-verifier` will check it. Where it says FLAG, `graph.py` or the HTTP layer does not yet
expose what the client needs, and that gap is itemised in §7.

---

## 0. The premise this design is built on

The system has a **live, reproducible cross-title misattribution defect** (log 009, B-2, 3/3):
asked about CS2 map veto while scoped to Valorant, it answers *"The map veto rules for CS2 are
as follows…"* citing VALORANT articles. The store filter is clean; the **prose** mislabels.
The eval gate passes ~47% of runs (B-1). `grade` was never built, so there is no
retrieval-sufficiency check. Contract #2's `superseded` path has no live instance.

A UI that looks authoritative over that system is a design defect. So the organising principle
of this design is:

> **The interface's job is to keep the user's own judgement in the loop, not to replace it.**
> Everything the pipeline *knows* is shown. Everything it *asserts* is shown next to the
> evidence it was built from, and next to a permanent statement of what was searched.

Three consequences that shape every screen:

1. **Scope is never off-screen.** Which books were searched is a persistent element of every
   turn, in the composer *before* the call and in the result *after* it. It is the user's only
   defence against B-2 today.
2. **Colour means authority. Structure means state.** Saturated colour is reserved *exclusively*
   for the three authority tiers. Abstention, withholding, and disclosure are expressed through
   rules, hatching and letterspaced labels — never through a red box. An abstention must not be
   able to *look* like a failure, and an amendment must not be able to look like an error.
3. **The client never re-renders a claim.** The answer string is displayed verbatim. The only
   permitted transformation is wrapping citation substrings that are already present in an
   anchor. See the render invariant in §4.1 — it is mechanically testable.

---

## 1. Information architecture

Three zones. Two persistent, one summoned.

```
┌──────────────┬───────────────────────────────────────┬─────────────────────┐
│              │  CorpusBar        (persistent, 40px)  │                     │
│  HistoryRail ├───────────────────────────────────────┤   SourceViewer      │
│  (persistent)│                                       │   (drawer, summoned)│
│   280px      │  ConversationPane   (scrolling)       │   46vw, min 520px   │
│              │    TurnCard                           │                     │
│              │      QuestionBlock                    │   opens BESIDE the  │
│              │      ScopeLedger        ← always      │   answer, never     │
│              │      TitleMismatchBanner  (cond.)     │   over it           │
│              │      AnswerSurface                    │                     │
│              │      ContextSurface                   │                     │
│              ├───────────────────────────────────────┤                     │
│  BudgetLedger│  Composer         (persistent, fixed) │                     │
└──────────────┴───────────────────────────────────────┴─────────────────────┘
```

**Persistent:** `HistoryRail`, `CorpusBar`, `Composer`, `BudgetLedger`.
**Transient:** `SourceViewer` (drawer), toasts (errors only).
**Scrolling:** `ConversationPane` only. The composer never moves.

The `SourceViewer` is a **drawer, not a modal**. This is load-bearing: the whole point of
feature 3 is to check a claim against its page, which requires seeing both at once. When it
opens, `ConversationPane` narrows; it does not dim, blur, or become inert.

**Responsive:** below 1100px the `SourceViewer` becomes a full-height sheet with a persistent
"back to answer" control that returns you to the exact `ContextCard` you opened it from.
Below 860px `HistoryRail` collapses to an icon rail that expands as an overlay.

### 1.1 What a conversation is — and is not

`graph.py` has **no conversation memory**. `ask()` builds a fresh state from a single question
every time. The UI MUST NOT imply otherwise:

- Turns are **independent records**, rendered as stacked documents, not as chat bubbles.
- There is no "continue the thread" affordance, no pronoun-resolving follow-up, no
  "based on your last question".
- A conversation is a **folder of related enquiries**, and the UI says exactly that in the
  empty state. Renaming it is allowed; threading it is not.

This is not a limitation to hide. Presenting independent lookups as a conversation with memory
would misrepresent what the system did.

---

## 2. Every state, enumerated

States divide into **request lifecycle** (2.1), **result** (2.2), **overlay** (2.3) and
**shell** (2.4). Overlay states compose with result states; the others are exclusive.

### 2.1 Request lifecycle

Each phase renders in `PipelineTrace` — a single-line, four-step progress indicator that names
the *actual node*, because the node names are meaningful to this user and a generic spinner is
a wasted opportunity to teach what the system does.

| State | Trigger | What the user sees |
|---|---|---|
| `idle` | no request in flight | `PipelineTrace` absent. Composer enabled. |
| `routing` | node `route` entered | `ROUTE ▸ retrieve ▸ resolve ▸ answer` — first step active, mono, letterspaced. Sub-label: *"choosing which rulebook to search"*. **Skipped entirely when the user set an explicit scope** — say so: *"scope set manually; router not called"*. |
| `retrieving` | node `retrieve` | Step 2 active. Sub-label names the resolved scope the moment it is known: *"searching VALORANT and the EWC Global Rulebook 2026"*. `ScopeLedger` renders here — **before** the answer exists. |
| `resolving` | node `resolve` | Step 3 active. Sub-label: *"comparing articles across rulebooks"*. |
| `generating` | node `answer`, first call | Step 4 active. Sub-label: *"drafting"*. |
| `verifying` | post-check running | Step 4 still active, sub-label changes to *"checking every citation against the retrieved text"*. A distinct sub-phase because it is distinctive and because it explains latency honestly. |
| `regenerating` | bounded retry fired | Sub-label: *"first draft failed a check — one correction attempt"*. This is the pipeline's single bounded retry (`graph.py:1619`), and disclosing it is more honest than hiding a 2× latency spike. |

`PipelineTrace` steps that are complete render as a filled square; the active one pulses at
0.9s (suppressed under `prefers-reduced-motion`, which uses a static filled marker plus the
text label). There is **no skeleton shimmer** — the trace *is* the loading state, and it carries
information.

**Phase events require streaming from the server (FLAG §7.10).** If the dev cannot get per-node
events in the first pass, degrade to: `routing` → `working` → result, with the `working`
sub-label listing all four node names. Do **not** fake phase timing with `setTimeout`.

### 2.2 Result states

Derived from `response.outcome` (FLAG §7.1) — **never** by the client pattern-matching answer
prose. Client-side regex over rule text is exactly the "re-render a claim" the role forbids, and
it is fragile against a model-authored abstention.

| `outcome` | Server derivation (from code that exists) | Presentation |
|---|---|---|
| `answered` | not withheld, `docs` non-empty, `cited_locators(answer)` non-empty | `AnswerSurface`. Prose in Literata, citations welded inline. |
| `uncited` | not withheld, `docs` non-empty, `cited_locators(answer)` **empty** | `AbstentionPanel`. See below. |
| `no_evidence` | `docs` empty → `graph.py:1564` early return | `AbstentionPanel`, variant `no-retrieval`. |
| `withheld` | `graph.py:1638` branch taken | `WithheldPanel`. |

**Why `uncited` and not `abstained`.** The pipeline cannot tell you it abstained — a model
abstention is prose. But non-negotiable #3 says every rule claim carries a citation. Therefore an
answer with **zero** citations either is an abstention or is a bug, and in **both** cases it must
not be presented as a rule statement. `cited_locators()` already exists at `graph.py:341` and is
purely mechanical. This is a fact the system genuinely has; "abstained" is not.

#### `AbstentionPanel` — a success state, designed as one

Full content width. **No colour, no icon, no red, no apology, no empty-state illustration.**
Structure only: a 1px `--rule-strong` hairline above and below, generous internal space.

```
  ─────────────────────────────────────────────────────────
   NO COVERAGE IN THE RETRIEVED TEXT          ← eyebrow, mono, letterspaced
                                                 --ink-2, NOT an alert colour
   [answer text, verbatim, Literata 16/1.55]

   Searched · VALORANT · EWC Global Rulebook 2026   ← ScopeLedger, full weight
   8 excerpts retrieved and reviewed → open the context below
  ─────────────────────────────────────────────────────────
```

It sits at the **same visual weight** as an answered turn — same type size, same rhythm, same
margins. A user scrolling the history must not be able to tell "did not answer" from "failed" by
silhouette, because one of those did not happen. The `ContextSurface` renders below it exactly as
it would for an answered turn: the excerpts were retrieved and paid for, and seeing what *was*
found is often the most useful part of an abstention.

Eyebrow copy by variant:
- `uncited` → `NO COVERAGE IN THE RETRIEVED TEXT`
- `no_evidence` → `NO EXCERPT MATCHED THIS QUERY`

#### `WithheldPanel` — a third state, distinct from both

Same structural family as `AbstentionPanel` — so it does not read as an error — but marked with a
**4px hatched left edge** (`repeating-linear-gradient(135deg, --ink-3 0 2px, transparent 2px 6px)`).
Hatching is the only place in the design that pattern is used, so it is unambiguous.

```
  ┃╱ ANSWER WITHHELD — FAILED THE CITATION CHECK
  ┃╱
  ┃╱  [withheld text verbatim: "The drafted answer could not be
  ┃╱   reconciled with the retrieved excerpts…" + Searched: + Unreconciled:
  ┃╱   + the locator listing]
  ┃╱
  ┃╱  Two drafts were produced. Both failed a mechanical check against the
  ┃╱  retrieved text, so neither is shown. This is the system refusing to
  ┃╱  show you something it could not verify.        ← UI gloss, --ink-2
  ┃╱
  ┃╱  What failed:  unsupported citation (VALORANT — Article 5.5.1, p.11)
  ┃╱                                        ← from citation_errors, mono
```

The final gloss paragraph is **UI chrome, not pipeline output**, and MUST be visually
distinguished (Archivo 14, `--ink-2`) from the verbatim answer text (Literata 16, `--ink`). The
`citation_errors` array renders as a mono list — it is operator-grade detail and the compliance
user is exactly the audience for it.

`ContextSurface` still renders. The excerpts are trustworthy; only the prose built from them was
not.

### 2.3 Overlay states — compose with any result state

| State | Trigger | Presentation |
|---|---|---|
| `title-mismatch` | client-side, zero cost: question text mentions a known title/alias that is **not** `response.game` | `TitleMismatchBanner` above `AnswerSurface`. See §4.4. |
| `disclosed` | `citation_errors` non-empty **and** `outcome != withheld` | `DisclosureStrip` below `AnswerSurface`. The answer shipped despite a failed check (over-quoting, or a skipped sibling article — `graph.py:1627`). Mono, hairline-boxed, `--ink-2`. Copy: *"This answer shipped with a known defect recorded by the post-check:"* + the errors. |
| `stale` | `response.corpus_fingerprint` ≠ current | `StaleStamp` on the turn. See §2.4. |
| `provenance` | any doc has `external_host: true` | `ProvenanceCaveat` in `AnswerSurface`; hatched border on the relevant `ContextCard`. See §4.3. |

### 2.4 Shell states

| State | Presentation |
|---|---|
| `history-empty` | `HistoryRail` shows, in Archivo 13 `--ink-3`: *"No saved enquiries. Each conversation is a folder of independent lookups — the system does not carry context between questions."* No illustration, no "Get started!" button. |
| `conversation-empty` | `ConversationPane` shows the corpus at rest: the 25 books as a quiet mono list with chunk counts, the amendment count, the corpus fingerprint, and one line: *"Ask about a rule. Answers cite the rulebook, article and PDF page they came from."* This doubles as a corpus inventory, which is genuinely useful and costs nothing. |
| `history-loading` | Rail rows render as 1px hairlines at their eventual height. No shimmer. |
| `stale-turn` | A recorded turn whose `corpus_fingerprint` ≠ the live one gets a `StaleStamp`: mono eyebrow *"RECORDED AGAINST AN EARLIER CORPUS — 2026-08-11"*, and the turn's text drops to `--ink-2`. It is **never** silently re-run, **never** hidden, and there is no "refresh this answer" button (that would be a speculative model call). |
| `error` | `ErrorPanel` inline where the turn would be. This is the **only** place the alert hue is permitted. Distinguish: `no-api-key`, `corpus-missing` (`chunks.pkl` absent — links the `python index.py` command), `upstream-refused` (OpenAI error), `network`. Each names the failure and the fix. A `Retry` control is permitted here **only** because no model call was completed, so retrying does not duplicate spend — and it MUST say so: *"the previous attempt did not complete a model call"*. |
| `budget-refused` | The server declined to spend. `BudgetLedger` goes to full weight, states the ceiling and the spend, and the composer disables with an inline explanation. Not a toast — this is a standing condition. |

---

## 3. Component inventory

Names are binding. Data contracts reference `§7` response shapes.

### 3.1 Shell

**`AppShell`** — three-zone grid, theme provider, keyboard scope manager.
Props: `{ theme: 'light'|'dark'|'system' }`.

**`CorpusBar`** — persistent 40px strip. Left: `EWC RULEBOOK RAG` wordmark (Archivo 600,
letterspaced). Centre: `CorpusFingerprint`. Right: theme toggle.
Props: `{ corpus: CorpusInfo }`.
States: `ok`, `mismatch` (client's cached fingerprint ≠ server's → shows a mono `Δ` and a
tooltip naming both).

**`CorpusFingerprint`** — mono, 12.5px, tabular. Renders `2382 chunks · 25 books · 1 amendment ·
e5819299`. The short sha is a **link** to a popover listing every book, its chunk count,
`version` and `effective_date`. Renders `unstated` — not a guess, not blank — where those are
empty, which is the case for 24 of 25 books. Do not invent a version.
Props: `{ chunks: number, books: number, amendments: number, fingerprint: string, catalog: BookInfo[] }`.

**`BudgetLedger`** — bottom of `HistoryRail`. Mono. `$0.5681 / $5.00` with a 3px hairline meter.
Below: `this turn $0.000412` after a completed request.
Props: `{ spentUsd, ceilingUsd, lastTurnUsd?, refused: boolean }`.
States: `ok`, `warn` (≥80% — meter thickens to 4px, no colour change), `refused`.

### 3.2 History

**`HistoryRail`** — persistent left column. Header: `ENQUIRIES` eyebrow + `New` button.
Props: `{ conversations: ConversationSummary[], activeId, onSelect, onCreate, onRename, onDelete }`.

**`HistoryEntry`** — one row. Two lines: the conversation title (Archivo 14, truncated at two
lines) and a mono meta line `4 turns · 12 Aug · valorant, global`. The scope summary is the third
place scope appears, deliberately.
Props: `{ id, title, turnCount, updatedAt, scopes: string[], stale: boolean, active: boolean }`.
States: `default`, `active` (2px `--ink` left rule, raised paper), `hover`, `focus-visible`,
`stale` (mono `Δ` marker), `renaming` (inline text input).
Delete requires a confirm step **inside the row** — no modal for a destructive-but-recoverable
action, and the row states what is lost: *"Deletes 4 recorded answers. Not recoverable."*

### 3.3 The turn

**`TurnCard`** — one question→result record. Not a bubble. A document block separated from its
neighbours by a full-bleed 1px `--rule` and 48px of space.
Props: `{ turn: Turn, corpusFingerprint: string, onOpenSource }`.

**`QuestionBlock`** — the question, Literata 22/1.25, `--ink`. Above it a mono meta line:
`14 Aug 2026, 10:52 · gpt-4o-mini · $0.000412 · 4.1s`. Below it, if the user forced a scope,
a mono tag `SCOPE SET MANUALLY: valorant`.
Props: `{ question, askedAt, model, costUsd, durationMs, forcedScope?: string }`.

**`ScopeLedger`** — **the most important component in this design.**
Renders immediately below `QuestionBlock`, present in *every* result state, never collapsible,
never truncated.

```
  SEARCHED   ⟨T⟩ VALORANT          ⟨G⟩ EWC Global Rulebook 2026
             ROUTED AUTOMATICALLY · 6 excerpts       · 2 excerpts
```

- Each book is a chip carrying its `AuthorityBadge` and its **published `game_title`**, never
  the slug. This matters concretely: the slug `cod-mw3` publishes as *"Call of Duty: Black Ops
  7"*, and log 009's B-2 reproduction is a Warzone question routed to `cod-mw3`. Showing the
  published title makes that visible at a glance; showing the slug hides it.
- Excerpt counts come from `docs`, grouped by `game`.
- `ROUTED AUTOMATICALLY` / `SCOPE SET MANUALLY` is stated explicitly.
- When `game` is `null`: `SEARCHED  ⟨G⟩ EWC Global Rulebook 2026 + published amendments —
  NO TITLE RULEBOOK`. The negative is stated, not left to inference.

Props: `{ scope: string, game: string|null, forced: boolean, books: {slug, title, authority, count}[] }`.

**`PipelineTrace`** — §2.1. Props: `{ phase, scopeLabel?, retried: boolean, routerSkipped: boolean }`.

### 3.4 Answer surface

**`AnswerSurface`** — §4.
Props: `{ answer: string, citationSpans: CitationSpan[], outcome, findings: Finding[], onOpenSource }`.

**`ClaimText`** — renders `answer` verbatim with citation spans wrapped. Enforces the render
invariant (§4.1).

**`CitationChip`** — inline anchor. §4.2.
Props: `{ locator: string, chunkId: string, gameTitle, article, page, pageEnd, onOpen }`.
States: `default`, `hover`, `focus-visible`, `active` (its `ContextCard`/viewer page is open —
persistent 2px underline in the tier colour), `unresolved`.

**`PrecedenceNotice`** — one card per `resolve` finding. §4.3.
Props: `{ finding: Finding, onOpenSource }`.
Variants: `conflict`, `primacy`, `amended`, `agreement`, `restatement`, `cross_ref`, `provenance`.

**`DisclosureStrip`** — §2.3. Props: `{ errors: string[] }`.

**`AbstentionPanel`** / **`WithheldPanel`** — §2.2.
Props: `{ answer: string, scope: string, variant, citationErrors?: string[] }`.

**`TitleMismatchBanner`** — §4.4.
Props: `{ mentioned: BookInfo[], routed: BookInfo|null, onRescope }`.

### 3.5 Context surface

**`ContextSurface`** — §5. Props: `{ docs: Doc[], ranks: Record<string,number>, accountable: string[], order: 'read'|'relevance', onOpenSource }`.

**`ContextCard`** — one retrieved chunk. §5.2.
Props: `{ doc: Doc, fusedRank: number, readOrder: number, accountable: boolean, expanded, active, onOpen }`.
States: `collapsed`, `expanded`, `accountable` (auto-expanded, marked), `active` (open in viewer),
`external` (hatched border), `unopenable` (no local PDF — §6.4).

**`AuthorityBadge`** — the tier mark, used everywhere a tier appears. 18px square, mono glyph.
Props: `{ authority: 0|1|2, scope: string, size?: 'sm'|'md' }`.
Renders `G` / `T` / `A` + tier colour + tier border treatment. **Never colour alone** — the glyph
and the border treatment carry the same information for colour-blind and greyscale-print users.

**`Locator`** — the canonical mono locator, used in cards, chips and the viewer.
`VALORANT · Art. 5.5.1 · p.11` (or `pp.11–12` when `page_end > page`).
Props: `{ gameTitle, article?, page, pageEnd? }`.

### 3.6 Source

**`SourceViewer`** — right drawer. §6.
Props: `{ doc: Doc, page: number, sourceInfo: SourceInfo, onClose, onPage }`.
States: `loading`, `ready`, `page-out-of-range`, `unavailable` (no local PDF), `error`.

**`PageProvenanceStrip`** — §6.2. The honest page-numbering disclosure.
Props: `{ physicalPage, pageCount, footerLabel?: string|null, footerAmbiguous: boolean, gameTitle }`.

**`SourceOriginNote`** — states which copy of the PDF you are reading. §6.3.
Props: `{ sha256, indexedAt, cdnUrl, external: boolean }`.

### 3.7 Composer

**`Composer`** — fixed bottom of `ConversationPane`. Textarea (Literata 16, grows to 6 lines),
`ScopeSelector`, `PreflightEstimate`, and two submit controls.
Props: `{ onAsk, onSearchOnly, disabled, catalog, budget }`.

**`ScopeSelector`** — `Auto (router decides)` | one of 25 titles | `Global only`. Mono listbox,
type-ahead. Choosing a title **skips the router entirely** (`graph.py:1457`), which is both
cheaper and more predictable, and the selector says so: *"Setting a scope skips the router — one
fewer model call, and no chance of a routing error."*

**`PreflightEstimate`** — mono, above the submit row, updates on scope change **without any
network call**: `≈ 2 model calls · ≈ $0.0004 · searches VALORANT + Global`. With a manual scope:
`≈ 1 model call`.

**Two submit controls, deliberately:**
- `Ask` (primary) — full pipeline.
- `Search only` (secondary) — `route → retrieve → resolve`, **no generation**. Renders
  `ScopeLedger` + `ContextSurface` with no `AnswerSurface`. With a manual scope this fires
  **zero chat completions** (embedding only, ~$0.0002). For a compliance user who wants to read
  the articles themselves, this is often the better tool, and it makes the cheap path the
  *visible* path rather than a hidden flag.

---

## 4. The answer surface

Visual rank, top to bottom: **precedence notices → answer prose → provenance → disclosure**.
Notices come *first* because a precedence relationship changes how you must read every sentence
that follows.

### 4.1 The render invariant — MUST

`ClaimText` renders `response.answer` verbatim. The **only** permitted DOM transformation is
wrapping substrings that are already present in the string with `<a class="citation">`.

`ewc-frontend-dev` MUST ship this test:

```
render(<ClaimText answer={A} citationSpans={S} />).textContent === A
```

Byte-for-byte, for every fixture including the withheld and abstention texts. No markdown
rendering that alters characters, no smart quotes, no `trim()`, no truncation, no "read more",
no ellipsis, no sentence re-flow, no highlight injection. Line breaks in the source string are
preserved with `white-space: pre-wrap`.

There is **no** UI affordance anywhere that edits, softens, summarises, re-generates, translates
or shortens a rule claim or a citation. Copy-to-clipboard copies the answer **with** citations
and appends the scope line and corpus fingerprint — a claim must not be able to leave this UI
naked.

### 4.2 Citations — welded to their claims

A `CitationChip` is an **inline `<a>` inside the paragraph text**, never absolutely positioned,
never floated, never a superscript marker with a footnote elsewhere. It renders the parenthetical
exactly as the pipeline wrote it, in IBM Plex Mono 12.5 with `--tier` colour, on a 1px
`--tier` bottom border that thickens to 2px on hover/focus.

- It never wraps mid-locator (`white-space: nowrap` on the chip, the paragraph wraps around it).
- Clicking opens the `SourceViewer` at that chunk's page **and** scrolls its `ContextCard` into
  view and expands it. One click, both surfaces.
- A parenthetical carrying several locators (`;`-separated, the format the prompt produces —
  `graph.py:1281`) renders as one bracket with individually clickable segments; the `(` `)` and
  `;` are plain text so the sentence still reads correctly to a screen reader.
- **`unresolved` state:** if a citation span cannot be matched to a `chunk_id`, the chip renders
  with a **dotted** underline and no link, plus a mono marker `⚠ not matched to a retrieved
  excerpt`. It is never silently unstyled. (This should be impossible when
  `citation_errors` is empty, but the pipeline's own post-check is the thing that can be wrong,
  and the UI should not conceal a disagreement between them.)

**Uncited claims are marked, not tidied.** Where `outcome === 'answered'` and a paragraph of
`answer` contains no citation span, `ClaimText` renders a `⌀` marker in `--ink-3` at the end of
that paragraph, with an accessible label *"no citation on this passage"*. By non-negotiable #3
that is a defect, and the UI's job is to surface defects, not to make the page look clean. This
marker is presentational only — it adds no characters to `textContent` (use `::after` with
`content` on a `data-` attribute, or an `aria-hidden` sibling outside the text node measured by
the invariant test).

### 4.3 Precedence, amendment and provenance notices

One `PrecedenceNotice` per entry in `response.findings` (from `state.conflicts`). Each is a
bordered block, 3px left border in the colour of the **governing** tier, mono eyebrow, one line
of plain-language relation, and the two `Locator`s as buttons.

The UI **restates the relation from structured fields** — it does not re-render `note`, and it
does not paraphrase the answer. The relation labels are fixed strings owned by this design:

| kind | Eyebrow | Border | Body |
|---|---|---|---|
| `conflict` | `GAME-TITLE RULE GOVERNS` | title (ochre) | *"{title} and {global} state different rules on {subject}. Under the precedence rule the game-title book governs."* Both locators shown, title first. |
| `primacy` | `GLOBAL RULEBOOK GOVERNS — EXPRESS PRIMACY` | global (slate) | *"The Global Rulebook asserts primacy in its own text on this point."* + the `quote` field in Literata italic, in quotation marks. This is the human's express-Global-primacy exception to #1 and it is the **only** case where Global outranks a title, so it gets its own eyebrow and its own colour, and it quotes the grounding text — never asserted without it. |
| `amended` (`incorporated: true`) | `CURRENT AS AMENDED` | amendment (vermilion) | *"Article {article} was amended effective {effective}. The rulebook text below already contains the amended wording."* + `caveat` in a nested hairline box, verbatim, attributed: *"The notice publishes its own caveat:"*. |
| `amended` (`incorporated: false`, base in evidence) | `SUPERSEDED — BASE TEXT PREDATES THE AMENDMENT` | amendment | *"The rulebook excerpt below predates this amendment and is not current."* **The base `ContextCard`(s) named in `base` are additionally stamped `SUPERSEDED` and their body text renders at 70% opacity with a hatched left edge.** ⚠ This path has **no live instance** (log 009, ruling 5) — build it, and mark it in code as unexercised. |
| `amended` (no base in evidence) | `AMENDED — BASE ARTICLE NOT RETRIEVED` | amendment | *"The underlying article was not among the retrieved excerpts."* |
| `agreement` | `BOOKS AGREE` | neutral `--rule-strong` | *"Both books state the same rule. No precedence question arises."* Deliberately **uncoloured** — agreement is the absence of a precedence relation, and colouring it would inflate it. |
| `restatement` | `TITLE BOOK REPRINTS THE GLOBAL RULE` | neutral | *"This is the Global rule reprinted in the title book, not a title rule. It does not outrank the Global Rulebook."* |
| `cross_ref` | `TITLE BOOK DEFERS TO GLOBAL BY SECTION NUMBER` | global | *"{title} refers to {global}; the Global article supplies the detail."* |
| `provenance` | `EXTERNALLY PUBLISHED SOURCE` | hatched, neutral | *"{cite} is published on a third-party host, not by the Esports World Cup."* |

**When `findings` is empty**, render a single `PrecedenceNotice` variant `none`, neutral border:
*"No divergence was found between the retrieved excerpts. Each rule below is stated from the book
whose excerpt carries its text."* — because the *absence* of a precedence finding is itself
information a compliance reader needs, and silence would leave them guessing.

**Apex / `external_host`.** The 161 `apex` chunks come from `algs.ea.com`, not the EWC CDN, and
`resolve` emits a `provenance` finding only when a Global group is also present. The UI is
stricter and cheaper: **any** `ContextCard` whose doc has `external_host: true` gets a hatched
border and a mono tag `THIRD-PARTY HOST · algs.ea.com`, regardless of whether the finding fired.
That is a metadata field being displayed, not an inference.

### 4.4 `TitleMismatchBanner` — the B-2 guard

**This is the design's direct answer to the open blocking finding.** It is client-side,
deterministic, and costs nothing.

Trigger: the question string mentions a book in `catalog` (by `game_title`, slug, or a listed
alias) whose slug ≠ `response.game`, **and** that book is not in `ScopeLedger`.

Renders **above** `AnswerSurface`, full width, hatched top and bottom rules, `--ink` text at
body weight — visually heavier than any notice, because it contradicts the answer:

```
  ╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱
   YOUR QUESTION NAMES A RULEBOOK THAT WAS NOT SEARCHED

   You mentioned Counter-Strike 2. This answer was produced from
   VALORANT and the EWC Global Rulebook 2026.

   Rules stated below are not Counter-Strike 2's, whatever the wording
   of the answer says.

   [ Ask again, scoped to Counter-Strike 2 ]   ← re-runs; cost shown on the button
  ╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱
```

The last sentence is deliberate. B-2 is a *prose* defect — the citations are correct and the
retrieval is clean — so the banner must tell the user not to trust the sentence over the
citation. The re-ask button is an explicit user action with its cost printed on it; nothing
fires automatically.

**Requires an alias map (FLAG §7.9).** "Warzone" cannot be derived from the corpus of the
`cod-mw3` book, whose `game_title` is *"Call of Duty: Black Ops 7"* — and that exact pair is one
of log 009's three B-2 reproductions. Without aliases the banner catches the CS2/Valorant case
but misses the Warzone case. This needs a human ruling (§9).

---

## 5. The context surface

### 5.1 Frame

Header row: `RETRIEVED CONTEXT · 8 EXCERPTS` eyebrow, and a segmented control:

- **`As the model read them`** (default) — `docs` order as returned. This is
  authority-descending with RRF order stable within each tier (`graph.py:245`). It is the
  default because it is *what actually happened*.
- **`By relevance`** — sorted by `ranks[chunk_id]` ascending (the pre-authority-sort fused rank).

Both orders are already in the response. Neither triggers a request.

The whole surface is **expanded by default**. It is a mandatory feature and the evidence base for
a compliance decision; hiding it behind a "Sources ▸" accordion would be a dark pattern here.

### 5.2 `ContextCard`

```
┌─────────────────────────────────────────────────────────────────┐
│ ⟨T⟩  VALORANT                              READ #1 · RANK 1  ★  │  ← header, always visible
│      Art. 5.5.1 · p.11                                          │
│      5 MATCH PROCEDURES › 5.5 Map Selection › 5.5.1 Veto        │  ← heading_path
│─────────────────────────────────────────────────────────────────│
│  Teams shall complete the map veto no later than fifteen        │  ← body, 3 lines collapsed
│  minutes before the scheduled start time. The higher-seeded     │
│  team elects…                                             ▾ more│
│─────────────────────────────────────────────────────────────────│
│  v unstated · effective unstated · 1,129 chars · chunk 1 of 2   │  ← footer, mono, --ink-3
│  ▸ OPEN PDF PAGE 11                                             │  ← the feature-3 target
└─────────────────────────────────────────────────────────────────┘
   3px left border in the authority-tier colour
```

Fields, all straight from chunk metadata — nothing invented:

| Shown | Source |
|---|---|
| Tier badge | `authority` + `scope` |
| Book name | `game_title` (published name, never the slug) |
| Locator | `article`, `page`, `page_end` |
| Section trail | `heading_path`, `part` (prefixed `Appendix B §` when `part` is set) |
| Body | `page_content` — **verbatim**, including the `[game · Article n — heading]` context label the chunker prepends. Do not strip it; it is what was embedded. |
| Read order | position in `docs` |
| Fused rank | `ranks[chunk_id]` |
| Accountable | `chunk_id ∈ accountable` → `★` + auto-expanded |
| Version / effective | `version`, `effective_date` → literal `unstated` when empty (true for 24 of 25 books) |
| Size | `n_chars`, `chunk`, `chunk_of` |
| External host | `external_host` → hatched border + host tag |
| Superseded | `chunk_id ∈ finding.base` for an `amended` finding with `incorporated: false` |

**`accountable` is load-bearing and gets a visible mark.** These are the chunks `resolve` judged
relevant enough that dropping one silently is a defect (`graph.py:1010`) — they are also what
`_coverage_lines` names to the model. `★ ACCOUNTABLE` + auto-expansion, with a popover:
*"Retrieval ranked this excerpt highly enough that the answer must either use it or say why not."*

Collapsed cards show 3 lines with a `▾ more`. Cards are **never** collapsed to header-only —
the point is to show the text.

---

## 6. Feature 3 — opening the exact source page, honestly

### 6.1 The rule

> **The page in a citation is the physical PDF page. The viewer opens at the physical page.
> The UI never converts to a printed page number, in either direction.**

This is not a shortcut. I measured the corpus while writing this spec, and printed page numbering
across these 25 PDFs is **not a function you can invert**:

- **8 of 25 books print no page number at all** (chess, crossfire, fatal-fury, lol,
  rocket-league, street-fighter-6, tekken-8, tft).
- **5 print numbers that match the physical page exactly** (apex, free-fire, global,
  pubg-mobile, warzone).
- **`honor-of-kings` is two documents concatenated into one file.** Physical pp.2–6 print
  "- 1 -" … "- 5 -"; physical p.7 **restarts** at "- 1 -" and runs to "- 44 -" at physical p.50;
  physical pp.51–60 print nothing. So the carried-forward "+6 offset" is true only for physical
  pp.7–50 — it is **+1** for pp.2–6 and undefined for pp.51–60. And critically: **printed labels
  1–5 each appear on two different physical pages.** A printed number in that book is not a
  unique locator.

Any UI that offered "printed p.5" as a locator for `honor-of-kings` would send a compliance user
to the wrong page half the time. So it doesn't offer one.

### 6.2 `PageProvenanceStrip`

Fixed at the top of the `SourceViewer`, always present, never dismissible:

```
  PHYSICAL PDF PAGE 11 OF 60 — the page this citation points to
  This page's printed footer reads "- 5 -".
  ⚠ This document's printed numbering restarts partway through; "- 5 -" also
    appears on physical page 6. Citations use the physical page.
```

- Line 1 is always shown.
- Line 2 only when a footer label was actually **observed** on that page (FLAG §7.7). It is
  reported as an observation of the page, never as a locator, never as a link target.
- Line 3 only when `footerAmbiguous` is true for that document.
- Where no footer was observed: *"No printed page number appears on this page."* — stated, not
  left blank.

### 6.3 Which copy of the PDF you are reading — `SourceOriginNote`

Two different files can answer "the source PDF", and log 009 documents that this distinction is
**real**: the publisher silently re-uploaded the Global Rulebook so that the amended paragraph
now sits on p.18. So the viewer names its copy:

- **Primary target: the locally indexed copy**, served same-origin from `source_path`
  (`data/pdfs/…`). This is the exact file the chunks were cut from — `manifest.json` carries its
  `sha256` and `downloaded_at`. It is the only copy for which the cited page number is guaranteed
  correct. It also works offline and sends no request to a third party.
- **Secondary: the publisher's copy**, `source_url`, offered as a labelled external link:
  `Publisher copy on cdn.esportsworldcup.com ↗ — may have been re-uploaded since 11 Aug 2026;
  page numbers may differ.` For `apex`, the host is `algs.ea.com` and the link carries the
  `THIRD-PARTY HOST` tag.

Note rendered under the viewer, mono, `--ink-3`:
`indexed copy · sha256 ecb33c7e · downloaded 11 Aug 2026`.

### 6.4 Page spans and unopenable sources

- `page_end > page` (**429 of 2,382 chunks, 18.0%**): the `Locator` reads `pp.11–12`; the card's
  open button reads `▸ OPEN PDF PAGES 11–12`; the viewer opens at `page` and renders a
  mono bar under the page: `This excerpt continues onto page 12  [▸ page 12]`. Paging within an
  open viewer is free and fires nothing.
- **`overwatch-2` has no PDF at all** (a Google Doc — `manifest.skipped`). It has no chunks, so
  it cannot be cited, but `ScopeSelector` MUST still list it, disabled, with the reason:
  *"No PDF published — not in the corpus."* Silently omitting it would let a user believe they
  searched a book that does not exist in the index. (FLAG §7.11.)
- If a local PDF is missing at request time, `ContextCard` enters `unopenable`: the open button
  is replaced by mono text *"Local PDF not available — run `python ingest.py`"* plus the
  publisher link. The card and its citation still render fully.

### 6.5 Viewer behaviour

Render with a self-hosted `pdf.js` build (no CDN — CLAUDE.md's don'ts and offline operation).
On open: jump to `page`, and draw a 2px `--tier` bracket in the left margin of that page as an
attention cue. **Do not attempt to highlight the chunk's text on the page** — the chunk text is
PyMuPDF-extracted and reflowed, so a text match would be approximate, and an approximate
highlight on a compliance document asserts a precision the system does not have. The page is the
unit of evidence, and the page is what is shown.

---

## 7. API contract

**Nothing in this section exists today.** `requirements.txt` contains no web framework —
no FastAPI, Flask, uvicorn or Starlette. The HTTP layer is entirely new work and should live in
a new module (`server.py`) that **imports** `graph.py` and does not modify the pipeline's shape.
Keep the module separation CLAUDE.md requires.

### 7.0 Endpoints

```
POST   /api/ask                    → AskResponse         (full pipeline)
POST   /api/search                 → AskResponse         (route→retrieve→resolve; answer null)
GET    /api/conversations          → ConversationSummary[]
POST   /api/conversations          → ConversationSummary
GET    /api/conversations/:id      → Conversation        (with all turns)
PATCH  /api/conversations/:id      → ConversationSummary (rename only)
DELETE /api/conversations/:id      → 204
GET    /api/catalog                → BookInfo[]
GET    /api/corpus                 → CorpusInfo
GET    /api/budget                 → Budget
GET    /api/source/:slug           → application/pdf     (Range-capable, the LOCAL indexed copy)
GET    /api/source/:slug/pages     → PageInfo[]          (observed footer labels; cached)
```

`POST /api/ask` streams **phase events** as SSE (§7.10) and terminates with the full
`AskResponse`. If streaming is not implemented in the first pass, it returns `AskResponse`
directly and the client degrades per §2.1.

### 7.1 `AskResponse`

```jsonc
{
  "turn_id": "t_01J…",
  "conversation_id": "c_01J…",
  "asked_at": "2026-08-14T10:52:04Z",
  "question": "What are the map veto rules?",

  "outcome": "answered",            // FLAG 7.1 — answered | uncited | withheld | no_evidence
  "answer": "…verbatim…",           // graph.py state.answer            ✅ exists
  "citation_spans": [               // FLAG 7.2
    { "start": 142, "end": 187,
      "locator": "VALORANT — Article 5.5.1, p.11",
      "chunk_id": "valorant:5.5.1:0" }
  ],

  "game": "valorant",               // ✅ state.game
  "forced_scope": true,             // FLAG 7.3 — did the caller set --game
  "scope": "the VALORANT rulebook and the EWC Global Rulebook 2026",   // ✅ state.scope
  "query": "…",                     // ✅ state.query

  "docs": [ /* Doc[], in state.docs order */ ],                        // ✅
  "ranks": { "valorant:5.5.1:0": 1 },                                  // ✅ state.ranks
  "accountable": ["valorant:5.5.1:0"],                                 // ✅
  "findings": [ /* state.conflicts, verbatim */ ],                     // ✅
  "top_findings": ["conflict at VALORANT (Article 5.5.1, p.11)"],      // ✅
  "note": "NOTE ON THIS EVIDENCE SET…",                                // ✅ (debug only, §7.6)
  "citation_errors": [],                                               // ✅

  "usage": [ {"node":"route","input":812,"output":9} ],                 // ✅ state.usage
  "cost_usd": 0.000412,             // FLAG 7.4
  "model": "gpt-4o-mini",
  "duration_ms": 4118,
  "retried": false,                 // FLAG 7.5
  "corpus_fingerprint": "e5819299"  // FLAG 7.8
}
```

`Doc` is the chunk's `metadata` verbatim plus `page_content`, plus two server-computed fields:
`source_available` (boolean — local PDF present) and `page_count`.

### 7.2 The FLAGs — what `graph.py` does not expose

| # | Need | Status | Recommendation |
|---|---|---|---|
| **7.1** | `outcome` | **Missing.** `answer()` returns only a string; the withheld/no-evidence branches are identifiable *only* by their hardcoded sentinel prose (`graph.py:1565`, `1638`). | **Return an explicit status key from `answer()`.** The server must not string-match the pipeline's own output — that couples the UI to prompt copy and breaks silently when the wording is edited. `uncited` is then derived server-side via the existing `cited_locators()`. Small, safe change; no prompt or retrieval impact. |
| **7.2** | `citation_spans` with character offsets | **Missing.** `cited_locators()` (`graph.py:341`) returns strings without positions, and drops non-citation parentheticals. | Compute server-side by re-running the existing `_PARENTHETICAL` regex with `finditer`, normalising each piece with `_normalise`, and mapping to `chunk_id` via `allowed_citations`. Reuse the existing functions so the chips can never disagree with the post-check. **The client must not parse citations itself.** |
| **7.3** | `forced_scope` | **Missing** as an output, though `route` branches on it (`graph.py:1457`). | Echo the caller's intent. `ScopeLedger` and `PipelineTrace` both need it. |
| **7.4** | `cost_usd` | **Present but CLI-only.** `CHAT_PRICE_PER_1M` lives at `graph.py:1690`, used only in `main()`. | Lift the computation into a helper and return it. Also needs the embedding cost for the retrieval leg to be complete; if it is not tracked, return `null` for it and label the figure `chat only` in `BudgetLedger` rather than under-reporting silently. |
| **7.5** | `retried` | **Derivable, not exposed.** `usage` contains a `{"node": "answer.recite"}` entry iff the retry fired (`graph.py:1620`). | Server derives it from `usage`; no pipeline change. |
| **7.6** | `note` | ✅ exists. | Return it, but render it **only** behind a `Show the note sent to the model` disclosure in a developer drawer. It is prompt text with imperatives ("Say that the Global Rulebook governs") and showing it in the answer flow would read as an assertion to the user. |
| **7.7** | Observed footer labels per page | **Missing entirely.** Nothing in the repo records printed page numbers. | New `GET /api/source/:slug/pages` → `[{physical, footer_label, ambiguous}]`, computed once with PyMuPDF and cached to `data/page_labels.json`. `ambiguous` MUST be true for any label appearing on more than one physical page — my `honor-of-kings` measurement proves this case is real, not theoretical. Purely additive; no re-index, no cost. |
| **7.8** | `corpus_fingerprint` | **Present in a file, not in the API.** `chunks.pkl` sha256 is recorded in `data/index_stats.json`. | Expose the first 8 hex chars. Drives `StaleStamp` and `CorpusBar`. |
| **7.9** | Title **aliases** for the B-2 guard | **Missing, and not fully derivable.** `catalog()` (`graph.py:109`) gives `(slug, game_title)` from the corpus. But `cod-mw3` publishes as *"Call of Duty: Black Ops 7"* — nothing in the corpus connects the user's word "Warzone" to it, and that is one of log 009's three B-2 reproductions. | Derive what is derivable (slug tokens, `game_title` tokens, `doc_title`, `manifest.detail_url` slug) and expose as `BookInfo.aliases`. A hand-written alias list would improve the guard but **conflicts with CLAUDE.md's "don't hardcode the slug list"** — see §9, needs a human ruling. Ship the derived version; the guard degrades gracefully, catching the CS2/Valorant case even without aliases. |
| **7.10** | Per-node phase events | **Missing.** `ask()` uses `.invoke()` (`graph.py:1683`). | LangGraph's `.stream()` yields per-node updates. Wrap as SSE: `{"phase":"retrieve","scope":"…"}`. **Phases only — never token streaming** (§8). |
| **7.11** | Books with no PDF | **Present in `manifest.json.skipped`, not in the API.** | Include in `GET /api/catalog` with `in_corpus: false` and `skip_reason`. `overwatch-2` must be visible-and-disabled in `ScopeSelector`, not absent. |

### 7.3 History persistence

**Server-side SQLite** at `data/history.db` (already gitignored). Not `localStorage`: a turn is
only reconstructable with its `docs`, `findings`, `ranks` and `accountable`, which is ~40–80 KB
of JSON per turn, and it must survive a browser change on a machine a compliance user might not
own.

```sql
CREATE TABLE conversation (
  id TEXT PRIMARY KEY, title TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE turn (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  asked_at TEXT NOT NULL,
  question TEXT NOT NULL,
  response_json TEXT NOT NULL,        -- the whole AskResponse, verbatim
  corpus_fingerprint TEXT NOT NULL,
  cost_usd REAL NOT NULL
);
CREATE UNIQUE INDEX turn_seq ON turn(conversation_id, seq);
```

Two rules the implementation MUST hold:

1. **Loading history never invokes the pipeline and never spends.** `GET /api/conversations/:id`
   is a pure read.
2. **A stored turn is a record, not a cache.** It is never served in response to a new question,
   even an identical one. CLAUDE.md forbids caching answers keyed on the question, because the
   corpus is versioned — and `corpus_fingerprint` is stored per turn precisely so a record can be
   *marked* stale (§2.4) rather than quietly reused. There is no question→answer lookup path
   anywhere in this design.

Auto-title a conversation from its first question, truncated at 60 chars; user-renameable.

---

## 8. Visual language

**Direction: bench memo.** The reference is a court bench memorandum and an instrument panel —
archival paper, hairline rules, letterspaced institutional labels, and colour used only where it
carries meaning. Explicitly *not* a consumer chat app: no bubbles, no avatars, no rounded cards,
no gradients, no drop shadows, no purple.

### 8.1 Type

Self-hosted woff2 (no CDN, works offline). Three voices, and the distinction is semantic:

| Role | Face | Why |
|---|---|---|
| **Corpus voice** — answers, rule text, questions, excerpt bodies | **Literata** | A reading serif designed for long-form screen reading. It says "document". Everything that is *text from or about the rulebooks* is set in it. |
| **System voice** — labels, buttons, notices, UI copy | **Archivo** | A grotesque with enough character to not read as default. Everything the *interface* says is set in it, so the user can always tell the tool apart from the corpus. |
| **Machine voice** — locators, citations, metadata, fingerprints, costs | **IBM Plex Mono** | Institutional, technical, tabular. Every locator and every number. |

Fallbacks: `Literata, 'Iowan Old Style', Charter, Georgia, serif` ·
`Archivo, 'Helvetica Neue', Arial, sans-serif` · `'IBM Plex Mono', ui-monospace, Menlo, monospace`.

```
--fs-display   28px / 1.15  Literata 500        conversation + empty-state headline
--fs-question  22px / 1.30  Literata 400        QuestionBlock
--fs-h2        17px / 1.35  Archivo 600         section headers
--fs-body      16px / 1.55  Literata 400        answer prose, excerpt bodies   ← 62–72ch measure
--fs-ui        14px / 1.45  Archivo 400         UI copy, buttons
--fs-meta      12.5px/1.45  Archivo 400         card footers
--fs-mono      12.5px/1.45  IBM Plex Mono 400   locators, numbers  (tabular-nums, ls .01em)
--fs-eyebrow   11px  /1.20  Archivo 600         UPPERCASE, ls .12em
```

Answer prose is capped at **68ch**. Long single words / locators use `overflow-wrap: anywhere`.

### 8.2 Colour

**The rule: saturated colour encodes authority tier and nothing else.**

```css
:root {                                   /* LIGHT — aged paper */
  --paper:        #F7F4EE;
  --paper-raised: #FFFDF8;
  --paper-sunk:   #EFEBE2;
  --ink:          #1A1815;
  --ink-2:        #4A463F;
  --ink-3:        #6E685E;
  --rule:         #DED8CC;
  --rule-strong:  #C4BBA9;

  --auth-global:      #2F4B7C;   /* slate-blue ink   — authority 0 */
  --auth-global-bg:   #EAEEF6;
  --auth-title:       #8A5A0B;   /* ochre            — authority 1 */
  --auth-title-bg:    #F6EEDE;
  --auth-amendment:   #9E3418;   /* vermilion        — authority 2 */
  --auth-amendment-bg:#F7E9E3;

  --alert:        #B3261E;       /* transport/config errors ONLY */
  --focus:        #1A1815;
}

:root[data-theme="dark"] {                /* DARK — the same document under a lamp */
  --paper:        #15120D;
  --paper-raised: #1D1913;
  --paper-sunk:   #100E0A;
  --ink:          #EDE6D8;
  --ink-2:        #B8AE9C;
  --ink-3:        #8C8474;
  --rule:         #322C22;
  --rule-strong:  #4A4234;

  --auth-global:      #8FB0E8;
  --auth-global-bg:   #1B2436;
  --auth-title:       #E0A94A;
  --auth-title-bg:    #2E2412;
  --auth-amendment:   #F0836A;
  --auth-amendment-bg:#331912;

  --alert:        #FF9C8F;
  --focus:        #EDE6D8;
}
```

Both palettes are defined on `:root` and `[data-theme="dark"]`; `@media (prefers-color-scheme: dark)`
applies the dark set only when no explicit `data-theme` is set. Never define a colour solely
inside a media query.

**Tier assignment and why:**

| Tier | Colour | Glyph | Left border | Reasoning |
|---|---|---|---|---|
| `global` (0) | slate-blue | `G` | 3px solid | The constitutional layer — cool, foundational, recessive. |
| `title` (1) | ochre | `T` | 3px double | Usually the *operative* rule under #1, so it is the warmest and most present. |
| `amendment` (2) | vermilion | `A` | 3px solid + 6px top notch | Newest and highest authority. Vermilion is used **nowhere else**, so "this has been amended" is unmistakable. |

**Colour is never the sole carrier.** Every tier appearance pairs its colour with its glyph and
its border treatment, so the design survives greyscale printing and all three common colour-vision
deficiencies. Verify: at least 4.5:1 for every `--auth-*` on both `--paper` and its `-bg`.

`--alert` appears **only** in `ErrorPanel`. Not in `WithheldPanel`, not in `DisclosureStrip`, not
in `TitleMismatchBanner`. Corpus states are never errors.

### 8.3 Space, shape, texture, motion

- **Space:** 4px base. `4 8 12 16 24 32 48 64`. Turns separated by 48px + a full-bleed hairline.
- **Radius:** `2px` everywhere. Documents have corners.
- **Elevation:** none. No `box-shadow` anywhere except the `SourceViewer` drawer edge
  (`-1px 0 0 var(--rule-strong)` — a rule, not a shadow). Depth comes from `--paper-raised` /
  `--paper-sunk` and hairlines.
- **Texture:** a single inline SVG `feTurbulence` grain as a `data:` URI on `body`, 3% opacity,
  `mix-blend-mode: multiply` in light / `overlay` in dark. It is what makes the surface read as
  paper rather than as `#FFF`. One asset, no network.
- **Motion:** 120–180ms `cubic-bezier(.2,0,0,1)`. Exactly three moments:
  1. `SourceViewer` drawer slide (180ms).
  2. `ContextCard` staggered reveal on answer arrival (40ms stagger, capped at 8 = the full set).
  3. `PipelineTrace` active-step pulse (900ms).
  Under `prefers-reduced-motion: reduce`, all three become instant state changes; the pulse
  becomes a static filled marker. Nothing conveys state through motion alone.

---

## 9. Accessibility

**Keyboard.** Every path is reachable without a pointer.

| Key | Action |
|---|---|
| `/` | focus the composer (unless already in a text field) |
| `⌘/Ctrl+Enter` | Ask |
| `⌘/Ctrl+⇧+Enter` | Search only |
| `⌘/Ctrl+K` | scope selector |
| `Esc` | close `SourceViewer` → **focus returns to the exact `CitationChip` or open button that summoned it** |
| `[` / `]` | previous / next page in an open `SourceViewer` |
| `⌥↑` / `⌥↓` | previous / next `TurnCard` |
| `Tab` | see focus order below |

**Focus order within a `TurnCard`:** question → `TitleMismatchBanner` (and its re-ask button,
if present) → each `PrecedenceNotice` and its locator buttons → answer prose with its
`CitationChip`s in reading order → `DisclosureStrip` → context order control → each `ContextCard`
header → its open button. The mismatch banner precedes the answer in the DOM as well as visually,
so a screen-reader user meets the caveat before the claim.

**Focus visibility:** 2px `--focus` outline with a 2px offset. Never removed, never a colour-only
change.

**Screen readers — citations.** A `CitationChip` is an inline anchor inside the sentence, so the
citation is read *as part of the claim*. There is no arrangement in which a claim can be read
aloud without its citation.

```html
<a class="citation" href="/api/source/valorant#page=11"
   aria-label="Citation: VALORANT, Article 5.5.1, physical PDF page 11. Opens the source page.">
  (VALORANT — Article 5.5.1, p.11)
</a>
```

The visible text stays exactly as the pipeline wrote it; `aria-label` expands the abbreviations
(`p.` → "physical PDF page") so the locator is unambiguous aloud. The `⌀` uncited marker gets
`aria-label="no citation on this passage"`.

**Screen readers — abstention and withholding.** `AbstentionPanel` and `WithheldPanel` are
`role="region"` with `aria-labelledby` pointing at their eyebrow, so the label
(`NO COVERAGE IN THE RETRIEVED TEXT` / `ANSWER WITHHELD — FAILED THE CITATION CHECK`) is
announced first and the state is unambiguous before the prose begins. Neither uses `role="alert"`
— an abstention is not an alert, and neither is a correct refusal.

**Live regions.** One `aria-live="polite"` region announces phase transitions in words
(*"searching VALORANT and the EWC Global Rulebook 2026"*) and the arrival of a result
(*"Answer received, 8 excerpts. One precedence finding: game-title rule governs."*).
`TitleMismatchBanner` is `aria-live="assertive"` — it is the one thing worth interrupting for.

**Contrast — measured, not asserted.** Every text token was checked against the **worst** ground
it appears on (`--paper`, `--paper-raised`, `--paper-sunk`). Worst-case ratios:

| token | light | dark |
|---|---|---|
| `--ink` | 14.89 | 14.08 |
| `--ink-2` | 7.88 | 7.97 |
| `--ink-3` | **4.64** | **4.72** |
| `--auth-global` | 7.30 | 7.95 |
| `--auth-title` | **4.98** | 8.28 |
| `--auth-amendment` | 5.97 | 6.80 |

All ≥4.5:1. `--ink-3` and `--auth-title` are the tight pairs — **do not lighten either**, and
re-run the check if any `--paper-*` value changes. (An earlier draft of this spec used
`#7A746A` / `#857C6C` for `--ink-3`; both measured 4.22–4.24 on the rail's sunk ground and were
corrected. Recorded so the old values are not reintroduced.)

Hairlines are decorative and exempt, but no information is ever carried by a hairline alone.

**Other.** Full functionality at 200% zoom and at 320px width. Respects
`prefers-reduced-motion` and `prefers-contrast: more` (the latter promotes `--rule` to
`--rule-strong` and thickens tier borders to 4px). The `SourceViewer` traps focus **only** when
it is a full-screen sheet (<1100px); as a drawer it does not, because side-by-side reading is the
point.

---

## 10. What I deliberately excluded

| Excluded | Why |
|---|---|
| **Token-by-token answer streaming** | The pipeline post-checks the draft and can **withhold it entirely** (`graph.py:1638`). Streaming would show the user text that is then retracted — the single worst thing this product could do. Phase streaming gives the same responsiveness honestly. |
| **A "regenerate" / "try again" button on a completed answer** | Fires a speculative model call against a $5 budget, and invites shopping for a nicer answer over a compliance system with a ~47% eval pass rate. The pipeline already has its one bounded retry. The *only* re-ask affordance is `TitleMismatchBanner`'s scoped re-ask, which is a different question, with its cost on the button. |
| **Suggested questions / autocomplete / "related rules"** | All require speculative model or embedding calls before the user has asked anything. |
| **A confidence score or percentage** | The system has no calibrated confidence. A number would be fabricated, and would be the single most misleading pixel on the page. What we *can* show — what was searched, what was retrieved, what the post-check found — is shown instead. |
| **Conversational follow-ups with memory** | `graph.py` has no conversation memory. A UI that accepted "and what about CS2?" would silently drop the referent and produce exactly B-2's failure shape. Each turn is an independent, self-contained record. |
| **Thumbs up / down** | Nothing consumes it. `eval/queries.yaml` is this project's feedback channel; a rating widget would be theatre. |
| **A side-by-side cross-title comparison view** | It would encourage reading two titles' rules as interchangeable — the exact confusion B-2 already produces without help. |
| **A printed-page-number toggle** | §6.1: printed numbering is absent in 8 books, and ambiguous in `honor-of-kings` where labels 1–5 each land on two physical pages. A toggle would offer a locator that is sometimes wrong. |
| **Text highlighting of the chunk inside the PDF page** | Chunk text is extracted and reflowed; a match would be approximate. An approximate highlight on a compliance document asserts precision the system does not have. The page is the unit of evidence. |
| **Collapsing the context surface by default** | It is a mandatory feature and the evidence base for the decision. Hiding it would be a dark pattern here. |
| **Rendering `note` in the answer flow** | It is prompt text written in imperatives to the model ("Say that the Global Rulebook governs"). Shown to a user it reads as the system's assertion. Available in a developer drawer only. |
| **Client-side detection of "abstained" by parsing prose** | Fragile, and it is the client re-interpreting a rule claim. Replaced by the mechanically-derived `outcome` (§7.1). |
| **Answer caching / dedupe on repeated questions** | CLAUDE.md forbids it; the corpus is versioned. History stores records, never a lookup path. |
| **Export to PDF/DOCX** | Out of scope for S6a. When it comes, it must carry the scope ledger, the citations and the corpus fingerprint, or it becomes a way to launder a claim out of its context. Noted so it is not added casually. |

---

## 11. Open questions needing a human ruling

1. **Alias list for `TitleMismatchBanner` (§4.4, FLAG 7.9).** The B-2 guard is materially weaker
   without one — "Warzone" cannot be derived from a book titled *"Call of Duty: Black Ops 7"*, and
   that is one of the three logged reproductions. A curated alias map is the fix, but CLAUDE.md's
   don'ts forbid hardcoding the slug list. **Is a derived-slugs-plus-curated-aliases map
   acceptable, and if so does it live in a data file rather than in code?** My recommendation: yes,
   as `data/aliases.json` produced by `ingest.py` from the detail pages, with a small hand-checked
   supplement — but this is the human's call.
2. **Does the front-end ship before B-2 is repaired?** This design is built to survive B-2 and
   makes it visible, but a mitigation in the UI is not a fix in the pipeline. If S6b lands before
   S5's repair, `TitleMismatchBanner` is doing compliance-critical work with no server-side
   backstop.
3. **Budget.** ~$4.43 remains. A UI invites more querying than a CLI does. Should
   `/api/ask` enforce a hard per-day or per-conversation ceiling server-side, and at what number?
   `BudgetLedger` and the `budget-refused` state are designed for it either way.
4. **Is the local PDF served to the browser at all?** §6.3 makes the locally indexed copy the
   primary target because it is the exact file the citations were computed against. It is also
   Esports Foundation content that CLAUDE.md declines to redistribute. Serving it from localhost
   to its own operator is not redistribution as I read it — but if the front-end is ever deployed
   beyond localhost, that changes, and the answer should be settled now rather than at deploy time.

---

## 12. Mockup

`frontend/mockup.html` — static, **not wired to any data**, every value hardcoded and fictional.
It exists to communicate type, colour, density and the three-zone layout, and shows: an answered
turn with a `conflict` finding and welded citations, the `ScopeLedger`, `TitleMismatchBanner`,
four `ContextCard`s, the open `SourceViewer` with `PageProvenanceStrip`, and the
`AbstentionPanel` / `WithheldPanel` treatments side by side. It is not an implementation
reference for behaviour — this document is.

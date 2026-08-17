import { formatUsd } from './Primitives'

/**
 * The ONLY place --alert is permitted in this design.
 *
 * A corpus state is never an error: an abstention is the product working, a
 * withheld answer is the product refusing to show what it could not verify, and
 * a budget refusal is a standing condition. Those three have their own
 * treatments and none of them is red. What lands here is transport and
 * configuration — the things that genuinely went wrong.
 */
const COPY = {
  no_api_key: {
    eyebrow: 'No API key',
    body: (
      <>
        <code>OPENAI_API_KEY</code> is not set in the server process. Add it to{' '}
        <code>.env</code> and restart <code>python server.py</code>. The browser never holds a
        key — every model call happens server-side.
      </>
    ),
  },
  'corpus-missing': {
    eyebrow: 'Corpus missing',
    body: (
      <>
        <code>data/chunks.pkl</code> is absent, so there is nothing to search. Run{' '}
        <code>python index.py</code> to rebuild the store. Note that a rebuild re-embeds the
        whole corpus and costs real money.
      </>
    ),
  },
  network: {
    eyebrow: 'Server unreachable',
    body: (
      <>
        The client could not reach the API. Start it with <code>python server.py</code> — it
        binds <code>127.0.0.1:8000</code> and serves loopback clients only.
      </>
    ),
  },
  'upstream-refused': {
    eyebrow: 'The model call failed',
    body: <>The pipeline raised an error before it produced an answer.</>,
  },
}

export function ErrorPanel({ error, onRetry, onDismiss }) {
  const kind = COPY[error.kind] ? error.kind : 'upstream-refused'
  const copy = COPY[kind]
  return (
    <section className="error-panel" role="alert">
      <div className="eyebrow">{copy.eyebrow}</div>
      <p>{copy.body}</p>
      {error.message && (
        <p className="mono" style={{ marginTop: 8 }}>
          {error.message}
        </p>
      )}
      <div className="retry">
        {/* Retry is permitted HERE and only here, because no model call
            completed — so retrying does not duplicate spend. It says so. */}
        {onRetry && (
          <button className="btn btn-2" onClick={onRetry}>
            Retry
          </button>
        )}
        <button className="btn-ghost" onClick={onDismiss}>
          Dismiss
        </button>
        <small>The previous attempt did not complete a model call, so retrying spends nothing extra.</small>
      </div>
    </section>
  )
}

/**
 * A standing condition, not a toast. The server declined to spend BEFORE
 * calling the model, so nothing was charged and nothing was recorded.
 */
export function BudgetRefusedPanel({ refusal, onDismiss }) {
  return (
    <section className="budget-refused" role="region" aria-label="Budget ceiling reached">
      <div className="eyebrow">Refused before the model call — {refusal.scope} ceiling</div>
      <p>{refusal.message}</p>
      <p className="figures mono">
        spent {formatUsd(refusal.spent_usd, 4)} · this question budgeted at{' '}
        {formatUsd(refusal.estimate_usd, 4)} · ceiling {formatUsd(refusal.ceiling_usd, 4)}
      </p>
      <div className="retry" style={{ marginTop: 10 }}>
        <button className="btn-ghost" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </section>
  )
}

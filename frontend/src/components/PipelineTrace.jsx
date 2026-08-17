/**
 * PipelineTrace — the loading state, which names the ACTUAL node.
 *
 * The node names are meaningful to this user and a generic spinner is a wasted
 * opportunity to teach what the system does. There is no skeleton shimmer: the
 * trace IS the loading state, and it carries information.
 *
 * Phases come from real per-node events streamed by the server (LangGraph's
 * `.stream()` wrapped as SSE). Nothing here is faked with setTimeout, and no
 * answer text is streamed — the pipeline post-checks its draft and can withhold
 * it entirely, and showing text that is then retracted is the worst thing this
 * product could do.
 */

const STEPS = [
  { key: 'route', label: 'Route' },
  { key: 'retrieve', label: 'Retrieve' },
  { key: 'resolve', label: 'Resolve' },
  { key: 'answer', label: 'Answer' },
]

const PHASE_STEP = {
  routing: 0,
  retrieving: 1,
  resolving: 2,
  generating: 3,
  verifying: 3,
  regenerating: 3,
}

const SUBLABEL = {
  routing: 'choosing which rulebook to search',
  retrieving: 'searching the rulebooks',
  resolving: 'comparing articles across rulebooks',
  generating: 'drafting, then checking every citation against the retrieved text',
  verifying: 'checking every citation against the retrieved text',
  regenerating: 'first draft failed a check — one correction attempt',
}

export function PipelineTrace({ phase, scopeLabel, routerSkipped, mode }) {
  if (phase === 'idle') return null
  const active = PHASE_STEP[phase] ?? 0
  const steps = mode === 'search' ? STEPS.slice(0, 3) : STEPS

  return (
    <div className="trace" role="status" aria-live="polite">
      <div className="trace-steps">
        {steps.map((step, index) => (
          <span key={step.key} className="step-wrap">
            {index > 0 && <span className="sep">▸ </span>}
            <span
              className={`step ${index < active ? 'done' : ''} ${index === active ? 'active' : ''}`}
            >
              <span className="mark" aria-hidden="true" />
              {step.label}
            </span>{' '}
          </span>
        ))}
      </div>

      <div className="sub">{scopeLabel ? `Searching ${scopeLabel}` : SUBLABEL[phase]}</div>

      {routerSkipped && (
        <div className="skipped mono">
          Scope set manually; the router was not called — one fewer model call.
        </div>
      )}
      {mode === 'search' && (
        <div className="skipped mono">
          Search only: the answer node will not run, so nothing will be generated.
        </div>
      )}
    </div>
  )
}

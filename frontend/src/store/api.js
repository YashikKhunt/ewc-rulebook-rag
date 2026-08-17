/**
 * The only place this client talks to the server.
 *
 * Two things it must never do, and does not:
 *   - hold or see OPENAI_API_KEY. Every model call happens in server.py.
 *   - fire a request that costs money without an explicit user action. There is
 *     no query on typing, on focus, on mount, on hover or on a timer. The only
 *     functions below that can reach the model are `ask` and `search`, and both
 *     are called from a submit handler and nowhere else.
 *
 * `catalog`, `corpus`, `budget` and the conversation reads are free: they touch
 * no model and no embedding.
 */

const BASE = ''

class ApiError extends Error {
  constructor(message, { status, kind, payload } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.kind = kind ?? 'network'
    this.payload = payload
  }
}

async function json(path, options = {}) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch (cause) {
    throw new ApiError(
      'Could not reach the server. Is `python server.py` running on 127.0.0.1:8000?',
      { kind: 'network' },
    )
  }
  if (response.status === 204) return null
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(body?.message || body?.error || `HTTP ${response.status}`, {
      status: response.status,
      kind: body?.error ?? 'upstream-refused',
      payload: body,
    })
  }
  return body
}

export { ApiError }

export const getCatalog = () => json('/api/catalog')
export const getCorpus = () => json('/api/corpus')
export const getBudget = (cid) =>
  json(`/api/budget${cid ? `?conversation_id=${encodeURIComponent(cid)}` : ''}`)

export const listConversations = () => json('/api/conversations')
export const getConversation = (id) => json(`/api/conversations/${id}`)
export const createConversation = (title) =>
  json('/api/conversations', { method: 'POST', body: JSON.stringify({ title }) })
export const renameConversation = (id, title) =>
  json(`/api/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) })
export const deleteConversation = (id) =>
  json(`/api/conversations/${id}`, { method: 'DELETE' })

/** route -> retrieve -> resolve. No generation. With a scope set: no model call. */
export const search = (body) =>
  json('/api/search', { method: 'POST', body: JSON.stringify(body) })

export const getPageLabels = (slug) => json(`/api/source/${slug}/pages`)

export const sourceUrl = (slug) => `${BASE}/api/source/${slug}`

/**
 * The full pipeline, consumed as SSE phase events.
 *
 * PHASES ONLY -- the answer text is never streamed. `answer` post-checks its own
 * draft and can withhold it entirely, and showing text that is then retracted is
 * the single worst thing this product could do (DESIGN.md §10).
 *
 * `onPhase` is called with each node as it completes. The promise resolves with
 * the terminal `done` payload.
 */
export async function ask(body, onPhase) {
  let response
  try {
    response = await fetch(`${BASE}/api/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (cause) {
    throw new ApiError(
      'Could not reach the server. Is `python server.py` running on 127.0.0.1:8000?',
      { kind: 'network' },
    )
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new ApiError(
      payload?.budget_refusal?.message || payload?.message || `HTTP ${response.status}`,
      { status: response.status, kind: payload?.error ?? 'upstream-refused', payload },
    )
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result = null

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      if (!frame.startsWith('data:')) continue
      let event
      try {
        event = JSON.parse(frame.slice(5).trim())
      } catch {
        continue
      }
      if (event.phase === 'error') {
        throw new ApiError(event.message || 'The pipeline raised an error.', {
          kind: 'upstream-refused',
          payload: event,
        })
      }
      if (event.phase === 'done') result = event
      else onPhase?.(event)
    }
  }

  if (!result) {
    throw new ApiError('The server closed the stream without returning an answer.', {
      kind: 'network',
    })
  }
  return result
}

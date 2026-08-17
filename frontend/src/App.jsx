import { useCallback, useEffect, useRef } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import {
  loadCorpus, loadConversations, loadBudget, openConversation,
  askQuestion, searchOnly, beginRequest, dismissError,
  openSource, setViewerPage, selectViewerDoc,
} from './store'
import { CorpusBar, CorpusAtRest } from './components/CorpusBar'
import { HistoryRail } from './components/HistoryRail'
import { TurnCard } from './components/TurnCard'
import { Composer } from './components/Composer'
import { PipelineTrace } from './components/PipelineTrace'
import { SourceViewer } from './components/SourceViewer'
import { ErrorPanel, BudgetRefusedPanel } from './components/ErrorPanel'

export default function App() {
  const dispatch = useDispatch()
  const corpus = useSelector((s) => s.corpus)
  const chat = useSelector((s) => s.chat)
  const viewer = useSelector((s) => s.ui.viewer)
  const viewerDoc = useSelector(selectViewerDoc)
  const streamRef = useRef(null)

  // Mount loads only FREE data: the catalog, the corpus summary and the budget.
  // No model call, no embedding, no speculative retrieval.
  useEffect(() => {
    dispatch(loadCorpus())
    dispatch(loadConversations())
    dispatch(loadBudget())
  }, [dispatch])

  // Restore the conversation the user was last reading. A pure read of a stored
  // record — it never invokes the pipeline and never spends.
  const restored = useRef(false)
  useEffect(() => {
    if (restored.current || chat.listStatus !== 'ready' || !chat.activeId) return
    restored.current = true
    dispatch(openConversation(chat.activeId))
  }, [dispatch, chat.listStatus, chat.activeId])

  useEffect(() => {
    if (chat.phase === 'idle') {
      streamRef.current?.scrollTo({ top: streamRef.current.scrollHeight, behavior: 'smooth' })
    }
  }, [chat.turns.length, chat.phase])

  const run = useCallback(
    (mode, { question, game }) => {
      dispatch(beginRequest({ question, game, mode }))
      const args = { question, game, conversationId: chat.activeId }
      const thunk = mode === 'ask' ? askQuestion : searchOnly
      dispatch(thunk(args)).then(() => dispatch(loadBudget(chat.activeId)))
    },
    [dispatch, chat.activeId],
  )

  const onAsk = useCallback((payload) => run('ask', payload), [run])
  const onSearch = useCallback((payload) => run('search', payload), [run])

  // The ONLY re-ask affordance in this UI, and it is a different question (a
  // different scope) with its cost printed on the button that triggers it.
  const onRescope = useCallback(
    (question, game) => run('ask', { question, game }),
    [run],
  )

  const onOpenSource = useCallback(
    (doc) => {
      const turn = chat.turns.find((t) => (t.docs ?? []).some((d) => d.chunk_id === doc.chunk_id))
      if (!turn) return
      dispatch(openSource({ turnId: turn.turn_id, chunkId: doc.chunk_id, page: doc.page }))
    },
    [dispatch, chat.turns],
  )

  const busy = chat.phase !== 'idle'
  const blocked = corpus.budget?.refused
    ? 'The server has reached its spend ceiling and will refuse before calling the model. Search only with a scope set still works — it makes no model call.'
    : null

  if (corpus.status === 'error') {
    return (
      <div className="shell">
        <div className="centre">
          <CorpusBar />
          <div className="stream">
            <div className="wrap">
              <ErrorPanel error={corpus.error} onRetry={() => dispatch(loadCorpus())} onDismiss={() => {}} />
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={`shell ${viewer && viewerDoc ? 'with-viewer' : ''}`}>
      <HistoryRail />

      <div className="centre">
        <CorpusBar />

        <main className="stream" ref={streamRef}>
          <div className="wrap">
            {chat.turns.length === 0 && !busy && <CorpusAtRest />}

            {chat.turns.map((turn) => (
              <TurnCard
                key={turn.turn_id}
                turn={turn}
                corpusFingerprint={corpus.info?.fingerprint}
                catalog={corpus.catalog}
                onOpenSource={onOpenSource}
                onRescope={onRescope}
              />
            ))}

            {busy && (
              <div className="turn">
                <h2 className="question">{chat.inFlight?.question}</h2>
                <PipelineTrace
                  phase={chat.phase}
                  scopeLabel={chat.scopeLabel}
                  routerSkipped={Boolean(chat.inFlight?.game)}
                  mode={chat.inFlight?.mode}
                />
              </div>
            )}

            {chat.budgetRefusal && (
              <BudgetRefusedPanel
                refusal={chat.budgetRefusal}
                onDismiss={() => dispatch(dismissError())}
              />
            )}

            {chat.error && (
              <ErrorPanel
                error={chat.error}
                onRetry={
                  chat.inFlight
                    ? () => run(chat.inFlight.mode, chat.inFlight)
                    : undefined
                }
                onDismiss={() => dispatch(dismissError())}
              />
            )}
          </div>
        </main>

        <Composer
          onAsk={onAsk}
          onSearch={onSearch}
          disabled={busy || corpus.status !== 'ready'}
          blockedReason={blocked}
        />
      </div>

      {viewer && viewerDoc && (
        <SourceViewer
          doc={viewerDoc}
          page={viewer.page}
          onOpenPage={(page) => dispatch(setViewerPage(page))}
        />
      )}
    </div>
  )
}

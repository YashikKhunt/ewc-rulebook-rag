import { configureStore, createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import * as api from './api'

/* ═══════════════════════════════════════════════════════════════════════════
   PERSISTENCE

   Chat history lives SERVER-SIDE, in SQLite at data/history.db, not in
   localStorage. A turn is only reconstructable with its docs, findings, ranks
   and accountable set -- 40-80 KB of JSON each -- and it must survive a browser
   change on a machine a compliance user may not own. localStorage holds exactly
   two things, both of them UI preference and neither of them rule content: the
   theme, and which conversation you were last looking at.

   A stored turn is a RECORD, never a cache. There is no question -> answer
   lookup path anywhere in this client or the server: CLAUDE.md forbids it
   because the corpus is versioned, and a turn carries the corpus fingerprint it
   was produced under precisely so a stale record can be MARKED rather than
   quietly reused.
   ═══════════════════════════════════════════════════════════════════════════ */

const LAST_CONVERSATION = 'ewc.conversation'
const THEME = 'ewc.theme'

const read = (key) => {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
const write = (key, value) => {
  try {
    value == null ? localStorage.removeItem(key) : localStorage.setItem(key, value)
  } catch {
    /* private mode */
  }
}

/* ── corpus ─────────────────────────────────────────────────────────────── */

export const loadCorpus = createAsyncThunk('corpus/load', async () => {
  const [corpus, catalog] = await Promise.all([api.getCorpus(), api.getCatalog()])
  return { corpus, catalog }
})

export const loadBudget = createAsyncThunk('corpus/budget', (cid) => api.getBudget(cid))

const corpusSlice = createSlice({
  name: 'corpus',
  initialState: { info: null, catalog: [], budget: null, status: 'idle', error: null },
  reducers: {},
  extraReducers: (b) => {
    b.addCase(loadCorpus.pending, (s) => {
      s.status = 'loading'
      s.error = null
    })
      .addCase(loadCorpus.fulfilled, (s, a) => {
        s.status = 'ready'
        s.info = a.payload.corpus
        s.catalog = a.payload.catalog
      })
      .addCase(loadCorpus.rejected, (s, a) => {
        s.status = 'error'
        s.error = { kind: a.error?.name === 'ApiError' ? 'corpus-missing' : 'network',
                    message: a.error?.message ?? 'The corpus could not be loaded.' }
      })
      .addCase(loadBudget.fulfilled, (s, a) => {
        s.budget = a.payload
      })
  },
})

/* ── conversations ──────────────────────────────────────────────────────── */

export const loadConversations = createAsyncThunk('chat/list', () => api.listConversations())

export const openConversation = createAsyncThunk('chat/open', async (id) => {
  const conversation = await api.getConversation(id)
  write(LAST_CONVERSATION, id)
  return conversation
})

export const startConversation = createAsyncThunk('chat/new', async () => {
  write(LAST_CONVERSATION, null)
  return null
})

export const renameConversation = createAsyncThunk('chat/rename', ({ id, title }) =>
  api.renameConversation(id, title),
)

export const removeConversation = createAsyncThunk('chat/delete', async (id) => {
  await api.deleteConversation(id)
  return id
})

/**
 * The only two thunks in this file that can spend money. Both are dispatched
 * from a submit handler, never from an effect.
 */
export const askQuestion = createAsyncThunk(
  'chat/ask',
  async ({ question, game, conversationId }, { dispatch, rejectWithValue }) => {
    try {
      const done = await api.ask({ question, game, conversation_id: conversationId }, (event) =>
        dispatch(chatSlice.actions.phase(event)),
      )
      write(LAST_CONVERSATION, done.response.conversation_id)
      return done
    } catch (error) {
      return rejectWithValue({
        kind: error.kind, message: error.message, payload: error.payload,
      })
    }
  },
)

export const searchOnly = createAsyncThunk(
  'chat/search',
  async ({ question, game, conversationId }, { rejectWithValue }) => {
    try {
      const done = await api.search({ question, game, conversation_id: conversationId })
      write(LAST_CONVERSATION, done.response.conversation_id)
      return done
    } catch (error) {
      return rejectWithValue({
        kind: error.kind, message: error.message, payload: error.payload,
      })
    }
  },
)

const initialChat = {
  conversations: [],
  listStatus: 'idle',
  activeId: read(LAST_CONVERSATION),
  turns: [],
  loadingConversation: false,
  // request lifecycle: idle | routing | retrieving | resolving | generating | verifying
  phase: 'idle',
  inFlight: null, // { question, game, mode } while a request is running
  error: null,
  budgetRefusal: null,
}

const NODE_TO_PHASE = {
  route: 'retrieving',   // `route` has COMPLETED when its update arrives
  retrieve: 'resolving',
  resolve: 'generating',
  answer: 'idle',
}

const chatSlice = createSlice({
  name: 'chat',
  initialState: initialChat,
  reducers: {
    phase(state, action) {
      const event = action.payload
      if (event.phase === 'start') {
        state.phase = state.inFlight?.game ? 'retrieving' : 'routing'
        return
      }
      const next = NODE_TO_PHASE[event.phase]
      if (next) state.phase = next
      if (event.scope) state.scopeLabel = event.scope
      if (event.phase === 'resolve') state.phase = 'generating'
    },
    dismissError(state) {
      state.error = null
      state.budgetRefusal = null
    },
    beginRequest(state, action) {
      state.inFlight = action.payload
      state.error = null
      state.budgetRefusal = null
      state.scopeLabel = null
      state.phase = action.payload.game ? 'retrieving' : 'routing'
    },
  },
  extraReducers: (b) => {
    b.addCase(loadConversations.pending, (s) => {
      s.listStatus = 'loading'
    })
      .addCase(loadConversations.fulfilled, (s, a) => {
        s.listStatus = 'ready'
        s.conversations = a.payload
        if (s.activeId && !a.payload.some((c) => c.id === s.activeId)) {
          s.activeId = null
          s.turns = []
          write(LAST_CONVERSATION, null)
        }
      })
      .addCase(loadConversations.rejected, (s) => {
        s.listStatus = 'error'
      })
      .addCase(openConversation.pending, (s) => {
        s.loadingConversation = true
      })
      .addCase(openConversation.fulfilled, (s, a) => {
        s.loadingConversation = false
        s.activeId = a.payload.id
        s.turns = a.payload.turns
        s.error = null
      })
      .addCase(openConversation.rejected, (s) => {
        s.loadingConversation = false
      })
      .addCase(startConversation.fulfilled, (s) => {
        s.activeId = null
        s.turns = []
        s.error = null
        s.budgetRefusal = null
      })
      .addCase(renameConversation.fulfilled, (s, a) => {
        const at = s.conversations.findIndex((c) => c.id === a.payload.id)
        if (at !== -1) s.conversations[at] = a.payload
      })
      .addCase(removeConversation.fulfilled, (s, a) => {
        s.conversations = s.conversations.filter((c) => c.id !== a.payload)
        if (s.activeId === a.payload) {
          s.activeId = null
          s.turns = []
          write(LAST_CONVERSATION, null)
        }
      })

    for (const thunk of [askQuestion, searchOnly]) {
      b.addCase(thunk.fulfilled, (s, a) => {
        s.phase = 'idle'
        s.inFlight = null
        s.activeId = a.payload.response.conversation_id
        s.turns.push(a.payload.response)
        const at = s.conversations.findIndex((c) => c.id === a.payload.conversation?.id)
        if (at !== -1) s.conversations[at] = a.payload.conversation
        else if (a.payload.conversation) s.conversations.unshift(a.payload.conversation)
      }).addCase(thunk.rejected, (s, a) => {
        s.phase = 'idle'
        s.inFlight = null
        if (a.payload?.kind === 'budget_refused') {
          s.budgetRefusal = a.payload.payload?.budget_refusal ?? null
        } else {
          s.error = a.payload ?? { kind: 'network', message: 'The request failed.' }
        }
      })
    }
  },
})

/* ── ui ─────────────────────────────────────────────────────────────────── */

const uiSlice = createSlice({
  name: 'ui',
  initialState: {
    theme: read(THEME) ?? 'system',
    // The viewer is scoped to ONE turn. A conversation scoped to a game must not
    // be able to display another title's chunks, so the viewer is addressed by
    // (turnId, chunkId) and resolved against that turn's own docs -- never
    // against a global doc pool.
    viewer: null, // { turnId, chunkId, page }
    contextOrder: 'read',
    expanded: {}, // chunkId -> bool
    railOpen: false,
    catalogOpen: false,
  },
  reducers: {
    setTheme(state, action) {
      state.theme = action.payload
      write(THEME, action.payload === 'system' ? null : action.payload)
      const root = document.documentElement
      if (action.payload === 'system') delete root.dataset.theme
      else root.dataset.theme = action.payload
    },
    openSource(state, action) {
      state.viewer = action.payload
      state.expanded[action.payload.chunkId] = true
    },
    setViewerPage(state, action) {
      if (state.viewer) state.viewer = { ...state.viewer, page: action.payload }
    },
    closeSource(state) {
      state.viewer = null
    },
    setContextOrder(state, action) {
      state.contextOrder = action.payload
    },
    toggleExpanded(state, action) {
      state.expanded[action.payload] = !state.expanded[action.payload]
    },
    toggleRail(state) {
      state.railOpen = !state.railOpen
    },
    setCatalogOpen(state, action) {
      state.catalogOpen = action.payload
    },
  },
})

export const {
  phase, dismissError, beginRequest,
} = chatSlice.actions
export const {
  setTheme, openSource, closeSource, setViewerPage, setContextOrder,
  toggleExpanded, toggleRail, setCatalogOpen,
} = uiSlice.actions

export const store = configureStore({
  reducer: {
    corpus: corpusSlice.reducer,
    chat: chatSlice.reducer,
    ui: uiSlice.reducer,
  },
  middleware: (getDefault) => getDefault({ serializableCheck: false }),
})

/* ── selectors ──────────────────────────────────────────────────────────── */

export const selectBook = (state, slug) =>
  state.corpus.catalog.find((b) => b.slug === slug) ?? null

/** The doc the viewer is showing, resolved ONLY within its own turn. */
export const selectViewerDoc = (state) => {
  const viewer = state.ui.viewer
  if (!viewer) return null
  const turn = state.chat.turns.find((t) => t.turn_id === viewer.turnId)
  if (!turn) return null
  return turn.docs.find((d) => d.chunk_id === viewer.chunkId) ?? null
}

# History Contract

This document defines the current rules for conversation history storage, trimming, and usage.
It is split into production rules (expected long-term behavior) and development rules (mock-only).

## Production Rules (Target Behavior)

### Scope and storage layers
- **Session-scoped history (ephemeral)** is stored in a session store (Redis in prod, in-memory mock in dev).
- **User-scoped history (durable)** is stored in SQL (real database in prod, mock in dev).
- Only **final Q/A pairs** are persisted as conversation history.
- Retrieval chunks, intermediate reasoning, and trace payloads are **never** stored in history.

### Trimming and limits
History is trimmed at multiple levels:
1) **Session hard cap (turn count)**  
   - Enforced in `KvSessionConversationStore`.  
   - Controlled by `APP_CONV_HIST_MAX_TURNS` (default 200).  
   - Storage keeps only the last N turns.

2) **Pipeline load limit (turn count)**  
   - Enforced in `load_conversation_history`.  
   - Controlled by `history_limit` in pipeline step (default 30).

3) **Prompt budget (token limit)**  
   - Enforced in `call_model` when `use_history=true`.  
   - Controlled by `settings.max_history_tokens`.  
   - If 0 → history not passed to the model.  
   - If >0 → history is trimmed oldest-first to fit token budget.

4) **Session TTL (optional)**  
   - Controlled by `APP_CONV_HIST_TTL_S`.  
   - If set, the session store key expires after the configured time.

### Data shape (user history)
- Sessions (metadata): `sessionId`, `tenantId`, `userId`, `title`, `consultantId`,
  `createdAt`, `updatedAt`, `messageCount`, `deletedAt`.
- Messages (turns): `messageId`, `sessionId`, `ts`, `q`, `a`, `meta`, `deletedAt`.

### API (durable history)
- `GET /chat-history/sessions?limit=50&cursor=...&q=...`
- `GET /chat-history/sessions/{sessionId}`
- `GET /chat-history/sessions/{sessionId}/messages?limit=100&before=...`
- `POST /chat-history/sessions`
- `POST /chat-history/sessions/{sessionId}/messages`
- `PATCH /chat-history/sessions/{sessionId}`
- `DELETE /chat-history/sessions/{sessionId}`

All operations must filter by `tenant_id` and `user_id`.

### Production note: replace both mocks
- Session store mock (Redis replacement) must be swapped for real Redis.
- Durable store mock (SQL replacement) must be swapped for real SQL.

## Development Rules (Mock-Only)

### When mock history is enabled
- Controlled by `mockSqlServer` in `config.json`.
- Mock history is enabled **only when** `development=true`.
- If `mockSqlServer=true` but `development=false`, the mock is disabled and the server returns:
  `503` with `history_persistence_unavailable`.

### Mock storage behavior
- Mock history is stored in memory for the life of the server process.
- Data is lost on server restart.
- The mock implements the same `/chat-history/...` API as production.

### Mock TTL
- Controlled by `mockSqlTtlHours` (hours, default 1440 ≈ 2 months).
- If set to `0` or negative → TTL is disabled.
- Pruning is performed on each history endpoint call.

### Frontend behavior
- Frontend always talks to `/chat-history/...`.
- If history persistence is unavailable, UI shows:
  `Brak uruchomionego serwera persystencji historii (chat-history).`
- No localStorage fallback is used.

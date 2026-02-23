(function () {
  const App = window.App = window.App || {};
  const config = App.config || {};
  const api = (App.services && App.services.api) || null;
  const { API_BASE } = config;

  function buildAuthHeaders(fakeAuthEnabled, activeDevUserId) {
    if (api && api.buildDevAuthHeaders) {
      return api.buildDevAuthHeaders(fakeAuthEnabled, activeDevUserId);
    }
    return fakeAuthEnabled ? { "Authorization": `Bearer dev-user:${activeDevUserId}` } : {};
  }

  async function fetchSessions({ limit = 200, fakeAuthEnabled, activeDevUserId }) {
    const headers = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    const res = await fetch(`${API_BASE}/chat-history/sessions?limit=${limit}`, { headers });
    if (!res.ok) throw new Error("history sessions failed");
    return res.json();
  }

  async function searchSessions({ query, cursor, limit, fakeAuthEnabled, activeDevUserId }) {
    const headers = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    const params = new URLSearchParams();
    params.set("limit", String(limit || 50));
    if (query) params.set("q", query);
    if (cursor) params.set("cursor", cursor);
    const res = await fetch(`${API_BASE}/chat-history/sessions?${params.toString()}`, { headers });
    if (!res.ok) throw new Error("history search failed");
    return res.json();
  }

  async function patchSession({ sessionId, patch, fakeAuthEnabled, activeDevUserId }) {
    const headers = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    return fetch(`${API_BASE}/chat-history/sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(patch || {}),
    });
  }

  async function deleteSession({ sessionId, fakeAuthEnabled, activeDevUserId }) {
    const headers = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    return fetch(`${API_BASE}/chat-history/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
      headers,
    });
  }

  async function createSession({ sessionId, title, consultantId, fakeAuthEnabled, activeDevUserId }) {
    const headers = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    const res = await fetch(`${API_BASE}/chat-history/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify({
        sessionId,
        title: title || "New chat",
        consultantId: consultantId || null,
      }),
    });
    return res;
  }

  async function postMessage({ sessionId, question, answer, fakeAuthEnabled, activeDevUserId }) {
    const headers = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    return fetch(`${API_BASE}/chat-history/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify({ q: question || "", a: answer || "" }),
    });
  }

  async function getMessages({ sessionId, limit = 200, fakeAuthEnabled, activeDevUserId }) {
    const headers = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    const res = await fetch(`${API_BASE}/chat-history/sessions/${encodeURIComponent(sessionId)}/messages?limit=${limit}`, { headers });
    if (!res.ok) throw new Error("history messages failed");
    return res.json();
  }

  App.services = App.services || {};
  App.services.historyStore = {
    fetchSessions,
    searchSessions,
    patchSession,
    deleteSession,
    createSession,
    postMessage,
    getMessages,
  };
})();

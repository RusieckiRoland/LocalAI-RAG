(function () {
  const App = window.App = window.App || {};
  const config = App.config || {};
  const api = (App.services && App.services.api) || null;
  const { API_BASE } = config;
  const oidc = (App.services && App.services.oidc) || null;

  function buildAuthHeaders(fakeAuthEnabled, activeDevUserId) {
    if (api && api.buildAuthHeaders) {
      return api.buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    }
    if (api && api.buildDevAuthHeaders) {
      return api.buildDevAuthHeaders(fakeAuthEnabled, activeDevUserId);
    }
    return fakeAuthEnabled ? { "Authorization": `Bearer dev-user:${activeDevUserId}` } : {};
  }

  async function maybeRefreshOidcIfAvailable() {
    try {
      if (oidc && typeof oidc.refresh === "function") {
        await oidc.refresh();
        return true;
      }
    } catch (e) {}
    return false;
  }

  async function fetchWithAuthRetry(url, fetchOpts, fakeAuthEnabled, activeDevUserId) {
    const authHeaders1 = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    let res = await fetch(url, {
      ...(fetchOpts || {}),
      headers: { ...(fetchOpts && fetchOpts.headers ? fetchOpts.headers : {}), ...authHeaders1 },
    });
    if (res.status === 401 && !fakeAuthEnabled) {
      const refreshed = await maybeRefreshOidcIfAvailable();
      if (refreshed) {
        const authHeaders2 = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
        res = await fetch(url, {
          ...(fetchOpts || {}),
          headers: { ...(fetchOpts && fetchOpts.headers ? fetchOpts.headers : {}), ...authHeaders2 },
        });
      }
    }
    return res;
  }

  async function fetchSessions({ limit = 200, fakeAuthEnabled, activeDevUserId }) {
    const res = await fetchWithAuthRetry(
      `${API_BASE}/chat-history/sessions?limit=${limit}`,
      { method: "GET" },
      fakeAuthEnabled,
      activeDevUserId
    );
    if (!res.ok) throw new Error("history sessions failed");
    return res.json();
  }

  async function searchSessions({ query, cursor, limit, fakeAuthEnabled, activeDevUserId }) {
    const params = new URLSearchParams();
    params.set("limit", String(limit || 50));
    if (query) params.set("q", query);
    if (cursor) params.set("cursor", cursor);
    const res = await fetchWithAuthRetry(
      `${API_BASE}/chat-history/sessions?${params.toString()}`,
      { method: "GET" },
      fakeAuthEnabled,
      activeDevUserId
    );
    if (!res.ok) throw new Error("history search failed");
    return res.json();
  }

  async function patchSession({ sessionId, patch, fakeAuthEnabled, activeDevUserId }) {
    return fetchWithAuthRetry(
      `${API_BASE}/chat-history/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch || {}),
      },
      fakeAuthEnabled,
      activeDevUserId
    );
  }

  async function deleteSession({ sessionId, fakeAuthEnabled, activeDevUserId }) {
    return fetchWithAuthRetry(
      `${API_BASE}/chat-history/sessions/${encodeURIComponent(sessionId)}`,
      { method: "DELETE" },
      fakeAuthEnabled,
      activeDevUserId
    );
  }

  async function createSession({ sessionId, title, consultantId, fakeAuthEnabled, activeDevUserId }) {
    return fetchWithAuthRetry(
      `${API_BASE}/chat-history/sessions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId,
          title: title || "New chat",
          consultantId: consultantId || null,
        }),
      },
      fakeAuthEnabled,
      activeDevUserId
    );
  }

  async function postMessage({ sessionId, question, answer, fakeAuthEnabled, activeDevUserId }) {
    return fetchWithAuthRetry(
      `${API_BASE}/chat-history/sessions/${encodeURIComponent(sessionId)}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q: question || "", a: answer || "" }),
      },
      fakeAuthEnabled,
      activeDevUserId
    );
  }

  async function getMessages({ sessionId, limit = 200, fakeAuthEnabled, activeDevUserId }) {
    const res = await fetchWithAuthRetry(
      `${API_BASE}/chat-history/sessions/${encodeURIComponent(sessionId)}/messages?limit=${limit}`,
      { method: "GET" },
      fakeAuthEnabled,
      activeDevUserId
    );
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

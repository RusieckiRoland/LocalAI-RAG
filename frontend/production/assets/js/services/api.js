(function () {
  const App = window.App = window.App || {};
  const config = (App.config || {});
  const {
    API_BASE,
    APP_CONFIG_PATH,
    SEARCH_PATH,
    CANCEL_PATH,
  } = config;

  function buildDevAuthHeaders(fakeAuthEnabled, activeDevUserId) {
    const headers = {};
    if (fakeAuthEnabled) {
      headers["Authorization"] = `Bearer dev-user:${activeDevUserId}`;
    }
    return headers;
  }

  async function fetchAppConfig({ fakeAuthEnabled, activeDevUserId } = {}) {
    const authHeaders = buildDevAuthHeaders(fakeAuthEnabled, activeDevUserId);
    const res = await fetch(`${API_BASE}${APP_CONFIG_PATH}`, {
      headers: { ...authHeaders },
    });
    if (!res.ok) throw new Error(`GET ${APP_CONFIG_PATH} failed: ${res.status}`);
    return res.json();
  }

  async function postSearch({ body, sessionId, fakeAuthEnabled, activeDevUserId, signal }) {
    const authHeaders = buildDevAuthHeaders(fakeAuthEnabled, activeDevUserId);
    const res = await fetch(`${API_BASE}${SEARCH_PATH}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
        ...(sessionId ? { "X-Session-ID": sessionId } : {}),
      },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok) throw new Error(`POST ${SEARCH_PATH} failed: ${res.status}`);
    return res.json();
  }

  async function cancelRun({ runId, sessionId, fakeAuthEnabled, activeDevUserId }) {
    if (!runId) return;
    const authHeaders = buildDevAuthHeaders(fakeAuthEnabled, activeDevUserId);
    await fetch(`${API_BASE}${CANCEL_PATH}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
        ...(sessionId ? { "X-Session-ID": sessionId } : {}),
      },
      body: JSON.stringify({ pipeline_run_id: runId }),
    });
  }

  App.services = App.services || {};
  App.services.api = {
    buildDevAuthHeaders,
    fetchAppConfig,
    postSearch,
    cancelRun,
  };
})();

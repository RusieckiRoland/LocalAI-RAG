(function () {
  const App = window.App = window.App || {};
  const config = (App.config || {});
  const {
    API_BASE,
    APP_CONFIG_PATH,
    SEARCH_PATH,
    CANCEL_PATH,
  } = config;

  function _getOidcAccessToken() {
    try {
      if (App.services && App.services.oidc && typeof App.services.oidc.getAccessToken === "function") {
        return String(App.services.oidc.getAccessToken() || "");
      }
    } catch (e) {}
    try {
      return String(sessionStorage.getItem("oidc_access_token") || "");
    } catch (e) {}
    return "";
  }

  function buildAuthHeaders(fakeAuthEnabled, activeDevUserId) {
    const headers = {};
    if (fakeAuthEnabled) {
      headers["Authorization"] = `Bearer dev-user:${activeDevUserId}`;
      return headers;
    }
    const oidc = _getOidcAccessToken();
    if (oidc) headers["Authorization"] = `Bearer ${oidc}`;
    return headers;
  }

  // Backward-compatible name kept for older callers.
  function buildDevAuthHeaders(fakeAuthEnabled, activeDevUserId) {
    return buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
  }

  async function fetchAppConfig({ fakeAuthEnabled, activeDevUserId } = {}) {
    const authHeaders = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    const res = await fetch(`${API_BASE}${APP_CONFIG_PATH}`, {
      headers: { ...authHeaders },
    });
    if (!res.ok) {
      let detail = "";
      try {
        const ct = String(res.headers.get("content-type") || "");
        if (ct.includes("application/json")) {
          const j = await res.json();
          if (j && typeof j === "object") {
            detail = String(j.error || j.message || "");
          }
        } else {
          detail = String(await res.text() || "");
        }
      } catch (e) {}
      const err = new Error(`GET ${APP_CONFIG_PATH} failed: ${res.status}${detail ? ` (${detail})` : ""}`);
      err.status = res.status;
      err.detail = detail;
      throw err;
    }
    return res.json();
  }

  async function postSearch({ body, sessionId, fakeAuthEnabled, activeDevUserId, signal }) {
    let authHeaders = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    let res = await fetch(`${API_BASE}${SEARCH_PATH}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
        ...(sessionId ? { "X-Session-ID": sessionId } : {}),
      },
      body: JSON.stringify(body),
      signal,
    });
    if (res.status === 401 && !fakeAuthEnabled) {
      const oidc = (App.services && App.services.oidc) || null;
      if (oidc && typeof oidc.refresh === "function") {
        await oidc.refresh();
        authHeaders = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
        res = await fetch(`${API_BASE}${SEARCH_PATH}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...authHeaders,
            ...(sessionId ? { "X-Session-ID": sessionId } : {}),
          },
          body: JSON.stringify(body),
          signal,
        });
      }
    }
    if (!res.ok) {
      const err = new Error(`POST ${SEARCH_PATH} failed: ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  async function cancelRun({ runId, sessionId, fakeAuthEnabled, activeDevUserId }) {
    if (!runId) return;
    const authHeaders = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
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
    buildAuthHeaders,
    fetchAppConfig,
    postSearch,
    cancelRun,
  };
})();

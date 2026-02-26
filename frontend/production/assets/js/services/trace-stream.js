(function () {
  const App = window.App = window.App || {};
  const config = App.config || {};
  const api = (App.services && App.services.api) || null;
  const { API_BASE, TRACE_STREAM_PATH } = config;

  function buildAuthHeaders(fakeAuthEnabled, activeDevUserId) {
    if (api && api.buildAuthHeaders) return api.buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    if (api && api.buildDevAuthHeaders) return api.buildDevAuthHeaders(fakeAuthEnabled, activeDevUserId);
    return fakeAuthEnabled ? { "Authorization": `Bearer dev-user:${activeDevUserId}` } : {};
  }

  async function maybeRefreshOidcIfAvailable() {
    try {
      const oidc = (App.services && App.services.oidc) || null;
      if (oidc && typeof oidc.refresh === "function") {
        await oidc.refresh();
        return true;
      }
    } catch (e) {}
    return false;
  }

  // Minimal SSE parser for fetch streams.
  async function _consumeSseStream(res, onEvent, onError, abortSignal) {
    try {
      if (!res.ok) throw new Error(`trace stream failed: ${res.status}`);
      const reader = res.body && res.body.getReader ? res.body.getReader() : null;
      if (!reader) throw new Error("trace stream body not readable");
      const decoder = new TextDecoder("utf-8");
      let buf = "";

      while (true) {
        if (abortSignal && abortSignal.aborted) return;
        const { value, done } = await reader.read();
        if (done) return;
        buf += decoder.decode(value, { stream: true });
        // SSE frames are separated by blank line.
        let idx = buf.indexOf("\n\n");
        while (idx !== -1) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const lines = frame.split("\n");
          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            const payloadRaw = line.slice(5).trim();
            if (!payloadRaw) continue;
            try {
              const payload = JSON.parse(payloadRaw);
              if (typeof onEvent === "function") onEvent(payload);
            } catch (e) {
              // ignore
            }
          }
          idx = buf.indexOf("\n\n");
        }
      }
    } catch (e) {
      if (typeof onError === "function") onError(e);
    }
  }

  function startTraceStream({ runId, onEvent, onError, fakeAuthEnabled, activeDevUserId }) {
    if (!runId) return null;
    const url = `${API_BASE}${TRACE_STREAM_PATH}?run_id=${encodeURIComponent(runId)}`;

    // Fetch streaming supports Authorization headers (EventSource can't send headers).
    const ctrl = new AbortController();
    let retryTimer = null;
    let closed = false;
    let doneReceived = false;
    let attempt = 0;

    const onEventWrapped = (payload) => {
      try {
        if (payload && typeof payload === "object" && payload.type === "done") doneReceived = true;
      } catch (e) {}
      if (typeof onEvent === "function") onEvent(payload);
    };

    async function _connect() {
      if (closed || (ctrl.signal && ctrl.signal.aborted) || doneReceived) return;
      const headers1 = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
      let res = null;
      try {
        res = await fetch(url, { method: "GET", headers: headers1, signal: ctrl.signal });
        if (res.status === 401 && !fakeAuthEnabled) {
          const refreshed = await maybeRefreshOidcIfAvailable();
          if (refreshed && !closed && !(ctrl.signal && ctrl.signal.aborted)) {
            const headers2 = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
            res = await fetch(url, { method: "GET", headers: headers2, signal: ctrl.signal });
          }
        }
        if (!res.ok) {
          const err = new Error(`trace stream failed: ${res.status}`);
          err.status = res.status;
          throw err;
        }
        attempt = 0;
        await _consumeSseStream(res, onEventWrapped, onError, ctrl.signal);
      } catch (e) {
        if (closed || (ctrl.signal && ctrl.signal.aborted) || doneReceived) return;
        if (typeof onError === "function") onError(e);
        attempt += 1;
        const delay = Math.min(5000, 500 * Math.pow(1.6, Math.max(0, attempt - 1)));
        retryTimer = setTimeout(_connect, delay);
      }
    }

    _connect();

    return {
      close: () => {
        closed = true;
        try {
          if (retryTimer) clearTimeout(retryTimer);
        } catch (e) {}
        retryTimer = null;
        try { ctrl.abort(); } catch (e) {}
      },
    };
  }

  function stopTraceStream(source) {
    if (!source) return;
    try { source.close(); } catch (_) {}
  }

  App.services = App.services || {};
  App.services.traceStream = {
    startTraceStream,
    stopTraceStream,
  };
})();

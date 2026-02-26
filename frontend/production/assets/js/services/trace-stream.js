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
    const headers = buildAuthHeaders(fakeAuthEnabled, activeDevUserId);
    const hasAuth = !!headers.Authorization;
    const url = `${API_BASE}${TRACE_STREAM_PATH}?run_id=${encodeURIComponent(runId)}`;

    // In unauthenticated mode we keep EventSource (lighter, reconnects).
    if (!hasAuth) {
      const source = new EventSource(url);
      source.onmessage = (evt) => {
        if (!evt || !evt.data) return;
        try {
          const payload = JSON.parse(evt.data);
          if (typeof onEvent === "function") onEvent(payload);
        } catch (e) {}
      };
      source.onerror = (evt) => {
        if (typeof onError === "function") onError(evt);
      };
      return source;
    }

    // With auth headers we use fetch streaming (EventSource can't send headers).
    const ctrl = new AbortController();
    fetch(url, {
      method: "GET",
      headers,
      signal: ctrl.signal,
    }).then((res) => _consumeSseStream(res, onEvent, onError, ctrl.signal));
    return { close: () => { try { ctrl.abort(); } catch (e) {} } };
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


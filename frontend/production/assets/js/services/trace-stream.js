(function () {
  const App = window.App = window.App || {};
  const config = App.config || {};
  const { API_BASE, TRACE_STREAM_PATH } = config;

  function startTraceStream({ runId, onEvent, onError }) {
    if (!runId) return null;
    const url = `${API_BASE}${TRACE_STREAM_PATH}?run_id=${encodeURIComponent(runId)}`;
    const source = new EventSource(url);

    source.onmessage = (evt) => {
      if (!evt || !evt.data) return;
      let payload = null;
      try { payload = JSON.parse(evt.data); } catch (e) { return; }
      if (typeof onEvent === "function") onEvent(payload);
    };

    source.onerror = (evt) => {
      if (typeof onError === "function") onError(evt);
    };

    return source;
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

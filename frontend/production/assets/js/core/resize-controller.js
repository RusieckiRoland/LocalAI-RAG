(function () {
  const callbacks = new Set();

  function emitResize() {
    const size = {
      width: window.innerWidth,
      height: window.innerHeight,
    };
    callbacks.forEach((cb) => {
      try {
        cb(size);
      } catch (_) {
        // ignore
      }
    });
  }

  function registerResizeHandler(cb) {
    if (typeof cb === "function") {
      callbacks.add(cb);
      cb({ width: window.innerWidth, height: window.innerHeight });
    }
  }

  function initResizeController() {
    window.addEventListener("resize", emitResize);
  }

  window.registerResizeHandler = registerResizeHandler;
  window.initResizeController = initResizeController;
})();

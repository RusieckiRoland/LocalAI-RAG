(function () {
  const THEME_MODE_STORAGE_KEY = "ui_theme";
  let mediaListener = null;

  function getSystemTheme() {
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    return prefersDark ? "dark" : "light";
  }

  function renderThemeButton(mode, effectiveTheme) {
    const btn = document.getElementById("themeToggleBtn");
    if (!btn) return;
    const icon = btn.querySelector(".theme-icon");
    if (icon) {
      icon.textContent = mode === "system" ? "◐" : (effectiveTheme === "dark" ? "☀️" : "🌙");
    }
    const title =
      mode === "system"
        ? "Motyw: system"
        : (effectiveTheme === "dark" ? "Motyw: noc" : "Motyw: dzien");
    btn.setAttribute("title", title);
  }

  function applyThemeMode(mode) {
    const nextMode = (mode === "light" || mode === "dark" || mode === "system") ? mode : "system";
    const effective = nextMode === "system" ? getSystemTheme() : nextMode;
    document.body.setAttribute("data-theme", effective);
    document.body.setAttribute("data-theme-mode", nextMode);
    renderThemeButton(nextMode, effective);
    localStorage.setItem(THEME_MODE_STORAGE_KEY, nextMode);

    // Track system changes only in system mode.
    if (mediaListener) {
      try { mediaListener.mql.removeEventListener("change", mediaListener.fn); } catch (e) {}
      mediaListener = null;
    }
    if (nextMode === "system" && window.matchMedia) {
      const mql = window.matchMedia("(prefers-color-scheme: dark)");
      const fn = () => {
        const sys = getSystemTheme();
        document.body.setAttribute("data-theme", sys);
        renderThemeButton("system", sys);
      };
      try { mql.addEventListener("change", fn); } catch (e) {}
      mediaListener = { mql, fn };
    }
  }

  function initTheme() {
    const stored = localStorage.getItem(THEME_MODE_STORAGE_KEY);
    // Backward compatible: treat legacy "light"/"dark" as explicit modes.
    if (stored === "dark" || stored === "light" || stored === "system") {
      applyThemeMode(stored);
      return;
    }
    applyThemeMode("system");
  }

  function wireThemeToggle() {
    const btn = document.getElementById("themeToggleBtn");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const currentMode = document.body.getAttribute("data-theme-mode") || "system";
      const next =
        currentMode === "system" ? "light" :
        currentMode === "light" ? "dark" :
        "system";
      applyThemeMode(next);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    wireThemeToggle();
  });
})();

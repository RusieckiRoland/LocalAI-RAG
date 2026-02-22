(function () {
  const THEME_STORAGE_KEY = "ui_theme";

  function applyTheme(theme) {
    const next = theme === "dark" ? "dark" : "light";
    document.body.setAttribute("data-theme", next);
    const btn = document.getElementById("themeToggleBtn");
    if (btn) {
      const icon = btn.querySelector(".theme-icon");
      if (icon) {
        icon.textContent = next === "dark" ? "☀️" : "🌙";
      }
      btn.setAttribute("title", next === "dark" ? "Tryb dzienny" : "Tryb nocny");
    }
    localStorage.setItem(THEME_STORAGE_KEY, next);
  }

  function initTheme() {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "dark" || stored === "light") {
      applyTheme(stored);
      return;
    }
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(prefersDark ? "dark" : "light");
  }

  function wireThemeToggle() {
    const btn = document.getElementById("themeToggleBtn");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const current = document.body.getAttribute("data-theme") || "light";
      applyTheme(current === "dark" ? "light" : "dark");
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    wireThemeToggle();
  });
})();

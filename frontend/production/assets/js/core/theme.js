(function () {
  const THEME_MODE_STORAGE_KEY = "ui_theme";
  let mediaListener = null;

  function normalizeLang(raw) {
    const value = String(raw || "").trim().toLowerCase();
    const base = value.split("-", 1)[0];
    return base === "pl" ? "pl" : "en";
  }

  function resolveLang(explicit) {
    if (explicit) return normalizeLang(explicit);
    let fromDoc = "";
    try { fromDoc = String(document.documentElement.getAttribute("lang") || ""); } catch (e) {}
    if (fromDoc) return normalizeLang(fromDoc);
    let stored = "";
    try { stored = String(localStorage.getItem("lang") || ""); } catch (e) {}
    return normalizeLang(stored);
  }

  function themeLabels(explicitLang) {
    const lang = resolveLang(explicitLang);
    if (lang === "pl") {
      return {
        buttonLabel: "Tryb dzień/noc",
        titlePrefix: "Tryb",
        system: "System",
        light: "Dzień",
        dark: "Noc",
      };
    }
    return {
      buttonLabel: "Day/night mode",
      titlePrefix: "Mode",
      system: "System",
      light: "Day",
      dark: "Night",
    };
  }

  function getSystemTheme() {
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    return prefersDark ? "dark" : "light";
  }

  function renderThemeButton(mode, effectiveTheme, explicitLang) {
    const btn = document.getElementById("themeToggleBtn");
    if (!btn) return;
    const labels = themeLabels(explicitLang);
    const icon = btn.querySelector(".theme-icon");
    if (icon) {
      icon.textContent = mode === "system" ? "◐" : (effectiveTheme === "dark" ? "☀" : "☾");
    }
    const value =
      mode === "system"
        ? labels.system
        : (effectiveTheme === "dark" ? labels.dark : labels.light);
    const title = `${labels.titlePrefix}: ${value}`;
    const label = document.getElementById("themeToggleLabel");
    if (label) label.textContent = labels.buttonLabel;
    const valueNode = document.getElementById("themeToggleValue");
    if (valueNode) valueNode.textContent = value;
    btn.setAttribute("title", title);
    btn.setAttribute("aria-label", `${labels.buttonLabel}: ${value}`);
  }

  function applyThemeMode(mode, explicitLang) {
    const nextMode = (mode === "light" || mode === "dark" || mode === "system") ? mode : "system";
    const effective = nextMode === "system" ? getSystemTheme() : nextMode;
    document.body.setAttribute("data-theme", effective);
    document.body.setAttribute("data-theme-mode", nextMode);
    renderThemeButton(nextMode, effective, explicitLang);
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

  function refreshThemeLabels(lang) {
    const mode = document.body.getAttribute("data-theme-mode") || "system";
    const effective = document.body.getAttribute("data-theme") || getSystemTheme();
    renderThemeButton(mode, effective, lang);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    wireThemeToggle();
  });

  document.addEventListener("localai:lang", (e) => {
    const lang = e && e.detail ? e.detail.lang : "";
    refreshThemeLabels(lang);
  });
})();

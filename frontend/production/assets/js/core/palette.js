(function () {
  const STORAGE_KEY = "ui_palette";
  // User-facing modes:
  // - normal: previous palette (we keep it for comparison)
  // - strong: WCAG-oriented palette (default)
  const PALETTES = ["normal", "strong"];

  function _normalizeLang(raw) {
    const v = String(raw || "").trim().toLowerCase();
    const base = v.split("-", 1)[0];
    return base === "pl" ? "pl" : "en";
  }

  function _resolveLang(explicit) {
    if (explicit) return _normalizeLang(explicit);
    let fromDoc = "";
    try { fromDoc = String(document.documentElement.getAttribute("lang") || ""); } catch (e) {}
    if (fromDoc) return _normalizeLang(fromDoc);
    let stored = "";
    try { stored = String(localStorage.getItem("lang") || ""); } catch (e) {}
    return _normalizeLang(stored);
  }

  function _labelsForLang(lang) {
    const l = _resolveLang(lang);
    if (l === "pl") {
      return { normal: "Normalny", strong: "Wyraźniejsze obrysy", titlePrefix: "Paleta" };
    }
    return { normal: "Normal", strong: "Sharper outlines", titlePrefix: "Palette" };
  }

  function _normalizeStored(raw) {
    const v = String(raw || "").trim().toLowerCase();
    // Backward compatible with earlier values.
    if (v === "legacy") return "normal";
    if (v === "wcag") return "strong";
    if (v === "normal" || v === "strong") return v;
    return "strong";
  }

  function refreshPaletteLabels(lang) {
    const current = _normalizeStored(document.body.getAttribute("data-palette") || "");
    const labels = _labelsForLang(lang);

    const btn = document.getElementById("paletteToggleBtn");
    if (!btn) return;
    const isOn = current === "strong";
    const label = current === "normal" ? labels.normal : labels.strong;
    btn.setAttribute("title", `${labels.titlePrefix}: ${label}`);
    btn.setAttribute("aria-checked", isOn ? "true" : "false");
    btn.classList.toggle("is-on", isOn);
    const text = document.getElementById("paletteToggleLabel");
    if (text) text.textContent = label;
  }

  function applyPalette(name, lang) {
    const next = _normalizeStored(name);
    document.body.setAttribute("data-palette", next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch (e) {}
    refreshPaletteLabels(lang);
  }

  function initPalette() {
    let stored = "";
    try { stored = String(localStorage.getItem(STORAGE_KEY) || ""); } catch (e) {}
    applyPalette(stored);
  }

  function wirePaletteToggle() {
    const btn = document.getElementById("paletteToggleBtn");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const current = _normalizeStored(document.body.getAttribute("data-palette") || "");
      const next = current === "strong" ? "normal" : "strong";
      applyPalette(next);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initPalette();
    wirePaletteToggle();
  });

  // Keep labels in sync when UI language changes (main.js dispatches this event).
  document.addEventListener("localai:lang", (e) => {
    const lang = e && e.detail ? e.detail.lang : "";
    refreshPaletteLabels(lang);
  });

  // For debugging / manual refresh (kept under a namespaced key).
  try {
    window.__localaiRagPalette = window.__localaiRagPalette || {};
    window.__localaiRagPalette.refreshLabels = refreshPaletteLabels;
  } catch (e) {}
})();

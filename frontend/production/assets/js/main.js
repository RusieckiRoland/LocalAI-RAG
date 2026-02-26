  // English comments only.

  const {
    API_BASE,
    URL_MODE,
    IS_FILE_MODE,
    APP_MODE,
    APP_CONFIG_PATH,
    SEARCH_PATH,
    CANCEL_PATH,
    TRACE_STREAM_PATH,
    DEFAULT_APP_CONFIG,
    HISTORY_STORAGE_KEY,
    HISTORY_SEARCH_PAGE_SIZE,
    MAX_BRANCH_LABEL_LEN,
  } = (window.App && window.App.config) || {};

  const publicCfg = (window.__RAG_PUBLIC_CONFIG__ && typeof window.__RAG_PUBLIC_CONFIG__ === "object")
    ? window.__RAG_PUBLIC_CONFIG__
    : {};
  const fakeLoginRequired = !!publicCfg.fake_login_required;
  const fakeUsers = Array.isArray(publicCfg.fake_users) ? publicCfg.fake_users.slice() : [];
  const oidc = (window.App && window.App.services && window.App.services.oidc) || null;
  const oidcEnabled = !!(oidc && typeof oidc.isEnabled === "function" && oidc.isEnabled() && !fakeLoginRequired);

  let sessionId = localStorage.getItem("sessionId") || null;

  let selectedConsultant = null;
  let appConfig = null;
  let consultantsById = {};
  let snapshotPolicy = "single";
  let currentSnapshotSetId = localStorage.getItem("snapshotSetId") || null;
  let currentSnapshotId = localStorage.getItem("snapshotId") || null;
  let currentSnapshotLabel = localStorage.getItem("snapshotLabel") || null;
  let conversationSnapshotSetId = localStorage.getItem("conversationSnapshotSetId") || null;

  let selectedSnapshotA = null;
  let selectedSnapshotB = null;
  let isQueryInProgress = false;

  let fakeAuthEnabled = false;
  let activeDevUserId = "";
  let isMultilingualProject = true;
  let neutralLanguageCode = "en";
  let translatedLanguageCode = "pl";
  let historyStore = null;
  let historyBackendAvailable = true;
  let activeHistorySessionId = null;
  let historySearchQuery = "";
  let historyCollapsed = false;
  let historySearchModalOpen = false;
  let historySearchModalQuery = "";
  let historySearchModalCursor = null;
  let historySearchModalLoading = false;
  let historySearchModalItems = [];
  const historyGroupCollapsed = {};
  let historySearchModalOnlyImportant = false;
  let historyOpenMenu = null;
  let renameTargetSessionId = null;
  let historyContextTarget = null;

  const {
    form,
    queryInput,
    responseDiv,
    submitButton,
    welcomeMessage,
    langSelect,
    consultantsContainer,
    newChatBtn,
    uiError,
    branchControls,
    controlsSpacer,
    authToggleBtn,
    authControls,
    authCompact,
    authCompactBtn,
    authCompactUserName,
    authCompactUserInitials,
    authCompactMenu,
    authCompactAction,
    authCompactActionLabel,
    authCompactActionIcon,
    authCompactClearHistory,
    authCompactClearHistoryLabel,
    historyPanel,
    historyCollapseBtn,
    historyExpandBtn,
    historyCompactNewChatBtn,
    historyCompactSearchBtn,
    historyNewChatBtn,
    historySearchInput,
    historySearchBtn,
    historySectionTitle,
    historyList,
    historyEmpty,
    snapshotModalBackdrop,
    snapshotModalTitle,
    snapshotModalBody,
    snapshotModalCancel,
    snapshotModalConfirm,
    traceList,
    traceTitle,
    traceStatus,
    traceFilterInput,
    traceDocFilterWrap,
    traceDocFilterInput,
    traceFilterClearBtn,
    traceFilterEmpty,
    traceHandle,
    traceCloseBtn,
    traceBackdrop,
    queryProgress,
    traceDocModalBackdrop,
    traceDocModalTitle,
    traceDocModalBody,
    traceDocModalCount,
    traceDocPrevBtn,
    traceDocNextBtn,
    traceDocModalClose,
    historySearchModalBackdrop,
    historySearchModalTitle,
    historySearchModalInput,
    historySearchModalList,
    historySearchModalEmpty,
    historySearchModalMore,
    historySearchModalClose,
    historySearchModalCount,
    historySearchModalImportant,
    historySearchModalImportantLabel,
    renameChatModalBackdrop,
    renameChatModalTitle,
    renameChatModalLabel,
    renameChatInput,
    renameChatModalCancel,
    renameChatModalConfirm,
    clearHistoryModalBackdrop,
    clearHistoryModalTitle,
    clearHistoryModalBody,
    clearHistoryModalCancel,
    clearHistoryModalConfirm,
    historyContextMenu,
    historyContextRename,
    historyContextImportant,
    historyContextDelete,
    historyContextClearAll,
    historyContextRenameLabel,
    historyContextImportantLabel,
    historyContextDeleteLabel,
    historyContextClearAllLabel,
    fakeLoginBackdrop,
    fakeLoginSelect,
    fakeLoginConfirm,
  } = (window.App && window.App.dom) || {};
  const api = (window.App && window.App.services && window.App.services.api) || null;
  const historyApi = (window.App && window.App.services && window.App.services.historyStore) || null;
  const traceApi = (window.App && window.App.services && window.App.services.traceStream) || null;

  // If name is longer than this, we shorten it in CLOSED state.
  // In compare mode we also shorten even if it's below the threshold (to make differences obvious).
  let traceSource = null;
  let currentTraceRunId = null;
  let traceEventCount = 0;
  let traceStatusKey = "idle";
  let traceStatusArg = null;
  let traceFilterQuery = "";
  let traceDocFilterQuery = "";
  let traceLastSearchTarget = null;
  const TRACE_FILTER_MAX_TOTAL_CHARS = 24000;
  const TRACE_FILTER_MAX_TOKEN_CHARS = 1200;
  let traceDocSeq = 0;
  const traceDocsByKey = {};
  let traceDocBatchSeq = 0;
  const traceDocBatches = {};
  let traceDocModalKeys = [];
  let traceDocModalIndex = -1;
  let traceDocTotal = 0;
  let activeAbortController = null;
  let requestInFlight = false;

  function hasConsultants(cfg) {
    return !!(cfg && Array.isArray(cfg.consultants) && cfg.consultants.length > 0);
  }

  function cloneDefaultAppConfig() {
    return JSON.parse(JSON.stringify(DEFAULT_APP_CONFIG));
  }

  function getHistoryUserKey() {
    if (fakeAuthEnabled && activeDevUserId) return `user:${activeDevUserId}`;
    return "user:missing";
  }

  async function loadHistoryStore() {
    historyStore = {};
    historyBackendAvailable = true;
    try {
      if (!historyApi || !historyApi.fetchSessions) {
        throw new Error("History API not ready");
      }
      const json = await historyApi.fetchSessions({
        limit: 200,
        fakeAuthEnabled,
        activeDevUserId
      });
      const sessions = Array.isArray(json.items) ? json.items : [];
      historyStore = { sessions };
    } catch (e) {
      historyBackendAvailable = false;
    }
  }

  function saveHistoryStore() {
    // No-op: history is persisted server-side.
  }

  function ensureUserHistory() {
    if (!historyStore) historyStore = {};
    if (!historyStore.sessions) historyStore.sessions = [];
    return historyStore;
  }

  function getUserSessions() {
    const user = ensureUserHistory();
    return Array.isArray(user.sessions) ? user.sessions : [];
  }

  function setUserSessions(sessions) {
    if (!historyStore) historyStore = {};
    historyStore.sessions = sessions || [];
    saveHistoryStore();
  }

  function slugifyTitle(text) {
    const raw = String(text || "").trim();
    if (!raw) return "";
    return raw.replace(/\s+/g, " ").slice(0, 64);
  }

  function buildHistoryItemTitle(session) {
    if (!session) return "";
    return slugifyTitle(session.title || session.firstQuestion || "New chat") || "New chat";
  }

  function isHistoryImportant(session) {
    return !!(session && session.important);
  }

  function getHistoryImportantConfig() {
    return (appConfig && appConfig.historyImportant) || DEFAULT_APP_CONFIG.historyImportant || {};
  }

  function getHistoryImportantLabel() {
    const cfg = getHistoryImportantConfig();
    const lang = getCurrentLang();
    if (lang === "pl") return String(cfg.translated_description || cfg.neutral_description || "").trim();
    return String(cfg.neutral_description || cfg.translated_description || "").trim();
  }

  function getHistoryGroupsConfig() {
    const cfg = (appConfig && appConfig.historyGroups) || DEFAULT_APP_CONFIG.historyGroups || [];
    return Array.isArray(cfg) ? cfg : [];
  }

  function getHistoryGroupLabel(group) {
    const lang = getCurrentLang();
    if (lang === "pl") return String((group && group.translated_description) || (group && group.neutral_description) || "").trim();
    return String((group && group.neutral_description) || (group && group.translated_description) || "").trim();
  }

  function resolveHistoryGroupRange(formula, nowMs) {
    if (!formula || !formula.type) return null;
    const type = String(formula.type || "").trim().toLowerCase();
    if (type === "today") {
      const d = new Date(nowMs);
      d.setHours(0, 0, 0, 0);
      return { startMs: d.getTime(), endMs: nowMs };
    }
    if (type === "last_n_days") {
      const days = parseInt(formula.days || 0, 10);
      if (!Number.isFinite(days) || days <= 0) return null;
      const todayStart = new Date(nowMs);
      todayStart.setHours(0, 0, 0, 0);
      return { startMs: todayStart.getTime() - (days * 86400000), endMs: todayStart.getTime() };
    }
    return null;
  }

  function appendHistoryItem(s) {
    const title = buildHistoryItemTitle(s);
    const item = document.createElement("div");
    item.className = "history-item";
    if (activeHistorySessionId && s.sessionId === activeHistorySessionId) {
      item.classList.add("active");
    }
    const t1 = document.createElement("div");
    t1.className = "history-item-title";
    const titleText = document.createElement("span");
    titleText.className = "history-item-title-text";
    titleText.textContent = title;
    t1.appendChild(titleText);
    if (isHistoryImportant(s)) {
      const badge = document.createElement("span");
      badge.className = "history-item-badge";
      badge.textContent = "!";
      t1.appendChild(badge);
    }
    const t2 = document.createElement("div");
    t2.className = "history-item-meta";
    t2.textContent = s.updatedAt ? new Date(s.updatedAt).toLocaleString(getTexts(getCurrentLang()).locale) : "";
    item.appendChild(t1);
    item.appendChild(t2);
    const actionsWrap = document.createElement("div");
    actionsWrap.className = "history-item-actions";
    const menuBtn = document.createElement("button");
    menuBtn.type = "button";
    menuBtn.setAttribute("aria-label", "Menu");
    menuBtn.textContent = "⋯";
    actionsWrap.appendChild(menuBtn);
    item.appendChild(actionsWrap);
    item.addEventListener("click", () => {
      loadHistorySession(s.sessionId);
    });
    menuBtn.addEventListener("click", (evt) => {
      evt.stopPropagation();
      openHistoryContextMenu({ session: s, anchor: menuBtn });
    });
    historyList.appendChild(item);
  }

  function renderHistoryList() {
    if (!historyList || !historyEmpty) return;
    const sessionsRaw = getUserSessions();
    const seen = new Set();
    const sessions = [];
    sessionsRaw.forEach((s) => {
      const sid = String((s && s.sessionId) || "");
      if (!sid || seen.has(sid)) return;
      seen.add(sid);
      sessions.push(s);
    });
    const q = normalizeTraceFilterQuery(historySearchQuery);
    historyList.innerHTML = "";
    let visible = 0;
    const groups = getHistoryGroupsConfig();
    if (!groups.length) {
      sessions.forEach((s) => {
        const title = buildHistoryItemTitle(s);
        const hay = `${title} ${(s.consultantId || "")}`.toLowerCase();
        if (q && !hay.includes(q)) return;
        visible += 1;
        appendHistoryItem(s);
      });
      historyEmpty.style.display = visible === 0 ? "block" : "none";
      return;
    }

    const assigned = new Set();
    const now = Date.now();
    const importantCfg = getHistoryImportantConfig();
    const showImportantTop = importantCfg && importantCfg.show_important_on_the_top !== false;
    const importantLabel = getHistoryImportantLabel();
    const importantItems = sessions.filter((s) => {
      if (!isHistoryImportant(s)) return false;
      const title = buildHistoryItemTitle(s);
      const hay = `${title} ${(s.consultantId || "")}`.toLowerCase();
      if (q && !hay.includes(q)) return false;
      return true;
    });
    const renderGroup = (label, groupKey, items, includeEmpty) => {
      if (label) {
        const titleEl = document.createElement("div");
        const collapsed = !!historyGroupCollapsed[groupKey];
        titleEl.className = `history-group-title${collapsed ? " is-collapsed" : ""}`;
        titleEl.dataset.groupKey = groupKey;
        titleEl.addEventListener("click", () => {
          historyGroupCollapsed[groupKey] = !historyGroupCollapsed[groupKey];
          renderHistoryList();
        });
        const caret = document.createElement("span");
        caret.className = "history-group-caret";
        caret.textContent = "▾";
        const labelEl = document.createElement("span");
        labelEl.textContent = label;
        titleEl.appendChild(caret);
        titleEl.appendChild(labelEl);
        historyList.appendChild(titleEl);
      }
      if (historyGroupCollapsed[groupKey]) return;
      if (!items.length) {
        if (!includeEmpty) return;
        const emptyEl = document.createElement("div");
        emptyEl.className = "history-empty-group";
        emptyEl.textContent = getTexts(getCurrentLang()).historyEmpty || "Brak historii";
        historyList.appendChild(emptyEl);
        return;
      }
      items.forEach((s) => {
        visible += 1;
        appendHistoryItem(s);
      });
    };

    if (showImportantTop && importantItems.length) {
      renderGroup(importantLabel, "important", importantItems, false);
    }

    groups.forEach((group, idx) => {
      const range = resolveHistoryGroupRange((group && group.formula), now);
      if (!range) return;
      const label = getHistoryGroupLabel(group);
      const groupKey = String((group && group.neutral_description) || label || idx);
      const items = sessions.filter((s) => {
        if (!s || assigned.has(s.sessionId)) return false;
        const ts = Number(s.updatedAt || 0);
        if (!ts || ts < range.startMs || ts > range.endMs) return false;
        const title = buildHistoryItemTitle(s);
        const hay = `${title} ${(s.consultantId || "")}`.toLowerCase();
        if (q && !hay.includes(q)) return false;
        return true;
      });
      items.forEach((s) => assigned.add(s.sessionId));
      renderGroup(label, groupKey, items, true);
    });
    historyEmpty.style.display = groups.length ? "none" : (visible === 0 ? "block" : "none");
  }

  function setHistorySearchModalVisible(show) {
    historySearchModalOpen = !!show;
    if (!historySearchModalBackdrop) return;
    historySearchModalBackdrop.style.display = historySearchModalOpen ? "flex" : "none";
    if (historySearchModalOpen) {
      if (historySearchModalInput) {
        historySearchModalInput.focus();
        historySearchModalInput.select();
      }
    }
  }

  function resetHistorySearchModal() {
    historySearchModalItems = [];
    historySearchModalCursor = null;
    historySearchModalQuery = "";
    historySearchModalLoading = false;
    if (historySearchModalInput) historySearchModalInput.value = "";
    renderHistorySearchResults();
  }

  function renderHistorySearchResults() {
    if (!historySearchModalList || !historySearchModalEmpty) return;
    historySearchModalList.innerHTML = "";
    const filtered = historySearchModalOnlyImportant
      ? historySearchModalItems.filter((s) => isHistoryImportant(s))
      : historySearchModalItems;
    filtered.forEach((s) => {
      const row = document.createElement("div");
      row.className = "history-search-item";
      const left = document.createElement("div");
      left.className = "history-search-item-title";
      left.textContent = buildHistoryItemTitle(s);
      const right = document.createElement("div");
      right.className = "history-search-item-meta";
      right.textContent = s.updatedAt ? new Date(s.updatedAt).toLocaleString(getTexts(getCurrentLang()).locale) : "";
      row.appendChild(left);
      row.appendChild(right);
      row.addEventListener("click", () => {
        loadHistorySession(s.sessionId);
        setHistorySearchModalVisible(false);
      });
      const actions = document.createElement("button");
      actions.type = "button";
      actions.className = "history-search-mark";
      actions.textContent = isHistoryImportant(s)
        ? (getTexts(getCurrentLang()).historyUnmarkImportant || "Usuń z ważnych")
        : (getTexts(getCurrentLang()).historyMarkImportant || "Oznacz jako ważne");
      actions.addEventListener("click", (evt) => {
        evt.stopPropagation();
        updateHistorySessionMeta(s.sessionId, { important: !isHistoryImportant(s) });
        renderHistorySearchResults();
      });
      row.appendChild(actions);
      historySearchModalList.appendChild(row);
    });
    const empty = filtered.length === 0;
    historySearchModalEmpty.style.display = empty ? "block" : "none";
    if (historySearchModalMore) {
      historySearchModalMore.style.display = historySearchModalCursor ? "inline-flex" : "none";
      historySearchModalMore.disabled = historySearchModalLoading;
    }
    if (historySearchModalCount) {
      historySearchModalCount.textContent = filtered.length ? `${filtered.length}` : "";
    }
  }

  async function fetchHistorySearchPage({ query, cursor }) {
    if (historySearchModalLoading) return;
    historySearchModalLoading = true;
    renderHistorySearchResults();
    const q = String(query || "").trim();
    if (historyBackendAvailable) {
      try {
        if (!historyApi || !historyApi.searchSessions) {
          throw new Error("History API not ready");
        }
        const json = await historyApi.searchSessions({
          query: q,
          cursor,
          limit: HISTORY_SEARCH_PAGE_SIZE,
          fakeAuthEnabled,
          activeDevUserId
        });
        const items = Array.isArray(json.items) ? json.items : [];
        historySearchModalItems = historySearchModalItems.concat(items);
        historySearchModalCursor = json.next_cursor || null;
      } catch (e) {
        historyBackendAvailable = false;
      }
    }

    if (!historyBackendAvailable) {
      const sessions = getUserSessions();
      const all = q
        ? sessions.filter((s) => (buildHistoryItemTitle(s) || "").toLowerCase().includes(q.toLowerCase()))
        : sessions.slice();
      const start = cursor ? parseInt(cursor, 10) : 0;
      const slice = all.slice(start, start + HISTORY_SEARCH_PAGE_SIZE);
      historySearchModalItems = historySearchModalItems.concat(slice);
      historySearchModalCursor = (start + slice.length) < all.length ? String(start + slice.length) : null;
    }

    historySearchModalLoading = false;
    renderHistorySearchResults();
  }

  function openHistorySearchModal() {
    resetHistorySearchModal();
    setHistorySearchModalVisible(true);
  }

  function closeHistoryContextMenu() {
    if (!historyContextMenu) return;
    historyContextMenu.classList.remove("is-open");
    historyContextTarget = null;
  }

  function openHistoryContextMenu({ session, anchor }) {
    if (!historyContextMenu || !anchor) return;
    historyContextTarget = session;
    const rect = anchor.getBoundingClientRect();
    historyContextMenu.style.top = `${Math.min(window.innerHeight - 10, rect.bottom + 6)}px`;
    historyContextMenu.style.left = `${Math.min(window.innerWidth - 200, rect.left - 140)}px`;
    historyContextMenu.classList.add("is-open");
    if (historyContextImportantLabel) {
      historyContextImportantLabel.textContent = isHistoryImportant(session)
        ? (getTexts(getCurrentLang()).historyUnmarkImportant || "Usuń z ważnych")
        : (getTexts(getCurrentLang()).historyMarkImportant || "Oznacz jako ważne");
    }
  }

  function setRenameChatModalVisible(show) {
    if (!renameChatModalBackdrop) return;
    renameChatModalBackdrop.style.display = show ? "flex" : "none";
    if (show && renameChatInput) {
      renameChatInput.focus();
      renameChatInput.select();
    }
  }

  function openRenameChatModal(sessionId, currentTitle) {
    renameTargetSessionId = sessionId;
    if (renameChatInput) {
      renameChatInput.value = currentTitle || "";
    }
    setRenameChatModalVisible(true);
  }

  function setClearHistoryModalVisible(show) {
    if (!clearHistoryModalBackdrop) return;
    clearHistoryModalBackdrop.style.display = show ? "flex" : "none";
  }

  function openClearHistoryModal() {
    const t = getTexts(getCurrentLang());
    if (clearHistoryModalTitle) {
      clearHistoryModalTitle.textContent = t.historyClearModalTitle || t.historyClear;
    }
    if (clearHistoryModalBody) {
      clearHistoryModalBody.textContent = t.historyClearConfirm || "Czy na pewno chcesz usunąć swoją historię?";
    }
    if (clearHistoryModalConfirm) {
      clearHistoryModalConfirm.textContent = t.historyClearModalConfirm || t.historyClear;
    }
    if (clearHistoryModalCancel) {
      clearHistoryModalCancel.textContent = t.historyClearModalCancel || t.modalCancel || "Anuluj";
    }
    setClearHistoryModalVisible(true);
  }

  function updateHistorySessionMeta(sessionId, patch) {
    const now = Date.now();
    const sessions = getUserSessions();
    const next = sessions.map((s) => {
      if (s.sessionId !== sessionId) return s;
      const updated = { ...s, ...patch, updatedAt: now };
      return updated;
    });
    setUserSessions(next);
    renderHistoryList();
    if (!historyBackendAvailable) return;
    if (!historyApi || !historyApi.patchSession) return;
    historyApi.patchSession({
      sessionId,
      patch,
      fakeAuthEnabled,
      activeDevUserId
    }).catch(() => {});
  }

  function updateAuthUi() {
    const t = getTexts(getCurrentLang());
    if (fakeLoginRequired) {
      fakeAuthEnabled = true;
      localStorage.setItem("fakeAuthEnabled", "1");
    }
    if (authToggleBtn) {
      const on = oidcEnabled
        ? (oidc && typeof oidc.getAccessToken === "function" && !!oidc.getAccessToken())
        : fakeAuthEnabled;
      authToggleBtn.classList.toggle("active", on);
      authToggleBtn.textContent = on ? t.authLogout : t.authLogin;
      if (fakeLoginRequired) authToggleBtn.style.display = "none";
    }
    if (authControls) {
      authControls.classList.toggle("active", fakeAuthEnabled);
      if (fakeLoginRequired) authControls.style.display = "none";
    }
    if (authCompactActionLabel) {
      if (oidcEnabled) {
        const hasOidc = oidc && typeof oidc.getAccessToken === "function" && !!oidc.getAccessToken();
        authCompactActionLabel.textContent = hasOidc ? t.authLogout : t.authLogin;
      } else {
        authCompactActionLabel.textContent = fakeAuthEnabled ? t.authLogout : t.authLogin;
      }
    }
    if (authCompactActionIcon) {
      const on = oidcEnabled
        ? (oidc && typeof oidc.getAccessToken === "function" && !!oidc.getAccessToken())
        : fakeAuthEnabled;
      authCompactActionIcon.innerHTML = on
        ? '<svg viewBox="0 0 24 24"><path d="M14 7v-2H5v14h9v-2h2v4H3V3h13v4zM16 13v3l5-4-5-4v3H9v2h7z"/></svg>'
        : '<svg viewBox="0 0 24 24"><path d="M10 17v-2h7V9h-7V7h9v10h-9zm-2-4V9l-5 4 5 4z"/></svg>';
    }
    if (authCompactUserName || authCompactUserInitials || authCompactBtn) {
      let label = "";
      if (fakeAuthEnabled) {
        const currentId = String(activeDevUserId || "").trim();
        const user = fakeUsers.find((u) => String(u.id || "") === currentId) || null;
        label = user ? String(user.userName || user.id || "").trim() : "";
      } else if (oidcEnabled && oidc && typeof oidc.getUserName === "function") {
        label = String(oidc.getUserName() || "").trim();
      }
      const initials = label ? getInitialsFromName(label) : "";
      if (authCompactUserName) authCompactUserName.textContent = label;
      if (authCompactUserInitials) authCompactUserInitials.textContent = initials;
      if (authCompactBtn) authCompactBtn.classList.toggle("has-user", !!label);
    }
  }

  function isValidFakeUserId(userId) {
    const id = String(userId || "").trim();
    if (!id) return false;
    return fakeUsers.some((u) => String(u.id || "") === id);
  }

  function getInitialsFromName(fullName) {
    const s = String(fullName || "").trim();
    if (!s) return "";
    const parts = s.split(/\s+/g).filter(Boolean);
    if (parts.length === 0) return "";
    const first = parts[0] || "";
    const last = parts.length > 1 ? parts[parts.length - 1] : "";
    const i1 = first ? first.slice(0, 1).toUpperCase() : "";
    const i2 = last ? last.slice(0, 1).toUpperCase() : "";
    return (i1 && i2) ? `${i1} ${i2}` : (i1 || i2);
  }

  function showFakeLoginModal(show) {
    if (!fakeLoginBackdrop) return;
    fakeLoginBackdrop.style.display = show ? "flex" : "none";
    if (show && fakeLoginSelect) {
      fakeLoginSelect.innerHTML = "";
      fakeUsers.forEach((u) => {
        const opt = document.createElement("option");
        opt.value = String(u.id || "");
        opt.textContent = String(u.userName || u.id || "");
        fakeLoginSelect.appendChild(opt);
      });
      if (activeDevUserId && isValidFakeUserId(activeDevUserId)) {
        fakeLoginSelect.value = activeDevUserId;
      }
    }
  }
  function deleteHistorySession(sessionId) {
    const now = Date.now();
    const sessions = getUserSessions().map((s) => {
      if (s.sessionId !== sessionId) return s;
      return { ...s, softDeletedAt: now, status: "soft_deleted", updatedAt: now };
    }).filter((s) => !s.softDeletedAt);
    setUserSessions(sessions);
    if (activeHistorySessionId === sessionId) {
      activeHistorySessionId = null;
    }
    renderHistoryList();
    if (!historyBackendAvailable) return;
    if (!historyApi || !historyApi.deleteSession) return;
    historyApi.deleteSession({
      sessionId,
      fakeAuthEnabled,
      activeDevUserId
    }).catch(() => {});
  }

  function clearAllHistoryConfirmed() {
    const now = Date.now();
    const sessions = getUserSessions().map((s) => ({
      ...s,
      softDeletedAt: now,
      status: "soft_deleted",
      updatedAt: now,
    }));
    setUserSessions([]);
    activeHistorySessionId = null;
    renderHistoryList();
    if (!historyBackendAvailable) return;
    sessions.forEach((s) => {
      if (!historyApi || !historyApi.patchSession) return;
      historyApi.patchSession({
        sessionId: s.sessionId,
        patch: { softDeleted: true },
        fakeAuthEnabled,
        activeDevUserId
      }).catch(() => {});
    });
  }

  function clearAllHistory() {
    openClearHistoryModal();
  }

  function setHistoryCollapsed(next) {
    historyCollapsed = !!next;
    document.body.classList.toggle("history-collapsed", historyCollapsed);
    try {
      localStorage.setItem("historyCollapsed", historyCollapsed ? "1" : "0");
    } catch (e) {}
  }

  function updateHistoryOverlayMode() {
    const root = getComputedStyle(document.documentElement);
    const contentMax = parseInt(root.getPropertyValue("--content-max-width"), 10) || 1050;
    const historyW = parseInt(root.getPropertyValue("--history-width"), 10) || 280;
    const padding = 64;
    const needsOverlay = window.innerWidth < (contentMax + historyW + padding);
    document.body.classList.toggle("history-overlay", needsOverlay);
  }

  function persistSessionUpdate(sessionId, updater) {
    const sessions = getUserSessions();
    let found = false;
    const next = sessions.map((s) => {
      if (s.sessionId !== sessionId) return s;
      found = true;
      return updater(s);
    });
    if (!found) return;
    next.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    setUserSessions(next);
  }

  async function upsertHistorySession({ sessionId, consultantId, snapshotSetId, snapshots, question, answer }) {
    const now = Date.now();
    const sessions = getUserSessions();
    let existing = sessions.find((s) => s.sessionId === sessionId);
    if (!existing) {
      existing = {
        sessionId,
        consultantId: consultantId || null,
        snapshotSetId: snapshotSetId || null,
        snapshots: snapshots || [],
        title: slugifyTitle(question),
        firstQuestion: question || "",
        createdAt: now,
        updatedAt: now,
        messages: []
      };
      sessions.unshift(existing);
    }
    existing.consultantId = consultantId || existing.consultantId;
    existing.snapshotSetId = snapshotSetId || existing.snapshotSetId;
    existing.snapshots = snapshots || existing.snapshots || [];
    existing.updatedAt = now;
    if (!existing.title) existing.title = slugifyTitle(question);
    if (question || answer) {
      existing.messages = Array.isArray(existing.messages) ? existing.messages : [];
      existing.messages.push({ q: question || "", a: answer || "", ts: now });
    }
    setUserSessions(sessions);
    activeHistorySessionId = sessionId;
    renderHistoryList();

    if (!historyBackendAvailable) return;
    try {
      if (!existing._persisted) {
        if (!historyApi || !historyApi.createSession) return;
        const res = await historyApi.createSession({
          sessionId,
          title: existing.title || existing.firstQuestion || "New chat",
          consultantId: consultantId || null,
          fakeAuthEnabled,
          activeDevUserId
        });
        if (res.ok) {
          existing._persisted = true;
        }
      }
      if (!historyApi || !historyApi.postMessage) return;
      await historyApi.postMessage({
        sessionId,
        question,
        answer,
        fakeAuthEnabled,
        activeDevUserId
      });
    } catch (e) {
      historyBackendAvailable = false;
    }
  }

  async function loadHistorySession(sessionId) {
    const sessions = getUserSessions();
    const session = sessions.find((s) => s.sessionId === sessionId);
    if (!session) return;
    const selectedSessionId = session.sessionId;
    activeHistorySessionId = selectedSessionId;
    sessionId = selectedSessionId;
    localStorage.setItem("sessionId", selectedSessionId);
    responseDiv.innerHTML = "";
    const lang = getCurrentLang();
    const t = getTexts(lang);
    let messages = session.messages || [];
    if (historyBackendAvailable) {
      try {
        if (!historyApi || !historyApi.getMessages) {
          throw new Error("History API not ready");
        }
        const json = await historyApi.getMessages({
          sessionId: selectedSessionId,
          limit: 200,
          fakeAuthEnabled,
          activeDevUserId
        });
        messages = Array.isArray(json.items) ? json.items : messages;
      } catch (e) {
        historyBackendAvailable = false;
      }
    }
    messages.slice().reverse().forEach((msg) => {
      const markdown = msg.a || t.noResponse;
      const html = DOMPurify.sanitize(marked.parse(markdown));
      const timestamp = new Date(msg.ts || Date.now()).toLocaleString(t.locale);
      const questionHTML = `
        <div class="bg-white p-4 rounded-xl shadow-sm border border-gray-100 response-entry">
          <div class="text-sm text-gray-500 mb-2">
            ${timestamp} ${t.ask}: <i>${escapeHtml(msg.q || "")}</i>
          </div>
          <div class="markdown-content text-gray-900">${html}</div>
        </div>
      `;
      responseDiv.innerHTML = questionHTML + responseDiv.innerHTML;
    });
    if (session.snapshotSetId) {
      conversationSnapshotSetId = session.snapshotSetId;
      localStorage.setItem("conversationSnapshotSetId", conversationSnapshotSetId);
    }
    if (session.consultantId) {
      proceedSelectConsultant(session.consultantId);
    }
    updateFormPosition();
    addCopyButtons();
    renderHistoryList();
  }

  function generateTraceRunId() {
    const ts = Date.now();
    const safeSession = String(sessionId || "nosession")
      .replace(/[^a-zA-Z0-9_-]+/g, "_")
      .slice(0, 24) || "nosession";
    const safeConsultant = String(selectedConsultant || "consultant")
      .replace(/[^a-zA-Z0-9_-]+/g, "_")
      .slice(0, 24) || "consultant";
    let rand = Math.random().toString(16).slice(2, 10);
    try {
      if (window.crypto && typeof window.crypto.randomUUID === "function") {
        rand = window.crypto.randomUUID().replace(/-/g, "").slice(0, 10);
      }
    } catch (e) {
      // Keep Math.random fallback.
    }
    return `${ts}_${safeSession}_${safeConsultant}_${rand}`;
  }

  const uiTexts = {
    pl: {
      send: "Wyślij",
      wait: "Czekaj...",
      error: "Wystąpił błąd podczas przetwarzania zapytania.",
      noResponse: "Brak odpowiedzi",
      ask: "zapytanie",
      placeholder: "Wpisz pytanie...",
      newChat: "♻️ Nowy Chat",
      locale: "pl-PL",
      copy: "Kopiuj",
      copied: "Skopiowano!",
      snapshotLabel: "Wersja",
      snapshotDisabled: "no retrieval",
      vs: "vs",
      compareChooseTwo: "Wybierz dwa snapshoty do porównania.",
      compareChooseDifferent: "W trybie porównania wybierz dwa różne snapshoty.",
      queryTooLong: "Za długie zapytanie",
      snapshotChangeSingleTitle: "Rozpocząć nową rozmowę?",
      snapshotChangeSingleBody: "Wskazany konsultant korzysta z innego zakresu wersji. Żeby się przełączyć rozpocznij nową rozmowę.",
	      snapshotChangeMultiTitle: "Zmienić zakres wersji?",
	      snapshotChangeMultiBody: "Zmiana zakresu wersji w trakcie tej samej rozmowy może pomieszać kontekst. Kontynuować?",
	      snapshotChanged: (from, to) => `Zmieniono wersję: ${from} → ${to}`,
	      modalConfirm: "Nowa rozmowa",
	      modalCancel: "Anuluj",
	      modalContinue: "Kontynuuj",
        traceTitle: "Etapy pipeline",
        traceHandle: "Etapy",
        traceStatusIdle: "Brak aktywnego zadania",
        traceStatusWaiting: "Oczekiwanie na start...",
        traceStatusConnecting: "Łączenie strumienia etapów...",
        traceStatusConnected: "Połączono. Odbieram etapy...",
        traceStatusRunning: (count) => `W trakcie... (${count})`,
        traceStatusDone: "Zakończono.",
        traceStatusCancelled: "Przerwano.",
        traceStatusRetry: "Połączenie przerwane, ponawiam...",
        traceStatusNoRunId: "Brak trace_id w odpowiedzi backendu.",
        traceStatusErrorStart: "Błąd podczas uruchamiania trace.",
        traceFilterPlaceholder: "Filtruj etapy...",
        traceDocFilterPlaceholder: "Szukaj w dokumentach...",
        traceFilterClear: "Wyczyść filtr",
        traceFilterNoMatch: "Brak dopasowań.",
        traceDocs: (count) => `Dokumenty (${count})`,
        traceOpenDoc: "Otwórz dokument",
        traceDocTitle: "Dokument",
        traceDocPrev: "Poprzedni dokument",
        traceDocNext: "Następny dokument",
        traceDocCount: (idx, total) => `${idx}/${total}`,
        findInDocs: "Szukaj w dok.",
        historyTitle: "Twoje czaty",
        historySearchPlaceholder: "Filtruj listę czatów",
        historySearchButton: "Szukaj w archiwum (Ctrl+K)",
        historySearchModalTitle: "Szukaj w archiwum",
        historySearchModalPlaceholder: "Szukaj w archiwum...",
        historySearchModalEmpty: "Brak wyników",
        historySearchModalMore: "Pokaż więcej",
        historySearchImportantOnly: "Tylko ważne",
        historyRename: "Zmień nazwę",
      historyRenamePrompt: "Nowa nazwa",
      historyDelete: "Usuń",
        historyDeleteConfirm: "Usunąć czat?",
        historyClear: "Usuń historię",
        historyClearConfirm: "Czy na pewno chcesz usunąć swoją historię?",
        historyClearModalTitle: "Usuń historię",
        historyClearModalConfirm: "Usuń",
        historyClearModalCancel: "Anuluj",
        historyMarkImportant: "Oznacz jako ważne",
      historyUnmarkImportant: "Usuń z ważnych",
      historyRenameModalTitle: "Zmień nazwę",
      historyRenameModalLabel: "Nowa nazwa",
      historyRenameModalConfirm: "Zapisz",
      historyRenameModalCancel: "Anuluj",
      authLogin: "Zaloguj",
      authLogout: "Wyloguj",
        historyEmpty: "Brak historii",
        historyNewChat: "Nowy czat",
        queryProgressText: "Zapytanie w toku",
        consultantLocked: "Nie można zmienić konsultanta w trakcie odpowiedzi."
	    },
    en: {
      send: "Send",
      wait: "Please wait...",
      error: "An error occurred while processing the request.",
      noResponse: "No response",
      ask: "query",
      placeholder: "Type your question...",
      newChat: "♻️ New Chat",
      locale: "en-GB",
      copy: "Copy",
      copied: "Copied!",
      snapshotLabel: "Version",
      snapshotDisabled: "no retrieval",
      vs: "vs",
      compareChooseTwo: "Choose two snapshots to compare.",
      compareChooseDifferent: "In compare mode, choose two different snapshots.",
      queryTooLong: "Query is too long",
      snapshotChangeSingleTitle: "Start a new chat?",
      snapshotChangeSingleBody: "The selected consultant uses a different version scope. To switch, start a new chat.",
	      snapshotChangeMultiTitle: "Change version scope?",
	      snapshotChangeMultiBody: "Changing the version scope within the same chat may mix context. Continue?",
	      snapshotChanged: (from, to) => `Snapshot changed: ${from} → ${to}`,
	      modalConfirm: "Start new chat",
	      modalCancel: "Cancel",
	      modalContinue: "Continue",
        traceTitle: "Pipeline stages",
        traceHandle: "Stages",
        traceStatusIdle: "No active task",
        traceStatusWaiting: "Waiting for start...",
        traceStatusConnecting: "Connecting to stage stream...",
        traceStatusConnected: "Connected. Receiving stages...",
        traceStatusRunning: (count) => `In progress... (${count})`,
        traceStatusDone: "Completed.",
        traceStatusCancelled: "Cancelled.",
        traceStatusRetry: "Connection interrupted, retrying...",
        traceStatusNoRunId: "No trace_id in backend response.",
        traceStatusErrorStart: "Trace startup failed.",
        traceFilterPlaceholder: "Filter stages...",
        traceDocFilterPlaceholder: "Search documents...",
        traceFilterClear: "Clear filter",
        traceFilterNoMatch: "No matches.",
        traceDocs: (count) => `Documents (${count})`,
      traceOpenDoc: "Open document",
      traceDocTitle: "Document",
      traceDocPrev: "Previous document",
      traceDocNext: "Next document",
      traceDocCount: (idx, total) => `${idx}/${total}`,
      findInDocs: "Search docs",
      historyTitle: "Your chats",
      historySearchPlaceholder: "Search chats",
      historySearchButton: "Search (Ctrl+K)",
      historySearchModalTitle: "Search chats",
      historySearchModalPlaceholder: "Search...",
      historySearchModalEmpty: "No results",
      historySearchModalMore: "Show more",
      historySearchImportantOnly: "Important only",
      historyRename: "Rename",
      historyRenamePrompt: "New name",
      historyDelete: "Delete",
      historyDeleteConfirm: "Delete chat?",
      historyClear: "Clear history",
      historyClearConfirm: "Are you sure you want to delete your history?",
      historyClearModalTitle: "Delete history",
      historyClearModalConfirm: "Delete",
      historyClearModalCancel: "Cancel",
      historyMarkImportant: "Mark as important",
      historyUnmarkImportant: "Remove from important",
      historyRenameModalTitle: "Rename chat",
      historyRenameModalLabel: "New name",
      historyRenameModalConfirm: "Save",
      historyRenameModalCancel: "Cancel",
      authLogin: "Log in",
      authLogout: "Log out",
      historyEmpty: "No history",
      historyNewChat: "New chat",
        queryProgressText: "Query in progress",
        consultantLocked: "You cannot change the consultant while a reply is in progress."
	    }
	  };

  function showUiError(msg) {
    if (!uiError) return;
    uiError.textContent = msg || "";
    uiError.style.display = msg ? "block" : "none";
  }

  function setTraceStatus(text) {
    if (!traceStatus) return;
    traceStatus.textContent = text || "";
  }

  function setQueryProgress(isActive) {
    if (!queryProgress) return;
    isQueryInProgress = !!isActive;
    const t = getTexts(getCurrentLang());
    queryProgress.textContent = isActive ? t.queryProgressText : "";
    queryProgress.classList.toggle("active", !!isActive);
    setConsultantsLocked(isQueryInProgress);
  }

  function setConsultantsLocked(isLocked) {
    const t = getTexts(getCurrentLang());
    document.querySelectorAll(".consultant-card").forEach(el => {
      el.classList.toggle("locked", !!isLocked);
      if (isLocked) {
        el.setAttribute("aria-disabled", "true");
        el.setAttribute("title", t.consultantLocked);
      } else {
        el.removeAttribute("aria-disabled");
        el.removeAttribute("title");
      }
    });
  }

  function setTraceStatusByKey(key, arg) {
    traceStatusKey = key;
    traceStatusArg = arg;
    const t = getTexts(getCurrentLang());
    switch (key) {
      case "idle":
        setTraceStatus(t.traceStatusIdle);
        return;
      case "waiting":
        setTraceStatus(t.traceStatusWaiting);
        return;
      case "connecting":
        setTraceStatus(t.traceStatusConnecting);
        return;
      case "connected":
        setTraceStatus(t.traceStatusConnected);
        return;
      case "running":
        setTraceStatus(t.traceStatusRunning(Number(arg || 0)));
        return;
      case "done":
        setTraceStatus(t.traceStatusDone);
        return;
      case "cancelled":
        setTraceStatus(t.traceStatusCancelled);
        return;
      case "retry":
        setTraceStatus(t.traceStatusRetry);
        return;
      case "no_run_id":
        setTraceStatus(t.traceStatusNoRunId);
        return;
      case "start_error":
        setTraceStatus(t.traceStatusErrorStart);
        return;
      default:
        setTraceStatus(String(arg || ""));
        return;
    }
  }

  function setTraceOpen(isOpen) {
    document.body.classList.toggle("trace-open", !!isOpen);
    if (isOpen) {
      document.body.classList.remove("trace-has-unread");
      document.body.classList.remove("trace-handle-boost");
    }
    updateFindDocButtonsVisibility();
  }

  function setTraceAvailable(isAvailable) {
    document.body.classList.toggle("trace-available", !!isAvailable);
    if (!isAvailable) {
      document.body.classList.remove("trace-has-unread");
      document.body.classList.remove("trace-handle-boost");
    }
  }

  let traceHandleBoostTimer = null;

  function boostTraceHandle() {
    document.body.classList.add("trace-handle-boost");
    if (traceHandleBoostTimer) {
      clearTimeout(traceHandleBoostTimer);
    }
    traceHandleBoostTimer = setTimeout(() => {
      document.body.classList.remove("trace-handle-boost");
      traceHandleBoostTimer = null;
    }, 1200);
  }

  function clearTraceAttention() {
    document.body.classList.remove("trace-has-unread");
    document.body.classList.remove("trace-handle-boost");
    if (traceHandleBoostTimer) {
      clearTimeout(traceHandleBoostTimer);
      traceHandleBoostTimer = null;
    }
  }

  function markTraceUnread() {
    if (!requestInFlight) return;
    if (document.body.classList.contains("trace-open")) return;
    document.body.classList.add("trace-has-unread");
    boostTraceHandle();
  }

  function normalizeTraceFilterQuery(value) {
    return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
  }

  function normalizeDocFilterQuery(value) {
    return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
  }

  function updateTraceFilterClearState() {
    if (!traceFilterClearBtn) return;
    const active = Boolean(traceFilterQuery || traceDocFilterQuery);
    traceFilterClearBtn.style.display = active ? "inline-flex" : "none";
  }

  function updateTraceDocFilterVisibility() {
    if (!traceDocFilterWrap) return;
    const show = traceDocTotal > 0;
    traceDocFilterWrap.style.display = show ? "flex" : "none";
    if (!show) {
      traceDocFilterQuery = "";
      if (traceDocFilterInput) traceDocFilterInput.value = "";
    }
    updateTraceFilterClearState();
    updateFindDocButtonsVisibility();
  }

  function scoreFuzzyMatch(haystack, needle) {
    if (!needle) return 0;
    let score = 0;
    let hIndex = 0;
    let lastMatch = -1;
    let streak = 0;

    for (let i = 0; i < needle.length; i += 1) {
      const ch = needle[i];
      let found = false;
      while (hIndex < haystack.length) {
        if (haystack[hIndex] === ch) {
          found = true;
          if (lastMatch === hIndex - 1) {
            streak += 1;
            score += 2 + streak;
          } else {
            streak = 0;
            score += 1;
          }
          lastMatch = hIndex;
          hIndex += 1;
          break;
        }
        hIndex += 1;
      }
      if (!found) return -1;
    }

    score += Math.max(0, 6 - Math.floor(lastMatch / 12));
    return score;
  }

  function scoreTraceSearch(haystack, query) {
    if (!query) return 0;
    const tokens = query.split(" ").filter(Boolean);
    let total = 0;
    for (const token of tokens) {
      const score = scoreFuzzyMatch(haystack, token);
      if (score < 0) return -1;
      total += score;
    }
    return total;
  }

  function appendTraceFilterToken(parts, budget, value) {
    if (budget.left <= 0 || value === null || value === undefined) return;
    let token = String(value).trim().toLowerCase();
    if (!token) return;
    if (token.length > TRACE_FILTER_MAX_TOKEN_CHARS) {
      token = token.slice(0, TRACE_FILTER_MAX_TOKEN_CHARS);
    }
    if (token.length > budget.left) {
      token = token.slice(0, budget.left);
    }
    if (!token) return;
    parts.push(token);
    budget.left -= (token.length + 1);
  }

  function buildTraceSearchText(evt) {
    if (!evt || typeof evt !== "object") return "";
    const budget = { left: TRACE_FILTER_MAX_TOTAL_CHARS };
    const parts = [];
    const push = (v) => appendTraceFilterToken(parts, budget, v);

    push(evt.type);
    push(evt.summary);
    push(evt.summary_translated);
    push(evt.caption);
    push(evt.caption_translated);
    push(evt.action_id);
    push(evt.step_id);
    push(evt.ts);

    if (evt.details && typeof evt.details === "object") {
      for (const [k, v] of Object.entries(evt.details)) {
        push(k);
        push(v);
      }
    }

    return parts.join(" ");
  }

  function buildDocFilterText(doc) {
    if (!doc || typeof doc !== "object") return "";
    const parts = [];
    const push = (v) => {
      if (v === null || v === undefined) return;
      const s = String(v).trim();
      if (!s) return;
      parts.push(s);
    };
    push(doc.id);
    push(doc.path || doc.file_path || doc.filePath || doc.relative_path || doc.source_path || doc.sourcePath);
    push(doc.preview);
    push(doc.markdown);
    return parts.join(" ").toLowerCase();
  }

  function applyTraceFilters() {
    if (!traceList) return;

    const items = traceList.querySelectorAll(".trace-item");
    let total = 0;
    let matches = 0;
    const hasStageFilter = Boolean(traceFilterQuery);
    const hasDocFilter = Boolean(traceDocFilterQuery);

    for (const item of items) {
      total += 1;
      const haystack = String(item.__traceFilterText || item.dataset.filterText || "").toLowerCase();
      const stageMatch = !hasStageFilter || haystack.includes(traceFilterQuery);
      let docMatch = true;

      const docItems = item.querySelectorAll(".trace-doc-item");
      const docsWrap = item.querySelector(".trace-docs");

      if (hasDocFilter) {
        let anyDoc = false;
        let anyMatch = false;
        docItems.forEach((docItem) => {
          anyDoc = true;
          const docText = String(docItem.dataset.docFilterText || "").toLowerCase();
          const isMatch = docText.includes(traceDocFilterQuery);
          docItem.style.display = isMatch ? "" : "none";
          if (isMatch) anyMatch = true;
        });
        if (docsWrap) docsWrap.style.display = anyMatch ? "" : "none";
        docMatch = anyDoc && anyMatch;
      } else {
        docItems.forEach((docItem) => { docItem.style.display = ""; });
        if (docsWrap) docsWrap.style.display = "";
      }

      const match = stageMatch && docMatch;
      item.style.display = match ? "" : "none";
      item.classList.toggle("is-search-match", (hasStageFilter || hasDocFilter) && match);
      if (match && (hasStageFilter || hasDocFilter)) matches += 1;
    }

    if (traceFilterEmpty) {
      const showEmpty = (hasStageFilter || hasDocFilter) && total > 0 && matches === 0;
      traceFilterEmpty.style.display = showEmpty ? "block" : "none";
    }

    updateTraceFilterClearState();
  }

  function resetTracePanel() {
    if (traceList) traceList.innerHTML = "";
    traceFilterQuery = "";
    if (traceFilterInput) traceFilterInput.value = "";
    traceDocFilterQuery = "";
    if (traceDocFilterInput) traceDocFilterInput.value = "";
    traceDocTotal = 0;
    if (traceFilterEmpty) traceFilterEmpty.style.display = "none";
    for (const key of Object.keys(traceDocsByKey)) delete traceDocsByKey[key];
    traceDocSeq = 0;
    traceDocBatchSeq = 0;
    for (const key of Object.keys(traceDocBatches)) delete traceDocBatches[key];
    traceDocModalKeys = [];
    traceDocModalIndex = -1;
    closeTraceDocModal();
    traceEventCount = 0;
    setTraceStatusByKey("waiting");
    updateTraceDocFilterVisibility();
    updateTraceFilterClearState();
  }

  function stopTraceStream(opts = {}) {
    const hidePanel = opts.hidePanel !== false;
    if (traceApi && traceApi.stopTraceStream) {
      traceApi.stopTraceStream(traceSource);
    } else if (traceSource) {
      try { traceSource.close(); } catch (e) {}
    }
    traceSource = null;
    currentTraceRunId = null;
    if (hidePanel) {
      setTraceAvailable(false);
      setTraceOpen(false);
    }
  }

  function startTraceStream(runId) {
    if (!runId) return;
    if (currentTraceRunId === runId && traceSource) return;
    stopTraceStream({ hidePanel: false });
    currentTraceRunId = runId;
    resetTracePanel();
    setTraceStatusByKey("connected");
    setTraceAvailable(true);

    if (traceApi && traceApi.startTraceStream) {
      traceSource = traceApi.startTraceStream({
        runId,
        onEvent: handleTraceEvent,
        onError: () => setTraceStatusByKey("retry"),
      });
    } else {
      const url = `${API_BASE}${TRACE_STREAM_PATH}?run_id=${encodeURIComponent(runId)}`;
      traceSource = new EventSource(url);

      traceSource.onmessage = (evt) => {
        if (!evt || !evt.data) return;
        let payload = null;
        try { payload = JSON.parse(evt.data); } catch (e) { return; }
        handleTraceEvent(payload);
      };

      traceSource.onerror = () => {
        setTraceStatusByKey("retry");
      };
    }
  }

  function handleTraceEvent(evt) {
    if (!evt || typeof evt !== "object") return;
    if (evt.type === "done") {
      setTraceStatusByKey("done");
      stopTraceStream({ hidePanel: false });
      setTraceOpen(false);
      clearTraceAttention();
      return;
    }
    if (evt.type === "consume" || evt.event_type === "CONSUME") {
      return;
    }
    traceEventCount += 1;
    setTraceStatusByKey("running", traceEventCount);
    appendTraceItem(evt);
  }

  function appendTraceItem(evt) {
    if (!traceList) return;
    const lang = getCurrentLang();
    const titleRaw = (lang === "pl")
      ? (evt.summary_translated || evt.summary || evt.type || "step")
      : (evt.summary || evt.summary_translated || evt.type || "step");
    const title = escapeHtml(titleRaw);
    const metaParts = [];
    if (evt.action_id) metaParts.push(`action: ${evt.action_id}`);
    if (evt.step_id) metaParts.push(`step: ${evt.step_id}`);
    if (evt.ts) metaParts.push(evt.ts);
    const meta = metaParts.join(" • ");
    const details = formatTraceDetails(evt.details);
    const docs = formatTraceDocs(evt.docs);

    const html = `
      <div class="trace-item">
        <div class="trace-item-title">${title}</div>
        ${meta ? `<div class="trace-item-meta">${escapeHtml(meta)}</div>` : ""}
        ${details ? `<div class="trace-item-body">${details}</div>` : ""}
        ${docs}
      </div>
    `;
    traceList.insertAdjacentHTML("beforeend", html);
    const inserted = traceList.lastElementChild;
    if (inserted) {
      inserted.__traceFilterText = buildTraceSearchText(evt);
      inserted.querySelectorAll(".trace-doc-open").forEach((btn) => {
        btn.addEventListener("click", () => {
          const key = btn.getAttribute("data-doc-key") || "";
          if (!key) return;
          const docsWrap = btn.closest(".trace-docs");
          let keys = null;
          if (docsWrap) {
            const batch = docsWrap.getAttribute("data-doc-batch") || "";
            if (batch && Array.isArray(traceDocBatches[batch])) {
              keys = traceDocBatches[batch];
            } else {
              keys = Array.from(docsWrap.querySelectorAll(".trace-doc-open"))
                .map((node) => node.getAttribute("data-doc-key"))
                .filter(Boolean);
            }
          }
          openTraceDocModalByKey(key, keys);
        });
      });
    }
    applyTraceFilters();
    markTraceUnread();
    if (!traceFilterQuery) {
      traceList.scrollTo({ top: traceList.scrollHeight, behavior: "smooth" });
    }
  }

  function formatTraceDetails(details) {
    if (!details || typeof details !== "object") return "";
    const parts = [];
    for (const [k, v] of Object.entries(details)) {
      if (v === null || v === undefined || v === "") continue;
      parts.push(`${k}: ${String(v)}`);
    }
    return escapeHtml(parts.join("\n"));
  }

  function formatTraceDocs(docs) {
    if (!Array.isArray(docs) || docs.length === 0) return "";
    const t = getTexts(getCurrentLang());
    const allKeys = docs.map((doc) => registerTraceDoc(doc));
    traceDocBatchSeq += 1;
    const batchKey = `b_${traceDocBatchSeq}`;
    traceDocBatches[batchKey] = allKeys;
    const items = docs.slice(0, 20).map((doc, idx) => {
      const title = escapeHtml(doc.id || "doc");
      const docKey = allKeys[idx];
      const docFilterText = escapeHtml(buildDocFilterText(doc));
      const meta = [];
      if (doc.depth !== undefined && doc.depth !== null) meta.push(`depth: ${doc.depth}`);
      if (doc.text_len !== undefined && doc.text_len !== null) meta.push(`len: ${doc.text_len}`);
      const metaStr = meta.length ? `<div class="trace-item-meta">${escapeHtml(meta.join(" • "))}</div>` : "";
      const preview = doc.preview ? `<div class="trace-doc-preview">${escapeHtml(doc.preview)}</div>` : "";
      const open = `<button type="button" class="trace-doc-open" data-doc-key="${escapeHtml(docKey)}">${escapeHtml(t.traceOpenDoc)}</button>`;
      return `<div class="trace-doc-item" data-doc-filter-text="${docFilterText}"><div class="trace-item-title">${title}</div>${metaStr}${preview}${open}</div>`;
    }).join("");

    return `
      <details class="trace-docs" data-doc-batch="${escapeHtml(batchKey)}">
        <summary>${escapeHtml(t.traceDocs(docs.length))}</summary>
        ${items}
      </details>
    `;
  }

  function registerTraceDoc(doc) {
    traceDocSeq += 1;
    const key = `d_${traceDocSeq}`;
    traceDocsByKey[key] = doc || {};
    traceDocTotal += 1;
    updateTraceDocFilterVisibility();
    return key;
  }

  function updateTraceDocNav() {
    const t = getTexts(getCurrentLang());
    const total = traceDocModalKeys.length;
    const index = traceDocModalIndex;
    const hasMany = total > 1;
    if (traceDocModalCount) {
      traceDocModalCount.textContent = hasMany ? t.traceDocCount(index + 1, total) : "";
      traceDocModalCount.style.display = hasMany ? "inline-flex" : "none";
    }
    if (traceDocPrevBtn) {
      traceDocPrevBtn.disabled = !hasMany || index <= 0;
      traceDocPrevBtn.setAttribute("aria-label", t.traceDocPrev);
      traceDocPrevBtn.classList.toggle("is-hidden", !hasMany);
    }
    if (traceDocNextBtn) {
      traceDocNextBtn.disabled = !hasMany || index >= total - 1;
      traceDocNextBtn.setAttribute("aria-label", t.traceDocNext);
      traceDocNextBtn.classList.toggle("is-hidden", !hasMany);
    }
  }

  function getTraceDocTitle(doc) {
    const t = getTexts(getCurrentLang());
    if (!doc || typeof doc !== "object") return t.traceDocTitle || "Document";
    const path = doc.path || doc.file_path || doc.filePath || doc.relative_path || doc.source_path || doc.sourcePath;
    if (path) return String(path);
    return String(doc.id || t.traceDocTitle || "Document");
  }

  function openTraceDocModalByKey(key, keys = null) {
    const doc = traceDocsByKey[key];
    if (!doc) return;
    if (Array.isArray(keys) && keys.length) {
      traceDocModalKeys = keys;
      traceDocModalIndex = Math.max(0, keys.indexOf(key));
    } else {
      traceDocModalKeys = [key];
      traceDocModalIndex = 0;
    }
    const t = getTexts(getCurrentLang());
    const title = getTraceDocTitle(doc);
    const raw = String(doc.markdown || doc.preview || "");
    let markdown = raw;
    if (markdown && !markdown.includes("```")) {
      markdown = `\`\`\`\n${markdown}\n\`\`\``;
    }
    if (traceDocModalTitle) traceDocModalTitle.textContent = title;
    if (traceDocModalBody) {
      traceDocModalBody.innerHTML = DOMPurify.sanitize(marked.parse(markdown || " "));
      addCopyButtons();
    }
    if (traceDocModalBackdrop) traceDocModalBackdrop.style.display = "flex";
    updateTraceDocNav();
  }

  function closeTraceDocModal() {
    if (traceDocModalBackdrop) traceDocModalBackdrop.style.display = "none";
    if (traceDocModalBody) traceDocModalBody.innerHTML = "";
    traceDocModalKeys = [];
    traceDocModalIndex = -1;
  }

  function normalizeLanguageCode(value, fallback = "en") {
    const raw = String(value || "").trim().toLowerCase();
    if (!raw) return fallback;
    const normalized = raw.replace("_", "-").split("-", 1)[0].trim();
    return normalized || fallback;
  }

  function getSupportedUiLang(value) {
    const normalized = normalizeLanguageCode(value, "en");
    if (uiTexts[normalized]) return normalized;
    return uiTexts[neutralLanguageCode] ? neutralLanguageCode : "en";
  }

  function getLanguageOptionLabel(code) {
    const normalized = normalizeLanguageCode(code, "en");
    if (normalized === "pl") return "PL Rozmawiaj po polsku";
    if (normalized === "en") return "EN English";
    return normalized.toUpperCase();
  }

  function renderLanguageSelector(selectedLang) {
    if (!langSelect) return;

    if (!isMultilingualProject) {
      langSelect.style.display = "none";
      return;
    }

    langSelect.style.display = "";
    const preferred = getSupportedUiLang(selectedLang || translatedLanguageCode);
    const options = [
      { value: translatedLanguageCode, label: getLanguageOptionLabel(translatedLanguageCode) },
      { value: neutralLanguageCode, label: getLanguageOptionLabel(neutralLanguageCode) },
    ];

    langSelect.innerHTML = "";
    const used = new Set();
    for (const opt of options) {
      const value = getSupportedUiLang(opt.value);
      if (used.has(value)) continue;
      used.add(value);
      const node = document.createElement("option");
      node.value = value;
      node.textContent = opt.label;
      langSelect.appendChild(node);
    }

    if (!used.has(preferred) && langSelect.options.length > 0) {
      langSelect.value = langSelect.options[0].value;
    } else {
      langSelect.value = preferred;
    }
  }

  function configureLanguageSettings(cfg) {
    const source = cfg || {};
    const enabled = source.isMultilingualProject;
    isMultilingualProject = (typeof enabled === "boolean") ? enabled : true;
    neutralLanguageCode = getSupportedUiLang(source.neutralLanguage || "en");
    translatedLanguageCode = getSupportedUiLang(source.translatedLanguage || "pl");

    if (neutralLanguageCode === translatedLanguageCode) {
      translatedLanguageCode = neutralLanguageCode === "pl" ? "en" : "pl";
    }
  }

  function getCurrentLang() {
    const selected = (langSelect && langSelect.value) || "";
    const saved = localStorage.getItem("lang");
    // UI language must follow the current selector when available; saved value is fallback only.
    const resolved = getSupportedUiLang(selected || saved || translatedLanguageCode);
    return isMultilingualProject ? resolved : neutralLanguageCode;
  }

  function shouldTranslateChatForLang(lang) {
    if (!isMultilingualProject) return false;
    return getSupportedUiLang(lang) === translatedLanguageCode;
  }

  function getTexts(lang) {
    return uiTexts[getSupportedUiLang(lang)] || uiTexts.en;
  }

  async function fetchAppConfig() {
    if (!api || !api.fetchAppConfig) {
      throw new Error("API not ready");
    }
    const data = await api.fetchAppConfig({ fakeAuthEnabled, activeDevUserId });
    try {
      localStorage.setItem("lastAppConfig", JSON.stringify(data));
    } catch (e) {
      // Ignore cache errors (private mode, quota, etc.)
    }
    return data;
  }

  function loadCachedAppConfig() {
    try {
      const raw = localStorage.getItem("lastAppConfig");
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function rebuildConsultantsIndex() {
    consultantsById = {};
    for (const c of ((appConfig && appConfig.consultants) || [])) {
      consultantsById[c.id] = c;
    }
    snapshotPolicy = String((appConfig && appConfig.snapshotPolicy) || "single").trim() || "single";
  }

  function updateConsultantLayout() {
    if (!consultantsContainer) return;
    const cards = Array.from(consultantsContainer.querySelectorAll(".consultant-card"));
    if (cards.length === 0) return;

    consultantsContainer.classList.remove("consultants-tight");
    cards.forEach(c => c.classList.remove("compact"));

    const fits = () => consultantsContainer.scrollWidth <= consultantsContainer.clientWidth + 1;
    if (fits()) return;

    cards.forEach(c => {
      const id = c.getAttribute("data-consultant-id");
      if (id !== selectedConsultant) c.classList.add("compact");
    });

    if (fits()) return;
    consultantsContainer.classList.add("consultants-tight");
  }

  function buildConsultantsBar(lang) {
    consultantsContainer.innerHTML = "";

    for (const c of ((appConfig && appConfig.consultants) || [])) {
      const desc = (c.cardDescription && c.cardDescription[lang]) || (c.cardDescription && c.cardDescription.pl) || "";

      const card = document.createElement("div");
      card.className = "consultant-card";
      card.setAttribute("data-consultant-id", c.id);
      card.addEventListener("click", () => selectConsultant(c.id));

      const icon = document.createElement("div");
      icon.className = "consultant-icon";
      icon.textContent = c.icon || "👤";

      const textWrap = document.createElement("div");
      textWrap.className = "consultant-text";

      const nameSpan = document.createElement("div");
      nameSpan.className = "consultant-name";
      nameSpan.textContent = c.displayName || c.id;

      const small = document.createElement("div");
      small.className = "consultant-desc";
      small.textContent = desc;

      textWrap.appendChild(nameSpan);
      textWrap.appendChild(small);

      card.appendChild(icon);
      card.appendChild(textWrap);

      consultantsContainer.appendChild(card);
    }

    document.querySelectorAll(".consultant-card").forEach(el => {
      const id = el.getAttribute("data-consultant-id");
      el.classList.toggle("active", id === selectedConsultant);
    });
    setConsultantsLocked(isQueryInProgress);
    requestAnimationFrame(updateConsultantLayout);
  }

  function renderWelcomeMessage(lang = getCurrentLang()) {
    const c = consultantsById[selectedConsultant];
    if (!welcomeMessage) return;

    if (!c) {
      welcomeMessage.textContent = "";
      return;
    }

    const template = (c.welcomeTemplate && c.welcomeTemplate[lang]) || (c.welcomeTemplate && c.welcomeTemplate.pl) || "";
    const href = (c.wikiUrl && c.wikiUrl[lang]) || (c.wikiUrl && c.wikiUrl.pl) || "";

    const linkText =
      (c.welcomeLinkText && c.welcomeLinkText[lang]) ||
      (c.welcomeLinkText && c.welcomeLinkText.pl) ||
      c.displayName ||
      c.id;

    const parts = String(template).split("{link}");
    const before = (parts[0] != null ? parts[0] : "");
    const after = (parts.slice(1).join("{link}") != null ? parts.slice(1).join("{link}") : "");

    welcomeMessage.innerHTML = "";
    welcomeMessage.appendChild(document.createTextNode(before));

    const a = document.createElement("a");
    a.href = href || "#";
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.title = (lang === "pl") ? "Wikipedia – otwiera się w nowej karcie" : "Wikipedia – opens in new tab";
    a.textContent = linkText;

    if (!href) {
      a.removeAttribute("href");
      a.style.textDecoration = "none";
      a.style.color = "inherit";
      a.style.cursor = "default";
    }

    welcomeMessage.appendChild(a);
    welcomeMessage.appendChild(document.createTextNode(after));
  }

  function firstSnapshotOrNull(list) {
    return list && list.length ? list[0] : null;
  }

  function getConsultantSnapshots(c) {
    return Array.isArray((c && c.snapshots)) ? c.snapshots : [];
  }

  function hasSnapshots(c) {
    return getConsultantSnapshots(c).length > 0;
  }

  function getSnapshotSetId(c) {
    const sid = String((c && c.snapshotSetId) || "").trim();
    return sid || null;
  }

  function updateSnapshotState(id, label, snapshotSetId) {
    if (id) {
      currentSnapshotId = id;
      localStorage.setItem("snapshotId", id);
    }
    if (label) {
      currentSnapshotLabel = label;
      localStorage.setItem("snapshotLabel", label);
    }
    if (snapshotSetId) {
      currentSnapshotSetId = snapshotSetId;
      localStorage.setItem("snapshotSetId", snapshotSetId);
    }
  }

  function hasActiveConversation() {
    return responseDiv && responseDiv.children && responseDiv.children.length > 0;
  }

  function showSnapshotModal(title, message, onConfirm, onCancel, confirmLabel) {
    if (!snapshotModalBackdrop) {
      const ok = confirm(`${title}\n\n${message}`);
      if (ok) onConfirm();
      else if (onCancel) onCancel();
      return;
    }
    const t = getTexts(getCurrentLang());
    snapshotModalTitle.textContent = title;
    snapshotModalBody.textContent = message;
    snapshotModalConfirm.textContent = confirmLabel || t.modalConfirm || "OK";
    snapshotModalCancel.textContent = t.modalCancel || "Anuluj";
    snapshotModalBackdrop.style.display = "flex";

    const cleanup = () => {
      snapshotModalBackdrop.style.display = "none";
      snapshotModalConfirm.onclick = null;
      snapshotModalCancel.onclick = null;
    };

    snapshotModalConfirm.onclick = () => {
      cleanup();
      onConfirm();
    };
    snapshotModalCancel.onclick = () => {
      cleanup();
      if (onCancel) onCancel();
    };
  }

  function addSystemMessage(text) {
    const lang = getCurrentLang();
    const t = getTexts(lang);
    const timestamp = new Date().toLocaleString(t.locale);
    const html = `
      <div class="bg-yellow-50 p-4 rounded-xl shadow-sm border border-yellow-200 response-entry">
        <div class="text-sm text-yellow-800 mb-2">${timestamp}</div>
        <div class="text-sm text-yellow-900">${escapeHtml(text)}</div>
      </div>
    `;
    responseDiv.innerHTML = html + responseDiv.innerHTML;
  }

  // Autosize select width to its selected option text (clamped).
  const __selectMeasureSpan = (() => {
    const s = document.createElement("span");
    s.style.position = "absolute";
    s.style.visibility = "hidden";
    s.style.whiteSpace = "pre";
    s.style.top = "-9999px";
    s.style.left = "-9999px";
    document.body.appendChild(s);
    return s;
  })();

  function autoSizeSelectToValue(selectEl, opts = {}) {
    if (!selectEl) return;

    const minPx = (opts.minPx != null ? opts.minPx : 160);
    const maxPx = (opts.maxPx != null ? opts.maxPx : 520);

    const optText = (selectEl.options && selectEl.options[selectEl.selectedIndex]) ? selectEl.options[selectEl.selectedIndex].text : null;
    const text = optText != null ? optText : "";
    const cs = window.getComputedStyle(selectEl);

    __selectMeasureSpan.style.fontFamily = cs.fontFamily;
    __selectMeasureSpan.style.fontSize = cs.fontSize;
    __selectMeasureSpan.style.fontWeight = cs.fontWeight;
    __selectMeasureSpan.style.letterSpacing = cs.letterSpacing;

    __selectMeasureSpan.textContent = text;

    const textWidth = __selectMeasureSpan.getBoundingClientRect().width;

    // Room for paddings + native arrow + safety.
    const extra = 80;

    const target = Math.ceil(textWidth + extra);
    const clamped = Math.max(minPx, Math.min(maxPx, target));

    selectEl.style.width = `${clamped}px`;
  }

  function autoSizeAllBranchSelects() {
    document.querySelectorAll("select.branch-select").forEach(sel => autoSizeSelectToValue(sel));
  }

  function commonPrefixLen(strings) {
    if (!strings || strings.length === 0) return 0;
    const s0 = String(strings[0] != null ? strings[0] : "");
    let i = 0;
    while (i < s0.length) {
      const ch = s0[i];
      for (let k = 1; k < strings.length; k++) {
        const sk = String(strings[k] != null ? strings[k] : "");
        if (i >= sk.length || sk[i] !== ch) return i;
      }
      i++;
    }
    return i;
  }

  function commonSuffixLen(strings) {
    if (!strings || strings.length === 0) return 0;
    const s0 = String(strings[0] != null ? strings[0] : "");
    let i = 0;
    while (i < s0.length) {
      const ch = s0[s0.length - 1 - i];
      for (let k = 1; k < strings.length; k++) {
        const sk = String(strings[k] != null ? strings[k] : "");
        if (i >= sk.length || sk[sk.length - 1 - i] !== ch) return i;
      }
      i++;
    }
    return i;
  }

  function trimLeadingSeparators(s) {
    return String(s).replace(/^[_\-.\/\\\s]+/, "");
  }

  function trimTrailingSeparators(s) {
    return String(s).replace(/[_\-.\/\\\s]+$/, "");
  }

  function computeClosedBranchLabel(fullName, mode, allLabels) {
    const name = String(fullName != null ? fullName : "");
    if (!name) return "";

    const inCompare = (mode === "compare");

    // Single mode: show full if "reasonable".
    // Compare mode: force smart-shortening to make A vs B obvious.
    const shouldShorten = inCompare || (name.length > MAX_BRANCH_LABEL_LEN);
    if (!shouldShorten) return name;

    if (!Array.isArray(allLabels) || allLabels.length <= 1) {
      if (name.length <= MAX_BRANCH_LABEL_LEN) return name;
      return "…" + name.slice(-(MAX_BRANCH_LABEL_LEN - 1));
    }

    const pref = commonPrefixLen(allLabels);
    const suff = commonSuffixLen(allLabels);

    // Candidate A: cut common PREFIX, keep the differing tail.
    let candPrefix = null;
    if (pref > 0 && pref < name.length) {
      const tail = trimLeadingSeparators(name.slice(pref));
      if (tail) candPrefix = "…" + tail;
    }

    // Candidate B: cut common SUFFIX, keep the differing head.
    let candSuffix = null;
    if (suff > 0 && suff < name.length) {
      const head = trimTrailingSeparators(name.slice(0, name.length - suff));
      if (head) candSuffix = head + "…";
    }

    // Prefer cutting the side that is more common across all names.
    let chosen = null;
    if (pref >= suff) {
      chosen = candPrefix || candSuffix || name;
    } else {
      chosen = candSuffix || candPrefix || name;
    }

    if (chosen.length <= MAX_BRANCH_LABEL_LEN) return chosen;

    if (chosen.startsWith("…")) {
      return "…" + name.slice(-(MAX_BRANCH_LABEL_LEN - 1));
    }
    return name.slice(0, MAX_BRANCH_LABEL_LEN - 1) + "…";
  }

  function setAllOptionsToFull(selectEl) {
    if (!selectEl) return;
    for (const opt of selectEl.options) {
      const full = opt.getAttribute("data-full");
      if (full != null) opt.textContent = full;
    }
  }

  function applyClosedLabelToSelected(selectEl, mode, allLabels) {
    if (!selectEl) return;

    setAllOptionsToFull(selectEl);

    const opt = (selectEl.options && selectEl.options[selectEl.selectedIndex]) ? selectEl.options[selectEl.selectedIndex] : null;
    const full = String(opt ? (opt.getAttribute("data-full") || "") : "");
    const label = computeClosedBranchLabel(full, mode, allLabels);

    if (opt) opt.textContent = label;

    selectEl.title = full || "";

    autoSizeSelectToValue(selectEl);
  }

  function prepareOpenSelect(selectEl) {
    setAllOptionsToFull(selectEl);
  }

  function renderBranchControls() {
    const lang = getCurrentLang();
    const t = getTexts(lang);
    const c = consultantsById[selectedConsultant];

    branchControls.innerHTML = "";
    branchControls.style.display = "";
    if (controlsSpacer) controlsSpacer.style.display = "none";

    const mode = (c && (c.snapshotPickerMode || c.branchPickerMode)) ? (c.snapshotPickerMode || c.branchPickerMode) : "single";
    if (!hasSnapshots(c) || mode === "none") {
      selectedSnapshotA = null;
      selectedSnapshotB = null;
      branchControls.style.display = "none";
      if (controlsSpacer) controlsSpacer.style.display = "block";
      updateSendButtonState();
      return;
    }

    const label = document.createElement("div");
    label.className = "branch-label";
    label.innerHTML = `🔀 <span>${t.snapshotLabel}</span>`;
    branchControls.appendChild(label);

    branchControls.classList.toggle("compare", mode === "compare");

    const snapshots = getConsultantSnapshots(c);
    if (!selectedSnapshotA) {
      const firstSnap = firstSnapshotOrNull(snapshots);
    selectedSnapshotA = firstSnap ? (firstSnap.id || null) : null;
    }
    if (mode === "compare") {
      if (!selectedSnapshotB) {
        const second = snapshots.length > 1 ? snapshots[1] : snapshots[0];
        selectedSnapshotB = (second && second.id) ? second.id : null;
      }
    } else {
      selectedSnapshotB = null;
    }

    updateSendButtonState();

    const makeSelect = (options, currentValue, onChange) => {
      const sel = document.createElement("select");
      sel.className = "branch-select";

      for (const optItem of options) {
        const opt = document.createElement("option");
        opt.value = optItem.value;
        opt.textContent = optItem.label;
        opt.setAttribute("data-full", optItem.label);
        sel.appendChild(opt);
      }

      const values = options.map(o => o.value);
      if (currentValue && values.includes(currentValue)) {
        sel.value = currentValue;
      } else if (options.length) {
        sel.value = options[0].value;
      }

      sel.addEventListener("focus", () => prepareOpenSelect(sel));
      sel.addEventListener("mousedown", () => prepareOpenSelect(sel));
      sel.addEventListener("keydown", (e) => {
        if (e.key === "ArrowDown" || e.key === " " || e.key === "Enter") {
          prepareOpenSelect(sel);
        }
      });

      sel.addEventListener("change", (e) => {
        onChange(e.target.value);
        updateSendButtonState();
        setTimeout(() => applyClosedLabelToSelected(sel, mode, options.map(o => o.label)), 0);
      });

      sel.addEventListener("blur", () => applyClosedLabelToSelected(sel, mode, options.map(o => o.label)));

      applyClosedLabelToSelected(sel, mode, options.map(o => o.label));

      return sel;
    };

    {
      const snapSet = getSnapshotSetId(c);
      if (snapSet && currentSnapshotSetId && snapSet === currentSnapshotSetId && !selectedSnapshotA) {
        selectedSnapshotA = currentSnapshotId;
      }
      const snapshotOptions = snapshots.map(s => ({
        value: s.id,
        label: s.label || s.id,
      }));
      const selA = makeSelect(snapshotOptions, selectedSnapshotA, v => {
        const prevId = selectedSnapshotA;
        const prevLabel = currentSnapshotLabel || prevId;
        selectedSnapshotA = v;
        const chosen = snapshots.find(s => s.id === v);
        const nextLabel = (chosen && chosen.label) || v;
        updateSnapshotState(v, nextLabel, getSnapshotSetId(c));
        if (responseDiv.children.length > 0 && prevId && prevId !== v) {
          const t = getTexts(getCurrentLang());
          const from = prevLabel || prevId;
          addSystemMessage(
            (typeof t.snapshotChanged === "function")
              ? t.snapshotChanged(from, nextLabel)
              : `Snapshot changed: ${from} → ${nextLabel}`
          );
        }
      });
      branchControls.appendChild(selA);

      if (mode === "compare") {
        const vs = document.createElement("div");
        vs.className = "vs-badge";
        vs.textContent = t.vs;
        branchControls.appendChild(vs);

        const selB = makeSelect(snapshotOptions, selectedSnapshotB, v => {
          selectedSnapshotB = v;
        });
        branchControls.appendChild(selB);
      }

      requestAnimationFrame(autoSizeAllBranchSelects);
      return;
    }

    requestAnimationFrame(autoSizeAllBranchSelects);
  }

  function refreshCopyButtonsText(lang) {
    const t = getTexts(lang);
    document.querySelectorAll(".copy-btn").forEach(btn => {
      const isCopied = btn.classList.contains("copied");
      btn.textContent = isCopied ? t.copied : t.copy;
    });
  }

  function refreshFindButtonsText(lang) {
    const t = getTexts(lang);
    document.querySelectorAll(".find-doc-btn").forEach(btn => {
      btn.textContent = t.findInDocs;
    });
  }

  function applyLang(lang) {
    const effectiveLang = isMultilingualProject ? getSupportedUiLang(lang) : neutralLanguageCode;
    renderLanguageSelector(effectiveLang);
    const t = getTexts(effectiveLang);
    try { document.documentElement.lang = effectiveLang; } catch (e) {}

    if (submitButton) {
      const label = submitButton.querySelector(".send-label");
      if (label) label.textContent = requestInFlight ? t.wait : t.send;
      submitButton.classList.toggle("is-cancel", !!requestInFlight);
    }
    if (queryInput) queryInput.placeholder = t.placeholder;
    if (newChatBtn) newChatBtn.textContent = t.newChat;
    if (traceTitle) traceTitle.textContent = t.traceTitle;
    if (traceHandle) traceHandle.textContent = t.traceHandle;
    if (traceFilterInput) {
      traceFilterInput.placeholder = t.traceFilterPlaceholder;
      traceFilterInput.setAttribute("aria-label", t.traceFilterPlaceholder);
    }
    if (traceDocFilterInput) {
      traceDocFilterInput.placeholder = t.traceDocFilterPlaceholder;
      traceDocFilterInput.setAttribute("aria-label", t.traceDocFilterPlaceholder);
    }
    if (traceFilterClearBtn) {
      traceFilterClearBtn.textContent = t.traceFilterClear;
    }
    if (traceFilterEmpty) traceFilterEmpty.textContent = t.traceFilterNoMatch;
    if (authToggleBtn) {
      authToggleBtn.textContent = fakeAuthEnabled ? t.authLogout : t.authLogin;
    }
    if (historySectionTitle) historySectionTitle.textContent = t.historyTitle;
    if (historySearchInput) {
      historySearchInput.placeholder = t.historySearchPlaceholder;
      historySearchInput.setAttribute("aria-label", t.historySearchPlaceholder);
    }
    if (historySearchBtn) {
      const label = historySearchBtn.querySelector(".btn-label");
      if (label) label.textContent = t.historySearchButton;
      else historySearchBtn.textContent = t.historySearchButton;
    }
    if (historySearchModalTitle) historySearchModalTitle.textContent = t.historySearchModalTitle;
    if (historySearchModalInput) {
      historySearchModalInput.placeholder = t.historySearchModalPlaceholder;
      historySearchModalInput.setAttribute("aria-label", t.historySearchModalPlaceholder);
    }
    if (historySearchModalEmpty) historySearchModalEmpty.textContent = t.historySearchModalEmpty;
    if (historySearchModalMore) historySearchModalMore.textContent = t.historySearchModalMore;
    if (historySearchModalImportantLabel) historySearchModalImportantLabel.textContent = t.historySearchImportantOnly;
    if (historyContextRenameLabel) historyContextRenameLabel.textContent = t.historyRename;
    if (historyContextImportantLabel) {
      historyContextImportantLabel.textContent = t.historyMarkImportant;
    }
    if (historyContextDeleteLabel) historyContextDeleteLabel.textContent = t.historyDelete;
    if (historyContextClearAllLabel) historyContextClearAllLabel.textContent = t.historyClear;
    if (authCompactClearHistoryLabel) authCompactClearHistoryLabel.textContent = t.historyClear;
    if (authCompactActionLabel) {
      authCompactActionLabel.textContent = fakeAuthEnabled ? t.authLogout : t.authLogin;
    }
    if (renameChatModalTitle) renameChatModalTitle.textContent = t.historyRenameModalTitle;
    if (renameChatModalLabel) renameChatModalLabel.textContent = t.historyRenameModalLabel;
    if (renameChatModalConfirm) renameChatModalConfirm.textContent = t.historyRenameModalConfirm;
    if (renameChatModalCancel) renameChatModalCancel.textContent = t.historyRenameModalCancel;
    if (clearHistoryModalTitle) clearHistoryModalTitle.textContent = t.historyClearModalTitle || t.historyClear;
    if (clearHistoryModalBody) clearHistoryModalBody.textContent = t.historyClearConfirm || "Czy na pewno chcesz usunąć swoją historię?";
    if (clearHistoryModalConfirm) clearHistoryModalConfirm.textContent = t.historyClearModalConfirm || t.historyClear;
    if (clearHistoryModalCancel) clearHistoryModalCancel.textContent = t.historyClearModalCancel || t.modalCancel || "Anuluj";
    if (historyNewChatBtn) {
      const label = historyNewChatBtn.querySelector(".btn-label");
      if (label) label.textContent = t.historyNewChat;
      else historyNewChatBtn.textContent = t.historyNewChat;
    }
    if (historyEmpty) historyEmpty.textContent = t.historyEmpty;
    if (queryProgress && queryProgress.classList.contains("active")) {
      queryProgress.textContent = t.queryProgressText;
    }
    updateTraceDocNav();
    updateAuthUi();

    localStorage.setItem("lang", effectiveLang);
    if (langSelect && langSelect.value !== effectiveLang) langSelect.value = effectiveLang;
    try {
      document.dispatchEvent(new CustomEvent("localai:lang", { detail: { lang: effectiveLang } }));
    } catch (e) {}

    buildConsultantsBar(effectiveLang);
    renderWelcomeMessage(effectiveLang);
    renderBranchControls();

    // Fix: existing copy buttons must update when language changes.
    refreshCopyButtonsText(effectiveLang);
    refreshFindButtonsText(effectiveLang);
    setTraceStatusByKey(traceStatusKey, traceStatusArg);
    applyTraceFilters();
    renderHistoryList();
  }

  function selectConsultant(id) {
    if (isQueryInProgress) return;
    const prevConsultant = selectedConsultant;
    const prev = consultantsById[prevConsultant];
    const next = consultantsById[id];
    const prevSet = getSnapshotSetId(prev);
    const nextSet = getSnapshotSetId(next);
    const effectivePrevSet = conversationSnapshotSetId;

    // Only enforce when the conversation already used a non-empty snapshot set.
    if (nextSet && effectivePrevSet && nextSet !== effectivePrevSet && hasActiveConversation()) {
      if (snapshotPolicy === "single") {
        const t = getTexts(getCurrentLang());
        showSnapshotModal(
          t.snapshotChangeSingleTitle,
          t.snapshotChangeSingleBody,
          () => {
            newChat();
            currentSnapshotSetId = nextSet;
            localStorage.setItem("snapshotSetId", nextSet);
            selectedSnapshotA = null;
            selectedSnapshotB = null;
            proceedSelectConsultant(id);
          },
          null,
          t.modalConfirm
        );
        return;
      } else if (snapshotPolicy === "multi_confirm") {
        const t = getTexts(getCurrentLang());
        showSnapshotModal(
          t.snapshotChangeMultiTitle,
          t.snapshotChangeMultiBody,
          () => {
            if (hasActiveConversation()) {
              addSystemMessage(`SnapshotSet changed: ${prevSet} → ${nextSet}`);
            }
            currentSnapshotSetId = nextSet;
            localStorage.setItem("snapshotSetId", nextSet);
            selectedSnapshotA = null;
            selectedSnapshotB = null;
            proceedSelectConsultant(id);
          },
          null,
          t.modalContinue
        );
        return;
      }
    }

    proceedSelectConsultant(id);
  }

  function proceedSelectConsultant(id) {
    selectedConsultant = id;

    document.querySelectorAll(".consultant-card").forEach(el => {
      const cid = el.getAttribute("data-consultant-id");
      el.classList.toggle("active", cid === id);
    });

    renderWelcomeMessage(getCurrentLang());
    renderBranchControls();
    updateSendButtonState();
    updateConsultantLayout();
  }

  function newChat() {
    sessionId = null;
    localStorage.removeItem("sessionId");
    conversationSnapshotSetId = null;
    localStorage.removeItem("conversationSnapshotSetId");
    responseDiv.innerHTML = "";
    activeHistorySessionId = null;
    stopTraceStream();
    resetTracePanel();
    setTraceStatusByKey("idle");
    setQueryProgress(false);
    closeTraceDocModal();
    updateFormPosition();
    updateSendButtonState();
    renderHistoryList();
  }

  function updateFormPosition() {
    const isEmpty = responseDiv.children.length === 0;
    form.classList.toggle("centered", isEmpty);
  }

  let queryInputBaseHeight = null;

  function growQueryInputIfNeeded() {
    if (!queryInput) return;
    if (queryInputBaseHeight === null) {
      queryInputBaseHeight = queryInput.offsetHeight || null;
    }
    const needsGrow = queryInput.scrollHeight > queryInput.clientHeight;
    if (!needsGrow) return;
    queryInput.style.height = "auto";
    const next = Math.max(queryInput.scrollHeight, queryInputBaseHeight || 0);
    if (next > 0) {
      queryInput.style.height = `${next}px`;
    }
  }

  function resetQueryInputHeight() {
    if (!queryInput) return;
    if (queryInputBaseHeight === null) {
      queryInputBaseHeight = queryInput.offsetHeight || null;
    }
    if (queryInputBaseHeight) {
      queryInput.style.height = `${queryInputBaseHeight}px`;
    } else {
      queryInput.style.height = "";
    }
  }

  function getSelectionTextInPre(pre) {
    if (!pre) return "";
    const sel = window.getSelection ? window.getSelection() : null;
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) return "";
    const range = sel.getRangeAt(0);
    const node = range.commonAncestorContainer;
    if (!pre.contains(node)) return "";
    return String(sel.toString() || "").trim();
  }

  function updateFindDocButtonsVisibility() {
    const traceOpen = document.body.classList.contains("trace-open");
    document.querySelectorAll("pre").forEach(pre => {
      const btn = pre.querySelector(".find-doc-btn");
      if (!btn) return;
      const selected = getSelectionTextInPre(pre);
      const shouldShow = traceOpen && traceDocTotal > 0 && Boolean(selected);
      btn.classList.toggle("hidden", !shouldShow);
    });
  }

  function setRequestInFlight(isActive) {
    requestInFlight = isActive;
    const t = getTexts(getCurrentLang());
    const label = submitButton ? submitButton.querySelector(".send-label") : null;
    if (label) label.textContent = isActive ? t.wait : t.send;
    submitButton.classList.toggle("is-cancel", !!isActive);
    if (typeof setQueryProgress === "function") setQueryProgress(isActive);
    if (!isActive && typeof clearTraceAttention === "function") {
      clearTraceAttention();
    }
  }

  async function sendCancelRequest(runId) {
    if (!runId) return;
    try {
      if (api && api.cancelRun) {
        await api.cancelRun({
          runId,
          sessionId,
          fakeAuthEnabled,
          activeDevUserId
        });
      }
    } catch (e) {
      // Best-effort cancel. Ignore failures.
    }
  }

  function cancelActiveRequest() {
    if (!requestInFlight) return;
    sendCancelRequest(currentTraceRunId);
    if (activeAbortController) {
      try { activeAbortController.abort(); } catch (e) {}
    }
    if (typeof stopTraceStream === "function") stopTraceStream({ hidePanel: false });
    if (typeof setTraceAvailable === "function") setTraceAvailable(true);
    if (typeof setTraceOpen === "function") setTraceOpen(false);
    if (typeof setTraceStatusByKey === "function") setTraceStatusByKey("cancelled");
    if (typeof clearTraceAttention === "function") clearTraceAttention();
  }

  function updateSendButtonState() {
    const lang = getCurrentLang();
    const t = getTexts(lang);

    const c = consultantsById[selectedConsultant];
    const mode = (c && (c.snapshotPickerMode || c.branchPickerMode)) ? (c.snapshotPickerMode || c.branchPickerMode) : "single";

    if (!submitButton) return;

    // Default: enabled.
    submitButton.disabled = false;
    submitButton.title = "";

    if (requestInFlight) {
      return;
    }

    if (mode !== "compare") return;

    // Compare mode: must have 2 different snapshots.
    let effectiveA = selectedSnapshotA;
    let effectiveB = selectedSnapshotB;
    const selects = typeof branchControls !== "undefined" && branchControls
      ? branchControls.querySelectorAll(".branch-select")
      : [];
    if (selects && selects.length >= 2) {
      effectiveA = selects[0].value || effectiveA;
      effectiveB = selects[1].value || effectiveB;
    }

    if (!effectiveA || !effectiveB) {
      submitButton.disabled = true;
      submitButton.title = t.compareChooseTwo;
      return;
    }

    if (effectiveA === effectiveB) {
      submitButton.disabled = true;
      submitButton.title = t.compareChooseDifferent;
      return;
    }
  }

  function addCopyButtons() {
    document.querySelectorAll("pre").forEach(pre => {
      if (pre.querySelector(".copy-btn")) return;

      const button = document.createElement("button");
      button.className = "copy-btn";
      const t = getTexts(getCurrentLang());
      button.textContent = t.copy;

      button.addEventListener("click", e => {
        e.preventDefault();
        const codeNode = pre.querySelector("code");
        const code = codeNode ? (codeNode.textContent || "") : "";
        const markCopied = () => {
          const t2 = getTexts(getCurrentLang());
          button.textContent = t2.copied;
          button.classList.add("copied");
          setTimeout(() => {
            const t3 = getTexts(getCurrentLang());
            button.textContent = t3.copy;
            button.classList.remove("copied");
          }, 2000);
        };

        const fallbackCopy = () => {
          const ta = document.createElement("textarea");
          ta.value = code;
          ta.style.position = "fixed";
          ta.style.top = "-1000px";
          ta.style.left = "-1000px";
          document.body.appendChild(ta);
          ta.focus();
          ta.select();
          try {
            const ok = document.execCommand("copy");
            if (ok) markCopied();
          } catch (err) {
          }
          document.body.removeChild(ta);
        };

        if (navigator.clipboard && window.isSecureContext) {
          navigator.clipboard.writeText(code).then(markCopied).catch(fallbackCopy);
        } else {
          fallbackCopy();
        }
      });

      pre.appendChild(button);

      const findBtn = document.createElement("button");
      findBtn.className = "find-doc-btn hidden";
      findBtn.textContent = t.findInDocs;
      findBtn.addEventListener("click", (e) => {
        e.preventDefault();
        if (!document.body.classList.contains("trace-open")) return;
        if (traceDocTotal <= 0) return;
        const selected = getSelectionTextInPre(pre);
        if (!selected) return;
        traceDocFilterQuery = normalizeDocFilterQuery(selected);
        if (traceDocFilterInput) traceDocFilterInput.value = selected;
        applyTraceFilters();
        updateTraceFilterClearState();
        if (typeof setTraceOpen === "function") setTraceOpen(true);
      });
      pre.appendChild(findBtn);
    });
    updateFindDocButtonsVisibility();
  }

  function scrollToLatestResponse() {
    if (responseDiv.firstChild) {
      responseDiv.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  marked.setOptions({
    breaks: true,
    gfm: true,
    highlight: function(code, lang) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value;
      }
      return hljs.highlightAuto(code).value;
    }
  });

  async function handleSubmit(e) {
    e.preventDefault();
    if (requestInFlight) {
      cancelActiveRequest();
      return;
    }
    const lang = getCurrentLang();
    const t = getTexts(lang);

    let query = (queryInput.value || "").trim();
    if (!query || query.length > 1000) {
      if (query.length > 1000) alert(t.error + " (" + t.queryTooLong + ")");
      return;
    }

    if (activeHistorySessionId) {
      sessionId = activeHistorySessionId;
      localStorage.setItem("sessionId", sessionId);
    }

    setRequestInFlight(true);

    const c = consultantsById[selectedConsultant];
    const mode = (c && (c.snapshotPickerMode || c.branchPickerMode)) ? (c.snapshotPickerMode || c.branchPickerMode) : "single";
    const snapshotsPayload = [];
    if (hasSnapshots(c)) {
      if (selectedSnapshotA) snapshotsPayload.push(selectedSnapshotA);
      if (mode === "compare" && selectedSnapshotB) snapshotsPayload.push(selectedSnapshotB);

      if (snapshotsPayload.length === 2 && snapshotsPayload[0] === snapshotsPayload[1]) {
        alert(t.compareChooseDifferent);
        submitButton.disabled = false;
        submitButton.innerText = t.send;
        return;
      }
    }

    const traceRunId = generateTraceRunId();

    const body = {
      query: query,
      consultant: selectedConsultant,
      translateChat: shouldTranslateChatForLang(lang),
      enableTrace: true,
      pipeline_run_id: traceRunId,
    };

    if (hasSnapshots(c)) {
      const snapSet = getSnapshotSetId(c);
      if (snapSet) body.snapshot_set_id = snapSet;
      body.snapshots = snapshotsPayload;
    } else {
      body.snapshots = [];
    }

    try {
      if (typeof setQueryProgress === "function") setQueryProgress(true);
      if (typeof setTraceAvailable === "function") setTraceAvailable(true);
      if (typeof setTraceOpen === "function") setTraceOpen(false);
      if (typeof resetTracePanel === "function") resetTracePanel();
      if (typeof setTraceStatusByKey === "function") setTraceStatusByKey("connecting");
      if (typeof startTraceStream === "function") startTraceStream(traceRunId);

      activeAbortController = new AbortController();
      if (!api || !api.postSearch) {
        throw new Error("API not ready");
      }
      const json = await api.postSearch({
        body,
        sessionId,
        fakeAuthEnabled,
        activeDevUserId,
        signal: activeAbortController.signal
      });
      if (json.session_id) {
        if (!activeHistorySessionId || activeHistorySessionId === json.session_id) {
          sessionId = json.session_id;
          localStorage.setItem("sessionId", sessionId);
        }
      }
      if (!sessionId) {
        sessionId = `local_${Date.now()}`;
        localStorage.setItem("sessionId", sessionId);
      }
      if (json.pipeline_run_id) {
        const backendRunId = String(json.pipeline_run_id);
        if (backendRunId !== traceRunId) {
          if (typeof startTraceStream === "function") startTraceStream(backendRunId);
        }
        setTraceOpen(false);
      } else {
        if (typeof stopTraceStream === "function") stopTraceStream({ hidePanel: false });
        if (typeof setTraceAvailable === "function") setTraceAvailable(true);
        if (typeof setTraceOpen === "function") setTraceOpen(false);
        if (typeof setTraceStatusByKey === "function") setTraceStatusByKey("no_run_id");
      }

      const markdown = json.results || t.noResponse;
      const html = DOMPurify.sanitize(marked.parse(markdown));
      const timestamp = new Date().toLocaleString(t.locale);

      const questionHTML = `
        <div class="bg-white p-4 rounded-xl shadow-sm border border-gray-100 response-entry">
          <div class="text-sm text-gray-500 mb-2">
            ${timestamp} ${t.ask}: <i>${escapeHtml(query)}</i>
          </div>
          <div class="markdown-content text-gray-900">${html}</div>
        </div>
      `;

      responseDiv.innerHTML = questionHTML + responseDiv.innerHTML;
      if (sessionId && typeof upsertHistorySession === "function") {
        upsertHistorySession({
          sessionId,
          consultantId: selectedConsultant,
          snapshotSetId: body.snapshot_set_id || null,
          snapshots: body.snapshots || [],
          question: query,
          answer: markdown
        });
      }
      if (body.snapshots && body.snapshots.length > 0 && body.snapshot_set_id) {
        conversationSnapshotSetId = body.snapshot_set_id;
        localStorage.setItem("conversationSnapshotSetId", conversationSnapshotSetId);
      }
      queryInput.value = "";
      if (typeof resetQueryInputHeight === "function") resetQueryInputHeight();
      addCopyButtons();
      scrollToLatestResponse();
    } catch (error) {
      if (error && error.name === "AbortError") {
        if (typeof stopTraceStream === "function") stopTraceStream({ hidePanel: false });
        if (typeof setTraceAvailable === "function") setTraceAvailable(true);
        if (typeof setTraceOpen === "function") setTraceOpen(false);
        if (typeof setTraceStatusByKey === "function") setTraceStatusByKey("cancelled");
        return;
      }
      console.error("submit:", error);
      alert(t.error);
      if (typeof stopTraceStream === "function") stopTraceStream({ hidePanel: false });
      if (typeof setTraceAvailable === "function") setTraceAvailable(true);
      if (typeof setTraceOpen === "function") setTraceOpen(false);
      if (typeof setTraceStatusByKey === "function") setTraceStatusByKey("start_error");
    } finally {
      activeAbortController = null;
      setRequestInFlight(false);
      if (typeof updateFormPosition === "function") updateFormPosition();
      localStorage.setItem("lang", lang);
      updateSendButtonState();
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  async function bootstrapUi() {
    showUiError("");

    // Auth state must be set before fetching /app-config.
    fakeAuthEnabled = fakeLoginRequired || localStorage.getItem("fakeAuthEnabled") === "1";
    const savedUser = localStorage.getItem("fakeAuthUserId") || "";
    if (isValidFakeUserId(savedUser)) {
      activeDevUserId = savedUser;
    } else if (fakeLoginRequired) {
      activeDevUserId = "";
      localStorage.removeItem("fakeAuthUserId");
    }
    // If OIDC is enabled, never send dev-user headers. Fake auth is only for DEV_ALLOW_NO_AUTH mode.
    if (oidcEnabled && !fakeLoginRequired) {
      fakeAuthEnabled = false;
      activeDevUserId = "";
      localStorage.setItem("fakeAuthEnabled", "0");
      localStorage.removeItem("fakeAuthUserId");
    }
    updateAuthUi();
    if (fakeLoginRequired && !activeDevUserId) {
      showFakeLoginModal(true);
      return;
    }

    await loadHistoryStore();
    historyCollapsed = localStorage.getItem("historyCollapsed") === "1";
    setHistoryCollapsed(historyCollapsed);
    updateHistoryOverlayMode();
    activeHistorySessionId = localStorage.getItem("sessionId") || null;
    renderHistoryList();
    if (!historyBackendAvailable) {
      showUiError("Brak uruchomionego serwera persystencji historii (chat-history).");
    }

    let startupIssue = null;
    let fetchedConfig = null;
    try {
      fetchedConfig = await fetchAppConfig();
    } catch (e) {
      console.error("bootstrapUi: fetchAppConfig:", e);
      startupIssue = e;
      // If OIDC is configured and backend requires auth, redirect to IdP.
      const status = e && typeof e === "object" ? e.status : null;
      if (oidcEnabled && oidc && (status === 401 || String(e && e.message || "").includes(" 401"))) {
        const hasAccess = typeof oidc.getAccessToken === "function" && !!oidc.getAccessToken();
        const hasRefresh = typeof oidc.getRefreshToken === "function" && !!oidc.getRefreshToken();

        // If we already have tokens, don't re-login in a loop. This is usually an API-side
        // validation mismatch (e.g. audience) and re-auth will not fix it.
        if (hasAccess || hasRefresh) {
          const detail = (e && typeof e === "object" && e.detail) ? String(e.detail || "").trim() : "";
          showUiError(
            `OIDC token was rejected by the API (401)${detail ? `: ${detail}` : ""}. ` +
            "Check server logs for [security_abuse] (invalid_audience/invalid_token/jwks_unavailable) and verify issuer/JWKS/audience."
          );
          return;
        }

        // Guard against accidental redirect loops.
        let last = 0;
        try { last = Number(sessionStorage.getItem("oidc_auto_login_ts") || "0") || 0; } catch (_) {}
        const now = Date.now();
        if (now - last < 30_000) {
          showUiError("Login required (401). Auto-redirect is paused to avoid a loop. Click Login.");
          return;
        }
        try { sessionStorage.setItem("oidc_auto_login_ts", String(now)); } catch (_) {}

        showUiError("Login required. Redirecting to the identity provider...");
        if (typeof oidc.login === "function") {
          try { await oidc.login(); } catch (_) {}
        }
        return;
      }
    }

    if (hasConsultants(fetchedConfig)) {
      appConfig = fetchedConfig;
    } else {
      const cached = loadCachedAppConfig();
      if (hasConsultants(cached)) {
        appConfig = cached;
        if (!startupIssue) startupIssue = new Error("No consultants in app-config response, using cached config.");
      } else {
        appConfig = cloneDefaultAppConfig();
        if (!startupIssue) startupIssue = new Error("No consultants in app-config response, using built-in config.");
      }
    }

    configureLanguageSettings(appConfig);
    rebuildConsultantsIndex();
    selectedConsultant =
      appConfig.defaultConsultantId ||
      (appConfig.consultants && appConfig.consultants[0] ? appConfig.consultants[0].id : null);

    selectedSnapshotA = null;
    selectedSnapshotB = null;

    const savedLang = getCurrentLang();
    applyLang(savedLang);
    resetTracePanel();
    setTraceAvailable(false);
    setTraceOpen(false);
    setTraceStatusByKey("idle");
    setQueryProgress(false);
    updateFormPosition();
    queryInput.focus();
    updateSendButtonState();

    if (startupIssue) {
      showUiError(
        `Brak połączenia z ${API_BASE}${APP_CONFIG_PATH}. Używam konfiguracji awaryjnej konsultantów.`
      );
    }
  }


  document.addEventListener("DOMContentLoaded", () => {
    if (langSelect) {
      renderLanguageSelector(getCurrentLang());
      langSelect.addEventListener("change", e => applyLang(e.target.value));
    }

    if (window.initResizeController) {
      window.initResizeController();
    }
    if (window.registerResizeHandler) {
      window.registerResizeHandler(() => {
        autoSizeAllBranchSelects();
        updateConsultantLayout();
        updateHistoryOverlayMode();
      });
    }

    form.addEventListener("submit", handleSubmit);

    if (authToggleBtn) {
      authToggleBtn.addEventListener("click", () => {
        if (fakeLoginRequired) return;
        if (oidcEnabled && oidc) {
          const hasOidc = typeof oidc.getAccessToken === "function" && !!oidc.getAccessToken();
          if (hasOidc && typeof oidc.logout === "function") {
            Promise.resolve(oidc.logout()).catch((e) => showUiError(`OIDC logout failed: ${String((e && e.message) || e)}`));
          }
          if (!hasOidc && typeof oidc.login === "function") {
            Promise.resolve(oidc.login()).catch((e) => showUiError(`OIDC login failed: ${String((e && e.message) || e)}`));
          }
          return;
        }
        fakeAuthEnabled = !fakeAuthEnabled;
        localStorage.setItem("fakeAuthEnabled", fakeAuthEnabled ? "1" : "0");
        updateAuthUi();
        if (!fakeAuthEnabled) {
          historySearchQuery = "";
          if (historySearchInput) historySearchInput.value = "";
          if (queryInput) {
            queryInput.value = "";
            resetQueryInputHeight();
          }
          newChat();
        }
        bootstrapUi();
      });
    }
    if (historyCollapseBtn) {
      historyCollapseBtn.addEventListener("click", () => setHistoryCollapsed(true));
    }
    if (historyExpandBtn) {
      historyExpandBtn.addEventListener("click", () => setHistoryCollapsed(false));
    }
    if (historyNewChatBtn) {
      historyNewChatBtn.addEventListener("click", () => newChat());
    }
    if (historyCompactNewChatBtn) {
      historyCompactNewChatBtn.addEventListener("click", () => newChat());
    }
    if (historySearchInput) {
      historySearchInput.addEventListener("input", (evt) => {
        historySearchQuery = String(evt.target.value || "");
        renderHistoryList();
      });
    }
    if (historySearchBtn) {
      historySearchBtn.addEventListener("click", () => openHistorySearchModal());
    }
    if (historyCompactSearchBtn) {
      historyCompactSearchBtn.addEventListener("click", () => openHistorySearchModal());
    }
    if (historySearchModalClose) {
      historySearchModalClose.addEventListener("click", () => setHistorySearchModalVisible(false));
    }
    if (historySearchModalBackdrop) {
      historySearchModalBackdrop.addEventListener("click", (evt) => {
        if (evt.target === historySearchModalBackdrop) setHistorySearchModalVisible(false);
      });
    }
    if (historySearchModalInput) {
      historySearchModalInput.addEventListener("input", (evt) => {
        historySearchModalQuery = String(evt.target.value || "");
        historySearchModalItems = [];
        historySearchModalCursor = null;
        fetchHistorySearchPage({ query: historySearchModalQuery, cursor: null });
      });
    }
    if (historySearchModalImportant) {
      historySearchModalImportant.addEventListener("change", (evt) => {
        historySearchModalOnlyImportant = !!evt.target.checked;
        renderHistorySearchResults();
      });
    }
    const toggleAuthCompactMenu = (btn, evt) => {
      if (!btn || !authCompactMenu) return;
      evt.stopPropagation();
      const rect = btn.getBoundingClientRect();
      authCompactMenu.style.left = `${Math.max(8, rect.left)}px`;
      authCompactMenu.style.bottom = `${Math.max(8, window.innerHeight - rect.top + 8)}px`;
      authCompactMenu.classList.toggle("is-open");
    };
    if (authCompactBtn) {
      authCompactBtn.addEventListener("click", (evt) => toggleAuthCompactMenu(authCompactBtn, evt));
    }
    if (authCompactAction) {
      authCompactAction.addEventListener("click", () => {
        if (oidcEnabled && oidc) {
          const hasOidc = typeof oidc.getAccessToken === "function" && !!oidc.getAccessToken();
          if (hasOidc && typeof oidc.logout === "function") {
            Promise.resolve(oidc.logout()).catch((e) => showUiError(`OIDC logout failed: ${String((e && e.message) || e)}`));
          } else if (!hasOidc && typeof oidc.login === "function") {
            Promise.resolve(oidc.login()).catch((e) => showUiError(`OIDC login failed: ${String((e && e.message) || e)}`));
          }
          if (authCompactMenu) authCompactMenu.classList.remove("is-open");
          return;
        }
        if (fakeLoginRequired) {
          activeDevUserId = "";
          localStorage.removeItem("fakeAuthUserId");
          updateAuthUi();
          if (authCompactMenu) authCompactMenu.classList.remove("is-open");
          newChat();
          showFakeLoginModal(true);
          return;
        }
        fakeAuthEnabled = !fakeAuthEnabled;
        localStorage.setItem("fakeAuthEnabled", fakeAuthEnabled ? "1" : "0");
        updateAuthUi();
        if (authCompactMenu) authCompactMenu.classList.remove("is-open");
        if (!fakeAuthEnabled) {
          historySearchQuery = "";
          if (historySearchInput) historySearchInput.value = "";
          if (queryInput) {
            queryInput.value = "";
            resetQueryInputHeight();
          }
          newChat();
        }
        bootstrapUi();
      });
    }
    if (fakeLoginConfirm) {
      fakeLoginConfirm.addEventListener("click", () => {
        const selected = fakeLoginSelect ? String(fakeLoginSelect.value || "") : "";
        if (!isValidFakeUserId(selected)) return;
        activeDevUserId = selected;
        localStorage.setItem("fakeAuthUserId", activeDevUserId);
        fakeAuthEnabled = true;
        localStorage.setItem("fakeAuthEnabled", "1");
        updateAuthUi();
        showFakeLoginModal(false);
        bootstrapUi();
      });
    }
    if (authCompactClearHistory) {
      authCompactClearHistory.addEventListener("click", () => {
        clearAllHistory();
        if (authCompactMenu) authCompactMenu.classList.remove("is-open");
      });
    }
    if (historyContextRename) {
      historyContextRename.addEventListener("click", () => {
        if (historyContextTarget) {
          openRenameChatModal(historyContextTarget.sessionId, buildHistoryItemTitle(historyContextTarget));
        }
        closeHistoryContextMenu();
      });
    }
    if (historyContextImportant) {
      historyContextImportant.addEventListener("click", () => {
        if (historyContextTarget) {
          updateHistorySessionMeta(historyContextTarget.sessionId, { important: !isHistoryImportant(historyContextTarget) });
        }
        closeHistoryContextMenu();
      });
    }
    if (historyContextDelete) {
      historyContextDelete.addEventListener("click", () => {
        if (historyContextTarget) {
          if (confirm(getTexts(getCurrentLang()).historyDeleteConfirm || "Usunąć czat?")) {
            deleteHistorySession(historyContextTarget.sessionId);
          }
        }
        closeHistoryContextMenu();
      });
    }
    if (historyContextClearAll) {
      historyContextClearAll.addEventListener("click", () => {
        clearAllHistory();
        closeHistoryContextMenu();
      });
    }
    if (renameChatModalCancel) {
      renameChatModalCancel.addEventListener("click", () => {
        setRenameChatModalVisible(false);
      });
    }
    if (renameChatModalConfirm) {
      renameChatModalConfirm.addEventListener("click", () => {
        const next = (renameChatInput && renameChatInput.value || "").trim();
        if (renameTargetSessionId && next) {
          updateHistorySessionMeta(renameTargetSessionId, { title: next });
        }
        setRenameChatModalVisible(false);
      });
    }
    if (clearHistoryModalCancel) {
      clearHistoryModalCancel.addEventListener("click", () => {
        setClearHistoryModalVisible(false);
      });
    }
    if (clearHistoryModalConfirm) {
      clearHistoryModalConfirm.addEventListener("click", () => {
        setClearHistoryModalVisible(false);
        clearAllHistoryConfirmed();
      });
    }
    if (renameChatModalBackdrop) {
      renameChatModalBackdrop.addEventListener("click", (evt) => {
        if (evt.target === renameChatModalBackdrop) setRenameChatModalVisible(false);
      });
    }
    if (clearHistoryModalBackdrop) {
      clearHistoryModalBackdrop.addEventListener("click", (evt) => {
        if (evt.target === clearHistoryModalBackdrop) setClearHistoryModalVisible(false);
      });
    }
    if (historySearchModalMore) {
      historySearchModalMore.addEventListener("click", () => {
        fetchHistorySearchPage({ query: historySearchModalQuery, cursor: historySearchModalCursor });
      });
    }
    document.addEventListener("keydown", (evt) => {
      const key = String(evt.key || "").toLowerCase();
      if ((evt.ctrlKey || evt.metaKey) && key === "k") {
        evt.preventDefault();
        openHistorySearchModal();
      }
      if (key === "escape" && historySearchModalOpen) {
        setHistorySearchModalVisible(false);
      }
    });
    document.addEventListener("click", (evt) => {
      if (historyContextMenu && historyContextMenu.classList.contains("is-open") && !historyContextMenu.contains(evt.target)) {
        closeHistoryContextMenu();
      }
      if (authCompactMenu && authCompactMenu.classList.contains("is-open") && !authCompactMenu.contains(evt.target) && evt.target !== authCompactBtn) {
        authCompactMenu.classList.remove("is-open");
      }
    });

    if (traceHandle) {
      traceHandle.addEventListener("click", () => setTraceOpen(true));
      traceHandle.addEventListener("keydown", (evt) => {
        if (evt.key === "Enter" || evt.key === " ") {
          evt.preventDefault();
          setTraceOpen(true);
        }
      });
    }
    if (traceCloseBtn) {
      traceCloseBtn.addEventListener("click", () => setTraceOpen(false));
    }
    if (traceBackdrop) {
      traceBackdrop.addEventListener("click", () => setTraceOpen(false));
    }
    if (traceDocModalClose) {
      traceDocModalClose.addEventListener("click", closeTraceDocModal);
    }
    if (traceDocModalBackdrop) {
      traceDocModalBackdrop.addEventListener("click", (evt) => {
        if (evt.target === traceDocModalBackdrop) closeTraceDocModal();
      });
    }
    if (traceDocPrevBtn) {
      traceDocPrevBtn.addEventListener("click", () => {
        if (traceDocModalIndex <= 0) return;
        const key = traceDocModalKeys[traceDocModalIndex - 1];
        if (key) openTraceDocModalByKey(key, traceDocModalKeys);
      });
    }
    if (traceDocNextBtn) {
      traceDocNextBtn.addEventListener("click", () => {
        if (traceDocModalIndex < 0 || traceDocModalIndex >= traceDocModalKeys.length - 1) return;
        const key = traceDocModalKeys[traceDocModalIndex + 1];
        if (key) openTraceDocModalByKey(key, traceDocModalKeys);
      });
    }
    if (traceFilterInput) {
      traceFilterInput.addEventListener("input", (evt) => {
        traceFilterQuery = normalizeTraceFilterQuery(evt.target.value);
        applyTraceFilters();
      });
    }
    if (traceDocFilterInput) {
      traceDocFilterInput.addEventListener("input", (evt) => {
        traceDocFilterQuery = normalizeDocFilterQuery(evt.target.value);
        applyTraceFilters();
      });
    }
    if (traceFilterClearBtn) {
      traceFilterClearBtn.addEventListener("click", () => {
        traceFilterQuery = "";
        traceDocFilterQuery = "";
        if (traceFilterInput) traceFilterInput.value = "";
        if (traceDocFilterInput) traceDocFilterInput.value = "";
        applyTraceFilters();
      });
    }

    queryInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        form.dispatchEvent(new Event("submit", { cancelable: true }));
        return;
      }
      if (e.key === "Enter" && e.shiftKey) {
        setTimeout(() => {
          growQueryInputIfNeeded();
        }, 0);
      }
    });
    document.addEventListener("keydown", (e) => {
      if (traceDocModalBackdrop && traceDocModalBackdrop.style.display !== "none") {
        if (e.key === "Escape") {
          closeTraceDocModal();
          return;
        }
        if (e.key === "ArrowLeft" && traceDocModalIndex > 0) {
          const key = traceDocModalKeys[traceDocModalIndex - 1];
          if (key) openTraceDocModalByKey(key, traceDocModalKeys);
          return;
        }
        if (e.key === "ArrowRight" && traceDocModalIndex >= 0 && traceDocModalIndex < traceDocModalKeys.length - 1) {
          const key = traceDocModalKeys[traceDocModalIndex + 1];
          if (key) openTraceDocModalByKey(key, traceDocModalKeys);
          return;
        }
      }
      if (e.key !== "Escape") return;
      if (document.body.classList.contains("trace-open")) {
        setTraceOpen(false);
      }
    });

    document.addEventListener("selectionchange", () => {
      updateFindDocButtonsVisibility();
    });

    resetTracePanel();
    setTraceAvailable(false);
    setTraceOpen(false);
    setTraceStatusByKey("idle");
    setQueryProgress(false);
    updateFormPosition();

    if (oidcEnabled && oidc && typeof oidc.handleRedirectCallback === "function") {
      oidc.handleRedirectCallback()
        .then((r) => {
          if (r && r.handled && r.ok === false) {
            showUiError(
              `Logowanie OIDC nie powiodło się (${String(r.error || "unknown")}). ` +
              "Sprawdź konfigurację klienta w IdP (redirect URI / web origins / CORS)."
            );
          }
          updateAuthUi();
        })
        .catch((e) => {
          showUiError(
            `Logowanie OIDC nie powiodło się (${String((e && e.message) || e)}). ` +
            "Sprawdź konfigurację klienta w IdP (redirect URI / web origins / CORS)."
          );
        })
        .finally(() => bootstrapUi());
    } else {
      bootstrapUi();
    }
  });

  window.App = window.App || {};
  window.App.features = window.App.features || {};

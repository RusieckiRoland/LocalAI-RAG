(function () {
  const App = window.App = window.App || {};

  const form = document.getElementById("queryForm");
  const queryInput = document.getElementById("query");
  const responseDiv = document.getElementById("response");
  const submitButton = document.getElementById("sendBtn");
  const welcomeMessage = document.getElementById("welcomeMessage");
  const langSelect = document.getElementById("lang");
  const consultantsContainer = document.getElementById("consultants");
  const newChatBtn = document.getElementById("newChatBtn");
  const uiError = document.getElementById("uiError");
  const branchControls = document.getElementById("branchControls");
  const controlsSpacer = document.getElementById("controlsSpacer");
  const authToggleBtn = document.getElementById("authToggleBtn");
  const authUserSelect = document.getElementById("authUserSelect");
  const authControls = document.getElementById("authControls");
  const authCompact = document.getElementById("authCompact");
  const authCompactBtn = document.getElementById("authCompactBtn");
  const authCompactMenu = document.getElementById("authCompactMenu");
  const authCompactAction = document.getElementById("authCompactAction");
  const authCompactActionLabel = document.getElementById("authCompactActionLabel");
  const authCompactActionIcon = document.getElementById("authCompactActionIcon");
  const authCompactClearHistory = document.getElementById("authCompactClearHistory");
  const authCompactClearHistoryLabel = document.getElementById("authCompactClearHistoryLabel");
  const historyPanel = document.getElementById("history-panel");
  const historyCollapseBtn = document.getElementById("historyCollapseBtn");
  const historyExpandBtn = document.getElementById("historyExpandBtn");
  const historyNewChatBtn = document.getElementById("historyNewChatBtn");
  const historySearchInput = document.getElementById("historySearchInput");
  const historySearchBtn = document.getElementById("historySearchBtn");
  const historySectionTitle = document.getElementById("historySectionTitle");
  const historyList = document.getElementById("historyList");
  const historyEmpty = document.getElementById("historyEmpty");
  const snapshotModalBackdrop = document.getElementById("snapshotModalBackdrop");
  const snapshotModalTitle = document.getElementById("snapshotModalTitle");
  const snapshotModalBody = document.getElementById("snapshotModalBody");
  const snapshotModalCancel = document.getElementById("snapshotModalCancel");
  const snapshotModalConfirm = document.getElementById("snapshotModalConfirm");
  const traceList = document.getElementById("traceList");
  const traceTitle = document.getElementById("traceTitle");
  const traceStatus = document.getElementById("traceStatus");
  const traceFilterInput = document.getElementById("traceFilterInput");
  const traceDocFilterWrap = document.getElementById("traceDocFilterWrap");
  const traceDocFilterInput = document.getElementById("traceDocFilterInput");
  const traceFilterClearBtn = document.getElementById("traceFilterClearBtn");
  const traceFilterEmpty = document.getElementById("traceFilterEmpty");
  const traceHandle = document.getElementById("traceHandle");
  const traceCloseBtn = document.getElementById("traceCloseBtn");
  const traceBackdrop = document.getElementById("trace-backdrop");
  const queryProgress = document.getElementById("queryProgress");
  const traceDocModalBackdrop = document.getElementById("traceDocModalBackdrop");
  const traceDocModalTitle = document.getElementById("traceDocModalTitle");
  const traceDocModalBody = document.getElementById("traceDocModalBody");
  const traceDocModalCount = document.getElementById("traceDocModalCount");
  const traceDocPrevBtn = document.getElementById("traceDocPrev");
  const traceDocNextBtn = document.getElementById("traceDocNext");
  const traceDocModalClose = document.getElementById("traceDocModalClose");
  const historySearchModalBackdrop = document.getElementById("historySearchModalBackdrop");
  const historySearchModalTitle = document.getElementById("historySearchModalTitle");
  const historySearchModalInput = document.getElementById("historySearchModalInput");
  const historySearchModalList = document.getElementById("historySearchModalList");
  const historySearchModalEmpty = document.getElementById("historySearchModalEmpty");
  const historySearchModalMore = document.getElementById("historySearchModalMore");
  const historySearchModalClose = document.getElementById("historySearchModalClose");
  const historySearchModalCount = document.getElementById("historySearchModalCount");
  const historySearchModalImportant = document.getElementById("historySearchModalImportant");
  const historySearchModalImportantLabel = document.getElementById("historySearchModalImportantLabel");
  const renameChatModalBackdrop = document.getElementById("renameChatModalBackdrop");
  const renameChatModalTitle = document.getElementById("renameChatModalTitle");
  const renameChatModalLabel = document.getElementById("renameChatModalLabel");
  const renameChatInput = document.getElementById("renameChatInput");
  const renameChatModalCancel = document.getElementById("renameChatModalCancel");
  const renameChatModalConfirm = document.getElementById("renameChatModalConfirm");
  const clearHistoryModalBackdrop = document.getElementById("clearHistoryModalBackdrop");
  const clearHistoryModalTitle = document.getElementById("clearHistoryModalTitle");
  const clearHistoryModalBody = document.getElementById("clearHistoryModalBody");
  const clearHistoryModalCancel = document.getElementById("clearHistoryModalCancel");
  const clearHistoryModalConfirm = document.getElementById("clearHistoryModalConfirm");
  const historyContextMenu = document.getElementById("historyContextMenu");
  const historyContextRename = document.getElementById("historyContextRename");
  const historyContextImportant = document.getElementById("historyContextImportant");
  const historyContextDelete = document.getElementById("historyContextDelete");
  const historyContextClearAll = document.getElementById("historyContextClearAll");
  const historyContextRenameLabel = document.getElementById("historyContextRenameLabel");
  const historyContextImportantLabel = document.getElementById("historyContextImportantLabel");
  const historyContextDeleteLabel = document.getElementById("historyContextDeleteLabel");
  const historyContextClearAllLabel = document.getElementById("historyContextClearAllLabel");

  App.dom = {
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
    authUserSelect,
    authControls,
    authCompact,
    authCompactBtn,
    authCompactMenu,
    authCompactAction,
    authCompactActionLabel,
    authCompactActionIcon,
    authCompactClearHistory,
    authCompactClearHistoryLabel,
    historyPanel,
    historyCollapseBtn,
    historyExpandBtn,
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
  };
})();

(function () {
  const App = window.App = window.App || {};

  const STORAGE = {
    accessToken: "oidc_access_token",
    idToken: "oidc_id_token",
    refreshToken: "oidc_refresh_token",
    expiresAt: "oidc_expires_at_ms",
    userName: "oidc_user_name",
    state: "oidc_pkce_state",
    nonce: "oidc_pkce_nonce",
    verifier: "oidc_pkce_verifier",
    discovery: "oidc_discovery_cache_v1",
  };

  function getPublicOidcConfig() {
    const root = (window.__RAG_PUBLIC_CONFIG__ && typeof window.__RAG_PUBLIC_CONFIG__ === "object")
      ? window.__RAG_PUBLIC_CONFIG__
      : {};
    // New pattern: auth.oidc + auth.oidc.client
    const auth = (root.auth && typeof root.auth === "object") ? root.auth : {};
    const oidc = (auth.oidc && typeof auth.oidc === "object") ? auth.oidc : {};
    const client = (oidc.client && typeof oidc.client === "object") ? oidc.client : {};

    // Legacy fallback (deprecated): root.oidc
    const legacy = (root.oidc && typeof root.oidc === "object") ? root.oidc : {};

    const enabled = (oidc.enabled !== undefined) ? !!oidc.enabled : !!legacy.enabled;
    const issuer = String(oidc.issuer || legacy.issuer || "").trim();
    const client_id = String(client.client_id || legacy.client_id || "").trim();
    const scopes = Array.isArray(client.scopes) ? client.scopes : (Array.isArray(legacy.scopes) ? legacy.scopes : []);
    const redirect_path = String(client.redirect_path || legacy.redirect_path || "/").trim() || "/";
    const post_logout_redirect_path = String(client.post_logout_redirect_path || legacy.post_logout_redirect_path || "/").trim() || "/";
    const authorization_endpoint = String(client.authorization_endpoint || legacy.authorization_endpoint || "").trim();
    const token_endpoint = String(client.token_endpoint || legacy.token_endpoint || "").trim();
    const end_session_endpoint = String(client.end_session_endpoint || legacy.end_session_endpoint || "").trim();
    const extra_auth_params = (client.extra_auth_params && typeof client.extra_auth_params === "object")
      ? client.extra_auth_params
      : ((legacy.extra_auth_params && typeof legacy.extra_auth_params === "object") ? legacy.extra_auth_params : {});
    const extra_token_params = (client.extra_token_params && typeof client.extra_token_params === "object")
      ? client.extra_token_params
      : ((legacy.extra_token_params && typeof legacy.extra_token_params === "object") ? legacy.extra_token_params : {});

    return {
      enabled,
      issuer,
      client_id,
      scopes,
      redirect_path,
      post_logout_redirect_path,
      authorization_endpoint,
      token_endpoint,
      end_session_endpoint,
      extra_auth_params,
      extra_token_params,
    };
  }

  function isOidcEnabled(cfg) {
    return !!(cfg && cfg.enabled && cfg.issuer && cfg.client_id);
  }

  function safeSessionGet(key) {
    try { return sessionStorage.getItem(key); } catch (e) { return null; }
  }
  function safeSessionSet(key, value) {
    try { sessionStorage.setItem(key, value); } catch (e) {}
  }
  function safeSessionRemove(key) {
    try { sessionStorage.removeItem(key); } catch (e) {}
  }

  function base64UrlEncode(bytes) {
    let s = "";
    for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    const b64 = btoa(s);
    return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
  }

  function randomString(len) {
    const n = Math.max(16, Math.min(128, Number(len) || 64));
    const buf = new Uint8Array(n);
    if (window.crypto && typeof window.crypto.getRandomValues === "function") {
      window.crypto.getRandomValues(buf);
    } else {
      for (let i = 0; i < buf.length; i++) buf[i] = Math.floor(Math.random() * 256);
    }
    return base64UrlEncode(buf).slice(0, n);
  }

  async function sha256Base64Url(input) {
    const enc = new TextEncoder();
    const data = enc.encode(String(input || ""));
    const digest = await crypto.subtle.digest("SHA-256", data);
    return base64UrlEncode(new Uint8Array(digest));
  }

  function decodeJwtPayload(token) {
    try {
      const raw = String(token || "");
      const parts = raw.split(".");
      if (parts.length < 2) return null;
      let b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
      while (b64.length % 4) b64 += "=";
      const json = atob(b64);
      return JSON.parse(json);
    } catch (e) {
      return null;
    }
  }

  function deriveUserNameFromIdToken(idToken) {
    const payload = decodeJwtPayload(idToken);
    if (!payload || typeof payload !== "object") return "";
    const family = String(payload.family_name || "").trim();
    const given = String(payload.given_name || "").trim();
    const name = String(payload.name || "").trim();
    const preferred = String(payload.preferred_username || "").trim();
    if (family && given) return `${family} ${given}`;
    if (name) return name;
    return preferred;
  }

  async function getDiscovery(cfg) {
    const cached = safeSessionGet(STORAGE.discovery);
    if (cached) {
      try {
        const parsed = JSON.parse(cached);
        if (parsed && typeof parsed === "object" && parsed.issuer === cfg.issuer) return parsed;
      } catch (e) {}
    }

    // Allow explicit overrides (useful for non-standard IdPs).
    const explicit = {
      issuer: String(cfg.issuer || "").trim(),
      authorization_endpoint: String(cfg.authorization_endpoint || "").trim(),
      token_endpoint: String(cfg.token_endpoint || "").trim(),
      end_session_endpoint: String(cfg.end_session_endpoint || "").trim(),
    };
    if (explicit.authorization_endpoint && explicit.token_endpoint) {
      safeSessionSet(STORAGE.discovery, JSON.stringify(explicit));
      return explicit;
    }

    const url = `${String(cfg.issuer).replace(/\\/+$/g, "")}/.well-known/openid-configuration`;
    const res = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!res.ok) throw new Error(`OIDC discovery failed: ${res.status}`);
    const json = await res.json();
    const out = {
      issuer: String(json.issuer || cfg.issuer || "").trim(),
      authorization_endpoint: String(json.authorization_endpoint || "").trim(),
      token_endpoint: String(json.token_endpoint || "").trim(),
      end_session_endpoint: String(json.end_session_endpoint || "").trim(),
    };
    safeSessionSet(STORAGE.discovery, JSON.stringify(out));
    return out;
  }

  function getAccessToken() {
    const token = safeSessionGet(STORAGE.accessToken) || "";
    const expiresAt = Number(safeSessionGet(STORAGE.expiresAt) || "0") || 0;
    if (!token) return "";
    if (expiresAt && Date.now() > (expiresAt - 10_000)) return ""; // 10s skew
    return token;
  }

  function getRefreshToken() {
    return String(safeSessionGet(STORAGE.refreshToken) || "").trim();
  }

  function getUserName() {
    return String(safeSessionGet(STORAGE.userName) || "").trim();
  }

  function clearTokens() {
    safeSessionRemove(STORAGE.accessToken);
    safeSessionRemove(STORAGE.idToken);
    safeSessionRemove(STORAGE.refreshToken);
    safeSessionRemove(STORAGE.expiresAt);
    safeSessionRemove(STORAGE.userName);
  }

  let refreshInFlight = null;

  async function refresh() {
    const cfg = getPublicOidcConfig();
    if (!isOidcEnabled(cfg)) return { ok: false, error: "oidc_disabled" };
    const rt = getRefreshToken();
    if (!rt) return { ok: false, error: "missing_refresh_token" };

    if (refreshInFlight) return refreshInFlight;
    refreshInFlight = (async () => {
      try {
        const disco = await getDiscovery(cfg);
        if (!disco.token_endpoint) throw new Error("OIDC missing token_endpoint");

        const body = new URLSearchParams();
        body.set("grant_type", "refresh_token");
        body.set("refresh_token", rt);
        body.set("client_id", String(cfg.client_id));

        const extra = (cfg.extra_token_params && typeof cfg.extra_token_params === "object") ? cfg.extra_token_params : {};
        Object.keys(extra).forEach((k) => {
          const key = String(k || "").trim();
          if (!key) return;
          body.set(key, String(extra[k]));
        });

        const res = await fetch(disco.token_endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: body.toString(),
        });
        if (!res.ok) {
          clearTokens();
          return { ok: false, error: `refresh_failed:${res.status}` };
        }
        const json = await res.json();
        const accessToken = String(json.access_token || "");
        const idToken = String(json.id_token || "");
        const refreshToken = String(json.refresh_token || rt);
        const expiresIn = Number(json.expires_in || 0) || 0;
        if (!accessToken) {
          clearTokens();
          return { ok: false, error: "missing_access_token" };
        }
        safeSessionSet(STORAGE.accessToken, accessToken);
        if (idToken) safeSessionSet(STORAGE.idToken, idToken);
        if (refreshToken) safeSessionSet(STORAGE.refreshToken, refreshToken);
        if (expiresIn) safeSessionSet(STORAGE.expiresAt, String(Date.now() + (expiresIn * 1000)));
        const userName = idToken ? deriveUserNameFromIdToken(idToken) : "";
        if (userName) safeSessionSet(STORAGE.userName, userName);
        return { ok: true };
      } catch (e) {
        clearTokens();
        return { ok: false, error: "refresh_exception" };
      } finally {
        refreshInFlight = null;
      }
    })();
    return refreshInFlight;
  }

  async function login() {
    const cfg = getPublicOidcConfig();
    if (!isOidcEnabled(cfg)) return;
    const disco = await getDiscovery(cfg);
    if (!disco.authorization_endpoint) throw new Error("OIDC missing authorization_endpoint");

    const state = randomString(32);
    const nonce = randomString(32);
    const verifier = randomString(64);
    const challenge = await sha256Base64Url(verifier);

    safeSessionSet(STORAGE.state, state);
    safeSessionSet(STORAGE.nonce, nonce);
    safeSessionSet(STORAGE.verifier, verifier);

    const scopes = Array.isArray(cfg.scopes) ? cfg.scopes : ["openid", "profile", "email"];
    const scope = scopes.map((s) => String(s || "").trim()).filter(Boolean).join(" ") || "openid profile email";
    const redirectUri = `${window.location.origin}${String(cfg.redirect_path || "/")}`;

    const params = new URLSearchParams();
    params.set("response_type", "code");
    params.set("client_id", String(cfg.client_id));
    params.set("redirect_uri", redirectUri);
    params.set("scope", scope);
    params.set("state", state);
    params.set("nonce", nonce);
    params.set("code_challenge", challenge);
    params.set("code_challenge_method", "S256");

    const extra = (cfg.extra_auth_params && typeof cfg.extra_auth_params === "object") ? cfg.extra_auth_params : {};
    Object.keys(extra).forEach((k) => {
      const key = String(k || "").trim();
      if (!key) return;
      params.set(key, String(extra[k]));
    });

    window.location.assign(`${disco.authorization_endpoint}?${params.toString()}`);
  }

  async function handleRedirectCallback() {
    const cfg = getPublicOidcConfig();
    if (!isOidcEnabled(cfg)) return { handled: false };

    const url = new URL(window.location.href);
    const code = url.searchParams.get("code");
    const state = url.searchParams.get("state");
    const err = url.searchParams.get("error");
    if (err) {
      // Clean URL and leave user unauthenticated.
      url.searchParams.delete("error");
      url.searchParams.delete("error_description");
      url.searchParams.delete("state");
      url.searchParams.delete("code");
      window.history.replaceState({}, document.title, url.toString());
      clearTokens();
      return { handled: true, ok: false, error: err };
    }
    if (!code || !state) return { handled: false };

    const expected = safeSessionGet(STORAGE.state) || "";
    const verifier = safeSessionGet(STORAGE.verifier) || "";
    if (!expected || state !== expected || !verifier) {
      // Clean URL so we don't keep re-processing the same callback params.
      url.searchParams.delete("code");
      url.searchParams.delete("state");
      window.history.replaceState({}, document.title, url.toString());
      clearTokens();
      return { handled: true, ok: false, error: "invalid_state" };
    }

    const disco = await getDiscovery(cfg);
    if (!disco.token_endpoint) throw new Error("OIDC missing token_endpoint");

    const redirectUri = `${window.location.origin}${String(cfg.redirect_path || "/")}`;

    const body = new URLSearchParams();
    body.set("grant_type", "authorization_code");
    body.set("code", code);
    body.set("redirect_uri", redirectUri);
    body.set("client_id", String(cfg.client_id));
    body.set("code_verifier", verifier);

    const extra = (cfg.extra_token_params && typeof cfg.extra_token_params === "object") ? cfg.extra_token_params : {};
    Object.keys(extra).forEach((k) => {
      const key = String(k || "").trim();
      if (!key) return;
      body.set(key, String(extra[k]));
    });

    const res = await fetch(disco.token_endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
    if (!res.ok) {
      clearTokens();
      return { handled: true, ok: false, error: `token_exchange_failed:${res.status}` };
    }
    const json = await res.json();
    const accessToken = String(json.access_token || "");
    const idToken = String(json.id_token || "");
    const refreshToken = String(json.refresh_token || "");
    const expiresIn = Number(json.expires_in || 0) || 0;
    if (!accessToken) {
      clearTokens();
      return { handled: true, ok: false, error: "missing_access_token" };
    }

    safeSessionSet(STORAGE.accessToken, accessToken);
    if (idToken) safeSessionSet(STORAGE.idToken, idToken);
    if (refreshToken) safeSessionSet(STORAGE.refreshToken, refreshToken);
    if (expiresIn) safeSessionSet(STORAGE.expiresAt, String(Date.now() + (expiresIn * 1000)));
    const userName = idToken ? deriveUserNameFromIdToken(idToken) : "";
    if (userName) safeSessionSet(STORAGE.userName, userName);

    // Cleanup.
    safeSessionRemove(STORAGE.state);
    safeSessionRemove(STORAGE.nonce);
    safeSessionRemove(STORAGE.verifier);
    url.searchParams.delete("code");
    url.searchParams.delete("state");
    window.history.replaceState({}, document.title, url.toString());
    return { handled: true, ok: true };
  }

  async function logout() {
    const cfg = getPublicOidcConfig();
    if (!isOidcEnabled(cfg)) {
      clearTokens();
      return;
    }
    const disco = await getDiscovery(cfg);
    const idToken = safeSessionGet(STORAGE.idToken) || "";
    const postLogout = `${window.location.origin}${String(cfg.post_logout_redirect_path || "/")}`;
    clearTokens();
    if (disco.end_session_endpoint) {
      const params = new URLSearchParams();
      if (idToken) params.set("id_token_hint", idToken);
      params.set("post_logout_redirect_uri", postLogout);
      window.location.assign(`${disco.end_session_endpoint}?${params.toString()}`);
      return;
    }
    window.location.assign(postLogout);
  }

  App.services = App.services || {};
  App.services.oidc = {
    isEnabled: () => isOidcEnabled(getPublicOidcConfig()),
    getAccessToken,
    getRefreshToken,
    getUserName,
    login,
    logout,
    handleRedirectCallback,
    refresh,
    clearTokens,
  };
})();

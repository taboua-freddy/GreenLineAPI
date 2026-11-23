const $ = id => document.getElementById(id);
  const adminInput = $("admin-token");
  adminInput.value = sessionStorage.getItem("greenlineAdminToken") || "";
  $("usage-date").value = new Date().toISOString().slice(0, 10);
  let endpointRows = [];

  function setStatus(message, type = "") {
    $("global-status").textContent = message;
    $("global-status").className = type;
  }

  async function adminRequest(path, options = {}) {
    const response = await fetch(`/api/v1/admin${path}`, {
      ...options,
      headers: {"X-Admin-Token": adminInput.value.trim(), ...(options.headers || {})},
    });
    const envelope = await response.json();
    if (!response.ok) throw new Error(envelope.message || `Erreur HTTP ${response.status}`);
    return envelope;
  }

  function setConnected(connected) {
    for (const id of ["create-button", "refresh-tokens", "refresh-usage", "save-limits"]) $(id).disabled = !connected;
  }

  function createTable(headers, rows) {
    const table = document.createElement("table");
    const thead = document.createElement("thead"), headerRow = document.createElement("tr");
    headers.forEach(text => { const th = document.createElement("th"); th.textContent = text; headerRow.append(th); });
    thead.append(headerRow); table.append(thead);
    const tbody = document.createElement("tbody");
    rows.forEach(cells => { const tr = document.createElement("tr"); cells.forEach(cell => { const td = document.createElement("td"); if (cell instanceof Node) td.append(cell); else td.textContent = cell ?? "—"; tr.append(td); }); tbody.append(tr); });
    table.append(tbody); return table;
  }

  async function loadTokens() {
    const envelope = await adminRequest("/tokens");
    const tokens = envelope.data.tokens;
    if (!tokens.length) { $("tokens-table").className = "empty"; $("tokens-table").textContent = "Aucun token pour le moment."; return; }
    const rows = tokens.map(token => {
      const state = document.createElement("span"); state.className = `badge ${token.revoked_at ? "revoked" : "active"}`; state.textContent = token.revoked_at ? "Révoqué" : "Actif";
      const actions = document.createElement("span");
      if (!token.revoked_at) {
        const button = document.createElement("button"); button.className = "danger"; button.textContent = "Révoquer";
        button.addEventListener("click", () => revokeToken(token)); actions.append(button);
      } else actions.textContent = "—";
      return [token.id, token.name, token.prefix, token.requests_today, token.last_used_at ? new Date(token.last_used_at).toLocaleString("fr-FR") : "Jamais", state, actions];
    });
    const table = createTable(["ID", "Nom", "Préfixe", "Req. aujourd’hui", "Dernier usage", "État", "Action"], rows);
    $("tokens-table").className = "table-wrap"; $("tokens-table").replaceChildren(table);
  }

  async function revokeToken(token) {
    if (!confirm(`Révoquer le token « ${token.name} » ? Les appels suivants seront refusés.`)) return;
    try { await adminRequest(`/tokens/${token.id}/revoke`, {method:"POST"}); setStatus(`Token « ${token.name} » révoqué.`, "success"); await loadTokens(); }
    catch (error) { setStatus(error.message, "error"); }
  }

  async function loadUsage() {
    const date = $("usage-date").value;
    const envelope = await adminRequest(`/usage?date=${encodeURIComponent(date)}`);
    const rows = envelope.data.rows;
    if (!rows.length) { $("usage-table").className = "empty"; $("usage-table").textContent = "Aucune requête comptabilisée pour cette journée."; return; }
    const table = createTable(["Token", "Préfixe", "Endpoint", "Requêtes admises", "Refus quota"], rows.map(row => [row.token_name, row.token_prefix, row.endpoint, row.request_count, row.rejected_count]));
    $("usage-table").className = "table-wrap"; $("usage-table").replaceChildren(table);
  }

  async function loadLimits() {
    const envelope = await adminRequest("/limits");
    const limits = envelope.data;
    $("default-limit").value = limits.default_daily_limit;
    endpointRows = limits.endpoints;
    const grid = $("quota-grid"); grid.replaceChildren();
    for (const endpoint of endpointRows) {
      const card = document.createElement("div"); card.className = "quota-card";
      const name = document.createElement("code"); name.textContent = `${endpoint.method} ${endpoint.endpoint}`;
      const label = document.createElement("label"); label.textContent = "Limite personnalisée";
      const input = document.createElement("input"); input.type = "number"; input.min = "1"; input.step = "1"; input.dataset.endpoint = endpoint.endpoint;
      input.placeholder = `Par défaut : ${limits.default_daily_limit}`; input.value = endpoint.limit_override ?? "";
      const note = document.createElement("small"); note.textContent = `Limite active : ${endpoint.effective_daily_limit} requêtes / jour`;
      card.append(name, label, input, note); grid.append(card);
    }
  }

  async function connect() {
    sessionStorage.setItem("greenlineAdminToken", adminInput.value.trim());
    setStatus("Vérification des accès…");
    try {
      await Promise.all([loadTokens(), loadUsage(), loadLimits()]);
      setConnected(true); setStatus("Connecté à l’administration API.", "success");
    } catch (error) { setConnected(false); setStatus(error.message, "error"); }
  }

  $("connect-button").addEventListener("click", connect);
  $("create-button").addEventListener("click", async () => {
    const name = $("token-name").value.trim();
    if (!name) { setStatus("Donnez un nom à ce token.", "error"); return; }
    try {
      const envelope = await adminRequest("/tokens", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({name})});
      const token = envelope.data.token;
      const notice = $("created-token"); notice.className = "notice show"; notice.replaceChildren();
      const title = document.createElement("strong"); title.textContent = "Token créé — copiez-le maintenant, il ne sera plus affiché.";
      const line = document.createElement("div"); line.className = "secret-line";
      const value = document.createElement("code"); value.textContent = token.token;
      const copy = document.createElement("button"); copy.className = "secondary"; copy.textContent = "Copier";
      copy.addEventListener("click", async () => { await navigator.clipboard.writeText(token.token); copy.textContent = "Copié"; });
      line.append(value, copy); notice.append(title, line); $("token-name").value = "";
      setStatus("Token créé avec succès.", "success"); await loadTokens();
    } catch (error) { setStatus(error.message, "error"); }
  });
  $("refresh-tokens").addEventListener("click", () => loadTokens().catch(error => setStatus(error.message, "error")));
  $("refresh-usage").addEventListener("click", () => loadUsage().catch(error => setStatus(error.message, "error")));
  $("usage-date").addEventListener("change", () => loadUsage().catch(error => setStatus(error.message, "error")));
  $("save-limits").addEventListener("click", async () => {
    const defaultLimit = Number($("default-limit").value);
    if (!Number.isInteger(defaultLimit) || defaultLimit < 1) { setStatus("La limite générale doit être un entier positif.", "error"); return; }
    const endpointLimits = {};
    for (const input of $("quota-grid").querySelectorAll("input[data-endpoint]")) {
      if (input.value.trim() === "") endpointLimits[input.dataset.endpoint] = null;
      else {
        const value = Number(input.value);
        if (!Number.isInteger(value) || value < 1) { setStatus("Chaque limite doit être un entier positif ou vide.", "error"); return; }
        endpointLimits[input.dataset.endpoint] = value;
      }
    }
    try {
      await adminRequest("/limits", {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify({default_daily_limit:defaultLimit,endpoint_limits:endpointLimits})});
      await loadLimits(); setStatus("Quotas enregistrés.", "success");
    } catch (error) { setStatus(error.message, "error"); }
  });

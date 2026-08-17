(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  function apiHeaders(extra = {}) {
    return { "X-User-Id": "admin", ...extra };
  }

  async function api(path, options = {}) {
    const headers = apiHeaders(options.headers || {});
    return fetch(path, { ...options, headers });
  }

  function showView(name) {
    $$(".view").forEach((el) => {
      const on = el.id === `view-${name}`;
      el.hidden = !on;
    });
    $$(".nav-item").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.view === name);
    });
    if (name === "team") loadTeam();
    if (name === "office-config") loadOfficeConfigForm();
    if (name === "agent-config") loadAgentConfigForm();
    if (name === "chat") loadChannel({ keepRoute: true });
    if (name === "memory") {
      loadMemory();
      loadOkf();
    }
    if (name === "approvals") loadApprovals();
    if (name === "stacks") {
      loadConnections();
      loadStacks();
      loadBedrockPanel();
    }
    if (name === "create") {
      loadCreateConnections();
      loadCreateProjects();
    }
  }

  let channelAgents = [];
  let selectedAgentId = ""; // "" = office front desk
  let configuringAgentId = "";

  async function loadTeam() {
    const list = $("#desk-list");
    const empty = $("#team-empty");
    const err = $("#team-error");
    err.hidden = true;
    try {
      const [agentsRes, cfgRes] = await Promise.all([
        api("/agents"),
        api("/office/config"),
      ]);
      if (!agentsRes.ok) throw new Error(`GET /agents ${agentsRes.status}`);
      if (!cfgRes.ok) throw new Error(`GET /office/config ${cfgRes.status}`);
      const agents = await agentsRes.json();
      const cfg = await cfgRes.json();
      const orc = cfg.orchestrator || {};
      list.innerHTML = "";
      list.appendChild(renderOfficeCard(orc, cfg.org));
      if (!agents.length) {
        empty.classList.remove("hidden");
      } else {
        empty.classList.add("hidden");
      }
      for (const a of agents) {
        list.appendChild(renderDeskCard(a));
      }
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
      empty.classList.add("hidden");
      list.innerHTML = "";
    }
  }

  function renderOfficeCard(orc, org) {
    const li = document.createElement("li");
    li.className = "is-office";
    const meta = document.createElement("div");
    const nameBtn = document.createElement("button");
    nameBtn.type = "button";
    nameBtn.className = "desk-name-btn";
    nameBtn.textContent = orc.name || "Office";
    nameBtn.addEventListener("click", () => openOfficeChannel());
    const sub = document.createElement("div");
    sub.className = "desk-meta";
    const maxA = org?.max_autonomy != null ? org.max_autonomy : "—";
    sub.textContent = `orchestrator · soft jobs · org max autonomy ${maxA}`;
    meta.append(nameBtn, sub);
    const right = document.createElement("div");
    right.className = "desk-actions";
    const stack = document.createElement("div");
    stack.className = "desk-meta";
    stack.textContent = `office / ${orc.model || "—"}`;
    const chatBtn = document.createElement("button");
    chatBtn.type = "button";
    chatBtn.className = "btn ghost";
    chatBtn.textContent = "Chat";
    chatBtn.addEventListener("click", () => openOfficeChannel());
    const cfgBtn = document.createElement("button");
    cfgBtn.type = "button";
    cfgBtn.className = "btn ghost";
    cfgBtn.textContent = "Configure";
    cfgBtn.addEventListener("click", () => showView("office-config"));
    right.append(stack, chatBtn, cfgBtn);
    li.append(meta, right);
    return li;
  }

  function renderDeskCard(a) {
    const li = document.createElement("li");
    const meta = document.createElement("div");
    const nameBtn = document.createElement("button");
    nameBtn.type = "button";
    nameBtn.className = "desk-name-btn";
    nameBtn.textContent = a.name;
    nameBtn.addEventListener("click", () => openChannelChat(a));
    const sub = document.createElement("div");
    sub.className = "desk-meta";
    sub.textContent = a.project_id
      ? `${a.id} · team ${a.team} · project ${a.project_id}`
      : `${a.id} · team ${a.team}`;
    meta.append(nameBtn, sub);
    const right = document.createElement("div");
    right.className = "desk-actions";
    const stack = document.createElement("div");
    stack.className = "desk-meta";
    stack.textContent = `${a.stack} / ${a.model}`;
    const chatBtn = document.createElement("button");
    chatBtn.type = "button";
    chatBtn.className = "btn ghost";
    chatBtn.textContent = "Chat";
    chatBtn.addEventListener("click", () => openChannelChat(a));
    const cfgBtn = document.createElement("button");
    cfgBtn.type = "button";
    cfgBtn.className = "btn ghost";
    cfgBtn.textContent = "Configure";
    cfgBtn.addEventListener("click", () => openAgentConfig(a.id));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn danger";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => removeAgent(a.id, a.name));
    right.append(stack, chatBtn, cfgBtn, remove);
    li.append(meta, right);
    return li;
  }

  function toggleStackModelFields(prefix, stack) {
    const sel = $(`#${prefix}-model`);
    const hint = $(`#${prefix}-model-hint`);
    const cid = $(`#${prefix}-connection`)?.value || "";
    fillStackModelSelect(sel, stack, sel?.value || "", hint, cid);
  }

  let connectionsCache = [];

  async function fetchConnections() {
    const res = await api("/stacks/connections");
    if (!res.ok) throw new Error(`connections ${res.status}`);
    const data = await res.json();
    connectionsCache = data.connections || [];
    return data;
  }

  async function loadConnections() {
    const root = $("#connections-by-kind");
    const err = $("#connections-error");
    if (!root) return;
    err.hidden = true;
    root.innerHTML = "";
    try {
      const data = await fetchConnections();
      for (const group of data.by_kind || []) {
        const section = document.createElement("section");
        section.className = "connection-kind";
        const h = document.createElement("h2");
        h.className = "memory-h2";
        h.textContent = group.label || group.kind;
        section.appendChild(h);
        const grid = document.createElement("div");
        grid.className = "connection-grid";
        const list = group.connections || [];
        if (!list.length) {
          const empty = document.createElement("p");
          empty.className = "desk-meta";
          empty.textContent =
            group.kind === "external"
              ? "Soon — external agents not wired yet."
              : "No connections.";
          section.appendChild(empty);
        } else {
          for (const c of list) {
            grid.appendChild(renderConnectionCard(c));
          }
          section.appendChild(grid);
        }
        root.appendChild(section);
      }
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  function renderConnectionCard(c) {
    const card = document.createElement("article");
    card.className = "connection-card";
    if (!c.enabled) card.classList.add("is-disabled");
    const title = document.createElement("h3");
    title.textContent = c.label || c.id;
    const meta = document.createElement("p");
    meta.className = "desk-meta";
    const used = (c.used_by || []).map((u) => u.id).join(", ") || "none";
    meta.textContent = [
      c.kind_label || c.kind,
      `status: ${c.status}`,
      c.enabled ? "enabled" : "disabled",
      c.tested_at ? `tested ${c.tested_at}` : null,
      `used by: ${used}`,
      (c.aliases || []).length ? `aka ${c.aliases.join(", ")}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
    if (c.last_error) {
      const errLine = document.createElement("p");
      errLine.className = "error";
      errLine.hidden = false;
      errLine.textContent = c.last_error;
      card.append(title, meta, errLine);
    } else {
      card.append(title, meta);
    }
    const actions = document.createElement("div");
    actions.className = "form-actions memory-actions";
    const testBtn = document.createElement("button");
    testBtn.type = "button";
    testBtn.className = "btn ghost";
    testBtn.textContent = "Test";
    testBtn.addEventListener("click", () => testConnection(c.id));
    const toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "btn primary";
    toggleBtn.textContent = c.enabled ? "Disable" : "Enable";
    toggleBtn.addEventListener("click", () =>
      setConnectionEnabled(c.id, !c.enabled)
    );
    actions.append(testBtn, toggleBtn);
    card.appendChild(actions);
    const runtimes = document.createElement("div");
    runtimes.className = "connection-runtimes";
    runtimes.dataset.connectionId = c.id;
    card.appendChild(runtimes);
    fillConnectionRuntimes(runtimes, c);
    if (c.product === "opencode") {
      const models = document.createElement("div");
      models.className = "connection-runtimes opencode-register";
      card.appendChild(models);
      fillOpencodeRegister(models, c);
    }
    return card;
  }

  async function fillOpencodeRegister(box, c) {
    box.innerHTML = `<p class="desk-meta">Loading Inference models…</p>`;
    const errEl = $("#connections-error");
    try {
      const res = await api(
        `/stacks/connections/${encodeURIComponent(c.id)}/inference-candidates`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `candidates ${res.status}`);
      box.innerHTML = "";
      const head = document.createElement("div");
      head.className = "runtime-head";
      const h = document.createElement("strong");
      h.textContent = "Registered models";
      const refresh = document.createElement("button");
      refresh.type = "button";
      refresh.className = "btn ghost btn-xs";
      refresh.textContent = "Refresh";
      refresh.addEventListener("click", () => fillOpencodeRegister(box, c));
      head.append(h, refresh);
      box.appendChild(head);

      const registered = data.registered_models || [];
      if (!registered.length) {
        const empty = document.createElement("p");
        empty.className = "desk-meta";
        empty.textContent = "None yet — pick an Inference model and Test & register.";
        box.appendChild(empty);
      }
      for (const m of registered) {
        const row = document.createElement("div");
        row.className = "runtime-row";
        const label = document.createElement("p");
        label.className = "desk-meta";
        label.textContent = [
          m.display_name || m.ref,
          m.ref,
          m.inference_connection_id,
          m.tested_at ? `tested ${m.tested_at}` : null,
        ]
          .filter(Boolean)
          .join(" · ");
        const del = document.createElement("button");
        del.type = "button";
        del.className = "btn ghost btn-xs";
        del.textContent = "Remove";
        del.addEventListener("click", async () => {
          try {
            const r = await api(
              `/stacks/connections/${encodeURIComponent(c.id)}/models/${encodeURIComponent(m.ref)}`,
              { method: "DELETE" }
            );
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(d.detail || `delete ${r.status}`);
            await fillOpencodeRegister(box, c);
          } catch (e) {
            errEl.textContent = String(e.message || e);
            errEl.hidden = false;
          }
        });
        row.append(label, del);
        box.appendChild(row);
      }

      const candidates = (data.candidates || []).filter((x) => !x.registered);
      const form = document.createElement("div");
      form.className = "runtime-row";
      const sel = document.createElement("select");
      sel.setAttribute("aria-label", "Inference model to register");
      const ph = document.createElement("option");
      ph.value = "";
      ph.textContent = candidates.length
        ? "Select Inference model…"
        : "No Inference models — Verify & add on Bedrock or pull Ollama";
      sel.appendChild(ph);
      for (const cand of candidates) {
        const o = document.createElement("option");
        o.value = `${cand.inference_connection_id}\t${cand.model_id}`;
        o.textContent = `${cand.display_name} (${cand.model_id}) · ${cand.inference_connection_id}`;
        sel.appendChild(o);
      }
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn primary btn-xs";
      btn.textContent = "Test & register";
      btn.disabled = !candidates.length;
      btn.addEventListener("click", async () => {
        const raw = sel.value;
        if (!raw) return;
        const [infId, modelId] = raw.split("\t");
        errEl.hidden = true;
        btn.disabled = true;
        btn.textContent = "Testing…";
        try {
          const r = await api(
            `/stacks/connections/${encodeURIComponent(c.id)}/models/register`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                inference_connection_id: infId,
                inference_model_id: modelId,
              }),
            }
          );
          const d = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(d.detail || `register ${r.status}`);
          await fillOpencodeRegister(box, c);
        } catch (e) {
          errEl.textContent = String(e.message || e);
          errEl.hidden = false;
          btn.disabled = false;
          btn.textContent = "Test & register";
        }
      });
      form.append(sel, btn);
      box.appendChild(form);
    } catch (e) {
      box.innerHTML = "";
      const err = document.createElement("p");
      err.className = "error";
      err.hidden = false;
      err.textContent = String(e.message || e);
      box.appendChild(err);
    }
  }

  async function fillConnectionRuntimes(box, c) {
    box.innerHTML = `<p class="desk-meta">Loading runtimes…</p>`;
    try {
      const res = await api(
        `/stacks/connections/${encodeURIComponent(c.id)}/runtimes`
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `runtimes ${res.status}`);
      box.innerHTML = "";
      const head = document.createElement("div");
      head.className = "runtime-head";
      const h = document.createElement("strong");
      h.textContent =
        c.product === "opencode" ? "Runtimes" : "Recent runs";
      const refresh = document.createElement("button");
      refresh.type = "button";
      refresh.className = "btn ghost btn-xs";
      refresh.textContent = "Refresh";
      refresh.addEventListener("click", () => fillConnectionRuntimes(box, c));
      head.append(h, refresh);
      box.appendChild(head);

      if (c.product === "opencode") {
        const serves = data.serves || [];
        const sessions = data.sessions || [];
        if (!serves.length && !sessions.length) {
          const empty = document.createElement("p");
          empty.className = "desk-meta";
          empty.textContent = "No live serves or sessions.";
          box.appendChild(empty);
          return;
        }
        for (const s of serves) {
          const row = document.createElement("div");
          row.className = "runtime-row";
          const label = document.createElement("p");
          label.className = "desk-meta";
          const cwdShort = String(s.cwd || "").split(/[/\\]/).slice(-2).join("/") || s.cwd;
          label.textContent = [
            `serve :${s.port}`,
            cwdShort,
            s.alive ? "alive" : "dead",
            s.busy ? `busy×${s.busy}` : "idle",
            `idle ${s.idle_seconds || 0}s`,
          ].join(" · ");
          const stop = document.createElement("button");
          stop.type = "button";
          stop.className = "btn ghost btn-xs";
          stop.textContent = "Stop serve";
          stop.disabled = !!s.busy;
          stop.addEventListener("click", () =>
            stopServe(c.id, s.cwd, box, c)
          );
          row.append(label, stop);
          box.appendChild(row);
        }
        for (const sess of sessions) {
          const row = document.createElement("div");
          row.className = "runtime-row";
          const label = document.createElement("p");
          label.className = "desk-meta";
          label.textContent = [
            sess.session_id,
            sess.agent_id || "—",
            sess.status,
            sess.run_id || "",
          ]
            .filter(Boolean)
            .join(" · ");
          const kill = document.createElement("button");
          kill.type = "button";
          kill.className = "btn ghost btn-xs";
          kill.textContent = "Kill session";
          kill.disabled = sess.status === "killed" || sess.status === "ended";
          kill.addEventListener("click", () =>
            killSession(c.id, sess.session_id, box, c)
          );
          row.append(label, kill);
          box.appendChild(row);
        }
      } else {
        const runs = data.runs || [];
        if (!runs.length) {
          const empty = document.createElement("p");
          empty.className = "desk-meta";
          empty.textContent = "No journal runs yet.";
          box.appendChild(empty);
          return;
        }
        for (const r of runs.slice(0, 8)) {
          const row = document.createElement("div");
          row.className = "runtime-row";
          const label = document.createElement("p");
          label.className = "desk-meta";
          label.textContent = [
            r.run_id,
            r.agent_id,
            r.status,
            r.model,
            r.started_at,
          ]
            .filter(Boolean)
            .join(" · ");
          row.appendChild(label);
          box.appendChild(row);
        }
      }
    } catch (e) {
      box.innerHTML = "";
      const err = document.createElement("p");
      err.className = "error";
      err.hidden = false;
      err.textContent = String(e.message || e);
      box.appendChild(err);
    }
  }

  async function stopServe(connectionId, cwd, box, c) {
    const err = $("#connections-error");
    err.hidden = true;
    try {
      const res = await api(
        `/stacks/connections/${encodeURIComponent(connectionId)}/serves/stop`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cwd }),
        }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `stop ${res.status}`);
      await fillConnectionRuntimes(box, c);
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function killSession(connectionId, sessionId, box, c) {
    const err = $("#connections-error");
    err.hidden = true;
    try {
      const res = await api(
        `/stacks/connections/${encodeURIComponent(connectionId)}/sessions/${encodeURIComponent(sessionId)}/kill`,
        { method: "POST" }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `kill ${res.status}`);
      await fillConnectionRuntimes(box, c);
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function testConnection(id) {
    const err = $("#connections-error");
    err.hidden = true;
    try {
      const res = await api(`/stacks/connections/${encodeURIComponent(id)}/test`, {
        method: "POST",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || `test ${res.status}`);
      if (!data.ok) {
        err.textContent = data.error || "Test failed";
        err.hidden = false;
      }
      await loadConnections();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function setConnectionEnabled(id, enabled) {
    const err = $("#connections-error");
    err.hidden = true;
    try {
      const res = await api(`/stacks/connections/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `patch ${res.status}`);
      await loadConnections();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function fillConnectionSelect(sel, preferred, hintEl, { includeDisabled = false } = {}) {
    if (!sel) return;
    if (!connectionsCache.length) {
      try {
        await fetchConnections();
      } catch (_) {
        /* hint below */
      }
    }
    const prev = preferred || sel.value;
    sel.innerHTML = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Select connection…";
    sel.appendChild(placeholder);
    const rows = connectionsCache.filter((c) => includeDisabled || c.enabled);
    if (!rows.length) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "No enabled connections — open Stacks";
      sel.appendChild(o);
      if (hintEl) hintEl.textContent = "Enable a connection on Stacks first.";
      return;
    }
    for (const c of rows) {
      const o = document.createElement("option");
      o.value = c.id;
      o.dataset.stack = c.stack || "";
      o.textContent = `${c.label} (${c.kind_label || c.kind})${
        c.enabled ? "" : " — disabled"
      }`;
      sel.appendChild(o);
    }
    if (prev && [...sel.options].some((o) => o.value === prev)) {
      sel.value = prev;
    } else if (rows.length === 1) {
      sel.value = rows[0].id;
    }
    if (hintEl) {
      const chosen = connectionsCache.find((c) => c.id === sel.value);
      hintEl.textContent = chosen
        ? `stack alias: ${chosen.stack}`
        : "";
    }
  }

  function stackForConnection(connectionId) {
    const c = connectionsCache.find((x) => x.id === connectionId);
    return c?.stack || "openai-compatible";
  }

  async function onConnectionChange(prefix) {
    const connSel = $(`#${prefix}-connection`);
    const stackEl = $(`#${prefix}-stack`);
    const cid = connSel?.value || "";
    const stack = stackForConnection(cid);
    if (stackEl) stackEl.value = stack;
    const hint = $(`#${prefix}-connection-hint`);
    if (hint) {
      const c = connectionsCache.find((x) => x.id === cid);
      hint.textContent = c ? `stack alias: ${c.stack}` : "";
    }
    await fillStackModelSelect(
      $(`#${prefix}-model`),
      stack,
      "",
      $(`#${prefix}-model-hint`),
      cid
    );
  }

  async function loadCreateConnections() {
    await fillConnectionSelect(
      $("#create-connection"),
      $("#create-connection")?.value || "ollama",
      $("#create-connection-hint")
    );
    await onConnectionChange("create");
  }

  async function fillStackModelSelect(sel, stack, preferred, hintEl, connectionId) {
    if (!sel) return;
    const prev = preferred || sel.value;
    sel.innerHTML = "";
    if (hintEl) hintEl.textContent = "";
    try {
      const qs = connectionId
        ? `?connection_id=${encodeURIComponent(connectionId)}`
        : "";
      const res = await api(`/stacks/${encodeURIComponent(stack)}/models${qs}`);
      if (!res.ok) throw new Error(`stack models ${res.status}`);
      const data = await res.json();
      const models = data.models || [];
      if (!models.length) {
        const o = document.createElement("option");
        o.value = "";
        o.textContent = data.hint || "No models for this stack";
        sel.appendChild(o);
        if (hintEl) hintEl.textContent = data.hint || "";
        return;
      }
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Select model…";
      sel.appendChild(placeholder);
      for (const m of models) {
        const o = document.createElement("option");
        o.value = m.id;
        o.textContent =
          m.display_name && m.display_name !== m.id
            ? `${m.display_name} (${m.id})`
            : m.id;
        sel.appendChild(o);
      }
      if (prev && [...sel.options].some((o) => o.value === prev)) {
        sel.value = prev;
      } else if (models.length === 1) {
        sel.value = models[0].id;
      }
      if (hintEl) hintEl.textContent = data.hint || "";
    } catch (e) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "Could not load models";
      sel.appendChild(o);
      if (hintEl) hintEl.textContent = String(e.message || e);
    }
  }

  async function loadBedrockPanel() {
    await Promise.all([loadBedrockStatus(), loadBedrockModels()]);
  }

  async function loadBedrockStatus() {
    const el = $("#bedrock-status");
    if (!el) return;
    try {
      const res = await api("/stacks/bedrock");
      if (!res.ok) throw new Error(`status ${res.status}`);
      const s = await res.json();
      const bits = [
        s.configured ? "credentials configured" : "credentials not set",
        s.source ? `source=${s.source}` : null,
        s.region ? `region ${s.region}` : null,
        s.access_key_hint ? `key ${s.access_key_hint}` : null,
        s.has_session_token ? "session token set" : null,
        s.updated_at ? `updated ${s.updated_at}` : null,
      ].filter(Boolean);
      el.textContent = bits.join(" · ");
      const form = $("#bedrock-creds-form");
      if (form && s.region) form.region.value = s.region;
    } catch (e) {
      el.textContent = String(e.message || e);
    }
  }

  async function loadBedrockModels() {
    const list = $("#bedrock-models-list");
    if (!list) return;
    list.innerHTML = "";
    try {
      const res = await api("/stacks/bedrock/models");
      if (!res.ok) throw new Error(`models ${res.status}`);
      const data = await res.json();
      const catalog = data.models || data.catalog || [];
      if (!catalog.length) {
        list.innerHTML = '<li class="desk-meta">No verified Bedrock models yet.</li>';
        return;
      }
      for (const m of catalog) {
        const li = document.createElement("li");
        li.className = "model-row";
        const meta = document.createElement("div");
        const title = document.createElement("div");
        title.textContent = m.display_name || m.id;
        const sub = document.createElement("div");
        sub.className = "desk-meta";
        const verified = m.meta?.verified_at || m.verified_at || "—";
        const region = m.meta?.region || m.region || "";
        sub.textContent = `${m.id} · verified ${verified} · ${region}`;
        meta.append(title, sub);
        const right = document.createElement("div");
        right.className = "desk-actions model-actions";
        const del = document.createElement("button");
        del.type = "button";
        del.className = "btn danger";
        del.textContent = "Remove";
        del.addEventListener("click", () => removeBedrockModel(m.id));
        right.append(del);
        li.append(meta, right);
        list.appendChild(li);
      }
    } catch (e) {
      list.innerHTML = `<li class="error">${String(e.message || e)}</li>`;
    }
  }

  async function removeBedrockModel(id) {
    if (!confirm(`Remove ${id} from Bedrock catalog?`)) return;
    const err = $("#bedrock-model-error");
    err.hidden = true;
    try {
      const res = await api(`/stacks/bedrock/models/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `delete ${res.status}`);
      }
      await loadBedrockModels();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  function openAgentConfig(agentId) {
    configuringAgentId = agentId;
    showView("agent-config");
  }

  async function loadAgentConfigForm() {
    const form = $("#agent-config-form");
    const err = $("#agent-config-error");
    const ok = $("#agent-config-ok");
    err.hidden = true;
    ok.hidden = true;
    if (!configuringAgentId) {
      err.textContent = "No desk selected.";
      err.hidden = false;
      return;
    }
    try {
      const [agentRes, orgRes] = await Promise.all([
        api(`/agents/${encodeURIComponent(configuringAgentId)}`),
        api("/org"),
      ]);
      if (!agentRes.ok) throw new Error(`GET agent ${agentRes.status}`);
      const a = await agentRes.json();
      const org = orgRes.ok ? await orgRes.json() : {};
      form.agent_id.value = a.id;
      $("#agent-config-id-label").textContent = a.id;
      $("#agent-config-team-label").textContent = a.team;
      form.name.value = a.name || "";
      const preferredConn =
        a.connection_id ||
        (a.stack === "bedrock"
          ? "bedrock"
          : a.stack === "opencode"
            ? "opencode"
            : "ollama");
      await fillConnectionSelect(
        $("#agent-config-connection"),
        preferredConn,
        $("#agent-config-connection-hint"),
        { includeDisabled: true }
      );
      const stack = stackForConnection($("#agent-config-connection")?.value || preferredConn);
      form.stack.value = stack;
      form.autonomy_default.value = a.autonomy?.default ?? 50;
      form.autonomy_max.value =
        a.autonomy?.max != null && a.autonomy.max !== "" ? a.autonomy.max : "";
      form.max_input_tokens.value = a.max_input_tokens ?? -1;
      form.max_output_tokens.value = a.max_output_tokens ?? -1;
      form.persona_markdown.value = a.persona_markdown || "";
      $("#agent-config-org").textContent =
        `Org ceiling: max ${org.max_autonomy ?? "—"} · default ${org.autonomy?.default ?? "—"}`;
      await fillStackModelSelect(
        $("#agent-config-model"),
        stack,
        a.model || "",
        $("#agent-config-model-hint"),
        $("#agent-config-connection")?.value || preferredConn
      );
      await loadProjectsInto(
        $("#agent-config-project"),
        $("#agent-config-project-hint"),
        a.workspace?.project_id
      );
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function loadProjectsInto(sel, hintEl, selectId, emptyHint) {
    if (!sel) return;
    const prev = selectId || sel.value;
    sel.innerHTML = "";
    if (hintEl) hintEl.textContent = "";
    try {
      const res = await api("/projects");
      if (!res.ok) throw new Error(`GET /projects ${res.status}`);
      const projects = await res.json();
      if (!projects.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No projects — create one first";
        sel.appendChild(opt);
        if (hintEl) {
          hintEl.textContent =
            emptyHint ||
            "Every desk needs a working directory. Create a project first.";
        }
        return;
      }
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Select a project…";
      sel.appendChild(placeholder);
      for (const p of projects) {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = `${p.name} (${p.path})`;
        sel.appendChild(opt);
      }
      if (prev && [...sel.options].some((o) => o.value === prev)) {
        sel.value = prev;
      }
    } catch (e) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Failed to load projects";
      sel.appendChild(opt);
      if (hintEl) hintEl.textContent = String(e.message || e);
    }
  }

  async function fillModelSelect(sel, preferred, hintEl) {
    // Office soft jobs always use openai-compatible / Ollama.
    await fillStackModelSelect(sel, "openai-compatible", preferred, hintEl);
  }

  async function loadOfficeConfigForm() {
    const form = $("#office-config-form");
    const err = $("#office-config-error");
    const ok = $("#office-config-ok");
    err.hidden = true;
    ok.hidden = true;
    try {
      const res = await api("/office/config");
      if (!res.ok) throw new Error(`GET /office/config ${res.status}`);
      const data = await res.json();
      const orc = data.orchestrator || {};
      const org = data.org || {};
      form.name.value = orc.name || "Office";
      form.office_qa_llm.checked = !!orc.office_qa_llm;
      form.okf_extract_enabled.checked = !!orc.okf_extract_enabled;
      form.okf_extract_llm.checked = orc.okf_extract_llm !== false;
      form.okf_extract_remember_lines.checked =
        orc.okf_extract_remember_lines !== false;
      form.pack_token_budget.value = orc.pack_token_budget ?? 8000;
      form.gold_max_chars.value = orc.gold_max_chars ?? 64000;
      form.recent_history_days.value = orc.recent_history_days ?? 7;
      form.recent_history_char_budget.value = orc.recent_history_char_budget ?? 6000;
      form.approver_mode.value = orc.approver_mode || "permissive";
      form.default_max_input_tokens.value = orc.default_max_input_tokens ?? -1;
      form.default_max_output_tokens.value = orc.default_max_output_tokens ?? 1024;
      $("#office-config-org").textContent =
        `max ${org.max_autonomy ?? "—"} · default ${org.autonomy?.default ?? "—"}`;
      await fillModelSelect(
        $("#office-config-model"),
        orc.model,
        $("#office-config-model-hint")
      );
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function openChannelChat(agent) {
    selectedAgentId = agent?.id || "";
    if (agent?.team) $("#chat-team").value = agent.team;
    showView("chat");
  }

  function openOfficeChannel() {
    selectedAgentId = "";
    showView("chat");
  }

  function renderAgentChips() {
    const wrap = $("#channel-agents");
    wrap.innerHTML = "";
    const officeBtn = document.createElement("button");
    officeBtn.type = "button";
    officeBtn.className =
      "channel-agent-btn" + (selectedAgentId === "" ? " is-selected" : "");
    officeBtn.textContent = "Office";
    officeBtn.addEventListener("click", () => {
      selectedAgentId = "";
      $("#chat-agent-id").value = "";
      renderAgentChips();
      $("#chat-meta").textContent = "Route: Office front desk";
    });
    wrap.appendChild(officeBtn);
    for (const a of channelAgents) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "channel-agent-btn" + (selectedAgentId === a.id ? " is-selected" : "");
      btn.textContent = a.name || a.id;
      btn.title = a.id;
      btn.addEventListener("click", () => {
        selectedAgentId = a.id;
        $("#chat-agent-id").value = a.id;
        if (a.team) $("#chat-team").value = a.team;
        renderAgentChips();
        $("#chat-meta").textContent = `Route: desk ${a.id}`;
      });
      wrap.appendChild(btn);
    }
    $("#chat-agent-id").value = selectedAgentId;
  }

  function renderHistory(messages) {
    const log = $("#chat-log");
    log.innerHTML = "";
    for (const m of messages || []) {
      const role =
        m.role === "user"
          ? "user"
          : m.role === "office"
            ? "office"
            : "assistant";
      const div = appendBubble(role, m.text, {
        tag:
          m.mode === "agent" && m.agent_id
            ? `desk ${m.agent_id}`
            : m.mode === "office"
              ? "office"
              : null,
      });
      void div;
    }
  }

  function renderChannelApprovals(cards) {
    const box = $("#channel-approvals");
    if (!cards || !cards.length) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML = "<strong>Pending approvals</strong>";
    for (const c of cards) {
      const row = document.createElement("div");
      row.className = "appr-row";
      const label = document.createElement("span");
      label.textContent = `[${c.agent_id}] ${c.summary}`;
      const accept = document.createElement("button");
      accept.type = "button";
      accept.className = "btn primary";
      accept.textContent = "Accept";
      accept.addEventListener("click", () => decideFromChannel(c.id, "accept"));
      const reject = document.createElement("button");
      reject.type = "button";
      reject.className = "btn danger";
      reject.textContent = "Reject";
      reject.addEventListener("click", () => decideFromChannel(c.id, "reject"));
      row.append(label, accept, reject);
      box.appendChild(row);
    }
  }

  async function decideFromChannel(id, decision) {
    const err = $("#chat-error");
    err.hidden = true;
    try {
      const res = await api(`/approvals/${encodeURIComponent(id)}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `decide ${res.status}`);
      await loadChannel({ keepRoute: true });
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function loadChannel(opts = {}) {
    const err = $("#chat-error");
    err.hidden = true;
    try {
      const res = await api("/channel");
      if (!res.ok) throw new Error(`GET /channel ${res.status}`);
      const data = await res.json();
      channelAgents = data.agents || [];
      if (!opts.keepRoute) selectedAgentId = "";
      if (
        selectedAgentId &&
        !channelAgents.some((a) => a.id === selectedAgentId)
      ) {
        selectedAgentId = "";
      }
      renderAgentChips();
      renderHistory(data.messages || []);
      renderChannelApprovals(data.pending_approvals || []);
      $("#chat-meta").textContent = selectedAgentId
        ? `Route: desk ${selectedAgentId} · user ${data.user_id}`
        : `Route: Office · user ${data.user_id}`;
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  function appendBubble(role, text, opts = {}) {
    const log = $("#chat-log");
    const div = document.createElement("div");
    div.className = `chat-bubble ${role}`;
    if (opts.tag) {
      const tag = document.createElement("span");
      tag.className = "bubble-tag";
      tag.textContent = opts.tag;
      div.appendChild(tag);
    }
    const body = document.createElement("span");
    body.className = "bubble-text";
    body.textContent = text;
    div.appendChild(body);
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  function ensureThinkingPanel(bubble) {
    let details = bubble.querySelector(".bubble-thinking");
    if (details) return details.querySelector(".bubble-thinking-text");
    details = document.createElement("details");
    details.className = "bubble-thinking";
    const summary = document.createElement("summary");
    summary.textContent = "Thinking";
    const pre = document.createElement("pre");
    pre.className = "bubble-thinking-text";
    details.append(summary, pre);
    bubble.appendChild(details);
    return pre;
  }

  async function loadRunThinking(runId) {
    if (!runId) return;
    const err = $("#chat-error");
    err.hidden = true;
    try {
      const res = await api(`/runs/${encodeURIComponent(runId)}/thinking`);
      if (!res.ok) throw new Error(`thinking ${res.status}`);
      const data = await res.json();
      const text = (data.text || "").trim();
      if (!text) {
        $("#chat-meta").textContent = `run ${runId} · no thinking stored`;
        return;
      }
      const box = appendBubble("assistant", "", { tag: `thinking · ${runId}` });
      const body = box.querySelector(".bubble-text");
      if (body) body.textContent = text;
      $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  function setChatRunMeta(payload) {
    const meta = $("#chat-meta");
    meta.textContent = "";
    if (payload.mode === "office") {
      meta.textContent = `Office · user ${payload.user_id}`;
      return;
    }
    meta.appendChild(document.createTextNode("run "));
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chat-run-link";
    btn.textContent = payload.run_id || "…";
    btn.title = "Load thinking for this run";
    btn.addEventListener("click", () => loadRunThinking(payload.run_id));
    meta.appendChild(btn);
    meta.appendChild(
      document.createTextNode(
        ` · ${payload.agent_id || ""} · ${payload.model || ""}${
          payload.stack ? ` · ${payload.stack}` : ""
        }`
      )
    );
  }

  async function removeAgent(id, name) {
    const ok = window.confirm(
      `Remove desk "${name}" (${id})?\n\nDeletes agent.yaml, AGENT.md, and gold/ for this desk.`
    );
    if (!ok) return;
    const err = $("#team-error");
    err.hidden = true;
    try {
      const res = await api(`/agents/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `DELETE /agents/${id} ${res.status}`);
      }
      await loadTeam();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function loadMemory() {
    const sel = $("#gold-agent");
    const err = $("#gold-error");
    const ok = $("#gold-ok");
    err.hidden = true;
    ok.hidden = true;
    const prev = sel.value;
    try {
      const res = await api("/agents");
      if (!res.ok) throw new Error(`GET /agents ${res.status}`);
      const agents = await res.json();
      sel.innerHTML = "";
      if (!agents.length) {
        sel.innerHTML = '<option value="">No desks yet</option>';
        $("#gold-content").value = "";
        $("#gold-meta").textContent = "Create a desk on Team first.";
        return;
      }
      for (const a of agents) {
        const opt = document.createElement("option");
        opt.value = a.id;
        opt.textContent = `${a.name} (${a.id})`;
        sel.appendChild(opt);
      }
      if (prev && [...sel.options].some((o) => o.value === prev)) {
        sel.value = prev;
      }
      const chosen = agents.find((a) => a.id === sel.value) || agents[0];
      if (chosen && $("#okf-team")) {
        $("#okf-team").value = chosen.team || "eng";
      }
      if (chosen && $("#office-team")) {
        $("#office-team").value = chosen.team || "eng";
      }
      await loadGoldForSelected();
      await loadOkf();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function loadGoldForSelected() {
    const agentId = $("#gold-agent").value;
    const err = $("#gold-error");
    const ok = $("#gold-ok");
    err.hidden = true;
    ok.hidden = true;
    if (!agentId) {
      $("#gold-content").value = "";
      return;
    }
    try {
      const res = await api(`/agents/${encodeURIComponent(agentId)}/gold`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `GET gold ${res.status}`);
      }
      const data = await res.json();
      $("#gold-content").value = data.content || "";
      $("#gold-meta").textContent =
        data.content && data.content.trim()
          ? "Agent-owned notepad · view only (scoped by session)"
          : "Empty — agent can fill via append_gold";
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  function formatBytes(n) {
    if (n == null || Number.isNaN(Number(n))) return "";
    const v = Number(n);
    if (v < 1024) return `${v} B`;
    if (v < 1024 ** 2) return `${(v / 1024).toFixed(1)} KB`;
    if (v < 1024 ** 3) return `${(v / 1024 ** 2).toFixed(1)} MB`;
    return `${(v / 1024 ** 3).toFixed(1)} GB`;
  }

  async function loadCreateProjects(selectId) {
    await loadProjectsInto(
      $("#create-project"),
      $("#create-project-hint"),
      selectId,
      "Every desk needs a working directory. Create a project first."
    );
  }

  async function createProjectFromForm() {
    const nameInput = $("#new-project-name");
    const err = $("#create-error");
    const ok = $("#create-project-ok");
    err.hidden = true;
    ok.hidden = true;
    const name = (nameInput?.value || "").trim();
    if (!name) {
      err.textContent = "Enter a new project name.";
      err.hidden = false;
      return;
    }
    try {
      const res = await api("/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        const msg = Array.isArray(detail)
          ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
          : detail || `POST /projects ${res.status}`;
        throw new Error(msg);
      }
      if (nameInput) nameInput.value = "";
      ok.textContent = `Created ${data.name} → ${data.path}`;
      ok.hidden = false;
      await loadCreateProjects(data.id);
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function loadCreateModels() {
    await loadCreateConnections();
  }

  function runTagLabel(tag) {
    const map = {
      running_gpu: "running · GPU",
      running_cpu: "running · CPU",
      running_split: "running · split",
      running_unknown: "running",
      likely_gpu: "likely GPU",
      likely_cpu: "likely CPU / tight VRAM",
      cpu_only_host: "CPU only (no GPU)",
      unknown: "unknown",
    };
    return map[tag] || tag || "unknown";
  }

  function renderStacksHealth(report) {
    const box = $("#stacks-health");
    if (!box || !report) {
      if (box) box.hidden = true;
      return;
    }
    box.hidden = false;
    box.innerHTML = "";
    const head = document.createElement("div");
    head.className = "stacks-health-head";
    const verdict = document.createElement("strong");
    verdict.textContent = `GPU check · ${report.verdict || "?"}`;
    const summary = document.createElement("p");
    summary.className = "desk-meta";
    summary.textContent = report.summary || "";
    head.append(verdict, summary);
    box.appendChild(head);
    const ul = document.createElement("ul");
    ul.className = "stacks-health-steps";
    for (const step of report.steps || []) {
      const li = document.createElement("li");
      li.className = `health-step is-${step.status || "skip"}`;
      const title = document.createElement("div");
      title.textContent = `[${step.status}] ${step.id}: ${step.detail || ""}`;
      li.appendChild(title);
      if (step.fix) {
        const fix = document.createElement("div");
        fix.className = "desk-meta health-fix";
        fix.textContent = `Fix: ${step.fix}`;
        li.appendChild(fix);
      }
      ul.appendChild(li);
    }
    box.appendChild(ul);
  }

  async function loadStacksHealth() {
    const err = $("#stacks-error");
    try {
      const res = await api("/models/health");
      if (!res.ok) throw new Error(`GET /models/health ${res.status}`);
      const report = await res.json();
      renderStacksHealth(report);
      return report;
    } catch (e) {
      renderStacksHealth({
        verdict: "error",
        summary: String(e.message || e),
        steps: [],
      });
      if (err) {
        err.textContent = String(e.message || e);
        err.hidden = false;
      }
      return null;
    }
  }

  async function loadStacks() {
    const list = $("#stacks-catalog");
    const err = $("#stacks-error");
    const note = $("#stacks-note");
    const engineEl = $("#stacks-engine");
    err.hidden = true;
    note.hidden = true;
    list.innerHTML = "";
    try {
      const [res, health] = await Promise.all([
        api("/models"),
        api("/models/health"),
      ]);
      if (!res.ok) throw new Error(`GET /models ${res.status}`);
      const data = await res.json();
      let report = null;
      if (health.ok) {
        report = await health.json();
        renderStacksHealth(report);
      } else {
        renderStacksHealth({
          verdict: "error",
          summary: `GET /models/health ${health.status}`,
          steps: [],
        });
      }
      const hintById = Object.fromEntries(
        (report?.catalog_hints || []).map((h) => [h.id, h])
      );
      const eng = data.engine || {};
      engineEl.textContent = eng.reachable
        ? `Ollama · ${eng.native_base} · reachable`
        : `Ollama · ${eng.native_base || "?"} · not reachable`;
      if (!eng.reachable) {
        note.textContent =
          eng.error ||
          "Start Ollama (CPU): docker compose --profile ollama up -d. NVIDIA GPU: add -f docker-compose.gpu.yml (fallback to CPU if that fails). Mac GPU: native Ollama + OLLAMA_BASE_URL.";
        note.hidden = false;
      }
      const sizeByName = Object.fromEntries(
        (data.installed || []).map((m) => [m.name, m.size])
      );
      for (const entry of data.catalog || []) {
        const li = document.createElement("li");
        li.className = "model-row";
        li.dataset.modelId = entry.id;
        const left = document.createElement("div");
        left.className = "model-row-main";
        const title = document.createElement("div");
        title.className = "model-title";
        title.textContent = entry.label || entry.id;
        const meta = document.createElement("div");
        meta.className = "desk-meta";
        const hint = hintById[entry.id];
        const size =
          sizeByName[entry.id] != null
            ? formatBytes(sizeByName[entry.id])
            : entry.size_hint || "";
        meta.textContent = [
          entry.note || "",
          size,
          entry.pulled ? "pulled" : "not pulled",
          hint ? hint.reason : "",
        ]
          .filter(Boolean)
          .join(" · ");
        left.append(title, meta);
        const right = document.createElement("div");
        right.className = "desk-actions model-actions";
        const gradeEl = document.createElement("span");
        gradeEl.className =
          "model-grade " +
          (entry.grade === "agent" ? "agent-grade" : "demo-grade");
        gradeEl.textContent = entry.grade === "agent" ? "agent" : "demo";
        right.appendChild(gradeEl);
        if (hint?.run_tag) {
          const runEl = document.createElement("span");
          runEl.className = `model-grade run-tag run-${hint.run_tag}`;
          runEl.textContent = runTagLabel(hint.run_tag);
          runEl.title = hint.reason || "";
          right.appendChild(runEl);
        }
        const progress = document.createElement("div");
        progress.className = "model-progress";
        progress.hidden = true;
        const bar = document.createElement("div");
        bar.className = "model-progress-bar";
        const fill = document.createElement("i");
        bar.appendChild(fill);
        const status = document.createElement("span");
        status.className = "desk-meta";
        progress.append(bar, status);
        if (entry.pulled) {
          const verify = document.createElement("button");
          verify.type = "button";
          verify.className = "btn ghost";
          verify.textContent = "Verify";
          verify.title = "Load model and confirm GPU vs CPU";
          verify.addEventListener("click", () =>
            verifyModel(entry.id, { fill, status, progress, verify })
          );
          right.appendChild(verify);
          const del = document.createElement("button");
          del.type = "button";
          del.className = "btn danger";
          del.textContent = "Delete";
          del.addEventListener("click", () => deleteModel(entry.id));
          right.appendChild(del);
        } else {
          const pull = document.createElement("button");
          pull.type = "button";
          pull.className = "btn primary";
          pull.textContent = "Pull";
          const cancel = document.createElement("button");
          cancel.type = "button";
          cancel.className = "btn ghost";
          cancel.textContent = "Cancel";
          cancel.hidden = true;
          pull.addEventListener("click", () =>
            pullModel(entry.id, { fill, status, progress, pull, cancel })
          );
          right.appendChild(pull);
          right.appendChild(cancel);
        }
        li.append(left, right, progress);
        list.appendChild(li);
      }
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function verifyModel(name, ui) {
    const err = $("#stacks-error");
    err.hidden = true;
    ui.progress.hidden = false;
    ui.verify.disabled = true;
    ui.status.textContent = "verifying…";
    ui.fill.style.width = "15%";
    try {
      const res = await api("/models/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `verify ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let failed = false;
      let resultMsg = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          const payload = JSON.parse(line.slice(5).trim());
          if (payload.type === "progress") {
            if (payload.phase === "loading") ui.fill.style.width = "40%";
            if (payload.phase === "checking") ui.fill.style.width = "80%";
            ui.status.textContent = payload.message || payload.phase || "…";
          } else if (payload.type === "result") {
            ui.fill.style.width = "100%";
            resultMsg = [
              runTagLabel(payload.run_tag),
              payload.processor,
              payload.reason,
              payload.fix ? `Fix: ${payload.fix}` : "",
            ]
              .filter(Boolean)
              .join(" · ");
            ui.status.textContent = resultMsg;
            if (payload.run_tag === "running_cpu" || payload.fix) {
              err.textContent = resultMsg;
              err.hidden = false;
            }
          } else if (payload.type === "error") {
            failed = true;
            err.textContent = payload.message || "verify failed";
            err.hidden = false;
            ui.status.textContent = "error";
          } else if (payload.type === "done") {
            ui.fill.style.width = "100%";
            if (!ui.status.textContent || ui.status.textContent === "verifying…") {
              ui.status.textContent = "done";
            }
          }
        }
      }
      if (!failed) await loadStacks();
      else ui.verify.disabled = false;
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
      ui.verify.disabled = false;
      ui.status.textContent = "error";
    }
  }

  async function pullModel(name, ui) {
    const err = $("#stacks-error");
    err.hidden = true;
    ui.progress.hidden = false;
    ui.pull.disabled = true;
    if (ui.cancel) {
      ui.cancel.hidden = false;
      ui.cancel.disabled = false;
    }
    ui.status.textContent = "starting…";
    ui.fill.style.width = "0%";
    const ac = new AbortController();
    const onCancel = () => {
      ac.abort();
      ui.status.textContent = "cancelling…";
      if (ui.cancel) ui.cancel.disabled = true;
    };
    if (ui.cancel) ui.cancel.onclick = onCancel;
    try {
      const res = await api("/models/pull", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
        signal: ac.signal,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `pull ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let failed = false;
      let cancelled = false;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          const payload = JSON.parse(line.slice(5).trim());
          if (payload.type === "progress") {
            const pct = payload.percent;
            if (pct != null) ui.fill.style.width = `${pct}%`;
            ui.status.textContent =
              pct != null
                ? `${payload.status || "pulling"} · ${pct}%`
                : payload.status || "pulling…";
          } else if (payload.type === "error") {
            failed = true;
            err.textContent = payload.message || "pull failed";
            err.hidden = false;
            ui.status.textContent = "error";
          } else if (payload.type === "cancelled") {
            cancelled = true;
            ui.status.textContent = "cancelled";
          } else if (payload.type === "done") {
            ui.fill.style.width = "100%";
            ui.status.textContent = "done";
          }
        }
      }
      if (!failed && !cancelled) await loadStacks();
      else ui.pull.disabled = false;
    } catch (e) {
      if (e && (e.name === "AbortError" || String(e.message || "").includes("abort"))) {
        ui.status.textContent = "cancelled";
      } else {
        err.textContent = String(e.message || e);
        err.hidden = false;
        ui.status.textContent = "error";
      }
      ui.pull.disabled = false;
    } finally {
      if (ui.cancel) {
        ui.cancel.hidden = true;
        ui.cancel.onclick = null;
      }
    }
  }

  async function flushModels() {
    const err = $("#stacks-error");
    const btn = $("#btn-stacks-flush");
    err.hidden = true;
    if (btn) btn.disabled = true;
    try {
      const res = await api("/models/flush", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `flush ${res.status}`);
      const still = data.still_loaded || [];
      const unloaded = data.unloaded || [];
      if (still.length) {
        err.textContent =
          `Flush partial — still loaded: ${still.join(", ")}. ` +
          "If VRAM stays high, restart the Ollama container.";
        err.hidden = false;
      } else if (!unloaded.length) {
        err.textContent = "Nothing loaded in Ollama — if VRAM is still high, that is outside Ollama (driver / other GPU apps). Restart Ollama or check nvidia-smi.";
        err.hidden = false;
      }
      await loadStacksHealth();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function deleteModel(name) {
    const err = $("#stacks-error");
    err.hidden = true;
    if (!confirm(`Delete local model ${name}?`)) return;
    try {
      const res = await api("/models/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `delete ${res.status}`);
      await loadStacks();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  $$(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.view === "chat") {
        openOfficeChannel();
        return;
      }
      showView(btn.dataset.view);
    });
  });

  $("#btn-open-create").addEventListener("click", () => showView("create"));
  $("#btn-empty-create").addEventListener("click", () => showView("create"));
  $("#btn-back-team").addEventListener("click", () => showView("team"));
  $("#btn-back-office-team").addEventListener("click", () => showView("team"));
  $("#btn-back-agent-team").addEventListener("click", () => showView("team"));
  const createConn = $("#create-connection");
  if (createConn) {
    createConn.addEventListener("change", () => onConnectionChange("create"));
  }
  const agentConn = $("#agent-config-connection");
  if (agentConn) {
    agentConn.addEventListener("change", () => onConnectionChange("agent-config"));
  }
  $("#btn-connections-refresh")?.addEventListener("click", () => loadConnections());

  $("#bedrock-creds-form")?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const err = $("#bedrock-creds-error");
    const ok = $("#bedrock-creds-ok");
    err.hidden = true;
    ok.hidden = true;
    const body = {};
    const ak = String(form.access_key_id.value || "").trim();
    const sk = String(form.secret_access_key.value || "").trim();
    const st = String(form.session_token.value || "").trim();
    const region = String(form.region.value || "").trim();
    if (ak) body.access_key_id = ak;
    if (sk) body.secret_access_key = sk;
    if (st) body.session_token = st;
    if (region) body.region = region;
    try {
      const res = await api("/stacks/bedrock", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `save ${res.status}`);
      }
      form.access_key_id.value = "";
      form.secret_access_key.value = "";
      form.session_token.value = "";
      ok.textContent = "Credentials saved (not shown again).";
      ok.hidden = false;
      await loadBedrockStatus();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  });

  $("#bedrock-test")?.addEventListener("click", async () => {
    const err = $("#bedrock-creds-error");
    const ok = $("#bedrock-creds-ok");
    err.hidden = true;
    ok.hidden = true;
    try {
      const res = await api("/stacks/bedrock/test", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        const msg =
          detail && typeof detail === "object"
            ? detail.message || JSON.stringify(detail)
            : detail || `test ${res.status}`;
        throw new Error(msg);
      }
      const arn = data.arn ? String(data.arn).split("/").pop() : "";
      ok.textContent = `Creds OK · account ${data.account || "?"} · ${arn || data.region || ""}`;
      ok.hidden = false;
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  });

  $("#bedrock-model-form")?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const err = $("#bedrock-model-error");
    const ok = $("#bedrock-model-ok");
    err.hidden = true;
    ok.hidden = true;
    const inference_id = String(form.inference_id.value || "").trim();
    const display_name = String(form.display_name.value || "").trim();
    const body = { inference_id };
    if (display_name) body.display_name = display_name;
    try {
      const res = await api("/stacks/bedrock/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        const msg =
          detail && typeof detail === "object"
            ? detail.message || JSON.stringify(detail)
            : detail || `verify ${res.status}`;
        throw new Error(msg);
      }
      form.inference_id.value = "";
      form.display_name.value = "";
      ok.textContent = `Verified ${data.id}`;
      ok.hidden = false;
      await loadBedrockModels();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  });

  $("#bedrock-models-refresh")?.addEventListener("click", () => loadBedrockModels());

  const btnCreateProject = $("#btn-create-project");
  if (btnCreateProject) {
    btnCreateProject.addEventListener("click", () => createProjectFromForm());
  }
  $("#btn-stacks-refresh").addEventListener("click", () => loadStacks());
  $("#btn-stacks-health").addEventListener("click", () => loadStacksHealth());
  $("#btn-stacks-flush").addEventListener("click", () => flushModels());

  $("#agent-config-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const err = $("#agent-config-error");
    const ok = $("#agent-config-ok");
    err.hidden = true;
    ok.hidden = true;
    const id = String(form.agent_id.value || configuringAgentId || "").trim();
    const projectId = String(form.project_id.value || "").trim();
    if (!id) {
      err.textContent = "No desk id.";
      err.hidden = false;
      return;
    }
    if (!projectId) {
      err.textContent = "Select a project.";
      err.hidden = false;
      return;
    }
    const autonomy = {
      default: Number(form.autonomy_default.value),
    };
    const maxRaw = String(form.autonomy_max.value || "").trim();
    if (maxRaw !== "") autonomy.max = Number(maxRaw);
    const connectionId = String(form.connection_id?.value || "").trim();
    const stack = String(form.stack.value || stackForConnection(connectionId));
    const model = String(form.model.value || "").trim();
    if (!connectionId) {
      err.textContent = "Select a connection.";
      err.hidden = false;
      return;
    }
    if (!model) {
      err.textContent = "Select a model for this connection.";
      err.hidden = false;
      return;
    }
    const body = {
      name: String(form.name.value || "").trim(),
      stack,
      connection_id: connectionId,
      model,
      autonomy,
      max_input_tokens: Number(form.max_input_tokens.value),
      max_output_tokens: Number(form.max_output_tokens.value),
      workspace: { project_id: projectId, path: "." },
      persona_markdown: String(form.persona_markdown.value || ""),
    };
    try {
      const res = await api(`/agents/${encodeURIComponent(id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        const msg = Array.isArray(detail)
          ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
          : detail || `save ${res.status}`;
        throw new Error(msg);
      }
      ok.textContent = `Saved desk ${data.id}`;
      ok.hidden = false;
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  });

  $("#office-config-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const err = $("#office-config-error");
    const ok = $("#office-config-ok");
    err.hidden = true;
    ok.hidden = true;
    const body = {
      name: String(form.name.value || "").trim(),
      model: String(form.model.value || "").trim(),
      office_qa_llm: !!form.office_qa_llm.checked,
      okf_extract_enabled: !!form.okf_extract_enabled.checked,
      okf_extract_llm: !!form.okf_extract_llm.checked,
      okf_extract_remember_lines: !!form.okf_extract_remember_lines.checked,
      pack_token_budget: Number(form.pack_token_budget.value),
      gold_max_chars: Number(form.gold_max_chars.value),
      recent_history_days: Number(form.recent_history_days.value),
      recent_history_char_budget: Number(form.recent_history_char_budget.value),
      approver_mode: String(form.approver_mode.value || "permissive"),
      default_max_input_tokens: Number(form.default_max_input_tokens.value),
      default_max_output_tokens: Number(form.default_max_output_tokens.value),
    };
    try {
      const res = await api("/office/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `save ${res.status}`);
      }
      ok.textContent = "Saved office/orchestrator.yaml";
      ok.hidden = false;
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  });
  $("#gold-agent").addEventListener("change", () => loadGoldForSelected());
  $("#gold-refresh").addEventListener("click", () => loadGoldForSelected());
  $("#okf-add").addEventListener("click", () => addOkfFact());
  $("#okf-refresh").addEventListener("click", () => loadOkf());
  $("#okf-export").addEventListener("click", () => exportOkf());

  async function exportOkf() {
    const team = ($("#okf-team").value || "eng").trim();
    const err = $("#okf-error");
    const ok = $("#okf-ok");
    err.hidden = true;
    ok.hidden = true;
    try {
      const res = await api("/okf/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ team, include_archived: true }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        throw new Error(
          typeof detail === "string" ? detail : detail?.message || `export ${res.status}`
        );
      }
      ok.textContent =
        `Exported ${data.fact_count} active + ${data.archived_count} archived → ${data.root}`;
      ok.hidden = false;
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  let approvalsFilter = "pending_human";

  async function loadApprovals() {
    const list = $("#approvals-list");
    const err = $("#approvals-error");
    err.hidden = true;
    try {
      const q = approvalsFilter
        ? `?status=${encodeURIComponent(approvalsFilter)}`
        : "";
      const res = await api(`/approvals${q}`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `GET approvals ${res.status}`);
      }
      const cards = await res.json();
      list.innerHTML = "";
      if (!cards.length) {
        list.innerHTML = "<li class=\"desk-meta\">No cards.</li>";
        return;
      }
      for (const c of cards) {
        const li = document.createElement("li");
        const id = document.createElement("span");
        id.className = "okf-id";
        id.textContent = `${c.id} · ${c.status} · ${c.action_type} · by ${c.user_id}`;
        const body = document.createElement("div");
        body.textContent = `[${c.agent_id}] ${c.summary}`;
        const meta = document.createElement("div");
        meta.className = "desk-meta";
        const gateBits = [
          c.gate ? `gate=${c.gate}` : null,
          c.effective_autonomy != null ? `eff=${c.effective_autonomy}` : null,
          `run=${c.run_id}`,
          c.decided_by ? `decided by ${c.decided_by}` : null,
        ].filter(Boolean);
        meta.textContent = gateBits.join(" · ");
        li.append(id, body, meta);
        if (c.status === "pending_human") {
          const actions = document.createElement("div");
          actions.className = "memory-actions";
          const accept = document.createElement("button");
          accept.type = "button";
          accept.className = "btn primary";
          accept.textContent = "Accept";
          accept.addEventListener("click", () => decideApproval(c.id, "accept"));
          const reject = document.createElement("button");
          reject.type = "button";
          reject.className = "btn danger";
          reject.textContent = "Reject";
          reject.addEventListener("click", () => decideApproval(c.id, "reject"));
          actions.append(accept, reject);
          li.append(actions);
        }
        list.appendChild(li);
      }
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function decideApproval(id, decision) {
    const err = $("#approvals-error");
    const ok = $("#approvals-ok");
    err.hidden = true;
    ok.hidden = true;
    try {
      const res = await api(`/approvals/${encodeURIComponent(id)}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `decide ${res.status}`);
      }
      ok.textContent = `${decision} ${data.id} → journal`;
      ok.hidden = false;
      await loadApprovals();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  $("#approvals-propose").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const err = $("#approvals-error");
    const ok = $("#approvals-ok");
    err.hidden = true;
    ok.hidden = true;
    const summary = ($("#appr-summary").value || "").trim();
    if (!summary) return;
    const overrideRaw = ($("#appr-override").value || "").trim();
    const body = {
      agent_id: ($("#appr-agent").value || "").trim(),
      team: ($("#appr-team").value || "eng").trim(),
      action_type: ($("#appr-type").value || "external_send").trim(),
      summary,
    };
    if (overrideRaw !== "") {
      body.autonomy_override = Number(overrideRaw);
    }
    try {
      const res = await api("/approvals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        let msg;
        if (detail && typeof detail === "object" && !Array.isArray(detail)) {
          msg = detail.message || JSON.stringify(detail);
        } else if (Array.isArray(detail)) {
          msg = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
        } else {
          msg = detail || `POST approvals ${res.status}`;
        }
        throw new Error(msg);
      }
      $("#appr-summary").value = "";
      ok.textContent =
        data.gate === "allow"
          ? `Auto-allow ${data.id} (eff=${data.effective_autonomy}) → journal`
          : `Proposed ${data.id} gate=${data.gate} eff=${data.effective_autonomy}`;
      ok.hidden = false;
      approvalsFilter = data.status === "pending_human" ? "pending_human" : "";
      await loadApprovals();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
      await loadApprovals();
    }
  });

  $("#appr-refresh").addEventListener("click", () => loadApprovals());
  $$("[data-appr-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      approvalsFilter = btn.dataset.apprFilter || "";
      loadApprovals();
    });
  });

  async function loadOkf() {
    const team = ($("#okf-team").value || "eng").trim();
    const list = $("#okf-list");
    const err = $("#okf-error");
    err.hidden = true;
    try {
      const res = await api(`/okf/facts?team=${encodeURIComponent(team)}`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `GET okf ${res.status}`);
      }
      const facts = await res.json();
      list.innerHTML = "";
      if (!facts.length) {
        list.innerHTML = "<li class=\"desk-meta\">No team facts yet.</li>";
        return;
      }
      for (const f of facts) {
        const li = document.createElement("li");
        const id = document.createElement("span");
        id.className = "okf-id";
        id.textContent = `${f.id} · ${f.type} · by ${f.created_by_user}`;
        const body = document.createElement("div");
        body.textContent = f.body;
        const arch = document.createElement("button");
        arch.type = "button";
        arch.className = "btn ghost";
        arch.textContent = "Archive";
        arch.addEventListener("click", () => archiveOkf(f.id));
        li.append(id, body, arch);
        list.appendChild(li);
      }
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function addOkfFact() {
    const team = ($("#okf-team").value || "eng").trim();
    const body = ($("#okf-body").value || "").trim();
    const err = $("#okf-error");
    const ok = $("#okf-ok");
    err.hidden = true;
    ok.hidden = true;
    if (!body) return;
    try {
      const res = await api("/okf/facts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ team, body }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        const msg = Array.isArray(detail)
          ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
          : detail || `POST okf ${res.status}`;
        throw new Error(msg);
      }
      $("#okf-body").value = "";
      ok.textContent = `Added ${data.id}`;
      ok.hidden = false;
      await loadOkf();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function archiveOkf(factId) {
    if (!window.confirm(`Archive ${factId}?`)) return;
    const err = $("#okf-error");
    err.hidden = true;
    try {
      const res = await api(`/okf/facts/${encodeURIComponent(factId)}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `DELETE okf ${res.status}`);
      }
      await loadOkf();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  $("#create-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const err = $("#create-error");
    err.hidden = true;
    const fd = new FormData(ev.target);
    const projectId = String(fd.get("project_id") || "").trim();
    if (!projectId) {
      err.textContent = "Select or create a project (working directory is required).";
      err.hidden = false;
      return;
    }
    const autonomy = {
      default: Number(fd.get("autonomy_default") ?? 50),
    };
    const maxRaw = String(fd.get("autonomy_max") || "").trim();
    if (maxRaw !== "") autonomy.max = Number(maxRaw);
    const connectionId = String(fd.get("connection_id") || "").trim();
    const stack = String(fd.get("stack") || stackForConnection(connectionId));
    const model = String(fd.get("model") || "").trim();
    if (!connectionId) {
      err.textContent = "Select a connection.";
      err.hidden = false;
      return;
    }
    if (!model) {
      err.textContent = "Select a model for this connection.";
      err.hidden = false;
      return;
    }
    const body = {
      id: String(fd.get("id") || "").trim(),
      name: String(fd.get("name") || "").trim(),
      team: String(fd.get("team") || "").trim(),
      stack,
      connection_id: connectionId,
      model,
      autonomy,
      max_input_tokens: Number(fd.get("max_input_tokens") ?? -1),
      max_output_tokens: Number(fd.get("max_output_tokens") ?? -1),
      workspace: {
        project_id: projectId,
        path: ".", // server overwrites from registry
      },
    };
    const persona = String(fd.get("persona_markdown") || "").trim();
    if (persona) body.persona_markdown = persona;

    try {
      const res = await api("/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        const msg = Array.isArray(detail)
          ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
          : detail || `POST /agents ${res.status}`;
        throw new Error(msg);
      }
      ev.target.reset();
      ev.target.team.value = "eng";
      ev.target.autonomy_default.value = "50";
      ev.target.max_input_tokens.value = "-1";
      ev.target.max_output_tokens.value = "-1";
      await loadCreateModels();
      await loadCreateProjects();
      showView("team");
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  });

  $("#chat-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const agentId = ($("#chat-agent-id").value || "").trim() || null;
    const team = ($("#chat-team").value || "eng").trim();
    const message = $("#chat-input").value.trim();
    const err = $("#chat-error");
    const send = $("#chat-send");
    err.hidden = true;
    if (!message) return;

    const routeTag = agentId ? `desk ${agentId}` : "office";
    appendBubble("user", message, { tag: routeTag });
    $("#chat-input").value = "";
    const reply = appendBubble(agentId ? "assistant" : "office", "…", {
      tag: routeTag,
    });
    const replyText = reply.querySelector(".bubble-text") || reply;
    send.disabled = true;

    try {
      const body = { message, team };
      if (agentId) body.agent_id = agentId;
      const res = await api("/channel/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `channel chat ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let text = "";
      let thinking = "";
      let lastRunId = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          const payload = JSON.parse(line.slice(5).trim());
          if (payload.type === "meta") {
            lastRunId = payload.run_id || lastRunId;
            setChatRunMeta(payload);
          } else if (payload.type === "token") {
            if (text === "" && replyText.textContent === "…") replyText.textContent = "";
            text += payload.text;
            replyText.textContent = text;
            $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
          } else if (payload.type === "thinking") {
            thinking += payload.text || "";
            const panel = ensureThinkingPanel(reply);
            panel.textContent = thinking;
            $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
          } else if (payload.type === "tool") {
            const tip = payload.ok === false
              ? `tool ${payload.name} failed`
              : `tool ${payload.name}`;
            $("#chat-meta").textContent = tip;
          } else if (payload.type === "answer") {
            text = payload.text || "";
            replyText.textContent = text;
            if (payload.kind) {
              $("#chat-meta").textContent = `office kind=${payload.kind}`;
            }
          } else if (payload.type === "approvals") {
            renderChannelApprovals(payload.cards || []);
          } else if (payload.type === "done" && lastRunId) {
            setChatRunMeta({
              run_id: lastRunId,
              agent_id: agentId,
              model: "",
              stack: "",
            });
          } else if (payload.type === "error") {
            err.textContent = payload.message || "chat error";
            err.hidden = false;
            if (!text) replyText.textContent = "(error)";
          }
        }
      }
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
      if (replyText.textContent === "…") replyText.textContent = "(error)";
    } finally {
      send.disabled = false;
    }
  });

  showView("team");
})();

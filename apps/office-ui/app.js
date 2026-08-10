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
      loadStacks();
      loadBedrockPanel();
    }
    if (name === "create") {
      loadCreateModels();
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
    const isBedrock = stack === "bedrock";
    const ollamaWrap = $(`#${prefix}-model-ollama-wrap`);
    const bedrockWrap = $(`#${prefix}-model-bedrock-wrap`);
    const ollamaSel = $(`#${prefix}-model`);
    const bedrockSel = $(`#${prefix}-model-bedrock`);
    const hint = $(`#${prefix}-model-hint`);
    if (ollamaWrap) ollamaWrap.hidden = isBedrock;
    if (bedrockWrap) bedrockWrap.hidden = !isBedrock;
    if (ollamaSel) ollamaSel.required = !isBedrock;
    if (bedrockSel) bedrockSel.required = isBedrock;
    if (hint) {
      hint.hidden = isBedrock;
      if (isBedrock) hint.textContent = "";
    }
    if (isBedrock) {
      fillBedrockModelSelect(bedrockSel, bedrockSel?.value || "");
    }
  }

  async function fillBedrockModelSelect(sel, preferred) {
    if (!sel) return;
    const prev = preferred || sel.value;
    sel.innerHTML = "";
    try {
      const res = await api("/stacks/bedrock/models");
      if (!res.ok) throw new Error(`bedrock models ${res.status}`);
      const data = await res.json();
      const catalog = data.catalog || [];
      if (!catalog.length) {
        const o = document.createElement("option");
        o.value = "";
        o.textContent = "Verify a model on Stacks → Bedrock first";
        sel.appendChild(o);
        return;
      }
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Select verified model…";
      sel.appendChild(placeholder);
      for (const m of catalog) {
        const o = document.createElement("option");
        o.value = m.id;
        o.textContent = m.display_name && m.display_name !== m.id
          ? `${m.display_name} (${m.id})`
          : m.id;
        sel.appendChild(o);
      }
      if (prev && [...sel.options].some((o) => o.value === prev)) {
        sel.value = prev;
      }
    } catch (e) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "Failed to load Bedrock catalog";
      sel.appendChild(o);
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
      const catalog = data.catalog || [];
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
        sub.textContent = `${m.id} · verified ${m.verified_at || "—"} · ${m.region || ""}`;
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
      form.stack.value = a.stack || "openai-compatible";
      toggleStackModelFields("agent-config", form.stack.value);
      form.autonomy_default.value = a.autonomy?.default ?? 50;
      form.autonomy_max.value =
        a.autonomy?.max != null && a.autonomy.max !== "" ? a.autonomy.max : "";
      form.max_input_tokens.value = a.max_input_tokens ?? -1;
      form.max_output_tokens.value = a.max_output_tokens ?? -1;
      form.persona_markdown.value = a.persona_markdown || "";
      $("#agent-config-org").textContent =
        `Org ceiling: max ${org.max_autonomy ?? "—"} · default ${org.autonomy?.default ?? "—"}`;
      if (a.stack === "bedrock") {
        await fillBedrockModelSelect(
          $("#agent-config-model-bedrock"),
          a.model || ""
        );
      } else {
        await fillModelSelect(
          $("#agent-config-model"),
          a.model,
          $("#agent-config-model-hint")
        );
      }
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
    sel.innerHTML = "";
    try {
      const res = await api("/models");
      if (!res.ok) throw new Error(`models ${res.status}`);
      const data = await res.json();
      const pulled = (data.catalog || []).filter((e) => e.pulled);
      const installed = data.installed || [];
      const names = new Set([
        ...pulled.map((e) => e.id),
        ...installed.map((m) => m.name),
      ]);
      if (preferred) names.add(preferred);
      const opts = [...names].sort();
      if (!opts.length) {
        const o = document.createElement("option");
        o.value = preferred || "";
        o.textContent = preferred || "Pull a model on Stacks first";
        sel.appendChild(o);
        if (hintEl) {
          hintEl.textContent = "Pull a model under Stacks, then return here.";
        }
        return;
      }
      for (const name of opts) {
        const o = document.createElement("option");
        o.value = name;
        o.textContent = name;
        if (name === preferred) o.selected = true;
        sel.appendChild(o);
      }
      if (hintEl) hintEl.textContent = "";
    } catch (e) {
      const o = document.createElement("option");
      o.value = preferred || "";
      o.textContent = preferred || String(e.message || e);
      sel.appendChild(o);
      if (hintEl) hintEl.textContent = String(e.message || e);
    }
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
    const sel = $("#create-model");
    const hint = $("#create-model-hint");
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = "";
    hint.textContent = "";
    try {
      const res = await api("/models");
      if (!res.ok) throw new Error(`GET /models ${res.status}`);
      const data = await res.json();
      const names = [
        ...new Set((data.installed || []).map((m) => m.name).filter(Boolean)),
      ].sort();
      if (!names.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No models pulled — open Stacks first";
        sel.appendChild(opt);
        hint.textContent =
          "Pull a model under Stacks, then return here to create a desk.";
        return;
      }
      for (const name of names) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        sel.appendChild(opt);
      }
      if (prev && names.includes(prev)) sel.value = prev;
      else sel.value = names[0];
      hint.textContent = `${names.length} pulled model(s) available`;
    } catch (e) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Could not load models";
      sel.appendChild(opt);
      hint.textContent = String(e.message || e);
    }
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
  const createStack = $("#create-stack");
  if (createStack) {
    createStack.addEventListener("change", () => {
      toggleStackModelFields("create", createStack.value);
    });
    toggleStackModelFields("create", createStack.value);
  }
  const agentStack = $("#agent-config-stack");
  if (agentStack) {
    agentStack.addEventListener("change", () => {
      toggleStackModelFields("agent-config", agentStack.value);
      if (agentStack.value !== "bedrock") {
        fillModelSelect(
          $("#agent-config-model"),
          $("#agent-config-model").value,
          $("#agent-config-model-hint")
        );
      }
    });
  }

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
      ok.textContent = `Test OK · model ${data.model}`;
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
    const stack = String(form.stack.value || "openai-compatible");
    const model =
      stack === "bedrock"
        ? String(form.model_bedrock.value || "").trim()
        : String(form.model.value || "").trim();
    const body = {
      name: String(form.name.value || "").trim(),
      stack,
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
    const stack = String(fd.get("stack") || "openai-compatible");
    const model =
      stack === "bedrock"
        ? String(fd.get("model_bedrock") || "").trim()
        : String(fd.get("model") || "").trim();
    if (!model) {
      err.textContent =
        stack === "bedrock"
          ? "Select a verified Bedrock model (Stacks → Verify & add)."
          : "Select a model.";
      err.hidden = false;
      return;
    }
    const body = {
      id: String(fd.get("id") || "").trim(),
      name: String(fd.get("name") || "").trim(),
      team: String(fd.get("team") || "").trim(),
      stack,
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
            $("#chat-meta").textContent = payload.mode === "office"
              ? `Office · user ${payload.user_id}`
              : `run ${payload.run_id || "…"} · ${payload.agent_id} · ${payload.model || ""}`;
          } else if (payload.type === "token") {
            if (text === "" && replyText.textContent === "…") replyText.textContent = "";
            text += payload.text;
            replyText.textContent = text;
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

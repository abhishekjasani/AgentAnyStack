(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const USER_KEY = "aas.user_id";

  function currentUserId() {
    return $("#user-id")?.value || "admin";
  }

  function apiHeaders(extra = {}) {
    return { "X-User-Id": currentUserId(), ...extra };
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
    if (name === "chat") loadChannel({ keepRoute: true });
    if (name === "memory") {
      loadMemory();
      loadOkf();
    }
    if (name === "approvals") loadApprovals();
    if (name === "stacks") loadStacks();
  }

  let channelAgents = [];
  let selectedAgentId = ""; // "" = office front desk

  async function loadTeam() {
    const list = $("#desk-list");
    const empty = $("#team-empty");
    const err = $("#team-error");
    err.hidden = true;
    try {
      const res = await api("/agents");
      if (!res.ok) throw new Error(`GET /agents ${res.status}`);
      const agents = await res.json();
      list.innerHTML = "";
      if (!agents.length) {
        empty.classList.remove("hidden");
        list.hidden = true;
        return;
      }
      empty.classList.add("hidden");
      list.hidden = false;
      for (const a of agents) {
        const li = document.createElement("li");
        const meta = document.createElement("div");
        const nameBtn = document.createElement("button");
        nameBtn.type = "button";
        nameBtn.className = "desk-name-btn";
        nameBtn.textContent = a.name;
        nameBtn.addEventListener("click", () => openChannelChat(a));
        const sub = document.createElement("div");
        sub.className = "desk-meta";
        sub.textContent = `${a.id} · team ${a.team}`;
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
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn danger";
        remove.textContent = "Remove";
        remove.addEventListener("click", () => removeAgent(a.id, a.name));
        right.append(stack, chatBtn, remove);
        li.append(meta, right);
        list.appendChild(li);
      }
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
      empty.classList.add("hidden");
      list.hidden = true;
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

  function initUserPicker() {
    const sel = $("#user-id");
    const saved = localStorage.getItem(USER_KEY);
    if (saved && [...sel.options].some((o) => o.value === saved)) {
      sel.value = saved;
    }
    sel.addEventListener("change", () => {
      localStorage.setItem(USER_KEY, sel.value);
      const mem = $("#view-memory");
      if (mem && !mem.hidden) loadGoldForSelected();
      const chat = $("#view-chat");
      if (chat && !chat.hidden) loadChannel({ keepRoute: true });
    });
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
        `User ${data.user_id} · path gold/${data.user_id}.md`;
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function saveGold() {
    const agentId = $("#gold-agent").value;
    const err = $("#gold-error");
    const ok = $("#gold-ok");
    err.hidden = true;
    ok.hidden = true;
    if (!agentId) return;
    try {
      const res = await api(`/agents/${encodeURIComponent(agentId)}/gold`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: $("#gold-content").value }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `PUT gold ${res.status}`);
      }
      $("#gold-content").value = data.content || "";
      ok.textContent = "Saved.";
      ok.hidden = false;
      await loadGoldForSelected();
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function clearGold() {
    const agentId = $("#gold-agent").value;
    if (!agentId) return;
    const okConfirm = window.confirm(
      `Clear gold for user ${currentUserId()} on desk ${agentId}?`
    );
    if (!okConfirm) return;
    const err = $("#gold-error");
    const ok = $("#gold-ok");
    err.hidden = true;
    ok.hidden = true;
    try {
      const res = await api(`/agents/${encodeURIComponent(agentId)}/gold`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `DELETE gold ${res.status}`);
      }
      $("#gold-content").value = "";
      ok.textContent = "Cleared.";
      ok.hidden = false;
      await loadGoldForSelected();
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

  async function loadStacks() {
    const list = $("#stacks-catalog");
    const err = $("#stacks-error");
    const note = $("#stacks-note");
    const engineEl = $("#stacks-engine");
    err.hidden = true;
    note.hidden = true;
    list.innerHTML = "";
    try {
      const res = await api("/models");
      if (!res.ok) throw new Error(`GET /models ${res.status}`);
      const data = await res.json();
      const eng = data.engine || {};
      engineEl.textContent = eng.reachable
        ? `Ollama · ${eng.native_base} · reachable`
        : `Ollama · ${eng.native_base || "?"} · not reachable`;
      if (!eng.reachable) {
        note.textContent =
          eng.error ||
          "Start Ollama: docker compose --profile ollama up -d (Mac GPU: native Ollama + OLLAMA_BASE_URL).";
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
        const grade =
          entry.grade === "agent" ? "agent-grade" : "demo-grade";
        const size =
          sizeByName[entry.id] != null
            ? formatBytes(sizeByName[entry.id])
            : entry.size_hint || "";
        meta.textContent = [
          entry.note || "",
          size,
          entry.pulled ? "pulled" : "not pulled",
        ]
          .filter(Boolean)
          .join(" · ");
        const gradeEl = document.createElement("span");
        gradeEl.className = `model-grade ${grade}`;
        gradeEl.textContent = entry.grade === "agent" ? "agent" : "demo";
        left.append(title, meta);
        const right = document.createElement("div");
        right.className = "desk-actions model-actions";
        right.appendChild(gradeEl);
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
          pull.addEventListener("click", () =>
            pullModel(entry.id, { fill, status, progress, pull })
          );
          right.appendChild(pull);
        }
        li.append(left, right, progress);
        list.appendChild(li);
      }
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    }
  }

  async function pullModel(name, ui) {
    const err = $("#stacks-error");
    err.hidden = true;
    ui.progress.hidden = false;
    ui.pull.disabled = true;
    ui.status.textContent = "starting…";
    ui.fill.style.width = "0%";
    try {
      const res = await api("/models/pull", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `pull ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let failed = false;
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
          } else if (payload.type === "done") {
            ui.fill.style.width = "100%";
            ui.status.textContent = "done";
          }
        }
      }
      if (!failed) await loadStacks();
      else ui.pull.disabled = false;
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
      ui.pull.disabled = false;
      ui.status.textContent = "error";
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
  $("#btn-stacks-refresh").addEventListener("click", () => loadStacks());
  $("#gold-agent").addEventListener("change", () => loadGoldForSelected());
  $("#gold-save").addEventListener("click", () => saveGold());
  $("#gold-clear").addEventListener("click", () => clearGold());
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
    const body = {
      id: String(fd.get("id") || "").trim(),
      name: String(fd.get("name") || "").trim(),
      team: String(fd.get("team") || "").trim(),
      stack: String(fd.get("stack") || "openai-compatible"),
      model: String(fd.get("model") || "").trim(),
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
      ev.target.model.value = "llama3.2";
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

  initUserPicker();
  showView("team");
})();

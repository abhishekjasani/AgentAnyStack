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
    if (name === "memory") {
      loadMemory();
      loadOkf();
    }
    if (name === "approvals") loadApprovals();
  }

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
        nameBtn.addEventListener("click", () => openChat(a));
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
        chatBtn.addEventListener("click", () => openChat(a));
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

  function openChat(agent) {
    $("#chat-agent-id").value = agent.id;
    $("#chat-title").textContent = agent.name;
    $("#chat-lede").textContent =
      `${agent.id} · ${agent.model} · user ${currentUserId()} — via orchestrator → Ollama`;
    $("#chat-log").innerHTML = "";
    $("#chat-meta").textContent = "";
    $("#chat-error").hidden = true;
    $("#chat-input").value = "";
    showView("chat");
  }

  function appendBubble(role, text) {
    const log = $("#chat-log");
    const div = document.createElement("div");
    div.className = `chat-bubble ${role}`;
    div.textContent = text;
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

  $$(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });

  $("#btn-open-create").addEventListener("click", () => showView("create"));
  $("#btn-empty-create").addEventListener("click", () => showView("create"));
  $("#btn-back-team").addEventListener("click", () => showView("team"));
  $("#btn-back-team-chat").addEventListener("click", () => showView("team"));
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

  $("#office-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const err = $("#office-error");
    const answer = $("#office-answer");
    const kind = $("#office-kind");
    const cites = $("#office-cites");
    const send = $("#office-send");
    err.hidden = true;
    answer.hidden = true;
    kind.textContent = "";
    cites.textContent = "";
    const message = ($("#office-input").value || "").trim();
    const team = ($("#office-team").value || "eng").trim();
    if (!message) return;
    send.disabled = true;
    try {
      const res = await api("/office/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, team }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `office ask ${res.status}`);
      }
      kind.textContent = `kind=${data.kind} · team=${data.team}`;
      answer.textContent = data.answer || "";
      answer.hidden = false;
      const bits = (data.citations || [])
        .map((c) => c.fact_id || c.run_id)
        .filter(Boolean);
      cites.textContent = bits.length ? `citations: ${bits.join(", ")}` : "";
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
    } finally {
      send.disabled = false;
    }
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
    const agentId = $("#chat-agent-id").value;
    const message = $("#chat-input").value.trim();
    const err = $("#chat-error");
    const send = $("#chat-send");
    err.hidden = true;
    if (!agentId || !message) return;

    appendBubble("user", message);
    $("#chat-input").value = "";
    const assistant = appendBubble("assistant", "…");
    send.disabled = true;

    try {
      const res = await api(`/agents/${encodeURIComponent(agentId)}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `chat ${res.status}`);
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
            $("#chat-meta").textContent =
              `run ${payload.run_id} · user ${payload.user_id} · ${payload.model}`;
          } else if (payload.type === "token") {
            if (text === "" && assistant.textContent === "…") assistant.textContent = "";
            text += payload.text;
            assistant.textContent = text;
            $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
          } else if (payload.type === "error") {
            err.textContent = payload.message || "chat error";
            err.hidden = false;
            if (!text) assistant.textContent = "(error)";
          }
        }
      }
    } catch (e) {
      err.textContent = String(e.message || e);
      err.hidden = false;
      if (assistant.textContent === "…") assistant.textContent = "(error)";
    } finally {
      send.disabled = false;
    }
  });

  initUserPicker();
  showView("team");
})();

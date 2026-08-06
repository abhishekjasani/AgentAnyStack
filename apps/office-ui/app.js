(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const USER_KEY = "aas.user_id";

  function currentUserId() {
    return $("#user-id")?.value || "anonymous";
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
    });
  }

  $$(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });

  $("#btn-open-create").addEventListener("click", () => showView("create"));
  $("#btn-empty-create").addEventListener("click", () => showView("create"));
  $("#btn-back-team").addEventListener("click", () => showView("team"));
  $("#btn-back-team-chat").addEventListener("click", () => showView("team"));

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

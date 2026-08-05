(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

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
      const res = await fetch("/agents");
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
        meta.innerHTML =
          `<div class="desk-name">${escapeHtml(a.name)}</div>` +
          `<div class="desk-meta">${escapeHtml(a.id)} · team ${escapeHtml(a.team)}</div>`;
        const right = document.createElement("div");
        right.className = "desk-actions";
        const stack = document.createElement("div");
        stack.className = "desk-meta";
        stack.textContent = `${a.stack} / ${a.model}`;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn danger";
        remove.textContent = "Remove";
        remove.addEventListener("click", () => removeAgent(a.id, a.name));
        right.append(stack, remove);
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

  async function removeAgent(id, name) {
    const ok = window.confirm(
      `Remove desk "${name}" (${id})?\n\nDeletes agent.yaml, AGENT.md, and gold/ for this desk.`
    );
    if (!ok) return;
    const err = $("#team-error");
    err.hidden = true;
    try {
      const res = await fetch(`/agents/${encodeURIComponent(id)}`, { method: "DELETE" });
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

  $$(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });

  $("#btn-open-create").addEventListener("click", () => showView("create"));
  $("#btn-empty-create").addEventListener("click", () => showView("create"));
  $("#btn-back-team").addEventListener("click", () => showView("team"));

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
      const res = await fetch("/agents", {
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

  showView("team");
})();

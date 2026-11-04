const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let categories = [];
let editingId = null;

// ---- API helper ----
async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(errorText(data));
  return data;
}
function errorText(data) {
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail))
    return data.detail.map((e) => e.msg.replace(/^Value error, /, "")).join("; ");
  return "Something went wrong. Please try again.";
}
let toastTimer;
function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = ""), 2800);
}
const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "No due date");
const fmtTime = (t) => new Date(t).toLocaleString();

// ---- categories ----
async function loadCategories() {
  categories = await api("/api/categories");
  const opts = categories.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  const keepFilter = $("#fCategory").value;
  $("#fCategory").innerHTML = `<option value="">All categories</option>${opts}`;
  $("#fCategory").value = keepFilter;
  $("#tCategory").innerHTML = `<option value="">No category</option>${opts}`;
}

// ---- stats ----
async function loadStats() {
  const s = await api("/api/stats");
  const box = (n, l, cls = "") => `<div class="stat ${cls}"><div class="n">${n}</div><div class="l">${l}</div></div>`;
  $("#stats").innerHTML =
    box(s.total, "Total tasks") + box(s.pending, "Pending") + box(s.in_progress, "In progress") +
    box(s.completed, "Completed") + box(s.overdue, "Overdue", "overdue") +
    `<div class="stat"><div class="n">${s.completion_percent}%</div><div class="l">Completion</div>
     <div class="bar"><span style="width:${s.completion_percent}%"></span></div></div>`;
}

// ---- tasks ----
async function loadTasks() {
  const p = new URLSearchParams();
  const add = (k, v) => v && p.set(k, v);
  add("search", $("#fSearch").value.trim());
  add("category_id", $("#fCategory").value);
  add("priority", $("#fPriority").value);
  add("status", $("#fStatus").value);
  p.set("sort", $("#fSort").value);
  const tasks = await api("/api/tasks?" + p);
  const filtering = [...p.keys()].some((k) => k !== "sort");
  $("#taskList").innerHTML = tasks.length
    ? tasks.map(card).join("")
    : `<div class="empty">${filtering ? "No tasks match these filters. Clear a filter to see more." : "No tasks yet. Choose Add task to create your first one."}</div>`;
}
function card(t) {
  const cls = t.status === "Completed" ? "s-done" : t.status === "In Progress" ? "s-progress" : "";
  const done = t.status === "Completed";
  return `<article class="card ${cls}" data-id="${t.id}">
    <h3>${esc(t.title)}</h3>
    <div class="badges">
      <span class="badge b-${t.priority}">${t.priority} priority</span>
      <span class="badge b-${t.status.replace(" ", "-")}">${t.status}</span>
    </div>
    ${t.description ? `<p>${esc(t.description)}</p>` : ""}
    <div class="meta">
      <span>${t.category ? esc(t.category) : "No category"}</span>
      <span class="${t.overdue ? "late" : ""}">${t.overdue ? "Overdue: " : "Due: "}${fmtDate(t.due_date)}</span>
    </div>
    <div class="actions">
      <button class="btn small" data-act="toggle" data-done="${done}">${done ? "Reopen" : "Mark completed"}</button>
      <button class="btn small" data-act="edit">Edit</button>
      <button class="btn small" data-act="history">History</button>
      <button class="btn small danger" data-act="delete">Delete</button>
    </div>
  </article>`;
}
async function refresh() {
  await Promise.all([loadStats(), loadTasks()]);
  if (!$("#view-insights").hidden) loadInsights();
}

$("#taskList").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.closest(".card").dataset.id;
  try {
    if (btn.dataset.act === "toggle") {
      const completing = btn.dataset.done !== "true";
      await api(`/api/tasks/${id}/complete?completed=${completing}`, { method: "PATCH" });
      toast(completing ? "Task marked completed" : "Task reopened");
      refresh();
    } else if (btn.dataset.act === "edit") {
      openTaskDialog(await api(`/api/tasks/${id}`));
    } else if (btn.dataset.act === "history") {
      showHistory(id);
    } else if (btn.dataset.act === "delete") {
      if (!confirm("Delete this task? This cannot be undone.")) return;
      await api(`/api/tasks/${id}`, { method: "DELETE" });
      toast("Task deleted");
      refresh();
    }
  } catch (err) { toast(err.message, true); }
});

// ---- filters ----
let searchTimer;
$("#fSearch").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadTasks, 250); });
["#fCategory", "#fPriority", "#fStatus", "#fSort"].forEach((s) => $(s).addEventListener("change", loadTasks));

// ---- task dialog ----
function openTaskDialog(task = null) {
  editingId = task ? task.id : null;
  $("#taskDialogTitle").textContent = task ? "Edit task" : "Add task";
  $("#tTitle").value = task?.title ?? "";
  $("#tDesc").value = task?.description ?? "";
  $("#tCategory").value = task?.category_id ?? "";
  $("#tDue").value = task?.due_date ?? "";
  $("#tPriority").value = task?.priority ?? "Medium";
  $("#tStatus").value = task?.status ?? "Pending";
  $("#taskError").textContent = "";
  $("#taskDialog").showModal();
  $("#tTitle").focus();
}
$("#newTaskBtn").addEventListener("click", () => openTaskDialog());
$("#taskForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    title: $("#tTitle").value,
    description: $("#tDesc").value.trim() || null,
    category_id: $("#tCategory").value ? Number($("#tCategory").value) : null,
    priority: $("#tPriority").value,
    status: $("#tStatus").value,
    due_date: $("#tDue").value || null,
  };
  try {
    await api(editingId ? `/api/tasks/${editingId}` : "/api/tasks",
      { method: editingId ? "PUT" : "POST", body: JSON.stringify(body) });
    $("#taskDialog").close();
    toast(editingId ? "Task saved" : "Task added");
    refresh();
  } catch (err) { $("#taskError").textContent = err.message; }
});

// ---- category dialog ----
$("#newCategoryBtn").addEventListener("click", () => {
  $("#cName").value = ""; $("#cDesc").value = ""; $("#categoryError").textContent = "";
  $("#categoryDialog").showModal(); $("#cName").focus();
});
$("#categoryForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/categories", { method: "POST",
      body: JSON.stringify({ name: $("#cName").value, description: $("#cDesc").value.trim() || null }) });
    $("#categoryDialog").close();
    toast("Category added");
    await loadCategories();
    if (!$("#view-insights").hidden) loadInsights();
  } catch (err) { $("#categoryError").textContent = err.message; }
});

// ---- history ----
async function showHistory(id) {
  const rows = await api(`/api/tasks/${id}/activity`);
  $("#historyTitle").textContent = `History for task #${id}`;
  $("#historyBody").innerHTML = `<ul class="history-list">${rows.map((r) =>
    `<li><b>${esc(r.action)}</b>${r.details ? " &ndash; " + esc(r.details) : ""}<small>${fmtTime(r.created_at)}</small></li>`).join("")}</ul>`;
  $("#historyDialog").showModal();
}

document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => b.closest("dialog").close()));

// ---- tabs and insights ----
document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
  const view = tab.dataset.view;
  $("#view-tasks").hidden = view !== "tasks";
  $("#view-insights").hidden = view !== "insights";
  if (view === "insights") loadInsights();
}));

function table(rows) {
  if (!rows.length) return "<p>No rows returned.</p>";
  const cols = Object.keys(rows[0]);
  return `<div class="tbl-wrap"><table><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>
    ${rows.map((r) => `<tr>${cols.map((c) => `<td>${esc(r[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
const pairs = (o) => Object.entries(o).map(([k, v]) => ({ value: k, tasks: v }));

async function loadInsights() {
  try {
    const [d, activity] = await Promise.all([api("/api/insights"), api("/api/activity?limit=10")]);
    $("#view-insights").innerHTML = `
      <h2>Database overview</h2>
      <div class="panel kv">
        <div><b>${esc(d.database)}</b><span>Database file</span></div>
        <div><b>${d.task_count}</b><span>Tasks</span></div>
        <div><b>${d.category_count}</b><span>Categories</span></div>
        <div><b>${d.tables.length}</b><span>Tables</span></div>
      </div>
      <div class="panel"><b>Tables:</b> ${d.tables.map(esc).join(", ")}</div>
      <h2>Table relationships</h2>
      <div class="panel">${d.relationships.map((r) =>
        `<div>${esc(r.from)} references ${esc(r.to)} <span style="color:var(--muted)">(on delete: ${esc(r.on_delete)})</span></div>`).join("")}</div>
      <h2>Tasks grouped by status</h2><div class="panel">${table(pairs(d.by_status).map((r) => ({ status: r.value, tasks: r.tasks })))}</div>
      <h2>Tasks grouped by priority</h2><div class="panel">${table(pairs(d.by_priority).map((r) => ({ priority: r.value, tasks: r.tasks })))}</div>
      <h2>Important SQL queries (live results)</h2>
      ${d.queries.map((q) => `<div class="panel query"><h3>${esc(q.title)}</h3><p>${esc(q.explanation)}</p><pre>${esc(q.sql)}</pre>${table(q.rows)}</div>`).join("")}
      <h2>Recent activity</h2><div class="panel">${table(activity.map((a) => ({ time: fmtTime(a.created_at), event: a.action, details: a.details || "" })))}</div>`;
  } catch (err) { toast(err.message, true); }
}

// ---- start ----
(async () => {
  try { await loadCategories(); await refresh(); } catch (err) { toast(err.message, true); }
})();

const $ = (sel) => document.querySelector(sel);
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const PW_KEY = "checkin-admin-pw";

// ---------- helpers ----------

// Local calendar date as YYYY-MM-DD (not UTC, so late-evening check-ins land on the right day).
function isoDay(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function parseDay(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}
function prettyDay(s, opts = { weekday: "long", month: "long", day: "numeric", year: "numeric" }) {
  return parseDay(s).toLocaleDateString(undefined, opts);
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function colorFor(id) {
  return `hsl(${(id * 137.508) % 360} 55% 45%)`;
}
function initials(name) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
}

async function api(path, { method = "GET", body, admin = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (admin) headers["X-Admin-Password"] = sessionStorage.getItem(PW_KEY) || "";
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

// ---------- tabs ----------

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  history.replaceState(null, "", `#${name}`);
  if (name === "checkin") loadPeople();
  if (name === "tracker") loadTracker();
  if (name === "admin") loadAdmin();
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
document.addEventListener("click", (e) => {
  const link = e.target.closest("[data-goto]");
  if (link) { e.preventDefault(); showTab(link.dataset.goto); }
});

// ---------- check-in ----------

async function loadPeople() {
  const today = isoDay();
  $("#today-label").textContent = prettyDay(today);
  const people = await api(`/api/people?day=${today}`);
  const list = $("#people-list");
  list.innerHTML = "";
  $("#people-empty").classList.toggle("hidden", people.length > 0);
  const done = people.filter((p) => p.checked_in).length;
  $("#today-count").textContent = people.length ? `${done} of ${people.length} checked in` : "";

  for (const p of people) {
    const li = document.createElement("li");
    li.className = `person${p.checked_in ? " done" : ""}`;
    const time = p.checked_in_at ? new Date(p.checked_in_at.replace(" ", "T") + "Z").toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
    li.innerHTML = `
      <div class="avatar" style="background:${colorFor(p.id)}">${esc(initials(p.name))}</div>
      <div class="name">${esc(p.name)}${p.checked_in ? `<span class="meta">Checked in at ${time}</span>` : ""}</div>
      <button class="checkin-btn ${p.checked_in ? "done" : "primary"}">${p.checked_in ? "✓ Checked in" : "Check in"}</button>`;
    const btn = li.querySelector("button");
    if (p.checked_in) {
      btn.addEventListener("mouseenter", () => (btn.textContent = "Undo"));
      btn.addEventListener("mouseleave", () => (btn.textContent = "✓ Checked in"));
    }
    btn.addEventListener("click", async () => {
      if (p.checked_in && !confirm(`Undo ${p.name}'s check-in for today?`)) return;
      btn.disabled = true;
      try {
        await api("/api/checkin", { method: p.checked_in ? "DELETE" : "POST", body: { person_id: p.id, day: today } });
      } catch (err) {
        alert(err.message);
      }
      loadPeople();
    });
    list.appendChild(li);
  }
}

// ---------- tracker ----------

const tooltip = $("#tooltip");
function showTip(e, html) {
  tooltip.innerHTML = html;
  tooltip.classList.remove("hidden");
  const r = e.target.getBoundingClientRect();
  const tw = tooltip.offsetWidth;
  tooltip.style.left = `${Math.max(8, Math.min(window.innerWidth - tw - 8, r.left + r.width / 2 - tw / 2))}px`;
  tooltip.style.top = `${r.top - tooltip.offsetHeight - 6}px`;
}
function hideTip() { tooltip.classList.add("hidden"); }

/**
 * Build a GitHub-style contribution grid.
 * levelFor(day) -> 0..4, tipFor(day) -> html, onClick(day, cell) optional.
 */
function buildHeatmap(container, endDay, weeks, levelFor, tipFor, onClick) {
  container.innerHTML = "";
  const end = parseDay(endDay);
  const start = new Date(end);
  start.setDate(start.getDate() - (weeks - 1) * 7 - end.getDay()); // Sunday, `weeks` columns back
  const todayStr = isoDay();

  // Weekday label column
  const add = (cls, text = "") => {
    const el = document.createElement("div");
    el.className = cls;
    el.textContent = text;
    container.appendChild(el);
    return el;
  };
  add("mo");
  ["", "Mon", "", "Wed", "", "Fri", ""].forEach((t) => add("wd", t));

  let lastMonth = -1;
  const d = new Date(start);
  for (let w = 0; w < weeks; w++) {
    // Label a column with the month when the month changes (skip a cramped label on the very first column)
    const m = d.getMonth();
    const label = m !== lastMonth && !(w === 0 && d.getDate() > 7) ? MONTHS[m] : "";
    lastMonth = m;
    add("mo", label);
    for (let i = 0; i < 7; i++) {
      const day = isoDay(d);
      if (d > end) {
        add("cell blank");
      } else {
        const cell = add(`cell l${levelFor(day)}${day === todayStr ? " today" : ""}`);
        cell.dataset.day = day;
        cell.addEventListener("mouseenter", (e) => showTip(e, tipFor(day)));
        cell.addEventListener("mouseleave", hideTip);
        if (onClick) cell.addEventListener("click", () => onClick(day, cell));
      }
      d.setDate(d.getDate() + 1);
    }
  }
}

async function loadTracker() {
  const end = isoDay();
  const data = await api(`/api/stats?end=${end}&days=371`);
  const peopleById = Object.fromEntries(data.people.map((p) => [p.id, p]));
  const activeCount = data.people.filter((p) => p.active).length || 1;
  const maxDay = Math.max(1, activeCount, ...Object.values(data.by_day).map((a) => a.length));

  const total = Object.values(data.by_day).reduce((n, a) => n + a.length, 0);
  $("#total-checkins").textContent = total;
  $("#session-days").textContent = Object.keys(data.by_day).length;

  const namesFor = (day) => (data.by_day[day] || []).map((id) => peopleById[id]).filter(Boolean);
  const level = (n) => (n === 0 ? 0 : Math.min(4, Math.ceil((n / maxDay) * 4)));

  buildHeatmap(
    $("#heatmap-all"), end, 53,
    (day) => level((data.by_day[day] || []).length),
    (day) => {
      const names = namesFor(day);
      const head = `<b>${names.length ? `${names.length} check-in${names.length > 1 ? "s" : ""}` : "No check-ins"}</b> on ${prettyDay(day, { month: "short", day: "numeric", year: "numeric" })}`;
      return names.length ? `${head}<br>${names.map((p) => esc(p.name)).join(", ")}` : head;
    },
    (day, cell) => {
      document.querySelectorAll("#heatmap-all .selected").forEach((c) => c.classList.remove("selected"));
      cell.classList.add("selected");
      const names = namesFor(day);
      $("#day-detail").innerHTML = `<b>${prettyDay(day)}</b> — ${names.length} checked in
        <div class="chips">${names.map((p) => `<span class="chip"><span class="dot" style="background:${colorFor(p.id)}"></span>${esc(p.name)}</span>`).join("") || '<span class="muted">Nobody</span>'}</div>`;
    }
  );

  const cards = $("#person-cards");
  cards.innerHTML = "";
  const sorted = [...data.people].sort((a, b) => b.active - a.active || b.total - a.total);
  if (!sorted.length) cards.innerHTML = '<p class="empty">No names yet.</p>';
  for (const p of sorted) {
    const daySet = new Set(p.days);
    const card = document.createElement("div");
    card.className = `card person-card${p.active ? "" : " inactive"}`;
    card.innerHTML = `
      <div class="top">
        <div class="avatar" style="background:${colorFor(p.id)}">${esc(initials(p.name))}</div>
        <div>
          <div class="name">${esc(p.name)}${p.active ? "" : ' <span class="muted small">(hidden)</span>'}</div>
          <div class="muted small">${p.last ? `Last seen ${prettyDay(p.last, { month: "short", day: "numeric", year: "numeric" })}` : "Never checked in"}</div>
        </div>
        <div class="stats">
          <div class="stat"><b>${p.total}</b><span>check-ins</span></div>
          <div class="stat"><b>${Math.round(p.rate * 100)}%</b><span>attendance</span></div>
          <div class="stat"><b>${p.streak}</b><span>streak</span></div>
        </div>
      </div>
      <div class="heatmap-wrap"><div class="heatmap"></div></div>`;
    buildHeatmap(
      card.querySelector(".heatmap"), end, 53,
      (day) => (daySet.has(day) ? 4 : 0),
      (day) => `<b>${esc(p.name)}</b> ${daySet.has(day) ? "checked in" : "—"} on ${prettyDay(day, { month: "short", day: "numeric", year: "numeric" })}`
    );
    cards.appendChild(card);
  }
}

// ---------- admin ----------

async function loadAdmin() {
  const loggedIn = !!sessionStorage.getItem(PW_KEY);
  $("#admin-login").classList.toggle("hidden", loggedIn);
  $("#admin-panel").classList.toggle("hidden", !loggedIn);
  if (!loggedIn) return;
  try {
    renderAdmin(await api("/api/admin/people", { admin: true }));
  } catch (err) {
    if (err.status === 401) { sessionStorage.removeItem(PW_KEY); loadAdmin(); }
    else showAdminError(err.message);
  }
}

function showAdminError(msg) {
  const el = $("#admin-error");
  el.textContent = msg;
  el.classList.toggle("hidden", !msg);
}

async function adminAction(path, opts) {
  showAdminError("");
  let ok = true;
  try {
    await api(path, { ...opts, admin: true });
  } catch (err) {
    showAdminError(err.message);
    ok = false;
  }
  loadAdmin();
  return ok;
}

function renderAdmin(people) {
  const list = $("#admin-list");
  list.innerHTML = "";
  if (!people.length) list.innerHTML = '<li class="muted">No names yet — add one above.</li>';
  people.forEach((p, i) => {
    const li = document.createElement("li");
    li.className = p.active ? "" : "inactive";
    li.innerHTML = `
      <div class="avatar" style="background:${colorFor(p.id)};width:28px;height:28px;font-size:12px">${esc(initials(p.name))}</div>
      <span class="aname">${esc(p.name)} <span class="muted small">· ${p.total} check-ins</span></span>
      <button data-act="up" ${i === 0 ? "disabled" : ""} title="Move up">↑</button>
      <button data-act="down" ${i === people.length - 1 ? "disabled" : ""} title="Move down">↓</button>
      <button data-act="rename">Rename</button>
      <button data-act="toggle">${p.active ? "Hide" : "Show"}</button>
      <button data-act="delete" class="danger">Delete</button>`;
    li.addEventListener("click", (e) => {
      const act = e.target.dataset.act;
      const url = `/api/admin/people/${p.id}`;
      if (act === "up" || act === "down") adminAction(url, { method: "PATCH", body: { move: act } });
      if (act === "toggle") adminAction(url, { method: "PATCH", body: { active: !p.active } });
      if (act === "rename") {
        const name = prompt("New name", p.name);
        if (name && name.trim() !== p.name) adminAction(url, { method: "PATCH", body: { name } });
      }
      if (act === "delete" && confirm(`Delete ${p.name} and all ${p.total} of their check-ins? This can't be undone.`)) {
        adminAction(url, { method: "DELETE" });
      }
    });
    list.appendChild(li);
  });
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  sessionStorage.setItem(PW_KEY, $("#admin-password").value);
  try {
    await api("/api/admin/login", { method: "POST", admin: true });
    $("#login-error").classList.add("hidden");
    $("#admin-password").value = "";
    loadAdmin();
  } catch (err) {
    sessionStorage.removeItem(PW_KEY);
    $("#login-error").textContent = err.message;
    $("#login-error").classList.remove("hidden");
  }
});

$("#logout").addEventListener("click", () => { sessionStorage.removeItem(PW_KEY); loadAdmin(); });

$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#new-name");
  if (await adminAction("/api/admin/people", { method: "POST", body: { name: input.value } })) input.value = "";
  input.focus();
});

// ---------- boot ----------

api("/api/config").then((c) => {
  $("#title").textContent = c.title;
  document.title = c.title;
});
const initial = location.hash.slice(1);
showTab(["checkin", "tracker", "admin"].includes(initial) ? initial : "checkin");
// Keep the list fresh if it's left open on a shared screen
setInterval(() => { if ($("#tab-checkin").classList.contains("active")) loadPeople(); }, 30000);

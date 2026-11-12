// LOCAL TEST FIXTURE: Google-Calendar-like views (eventedit template URL, day view with [data-eventid]).
// Controls: reset=1, login=1, savefail=1|0 (Save shows an error), silentsave=1|0 (Save stores nothing and shows
// no confirmation -> status must be UNKNOWN), conflict=<UTC ISO start>/<minutes>/<title> (seed an event).
const P = new URLSearchParams(location.search);
const K = { events: "fx_cal_events", fail: "fx_cal_savefail", silent: "fx_cal_silent", invites: "fx_cal_invites", saves: "fx_cal_save_clicks" };
if (P.get("reset") === "1") Object.values(K).forEach((k) => localStorage.removeItem(k));
for (const [param, key] of [["savefail", K.fail], ["silentsave", K.silent]]) {
  if (P.get(param) === "1") localStorage.setItem(key, "1");
  if (P.get(param) === "0") localStorage.removeItem(key);
}
if (P.get("login") === "1") location.replace("signin.html");
const events = () => JSON.parse(localStorage.getItem(K.events) || "[]");
const store = (e) => localStorage.setItem(K.events, JSON.stringify(e));
if (P.get("conflict")) {
  const [start, minutes, title] = P.get("conflict").split("/");
  const s = new Date(start);
  store([...events(), { id: "seed" + Date.now(), title: decodeURIComponent(title || "Busy"), start: s.toISOString(), end: new Date(s.getTime() + Number(minutes) * 60000).toISOString(), guests: [] }]);
}
window.__fxCal = () => ({ events: events(), invites: Number(localStorage.getItem(K.invites) || "0"), saves: Number(localStorage.getItem(K.saves) || "0") });

const TZ = P.get("ctz") || "Asia/Kolkata";
const fmt = (d, opts) => new Intl.DateTimeFormat("en-US", { timeZone: TZ, ...opts }).format(d);
const clock = (d) => fmt(d, { hour: "numeric", minute: "2-digit", hour12: true }).replace(" ", "").toLowerCase();
const ymd = (d) => { const p = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(d); return p; };
const longDate = (d) => fmt(d, { month: "long", day: "numeric", year: "numeric" });
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function toast(text) { const t = document.getElementById("toast"); if (!t) return; t.textContent = text; t.style.display = "block"; }

function chip(e) {
  const s = new Date(e.start), en = new Date(e.end);
  const label = `${clock(s)} to ${clock(en)}, ${e.title}, ${longDate(s)}`;
  return `<div class="ev" role="button" data-eventid="${esc(e.id)}" aria-label="${esc(label)}"><b>${esc(e.title)}</b><br>${clock(s)} – ${clock(en)}</div>`;
}

function renderIndex() {
  const list = events().slice().sort((a, b) => a.start.localeCompare(b.start));
  document.getElementById("grid").innerHTML = list.length ? list.map(chip).join("") : "<p>No upcoming events</p>";
  if (P.get("saved") === "1") toast("Event saved");
}

function renderDay() {
  const day = P.get("date");
  const list = events().filter((e) => ymd(new Date(e.start)) === day).sort((a, b) => a.start.localeCompare(b.start));
  document.getElementById("day-title").textContent = day;
  document.getElementById("grid").innerHTML = list.length ? list.map(chip).join("") : '<p class="empty">No events</p>';
}

function parseDates(v) {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z\/(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(v || "");
  if (!m) return null;
  return [new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6])), new Date(Date.UTC(+m[7], +m[8] - 1, +m[9], +m[10], +m[11], +m[12]))];
}

function renderEdit() {
  const dates = parseDates(P.get("dates"));
  const form = document.getElementById("form");
  if (!dates) { form.innerHTML = "<p>Invalid event link.</p>"; return; }
  const [s, e] = dates;
  const guests = (P.get("add") || "").split(",").filter(Boolean);
  form.innerHTML = `
    <input aria-label="Title" id="xTiIn" value="${esc(P.get("text") || "")}">
    <div class="row"><input aria-label="Start date" id="xStDaIn" value="${fmt(s, { weekday: "long", month: "long", day: "numeric" })}" readonly>
      <input aria-label="Start time" id="xStTiIn" value="${clock(s)}" readonly> to
      <input aria-label="End time" id="xEnTiIn" value="${clock(e)}" readonly>
      <input aria-label="End date" id="xEnDaIn" value="${fmt(e, { weekday: "long", month: "long", day: "numeric" })}" readonly></div>
    <div class="row" data-ctz="${esc(TZ)}">Time zone: ${esc(TZ)}</div>
    <input aria-label="Add location" value="${esc(P.get("location") || "")}">
    <div aria-label="Description" contenteditable="true" class="desc">${esc(P.get("details") || "")}</div>
    <div class="guests">${guests.map((g) => `<div data-email="${esc(g)}" class="guest">${esc(g)}</div>`).join("")}</div>
    <button id="xSaveBu" aria-label="Save">Save</button>`;
  document.getElementById("xSaveBu").addEventListener("click", () => {
    localStorage.setItem(K.saves, String(window.__fxCal().saves + 1));
    if (localStorage.getItem(K.fail) === "1") { toast("Couldn't save event. Try again."); return; }
    const finish = () => {
      if (localStorage.getItem(K.silent) === "1") { location.href = "index.html"; return; }
      store([...events(), { id: "ev" + Date.now(), title: document.getElementById("xTiIn").value, start: s.toISOString(), end: e.toISOString(), guests }]);
      location.href = "index.html?saved=1&ctz=" + encodeURIComponent(TZ);
    };
    if (!guests.length) return finish();
    const d = document.createElement("div");
    d.setAttribute("role", "dialog"); d.className = "dialog";
    d.innerHTML = '<p>Would you like to send invitation emails to Google Calendar guests?</p><button data-act="no">Don\'t send</button> <button data-act="yes">Send</button>';
    document.body.appendChild(d);
    d.querySelector("[data-act=no]").addEventListener("click", () => { d.remove(); finish(); });
    d.querySelector("[data-act=yes]").addEventListener("click", () => { localStorage.setItem(K.invites, String(window.__fxCal().invites + guests.length)); d.remove(); finish(); });
  });
}

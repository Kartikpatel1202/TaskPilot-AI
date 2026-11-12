// LOCAL TEST FIXTURE: Gmail-like compose + drafts (markup mirrors Gmail's selectors).
// Controls: reset=1 (clear drafts/sent counter), login=1 (redirect to a sign-in page),
// nosave=1 (autosave and Save & close never save -> DRAFT_SAVE_FAILED / unknown).
// The Send button is FAKE: clicking it only increments a counter the tests check is still 0.
const P = new URLSearchParams(location.search);
const K = { drafts: "fx_gmail_drafts", sent: "fx_gmail_sent_clicks", nosave: "fx_gmail_nosave" };
if (P.get("reset") === "1") { localStorage.removeItem(K.drafts); localStorage.removeItem(K.sent); localStorage.removeItem(K.nosave); }
if (P.get("nosave") === "1") localStorage.setItem(K.nosave, "1");
if (P.get("nosave") === "0") localStorage.removeItem(K.nosave);
if (P.get("login") === "1") location.replace("signin.html");

const drafts = () => JSON.parse(localStorage.getItem(K.drafts) || "[]");
const saveDrafts = (d) => localStorage.setItem(K.drafts, JSON.stringify(d));
const noSave = () => localStorage.getItem(K.nosave) === "1";
window.__fxSendClicks = () => Number(localStorage.getItem(K.sent) || "0");

function toast(text) { const t = document.getElementById("toast"); t.textContent = text; t.style.display = "block"; setTimeout(() => { t.style.display = "none"; }, 4000); }
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function renderMain() {
  const main = document.getElementById("main");
  document.getElementById("draft-count").textContent = drafts().length || "";
  if (location.hash === "#drafts") {
    const rows = drafts().map((d) => `<tr class="zA" data-draft-id="${d.id}"><td><span class="bA4"><span class="bog-draft">Draft</span> ${esc(d.to.join(", "))}</span></td>
      <td><span class="bog">${esc(d.subject)}</span></td><td><span class="y2">${esc(d.body.slice(0, 60))}</span></td></tr>`).join("");
    main.innerHTML = `<h2>Drafts</h2><table id="drafts-table" role="grid"><tbody>${rows || '<tr><td>You don\'t have any saved drafts.</td></tr>'}</tbody></table>`;
  } else {
    main.innerHTML = '<h2>Inbox</h2><table role="grid"><tbody><tr class="zA"><td>Fixture Team</td><td><span class="bog">Welcome to the fixture inbox</span></td></tr></tbody></table>';
  }
}
window.addEventListener("hashchange", renderMain);

function openCompose() {
  if (document.querySelector(".compose")) return;
  const id = "d" + Date.now();
  const box = document.createElement("div");
  box.className = "compose"; box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "New Message");
  box.innerHTML = `<div class="head"><span>New Message</span><img src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" alt="" role="button" aria-label="Save &amp; close" data-tooltip="Save &amp; close" class="Ha" tabindex="0" style="width:16px;height:16px;background:#999"></div>
    <div class="to"><span class="chips"></span><input aria-label="To recipients" class="agP aFw" autocomplete="off"></div>
    <input name="subjectbox" aria-label="Subject" placeholder="Subject">
    <div aria-label="Message Body" role="textbox" contenteditable="true" class="Am Al editable body" aria-multiline="true"></div>
    <div class="foot"><div role="button" class="T-I J-J5-Ji aoO v7 T-I-atl L3 send" aria-label="Send ‪(Ctrl-Enter)‬" data-tooltip="Send" tabindex="0">Send</div>
      <span class="aDj" aria-live="polite"><span class="draft-state"></span></span></div>`;
  document.body.appendChild(box);
  const to = box.querySelector("input[aria-label='To recipients']");
  const chips = box.querySelector(".chips");
  const state = box.querySelector(".draft-state");
  const chipify = () => {
    to.value.split(/[,;\s]+/).filter(Boolean).forEach((addr) => {
      const s = document.createElement("span"); s.className = "chip"; s.setAttribute("email", addr.trim()); s.textContent = addr.trim(); chips.appendChild(s);
    });
    to.value = "";
    schedule();
  };
  to.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === "Tab" || e.key === ",") { if (to.value.trim()) { e.preventDefault(); chipify(); } } });
  to.addEventListener("blur", () => { if (to.value.trim()) chipify(); });
  const read = () => ({ id, to: [...chips.querySelectorAll("[email]")].map((c) => c.getAttribute("email")), subject: box.querySelector("[name=subjectbox]").value, body: box.querySelector("[aria-label='Message Body']").innerText });
  const persist = () => { if (noSave()) return false; const d = drafts().filter((x) => x.id !== id); d.push(read()); saveDrafts(d); return true; };
  let timer = null;
  function schedule() {
    clearTimeout(timer);
    state.textContent = "";
    timer = setTimeout(() => { state.textContent = "Saving…"; setTimeout(() => { if (persist()) state.textContent = "Draft saved"; else state.textContent = "Couldn't save draft"; renderMain(); }, 400); }, 900);
  }
  box.querySelector("[name=subjectbox]").addEventListener("input", schedule);
  box.querySelector("[aria-label='Message Body']").addEventListener("input", schedule);
  box.querySelector(".send").addEventListener("click", () => { localStorage.setItem(K.sent, String(window.__fxSendClicks() + 1)); toast("Message sent (FAKE — fixture only)"); });
  box.querySelector("[aria-label='Save & close']").addEventListener("click", () => {
    clearTimeout(timer);
    const ok = persist();
    box.remove();
    renderMain();
    toast(ok ? "Draft saved" : "Couldn't save draft. Try again.");
  });
}
document.querySelector("[gh=cm]").addEventListener("click", openCompose);
renderMain();

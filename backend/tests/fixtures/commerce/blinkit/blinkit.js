// LOCAL TEST FIXTURE ONLY — a Blinkit-like grocery site for TaskPilot's Playwright tests.
// Not affiliated with Blinkit. No network calls; state lives in this origin's localStorage.
const FX = "fxb:";
const CATALOG = [
  { id: "amul-taaza-1l", name: "Amul Taaza Toned Fresh Milk", size: "1 ltr", price: 56, mrp: 58, stock: true },
  { id: "amul-taaza-500", name: "Amul Taaza Toned Fresh Milk", size: "500 ml", price: 28, stock: true },
  { id: "amul-gold-1l", name: "Amul Gold Full Cream Fresh Milk", size: "1 ltr", price: 68, stock: true },
  { id: "md-toned-1l", name: "Mother Dairy Toned Milk", size: "1 ltr", price: 56, stock: true },
  { id: "hg-bread", name: "Harvest Gold White Bread", size: "400 g", price: 40, stock: true },
  { id: "britannia-bread", name: "Britannia 100% Whole Wheat Bread", size: "400 g", price: 55, stock: true },
  { id: "eggs-12", name: "Farm Fresh White Eggs", size: "12 pieces", price: 96, stock: true },
  { id: "eggs-6", name: "Farm Fresh White Eggs", size: "6 pieces", price: 52, stock: true },
  { id: "apple-1kg", name: "Shimla Apple", size: "1 kg", price: 180, stock: true },
  { id: "paneer-200", name: "Amul Malai Paneer", size: "200 g", price: 90, stock: false },
];
const get = (k, d) => { try { const v = localStorage.getItem(FX + k); return v === null ? d : JSON.parse(v); } catch { return d; } };
const set = (k, v) => localStorage.setItem(FX + k, JSON.stringify(v));
const price = (p) => (get("prices", {})[p.id] ?? p.price);
const money = (n) => "₹" + n;
function cart() { return get("cart", {}); }
function setQty(id, q) {
  const c = cart();
  if (q <= 0) delete c[id]; else c[id] = q;
  set("cart", c);
  renderCartCount();
}
function cartCount() { return Object.values(cart()).reduce((a, b) => a + b, 0); }
function renderCartCount() {
  document.querySelectorAll("[data-cart-count]").forEach((el) => { el.textContent = cartCount() ? cartCount() + " items" : "My Cart"; });
}
// Fixture controls (?login=0&location=0&cod=0&captcha=1&reset=1&price.amul-taaza-1l=60) for tests.
(function applyControls() {
  const q = new URLSearchParams(location.search);
  if (q.get("reset") === "1") Object.keys(localStorage).filter((k) => k.startsWith(FX)).forEach((k) => localStorage.removeItem(k));
  for (const key of ["login", "location", "cod", "captcha"]) if (q.has(key)) set(key, q.get(key) === "1");
  const prices = get("prices", {});
  for (const [k, v] of q.entries()) if (k.startsWith("price.")) prices[k.slice(6)] = Number(v);
  set("prices", prices);
})();
const flag = (k) => get(k, k === "captcha" ? false : true);

function header() {
  const loc = flag("location");
  return `<header class="hdr"><a href="index.html" class="logo">blinkit <small>(test fixture)</small></a>
    <div class="loc">${loc ? '<b>Delivery in 12 minutes</b><br><span data-address>Flat 12, Fixture Lane, Sector 1, Gurugram 122001</span>' : "<b>Select location</b>"}</div>
    <a href="search.html" class="searchbar" role="link">Search "milk"</a>
    <a href="cart.html" class="cartbtn" role="button"><span data-cart-count>My Cart</span></a></header>
    <p class="banner">LOCAL TEST FIXTURE — not the real Blinkit. Nothing here is a real product, price or order.</p>`;
}
function locationModal() {
  return `<div role="dialog" aria-modal="true" class="modal"><h2>Select your location</h2>
    <p>Provide your delivery location to see products available at your location</p>
    <button type="button">Detect my location</button><input placeholder="search delivery location"></div>`;
}
function captchaPage() {
  return `<main><h1>Please verify you are a human</h1><p>Complete the security check (CAPTCHA) to continue.</p>
    <div class="g-recaptcha">captcha</div></main>`;
}
function card(p) {
  const q = cart()[p.id] || 0;
  const control = !p.stock
    ? '<div class="oos">Out of Stock</div>'
    : q
      ? `<div class="stepper"><button type="button" aria-label="Remove ${p.name}" data-dec>−</button><span data-qty>${q}</span><button type="button" aria-label="Add ${p.name}" data-inc>+</button></div>`
      : '<div role="button" tabindex="0" class="add" data-add>ADD</div>';
  const mrp = p.mrp ? `<span class="mrp">${money(p.mrp)}</span>` : "";
  return `<div class="plp-card" data-test-id="plp-product" data-pid="${p.id}"><img alt="${p.name}" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=">
    <div class="eta">12 MINS</div><div class="title">${p.name}</div><div class="size">${p.size}</div>
    <div class="row"><div class="prices"><span class="price">${money(price(p))}</span>${mrp}</div>${control}</div></div>`;
}
function wireCards(root, rerender) {
  root.querySelectorAll("[data-pid]").forEach((el) => {
    const id = el.dataset.pid;
    const bump = (d) => setTimeout(() => { setQty(id, (cart()[id] || 0) + d); rerender(); }, 250); // async like the real site
    el.querySelector("[data-add]")?.addEventListener("click", () => bump(1));
    el.querySelector("[data-inc]")?.addEventListener("click", () => bump(1));
    el.querySelector("[data-dec]")?.addEventListener("click", () => bump(-1));
  });
}
function search(qs) {
  const words = qs.toLowerCase().split(/\s+/).filter((w) => w && !/^\d/.test(w) && !["l", "ltr", "litre", "ml", "g", "kg", "pack", "packet", "pieces", "dozen"].includes(w));
  const syn = { doodh: "milk", eggs: "eggs", egg: "eggs", ande: "eggs", anda: "eggs", apples: "apple", breads: "bread" };
  const norm = words.map((w) => syn[w] || w);
  const scored = CATALOG.map((p) => ({ p, s: norm.filter((w) => p.name.toLowerCase().includes(w)).length }));
  const best = Math.max(0, ...scored.map((x) => x.s));
  return best === 0 ? [] : scored.filter((x) => x.s === best || x.s >= Math.max(1, best - 1)).map((x) => x.p);
}
function totals() {
  const c = cart();
  const items = Object.entries(c).map(([id, q]) => ({ p: CATALOG.find((x) => x.id === id), q })).filter((x) => x.p);
  const sub = items.reduce((a, x) => a + price(x.p) * x.q, 0);
  const delivery = sub >= 199 ? 0 : 25;
  const handling = items.length ? 4 : 0;
  return { items, sub, delivery, handling, total: sub + delivery + handling };
}

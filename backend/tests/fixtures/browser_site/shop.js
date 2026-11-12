// TaskPilot Demo Shop — a controlled, local-only fixture for browser tests.
// It never talks to a server: the cart lives in localStorage of this origin.
const PRODUCTS = [
  { id: "amul-taaza-1l", name: "Amul Taaza Toned Milk", size: "1 L", price: 54, stock: true },
  { id: "amul-gold-500", name: "Amul Gold Full Cream Milk", size: "500 ml", price: 34, stock: true },
  { id: "md-toned-500", name: "Mother Dairy Toned Milk", size: "500 ml", price: 28, stock: true },
  { id: "nandini-1l", name: "Nandini Pasteurised Milk", size: "1 L", price: 48, stock: false },
  { id: "hg-bread", name: "Harvest Gold White Bread", size: "400 g packet", price: 45, stock: true },
  { id: "eggs-12", name: "Farm Fresh Eggs", size: "12 pcs", price: 84, stock: true },
  { id: "acer-laptop", name: "Acer Aspire 7 Laptop", size: "1 unit", price: 58990, stock: true },
];

function readCart() {
  try { return JSON.parse(localStorage.getItem("tp-demo-cart") || "{}"); } catch { return {}; }
}
function writeCart(cart) { localStorage.setItem("tp-demo-cart", JSON.stringify(cart)); renderCount(); }
function cartCount() { return Object.values(readCart()).reduce((a, b) => a + b, 0); }
function renderCount() {
  document.querySelectorAll("[data-cart-count]").forEach((el) => { el.textContent = String(cartCount()); });
}
function addToCart(id, button) {
  const cart = readCart();
  cart[id] = (cart[id] || 0) + 1;
  writeCart(cart);
  if (button) { button.textContent = "Added ✓"; }
}
function money(v) { return "₹" + v.toLocaleString("en-IN"); }

function productCard(p) {
  const li = document.createElement("li");
  li.dataset.product = p.id;
  li.className = "card";
  li.innerHTML = `<h3>${p.name}</h3><p>${p.size}</p><p class="price">${money(p.price)}</p>
    <p>${p.stock ? "In stock" : "Out of stock"}</p>`;
  const btn = document.createElement("button");
  btn.textContent = "Add";
  btn.disabled = !p.stock;
  btn.addEventListener("click", () => addToCart(p.id, btn));
  li.appendChild(btn);
  return li;
}

function renderResults(query, list, delayMs) {
  const terms = query.toLowerCase().split(/\s+/).filter((t) => t && !/^\d+(\.\d+)?$/.test(t) && !["l", "ml", "litre", "liter", "g", "kg"].includes(t));
  const status = document.getElementById("status");
  status.textContent = "Searching…";
  setTimeout(() => {
    list.innerHTML = "";
    const hits = PRODUCTS.filter((p) => terms.every((t) => (p.name + " " + p.size).toLowerCase().includes(t.replace(/s$/, ""))));
    hits.forEach((p) => list.appendChild(productCard(p)));
    status.textContent = hits.length ? `${hits.length} result(s) for “${query}”` : `No results for “${query}”`;
  }, delayMs);
}

document.addEventListener("DOMContentLoaded", renderCount);

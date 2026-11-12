// LOCAL TEST FIXTURE ONLY — an Amazon.in-like store for TaskPilot's Playwright tests.
// Not affiliated with Amazon. Ids/attributes mirror common amazon.in markup so the adapter's
// selectors are exercised, but every product, price, seller and order here is fake.
const FX = "fxa:";
const CATALOG = [
  { asin: "FXL0000001", kw: "laptop notebook", title: "ASUS Vivobook 15, Intel Core i5-1235U 12th Gen (16GB RAM/512GB SSD/Windows 11/Office 2021) Laptop, Silver", brand: "ASUS", price: 54990, mrp: 70990, rating: "4.1 out of 5 stars", reviews: "1,204", seller: "Fixture Retail Pvt Ltd", specs: { RAM: "16 GB", "Hard Disk Size": "512 GB SSD", Colour: "Silver" }, stock: true },
  { asin: "FXL0000002", kw: "laptop notebook", title: "HP 15s, 12th Gen Intel Core i5-1235U (8GB RAM/512GB SSD/Windows 11) Laptop, Natural Silver", brand: "HP", price: 47990, rating: "4.0 out of 5 stars", reviews: "845", seller: "Fixture Retail Pvt Ltd", specs: { RAM: "8 GB", "Hard Disk Size": "512 GB SSD" }, stock: true },
  { asin: "FXL0000003", kw: "laptop notebook", title: "Lenovo IdeaPad Slim 3 Intel Core i7 (16GB RAM/512GB SSD/Windows 11) Laptop, Arctic Grey", brand: "Lenovo", price: 62490, rating: "4.2 out of 5 stars", reviews: "512", seller: "Fixture Appario", specs: { RAM: "16 GB", "Hard Disk Size": "512 GB SSD" }, stock: true },
  { asin: "FXL0000004", kw: "laptop notebook", title: "Acer Aspire Lite AMD Ryzen 5 5625U (16GB RAM/512GB SSD/Windows 11) Laptop, Steel Gray", brand: "Acer", price: 41990, rating: "3.9 out of 5 stars", reviews: "2,310", seller: "Fixture Cloudtail", specs: { RAM: "16 GB", "Hard Disk Size": "512 GB SSD" }, stock: true },
  { asin: "FXM0000001", kw: "mouse mice", title: "Logitech M331 Silent Plus Wireless Mouse, Black", brand: "Logitech", price: 1395, rating: "4.4 out of 5 stars", reviews: "30,112", seller: "Fixture Retail Pvt Ltd", specs: { Colour: "Black" }, stock: true },
  { asin: "FXM0000002", kw: "mouse mice", title: "Logitech MX Master 3S Wireless Performance Mouse, Graphite", brand: "Logitech", price: 9495, rating: "4.6 out of 5 stars", reviews: "7,020", seller: "Fixture Retail Pvt Ltd", specs: {}, stock: true },
  { asin: "FXP0000001", kw: "phone mobile smartphone", title: "Samsung Galaxy M34 5G (Midnight Blue, 6GB RAM, 128GB Storage)", brand: "Samsung", price: 15999, rating: "4.1 out of 5 stars", reviews: "9,875", seller: "Fixture Appario", specs: { RAM: "6 GB", Storage: "128 GB", Colour: "Midnight Blue" }, stock: true },
  { asin: "FXP0000002", kw: "phone mobile smartphone", title: "Samsung Galaxy M34 5G (Midnight Blue, 8GB RAM, 128GB Storage)", brand: "Samsung", price: 17999, rating: "4.1 out of 5 stars", reviews: "9,875", seller: "Fixture Appario", specs: { RAM: "8 GB", Storage: "128 GB", Colour: "Midnight Blue" }, stock: true },
  { asin: "FXP0000003", kw: "phone mobile smartphone", title: "Samsung Galaxy S23 5G (Phantom Black, 8GB RAM, 256GB Storage)", brand: "Samsung", price: 64999, rating: "4.5 out of 5 stars", reviews: "3,404", seller: "Fixture Retail Pvt Ltd", specs: { RAM: "8 GB", Storage: "256 GB" }, stock: false },
];
const get = (k, d) => { try { const v = localStorage.getItem(FX + k); return v === null ? d : JSON.parse(v); } catch { return d; } };
const set = (k, v) => localStorage.setItem(FX + k, JSON.stringify(v));
const price = (p) => (get("prices", {})[p.asin] ?? p.price);
const inr = (n) => "₹" + n.toLocaleString("en-IN") + ".00";
const cart = () => get("cart", {});
function setQty(asin, q) { const c = cart(); if (q <= 0) delete c[asin]; else c[asin] = q; set("cart", c); }
(function applyControls() {
  const q = new URLSearchParams(location.search);
  if (q.get("reset") === "1") Object.keys(localStorage).filter((k) => k.startsWith(FX)).forEach((k) => localStorage.removeItem(k));
  for (const key of ["login", "cod", "captcha"]) if (q.has(key)) set(key, q.get(key) === "1");
  const prices = get("prices", {});
  for (const [k, v] of q.entries()) if (k.startsWith("price.")) prices[k.slice(6)] = Number(v);
  set("prices", prices);
})();
const flag = (k) => get(k, k === "captcha" ? false : true);
function nav() {
  const count = Object.values(cart()).reduce((a, b) => a + b, 0);
  return `<header id="navbar"><a href="index.html" id="nav-logo-sprites">amazon.in <small>(test fixture)</small></a>
    <form id="nav-search-bar-form" action="search.html" role="search"><input type="text" id="twotabsearchtextbox" name="k" placeholder="Search Amazon.in" aria-label="Search Amazon.in">
    <input type="submit" id="nav-search-submit-button" value="Go" aria-label="Go"></form>
    <a href="cart.html" id="nav-cart" aria-label="${count} items in cart">Cart <span id="nav-cart-count">${count}</span></a></header>
    <p class="banner">LOCAL TEST FIXTURE — not the real Amazon. Nothing here is a real product, price, seller or order.</p>`;
}
function captcha() {
  return `<div class="a-box"><h4>Enter the characters you see below</h4><p>Sorry, we just need to make sure you're not a robot.</p>
    <form method="get" action="/errors/validateCaptcha"><input id="captchacharacters" name="field-keywords"><button type="submit">Continue shopping</button></form></div>`;
}

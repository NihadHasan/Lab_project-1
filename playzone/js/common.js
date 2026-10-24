/* Shared header, footer, cards and ad slots */
const $ = (s, el=document) => el.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function thumbStyle(g) {
  const thumb = g.thumbnail_path || g.thumb;
  if (thumb) return `background-image:url('${esc(thumb.startsWith("uploads/") ? `/static/${thumb}` : thumb)}');background-size:cover;background-position:center`;
  const colors = g.colors || [g.color_start || "#11a8a1", g.color_end || "#147d72"];
  return `background:linear-gradient(135deg,${colors[0]},${colors[1]})`;
}

function gameCard(g) {
  const hasThumb = g.thumbnail_path || g.thumb;
  const slug = g.slug || g.id;
  return `<a class="card" href="/game.html?id=${encodeURIComponent(slug)}">
    <div class="thumb" style="${thumbStyle(g)}">${hasThumb ? "" : `<span class="emoji">${g.emoji || "🎮"}</span>`}${(g.is_new || g.isNew) ? '<b class="tag">NEW</b>' : ""}</div>
    <div class="card-body"><h3>${esc(g.title)}</h3><p>${esc(g.category)}</p></div></a>`;
}

function renderHeader() {
  $("#site-header").innerHTML = `
  <div class="wrap bar">
    <a class="logo" href="/"><span class="logo-mark">🎮</span>${SITE.name}</a>
    <button class="burger" aria-label="Menu" onclick="document.body.classList.toggle('nav-open')">☰</button>
    <nav class="nav" aria-label="Main">
      <a href="/">Home</a>
      <a href="/#categories">Categories</a>
      <a href="/#popular">Popular</a>
      <a href="/#new">New</a>
      <a href="/#leaderboard">Leaderboard</a>
      <a class="pill" href="/#premium">⭐ Premium</a>
    </nav>
    <label class="search"><span>Search games</span><input id="game-search" type="search" placeholder="Find a game" aria-label="Search games"></label>
  </div>`;
  const searchInput = $("#game-search");
  searchInput.addEventListener("keydown", event => {
    if (event.key === "Enter" && !document.querySelector("#popular")) {
      location.href = `/?q=${encodeURIComponent(searchInput.value.trim())}`;
    }
  });
}

function renderFooter() {
  $("#site-footer").innerHTML = `
  <div class="wrap foot">
    <div><a class="logo" href="/"><span class="logo-mark">🎮</span>${SITE.name}</a><p>${SITE.tagline}</p></div>
    <nav aria-label="Footer"><a href="/about.html">About</a><a href="/contact.html">Contact</a><a href="/privacy.html">Privacy Policy</a><a href="/terms.html">Terms</a></nav>
    <p class="copy">© ${new Date().getFullYear()} ${SITE.name}. All rights reserved.</p>
  </div>`;
}

/* ---- Scores (saved in this visitor's browser) ---- */
function getScores() { try { return JSON.parse(localStorage.getItem("pz_scores")) || {}; } catch(e) { return {}; } }
function saveScore(id, score) {
  const s = getScores();
  if (s[id] == null || score > s[id]) { s[id] = score; try { localStorage.setItem("pz_scores", JSON.stringify(s)); } catch(e) {} return true; }
  return false;
}

document.addEventListener("DOMContentLoaded", () => {
  renderHeader();
  renderFooter();
  const recommendations = $("#side-recommendations");
  if (!recommendations) return;
  fetch("/api/games").then(response => response.json()).then(games => {
    const current = new URLSearchParams(location.search).get("id");
    const picks = games.filter(game => game.slug !== current).slice(0, 3);
    recommendations.innerHTML = `<p class="pick-kicker">PLAYZONE PICKS</p><h2>Play next</h2><p class="pick-intro">A few quick games for your next round.</p>` +
      `<div class="pick-list">${picks.map(game => `<a class="pick-item" href="/game.html?id=${encodeURIComponent(game.slug)}"><span class="pick-art" style="${thumbStyle(game)}">${game.thumbnail_path ? "" : esc(game.emoji || "🎮")}</span><span class="pick-copy"><b>${esc(game.title)}</b><small>${esc(game.category)}</small><strong>Play now <span aria-hidden="true">→</span></strong></span></a>`).join("")}</div>` +
      `<a class="pick-more" href="/">Browse all games <span aria-hidden="true">→</span></a>`;
  }).catch(() => {
    recommendations.innerHTML = `<h2>Play next</h2><p class="empty">Game recommendations are temporarily unavailable.</p>`;
  });
});

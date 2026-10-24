document.addEventListener("DOMContentLoaded", () => {
  const params = new URLSearchParams(location.search);
  const category = params.get("cat") || "";
  const searchInput = $("#game-search");
  if (searchInput) searchInput.value = params.get("q") || "";
  let catalog = [];
  let categories = [];
  const grid = list => list.length ? `<div class="grid">${list.map(gameCard).join("")}</div>` : `<p class="empty">No games here yet. Check back soon!</p>`;

  async function render() {
    const query = searchInput ? searchInput.value.trim() : "";
    const search = new URLSearchParams();
    if (category) search.set("category", category);
    if (query) search.set("q", query);
    const response = await fetch(`/api/games?${search}`);
    if (!response.ok) throw new Error("Could not load games.");
    const visible = await response.json();
    const picked = categories.find(item => item.slug === category);
    const feature = catalog.find(game => game.featured) || catalog[0];
    const widePicks = catalog.slice(0, 3);

    $("#home-wide-picks").innerHTML = `<div class="wide-pick-heading"><span>QUICK PLAY</span><strong>Pick your next game</strong></div>` +
      `<div class="wide-pick-list">${widePicks.map(game => `<a class="wide-pick" href="/game.html?id=${encodeURIComponent(game.slug)}"><span class="wide-pick-art" style="${thumbStyle(game)}">${game.thumbnail_path ? "" : esc(game.emoji || "🎮")}</span><span><b>${esc(game.title)}</b><small>${esc(game.category)}</small></span><strong aria-hidden="true">→</strong></a>`).join("")}</div>`;
    $("#home-snapshot").innerHTML = `<span class="snapshot-kicker">PLAYZONE LIBRARY</span><strong class="snapshot-total">${catalog.length}<small> games ready to play</small></strong><p>${categories.length} categories to explore</p>` +
      `<div class="snapshot-categories">${categories.slice(0, 4).map(item => `<a href="/?cat=${encodeURIComponent(item.slug)}">${esc(item.name)}</a>`).join("")}</div>`;

    if (feature && !category && !query) {
      $("#featured").innerHTML = `<div class="hero" style="${thumbStyle(feature)}">
        <div class="hero-text"><span class="badge">Featured game</span><h1>${esc(feature.title)}</h1><p>${esc(feature.description)}</p>
        <a class="play" href="/game.html?id=${encodeURIComponent(feature.slug)}">▶ Play now</a></div>
        ${feature.thumbnail_path ? "" : `<div class="hero-emoji">${feature.emoji}</div>`}</div>`;
    } else {
      $("#featured").innerHTML = "";
    }

    $("#categories").innerHTML = `<h2>Game categories</h2><div class="chips">` +
      `<a class="chip ${!category ? "on" : ""}" href="/">All</a>` +
      categories.map(item => `<a class="chip ${item.slug === category ? "on" : ""}" href="/?cat=${encodeURIComponent(item.slug)}">${esc(item.name)}</a>`).join("") + `</div>`;

    if (category || query) {
      $("#popular").innerHTML = `<h2>${esc(picked ? picked.name : "Search results")}</h2>` + grid(visible);
      $("#new").hidden = true;
    } else {
      $("#popular").innerHTML = `<h2>Popular games</h2>` + grid(visible.filter(game => game.popular));
      $("#new").hidden = false;
      $("#new").innerHTML = `<h2>New games</h2>` + grid(visible.filter(game => game.is_new));
    }
    if (searchInput) {
      const next = new URL(location.href);
      query ? next.searchParams.set("q", query) : next.searchParams.delete("q");
      history.replaceState(null, "", next);
    }
  }

  Promise.all([fetch("/api/games").then(response => response.json()), fetch("/api/categories").then(response => response.json())])
    .then(([games, categoryRows]) => {
      catalog = games;
      categories = categoryRows;
      return render();
    })
    .catch(() => {
      $("#popular").innerHTML = `<p class="empty">The game list is temporarily unavailable.</p>`;
    });

  if (searchInput) {
    let timer;
    searchInput.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => render().catch(() => {}), 160);
    });
  }

  fetch("/api/leaderboard").then(response => response.json()).then(rows => {
    $("#leaderboard").innerHTML = `<h2>Leaderboard</h2>` + (rows.length
      ? `<ol class="scores">${rows.map(row => `<li><span>${esc(row.player_name)} · ${esc(row.game_title)}<small>${esc(row.created_at)}</small></span><b>${row.score}</b></li>`).join("")}</ol>`
      : `<p class="empty">No scores yet. Play a game to set the first record.</p>`);
  }).catch(() => {
    $("#leaderboard").innerHTML = `<h2>Leaderboard</h2><p class="empty">Scores are temporarily unavailable.</p>`;
  });
});

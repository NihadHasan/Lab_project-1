document.addEventListener("DOMContentLoaded", () => {
  const id = new URLSearchParams(location.search).get("id");
  const main = $("#game-main");
  if (!id) { main.innerHTML = `<h1>Game not found</h1><p><a href="/">Back to all games</a></p>`; return; }

  fetch(`/api/games/${encodeURIComponent(id)}`).then(response => {
    if (!response.ok) throw new Error("Game not found");
    return response.json();
  }).then(async game => {
    const best = getScores()[game.slug];
    const allGames = await fetch("/api/games").then(response => response.json());
    document.title = `${game.title} - Play Free Online | PlayZone`;
    const description = document.querySelector('meta[name="description"]');
    if (description) description.content = game.description;
    const isExternal = game.game_path.startsWith("https://");
    const gamePath = isExternal ? game.game_path : `/${game.game_path.split("/").map(encodeURIComponent).join("/")}`;
    const sandbox = isExternal ? "allow-scripts allow-same-origin allow-pointer-lock allow-popups allow-presentation" : "allow-scripts allow-pointer-lock allow-popups allow-presentation";
    main.innerHTML = `
      <p class="crumbs"><a href="/">Home</a> / <a href="/?cat=${encodeURIComponent(game.category_slug)}">${esc(game.category)}</a> / ${esc(game.title)}</p>
      <h1>${esc(game.title)}</h1>
      <section class="game-guide" aria-label="Game instructions"><span class="guide-art" style="${thumbStyle(game)}">${game.thumbnail_path ? "" : esc(game.emoji || "🎮")}</span><div><span class="guide-kicker">${esc(game.category)} · GAME GUIDE</span><p>${esc(game.description)}</p></div><a href="#frame">Play now ↓</a></section>
      <div class="stage"><iframe id="frame" src="${esc(gamePath)}" title="${esc(game.title)}" allow="fullscreen; gamepad" sandbox="${sandbox}"></iframe></div>
      <div class="stage-bar"><span>Your best: <b id="best">${best != null ? best : "–"}</b></span>
        <label class="player-label">Leaderboard name <input id="player-name" maxlength="32" value="Guest"></label>
        <button class="btn" id="restart-game" type="button" aria-label="Restart game">↻ Restart</button>
        <button class="btn" id="fullscreen-game" type="button" aria-label="Enter fullscreen">⛶ Fullscreen</button></div>
      <p id="score-status" class="empty" aria-live="polite"></p>
      <section class="keep-playing"><div class="keep-playing-heading"><span>KEEP PLAYING</span><h2>Try another game</h2></div><div class="mini-promo-list">${allGames.filter(item => item.slug !== game.slug).slice(0, 3).map(item => `<a class="mini-promo" href="/game.html?id=${encodeURIComponent(item.slug)}"><span class="mini-promo-art" style="${thumbStyle(item)}">${item.thumbnail_path ? "" : esc(item.emoji || "🎮")}</span><span><b>${esc(item.title)}</b><small>${esc(item.category)}</small></span><strong aria-hidden="true">→</strong></a>`).join("") || `<a class="pick-more" href="/">Browse all games →</a>`}</div></section>`;

    $("#game-snapshot").innerHTML = `<span class="snapshot-kicker">GAME SNAPSHOT</span><h2>${esc(game.title)}</h2><p class="snapshot-category">${esc(game.category)}</p><div class="snapshot-stats"><div><strong>${allGames.length}</strong><span>games live</span></div><div><strong>${best != null ? best : "–"}</strong><span>your best</span></div></div><a class="pick-more" href="/?cat=${encodeURIComponent(game.category_slug)}">More ${esc(game.category)} games <span aria-hidden="true">→</span></a>`;

    fetch(`/api/games/${encodeURIComponent(game.slug)}/play`, { method: "POST" }).catch(() => {});
    $("#restart-game").addEventListener("click", () => { $("#frame").src = gamePath; });
    $("#fullscreen-game").addEventListener("click", () => $("#frame").requestFullscreen?.());

    window.addEventListener("message", async event => {
      const frame = $("#frame");
      const expectedOrigin = isExternal ? new URL(gamePath).origin : "null";
      if (event.source !== frame.contentWindow || event.origin !== expectedOrigin) return;
      if (!event.data || event.data.type !== "score" || !Number.isSafeInteger(event.data.score) || event.data.score < 0) return;
      const score = event.data.score;
      saveScore(game.slug, score);
      $("#best").textContent = getScores()[game.slug];
      const player = $("#player-name").value.trim().slice(0, 32) || "Guest";
      const response = await fetch("/api/scores", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game: game.slug, player, score })
      });
      $("#score-status").textContent = response.ok ? "Score saved to the leaderboard." : "This score could not be saved.";
    });
  }).catch(() => {
    main.innerHTML = `<h1>Game not found</h1><p><a href="/">Back to all games</a></p>`;
  });
});

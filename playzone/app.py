import html
import ipaddress
import os
import re
import secrets
import sqlite3
import time
import xml.etree.ElementTree as ET
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import click
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
ALLOWED_PAGES = {"about.html", "contact.html", "privacy.html", "terms.html"}
ALLOWED_ASSET_DIRS = {"css", "js", "images"}
IMAGE_SIGNATURES = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
}
MAX_HTML_GAME_SIZE = 10 * 1024 * 1024
MAX_THUMBNAIL_SIZE = 2 * 1024 * 1024


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("PLAYZONE_SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get("PLAYZONE_DATABASE") or str(Path(app.instance_path) / "playzone.sqlite3"),
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
        EMBED_HOSTS=tuple(host.strip().lower().rstrip(".") for host in os.environ.get("PLAYZONE_EMBED_HOSTS", "").split(",") if host.strip()),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("PLAYZONE_COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    (ROOT / "static" / "uploads").mkdir(parents=True, exist_ok=True)
    (ROOT / "static" / "game_uploads").mkdir(parents=True, exist_ok=True)
    app.extensions["login_attempts"] = {}
    app.extensions["score_attempts"] = {}

    @app.teardown_appcontext
    def close_db(_error=None):
        db = g.pop("db", None)
        if db is not None:
            if _error is not None:
                db.rollback()
            db.close()

    with app.app_context():
        init_db()

    @app.context_processor
    def template_values():
        return {
            "csrf_token": csrf_token,
            "site_url": os.environ.get("PLAYZONE_SITE_URL", request.url_root.rstrip("/")),
        }

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        frame_sources = " ".join(f"https://{host}" for host in current_app.config["EMBED_HOSTS"])
        csp = "default-src 'self' https:; script-src 'self' 'unsafe-inline' https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data: https:; frame-src 'self'" + (f" {frame_sources}" if frame_sources else "") + "; form-action 'self'; frame-ancestors 'self'"
        response.headers.setdefault("Content-Security-Policy", csp)
        if response.mimetype == "text/html" and not request.path.startswith("/game-uploads/"):
            response.direct_passthrough = False
            source = response.get_data(as_text=True)
            if "</head>" in source and 'rel="canonical"' not in source:
                base = os.environ.get("PLAYZONE_SITE_URL", request.url_root).rstrip("/")
                canonical_path = request.path
                if request.path == "/index.html":
                    canonical_path = "/"
                elif request.path == "/game.html" and request.args.get("id"):
                    canonical_path += "?id=" + request.args["id"]
                link = f'<link rel="canonical" href="{html.escape(base + canonical_path, quote=True)}">'
                source = source.replace("</head>", f"{link}</head>", 1)
            if "</head>" in source and 'rel="icon"' not in source:
                source = source.replace("</head>", '<link rel="icon" type="image/svg+xml" href="/images/favicon.svg"></head>', 1)
            response.set_data(source)
        return response

    @app.get("/")
    @app.get("/index.html")
    def home():
        return send_from_directory(ROOT, "index.html")

    @app.get("/game.html")
    def game_page():
        slug = request.args.get("id", "")
        game = get_game(slug) if slug else None
        if game is None or not game["published"]:
            abort(404)
        response = send_from_directory(ROOT, "game.html")
        response.direct_passthrough = False
        source = response.get_data(as_text=True)
        source = source.replace("<title>Play Game - PlayZone</title>", f"<title>{html.escape(game['title'])} - PlayZone</title>")
        source = source.replace('content="Play free online games on PlayZone."', f'content="{html.escape(game["description"], quote=True)}"')
        response.set_data(source)
        return response

    @app.get("/robots.txt")
    def robots():
        base = os.environ.get("PLAYZONE_SITE_URL", request.url_root).rstrip("/")
        return Response(f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {base}/sitemap.xml\n", mimetype="text/plain")

    @app.get("/sitemap.xml")
    def sitemap():
        base = os.environ.get("PLAYZONE_SITE_URL", request.url_root).rstrip("/")
        namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
        root = ET.Element("urlset", xmlns=namespace)
        paths = ["/", "/about.html", "/contact.html", "/privacy.html", "/terms.html"]
        paths.extend(f"/game.html?id={row['slug']}" for row in get_db().execute("SELECT slug FROM games WHERE published=1 ORDER BY sort_order"))
        for path in paths:
            item = ET.SubElement(root, "url")
            ET.SubElement(item, "loc").text = base + path
        return Response(ET.tostring(root, encoding="unicode", xml_declaration=True), mimetype="application/xml")

    @app.get("/games/<path:filename>")
    def game_asset(filename):
        return send_from_directory(ROOT / "games", filename)

    @app.get("/game-uploads/<filename>")
    def uploaded_game(filename):
        response = send_from_directory(ROOT / "static" / "game_uploads", filename)
        response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob:; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; sandbox allow-scripts; frame-ancestors 'self'"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    @app.get("/static/uploads/<path:filename>")
    def uploaded_thumbnail(filename):
        return send_from_directory(ROOT / "static" / "uploads", filename)

    @app.get("/<path:asset>")
    def public_files(asset):
        if asset in ALLOWED_PAGES and (ROOT / asset).is_file():
            return send_from_directory(ROOT, asset)
        first = asset.split("/", 1)[0]
        if first in ALLOWED_ASSET_DIRS and (ROOT / asset).is_file():
            return send_from_directory(ROOT, asset)
        if asset in {"robots.txt", "sitemap.xml"}:
            return send_from_directory(ROOT, asset)
        abort(404)

    @app.get("/api/categories")
    def api_categories():
        rows = get_db().execute("SELECT id, name, slug FROM categories ORDER BY name").fetchall()
        return jsonify([dict(row) for row in rows])

    @app.get("/api/games")
    def api_games():
        query = request.args.get("q", "").strip()[:100]
        category = request.args.get("category", "").strip()[:80]
        filters = ["g.published = 1"]
        values = []
        if query:
            filters.append("(g.title LIKE ? OR g.description LIKE ?)")
            values.extend((f"%{query}%", f"%{query}%"))
        if category:
            filters.append("c.slug = ?")
            values.append(category)
        rows = get_db().execute(
            f"""SELECT g.*, c.name AS category, c.slug AS category_slug
                FROM games g JOIN categories c ON c.id = g.category_id
                WHERE {' AND '.join(filters)} ORDER BY g.sort_order, g.id""",
            values,
        ).fetchall()
        return jsonify([game_json(row) for row in rows])

    @app.get("/api/games/<slug>")
    def api_game(slug):
        row = get_game(slug)
        if row is None or not row["published"]:
            abort(404)
        return jsonify(game_json(row))

    @app.post("/api/games/<slug>/play")
    def api_game_play(slug):
        row = get_game(slug)
        if row is None or not row["published"]:
            abort(404)
        get_db().execute("INSERT INTO plays (game_id) VALUES (?)", (row["id"],))
        get_db().commit()
        return jsonify({"ok": True})

    @app.get("/api/leaderboard")
    def api_leaderboard():
        slug = request.args.get("game", "").strip()[:80]
        sql = """SELECT s.player_name, s.score, s.created_at, g.title AS game_title, g.slug AS game_slug
                 FROM scores s JOIN games g ON g.id = s.game_id WHERE g.published = 1"""
        values = []
        if slug:
            sql += " AND g.slug = ?"
            values.append(slug)
        rows = get_db().execute(sql + " ORDER BY s.score DESC, s.created_at ASC LIMIT 10", values).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post("/api/scores")
    def api_scores():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Expected JSON data."}), 400
        slug = str(data.get("game", ""))[:80]
        raw_player = data.get("player", "Guest")
        if not isinstance(raw_player, str) or len(raw_player) > 32 or any(ord(char) < 32 for char in raw_player):
            return jsonify({"error": "Player name must be 1 to 32 printable characters."}), 400
        player = raw_player.strip() or "Guest"
        score = data.get("score")
        if isinstance(score, bool) or not isinstance(score, int) or score < 0 or score > 100000:
            return jsonify({"error": "Score must be a whole number from 0 to 100000."}), 400
        row = get_game(slug)
        if row is None or not row["published"]:
            return jsonify({"error": "Game not found."}), 404
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            return jsonify({"error": "Cross-origin submission rejected."}), 403
        caps = {"snake": 100000, "memory-match": 200, "whack-a-mole": 1000, "2048": 100000, "tic-tac-toe": 100, "pong": 5}
        if score > caps.get(slug, 100000):
            return jsonify({"error": "Score exceeds this game's maximum."}), 400
        remote = request.remote_addr or "unknown"
        now = time.time()
        attempts = app.extensions["score_attempts"]
        recent = [stamp for stamp in attempts.get(remote, []) if now - stamp < 60]
        if len(recent) >= 30:
            return jsonify({"error": "Too many score submissions. Try again shortly."}), 429
        recent.append(now)
        attempts[remote] = recent
        get_db().execute(
            "INSERT INTO scores (game_id, player_name, score) VALUES (?, ?, ?)",
            (row["id"], player, score),
        )
        get_db().commit()
        return jsonify({"ok": True}), 201

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if session.get("admin_id"):
            return redirect(url_for("admin_dashboard"))
        error = None
        if request.method == "POST":
            if not valid_csrf():
                abort(400)
            username = request.form.get("username", "").strip()[:80]
            password = request.form.get("password", "")
            remote = request.remote_addr or "unknown"
            now = time.time()
            attempts = app.extensions["login_attempts"]
            recent = [stamp for stamp in attempts.get(remote, []) if now - stamp < 900]
            if len(recent) >= 5:
                error = "Too many attempts. Wait 15 minutes and try again."
            else:
                admin = get_db().execute("SELECT id, username, password_hash FROM admins WHERE username = ?", (username,)).fetchone()
                if admin and check_password_hash(admin["password_hash"], password):
                    attempts.pop(remote, None)
                    session.clear()
                    session["admin_id"] = admin["id"]
                    session["admin_username"] = admin["username"]
                    session.permanent = True
                    return redirect(url_for("admin_dashboard"))
                recent.append(now)
                attempts[remote] = recent
                error = "Invalid username or password."
        return render_template("admin_login.html", error=error)

    @app.post("/admin/logout")
    @admin_required
    def admin_logout():
        if not valid_csrf():
            abort(400)
        session.clear()
        return redirect(url_for("admin_login"))

    @app.get("/admin")
    @admin_required
    def admin_dashboard():
        db = get_db()
        games = db.execute("""SELECT g.*, c.name AS category,
            (SELECT COUNT(*) FROM plays p WHERE p.game_id=g.id) AS play_count,
            (SELECT COUNT(*) FROM scores s WHERE s.game_id=g.id) AS score_count
            FROM games g JOIN categories c ON c.id=g.category_id ORDER BY g.sort_order, g.id""").fetchall()
        categories = db.execute("""SELECT c.id, c.name, c.slug, COUNT(g.id) AS game_count
            FROM categories c LEFT JOIN games g ON g.category_id=c.id GROUP BY c.id ORDER BY c.name""").fetchall()
        scores = db.execute("""SELECT s.player_name, s.score, s.created_at, g.title AS game_title
            FROM scores s JOIN games g ON g.id=s.game_id ORDER BY s.created_at DESC LIMIT 20""").fetchall()
        stats = db.execute("SELECT (SELECT COUNT(*) FROM games) AS games, (SELECT COUNT(*) FROM plays) AS plays, (SELECT COUNT(*) FROM scores) AS scores").fetchone()
        return render_template("admin.html", games=games, categories=categories, scores=scores, stats=stats)

    @app.post("/admin/categories/new")
    @admin_required
    def admin_category_new():
        if not valid_csrf():
            abort(400)
        name = request.form.get("name", "").strip()
        if not name or len(name) > 60:
            flash("Category name must be 1 to 60 characters.", "error")
            return redirect(url_for("admin_dashboard"))
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not slug:
            flash("Use letters or numbers in the category name.", "error")
            return redirect(url_for("admin_dashboard"))
        try:
            get_db().execute("INSERT INTO categories (name, slug) VALUES (?, ?)", (name, slug))
            get_db().commit()
        except sqlite3.IntegrityError:
            flash("That category name already exists.", "error")
            return redirect(url_for("admin_dashboard"))
        flash("Category added.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/categories/<int:category_id>/delete")
    @admin_required
    def admin_category_delete(category_id):
        if not valid_csrf():
            abort(400)
        category = get_db().execute("SELECT name FROM categories WHERE id=?", (category_id,)).fetchone()
        if category is None:
            abort(404)
        used = get_db().execute("SELECT 1 FROM games WHERE category_id=? LIMIT 1", (category_id,)).fetchone()
        if used:
            flash("Move or delete this category's games before removing it.", "error")
            return redirect(url_for("admin_dashboard"))
        get_db().execute("DELETE FROM categories WHERE id=?", (category_id,))
        get_db().commit()
        flash("Category deleted.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/games/new", methods=["GET", "POST"])
    @admin_required
    def admin_game_new():
        if request.method == "POST":
            if not valid_csrf():
                abort(400)
            values = parse_game_form()
            if isinstance(values, str):
                return render_template("admin_game_form.html", game=None, categories=categories(), error=values), 400
            db = get_db()
            try:
                next_order = db.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM games").fetchone()[0]
                db.execute("""INSERT INTO games (slug, title, description, category_id, thumbnail_path, game_path,
                    featured, popular, is_new, published, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*values, next_order))
                db.commit()
            except sqlite3.IntegrityError:
                delete_uploaded_game(values[5])
                delete_uploaded_thumbnail(values[4])
                return render_template("admin_game_form.html", game=None, categories=categories(), error="That game slug is already in use."), 400
            flash("Game added.", "success")
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_game_form.html", game=None, categories=categories(), error=None)

    @app.route("/admin/games/<int:game_id>/edit", methods=["GET", "POST"])
    @admin_required
    def admin_game_edit(game_id):
        game = get_db().execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if game is None:
            abort(404)
        if request.method == "POST":
            if not valid_csrf():
                abort(400)
            values = parse_game_form(game)
            if isinstance(values, str):
                return render_template("admin_game_form.html", game=game, categories=categories(), error=values), 400
            try:
                get_db().execute("""UPDATE games SET slug=?, title=?, description=?, category_id=?, thumbnail_path=?,
                    game_path=?, featured=?, popular=?, is_new=?, published=? WHERE id=?""", (*values, game_id))
                get_db().commit()
            except sqlite3.IntegrityError:
                if values[5] != game["game_path"]:
                    delete_uploaded_game(values[5])
                if values[4] != game["thumbnail_path"]:
                    delete_uploaded_thumbnail(values[4])
                return render_template("admin_game_form.html", game=game, categories=categories(), error="That game slug is already in use."), 400
            if values[5] != game["game_path"]:
                delete_uploaded_game(game["game_path"])
            if values[4] != game["thumbnail_path"]:
                delete_uploaded_thumbnail(game["thumbnail_path"])
            flash("Game updated.", "success")
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_game_form.html", game=game, categories=categories(), error=None)

    @app.post("/admin/games/<int:game_id>/delete")
    @admin_required
    def admin_game_delete(game_id):
        if not valid_csrf():
            abort(400)
        game = get_db().execute("SELECT thumbnail_path, game_path FROM games WHERE id = ?", (game_id,)).fetchone()
        if game is None:
            abort(404)
        get_db().execute("DELETE FROM games WHERE id = ?", (game_id,))
        get_db().commit()
        delete_uploaded_thumbnail(game["thumbnail_path"])
        delete_uploaded_game(game["game_path"])
        flash("Game deleted.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/games/reorder")
    @admin_required
    def admin_game_reorder():
        if not valid_csrf():
            abort(400)
        try:
            game_id = int(request.form.get("game_id", ""))
            direction = request.form.get("direction")
        except ValueError:
            abort(400)
        if direction not in {"up", "down"}:
            abort(400)
        db = get_db()
        rows = db.execute("SELECT id, sort_order FROM games ORDER BY sort_order, id").fetchall()
        current = next((index for index, row in enumerate(rows) if row["id"] == game_id), None)
        target = current - 1 if direction == "up" and current is not None else current + 1 if current is not None else None
        if current is not None and target is not None and 0 <= target < len(rows):
            db.execute("UPDATE games SET sort_order=? WHERE id=?", (rows[current]["sort_order"], rows[target]["id"]))
            db.execute("UPDATE games SET sort_order=? WHERE id=?", (rows[target]["sort_order"], rows[current]["id"]))
            db.commit()
        return redirect(url_for("admin_dashboard"))

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_admin(username, password):
        username = username.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,80}", username):
            raise click.ClickException("Username must be 3-80 characters: letters, digits, dot, underscore, or hyphen.")
        if len(password) < 12:
            raise click.ClickException("Password must be at least 12 characters.")
        try:
            get_db().execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                             (username, generate_password_hash(password)))
            get_db().commit()
        except sqlite3.IntegrityError as exc:
            raise click.ClickException("That admin username already exists.") from exc
        click.echo(f"Administrator '{username}' created.")

    return app


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def init_db():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    db = get_db()
    db.executescript(schema)
    categories_seed = ["Puzzle", "Action", "Racing", "Arcade", "Adventure", "Brain Training"]
    for name in categories_seed:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        db.execute("INSERT OR IGNORE INTO categories (name, slug) VALUES (?, ?)", (name, slug))
    seed_games = [
        ("snake", "Snake Classic", "Guide the snake, eat the apples and grow longer. Don't hit the walls or yourself! Use arrow keys or swipe on mobile.", "Arcade", "games/snake.html", 1, 1, 0, 1, "🐍", "#34d399", "#059669"),
        ("memory-match", "Memory Match", "Flip the cards and find all the matching pairs in as few moves as possible. A great way to train your memory.", "Brain Training", "games/memory.html", 0, 1, 0, 1, "🧠", "#a78bfa", "#6d28d9"),
        ("whack-a-mole", "Whack-a-Mole", "Moles pop up everywhere! Tap or click as many as you can in 30 seconds.", "Action", "games/whack.html", 0, 1, 1, 1, "🔨", "#fb923c", "#dc2626"),
        ("2048", "2048", "Slide matching number tiles together to reach 2048. Use arrow keys or swipe on mobile.", "Puzzle", "games/2048.html", 0, 1, 1, 1, "🔢", "#71c9a2", "#168576"),
        ("tic-tac-toe", "Tic-Tac-Toe", "Take turns placing X and O. Be the first player to make a row of three.", "Puzzle", "games/tictactoe.html", 0, 0, 1, 1, "❌", "#a99cf4", "#5d58b7"),
        ("pong", "Pong", "Move your paddle and return the ball. First to five points wins. Use arrow keys, W/S, or touch controls.", "Arcade", "games/pong.html", 0, 1, 1, 1, "🏓", "#65d4c0", "#17888a"),
    ]
    for order, game in enumerate(seed_games, start=1):
        slug, title, description, category, path, featured, popular, is_new, published, emoji, color_a, color_b = game
        db.execute("""INSERT OR IGNORE INTO games (slug,title,description,category_id,game_path,featured,popular,is_new,published,sort_order,emoji,color_start,color_end)
            VALUES (?,?,?,(SELECT id FROM categories WHERE name=?),?,?,?,?,?,?,?,?,?)""",
            (slug, title, description, category, path, featured, popular, is_new, published, order, emoji, color_a, color_b))
    db.commit()


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def valid_csrf():
    supplied = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def get_game(slug):
    return get_db().execute("""SELECT g.*, c.name AS category, c.slug AS category_slug
        FROM games g JOIN categories c ON c.id=g.category_id WHERE g.slug=?""", (slug,)).fetchone()


def game_json(row):
    return {key: row[key] for key in ("slug", "title", "description", "category", "category_slug", "thumbnail_path", "game_path", "featured", "popular", "is_new", "published", "sort_order", "emoji", "color_start", "color_end")}


def categories():
    return get_db().execute("SELECT id, name FROM categories ORDER BY name").fetchall()


def parse_game_form(existing=None):
    slug = request.form.get("slug", "").strip().lower()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    try:
        category_id = int(request.form.get("category_id", ""))
    except ValueError:
        return "Choose a valid category."
    local_path = request.form.get("game_path", "").strip().replace("\\", "/")
    embed_url = request.form.get("embed_url", "").strip()
    game_upload = request.files.get("game_file")
    has_game_upload = bool(game_upload and game_upload.filename)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        return "Slug must use lowercase letters, numbers, and hyphens."
    if not title or len(title) > 100 or not description or len(description) > 1000:
        return "Title (1-100 characters) and description (1-1000 characters) are required."
    if get_db().execute("SELECT 1 FROM categories WHERE id=?", (category_id,)).fetchone() is None:
        return "Choose a valid category."
    if get_db().execute("SELECT 1 FROM games WHERE slug=? AND (? IS NULL OR id<>?)", (slug, existing["id"] if existing else None, existing["id"] if existing else None)).fetchone():
        return "That game slug is already in use."
    if sum((bool(local_path), bool(embed_url), has_game_upload)) > 1:
        return "Choose only one game source."

    game_data = None
    if embed_url:
        if not valid_embed_url(embed_url):
            return "Use an HTTPS embed URL on a domain configured in PLAYZONE_EMBED_HOSTS."
        game_path = embed_url
    elif has_game_upload:
        if Path(game_upload.filename).suffix.lower() != ".html":
            return "Upload a single .html game file."
        game_data = game_upload.stream.read(MAX_HTML_GAME_SIZE + 1)
        if len(game_data) > MAX_HTML_GAME_SIZE:
            return "HTML game files must be 10 MB or smaller."
        if not re.search(br"<!doctype\s+html|<html(?:\s|>)", game_data[:4096], re.IGNORECASE):
            return "The uploaded file does not look like an HTML document."
        game_path = ""
    elif local_path:
        if not re.fullmatch(r"games/[A-Za-z0-9_./-]+\.html", local_path):
            return "Choose an HTML file inside the games folder."
        resolved = (ROOT / local_path).resolve()
        if not is_within(resolved, (ROOT / "games").resolve()) or not resolved.is_file():
            return "The selected game file does not exist inside the games folder."
        game_path = local_path
    elif existing:
        game_path = existing["game_path"]
    else:
        return "Upload an HTML game, select a local game file, or use an allowed HTTPS embed URL."

    thumbnail = existing["thumbnail_path"] if existing else None
    upload = request.files.get("thumbnail")
    thumbnail_data = None
    thumbnail_extension = None
    if upload and upload.filename:
        extension = Path(upload.filename).suffix.lower()
        signature = IMAGE_SIGNATURES.get(extension)
        image_data = upload.stream.read(MAX_THUMBNAIL_SIZE + 1)
        if len(image_data) > MAX_THUMBNAIL_SIZE:
            return "Thumbnail files must be 2 MB or smaller."
        header = image_data[:12]
        valid_signature = signature and any(header.startswith(item) for item in signature)
        if extension == ".webp":
            valid_signature = header.startswith(b"RIFF") and header[8:12] == b"WEBP"
        if not valid_signature:
            return "Upload a valid PNG, JPG, GIF, or WebP image."
        thumbnail_data = image_data
        thumbnail_extension = extension
    elif request.form.get("remove_thumbnail") == "1":
        thumbnail = None

    if game_data is not None:
        safe_name = secure_filename(Path(game_upload.filename).stem)[:40] or "game"
        filename = f"{safe_name}-{secrets.token_hex(8)}.html"
        (ROOT / "static" / "game_uploads" / filename).write_bytes(game_data)
        game_path = f"game-uploads/{filename}"
    if thumbnail_data is not None:
        safe_name = secure_filename(Path(upload.filename).stem)[:40] or "game"
        filename = f"{safe_name}-{secrets.token_hex(8)}{thumbnail_extension}"
        (ROOT / "static" / "uploads" / filename).write_bytes(thumbnail_data)
        thumbnail = f"uploads/{filename}"
    flags = tuple(1 if request.form.get(field) == "on" else 0 for field in ("featured", "popular", "is_new", "published"))
    return (slug, title, description, category_id, thumbnail, game_path, *flags)


def valid_embed_url(value):
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port
    except (ValueError, UnicodeError):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and host in current_app.config["EMBED_HOSTS"]
    )


def delete_uploaded_thumbnail(path):
    if not path or not path.startswith("uploads/"):
        return
    target = (ROOT / "static" / path).resolve()
    if is_within(target, (ROOT / "static" / "uploads").resolve()) and target.is_file():
        target.unlink()


def delete_uploaded_game(path):
    if not path or not path.startswith("game-uploads/"):
        return
    filename = path.removeprefix("game-uploads/")
    target = (ROOT / "static" / "game_uploads" / filename).resolve()
    if is_within(target, (ROOT / "static" / "game_uploads").resolve()) and target.is_file():
        target.unlink()


def is_within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


app = create_app()


if __name__ == "__main__":
    app.run()

# PlayZone Gaming Portal

PlayZone now runs through Flask and SQLite. The original HTML game files remain in `games/`, and their game mechanics, keyboard/touch input, restart controls, and score messages are retained. Run the site through Flask rather than opening `index.html` directly so database-backed catalog, search, statistics, and leaderboard features work.

## Included games

The supplied project originally contained three playable games: Snake Classic, Memory Match, and Whack-a-Mole. Three more standalone games have been added: 2048, Tic-Tac-Toe, and Pong. The requested upload `playzone.zip` was not present in the workspace; the extracted project folder was used as the source. All six database entries point to playable game files; no fabricated leaderboard scores were added.

## Requirements and installation

Python 3.9 or newer is recommended. From PowerShell, run:

```powershell
cd C:\Users\DLC\Downloads\playzone\playzone
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Generate a secret key and replace `PLAYZONE_SECRET_KEY` in `.env`:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Set `PLAYZONE_SITE_URL` to the public HTTPS origin before deployment. To permit external game embeds, set `PLAYZONE_EMBED_HOSTS` to comma-separated exact hostnames you trust. The default SQLite database is `instance/playzone.sqlite3`; tables, indexes, categories, and all six games are initialized automatically on first startup. The `instance/` directory is created when needed.

## Create the first administrator

With the virtual environment active and `.env` configured, run:

```powershell
python -m flask --app app create-admin
```

Enter a username and a password of at least 12 characters when prompted. Passwords are stored as Werkzeug hashes. Sign in at `/admin/login`; do not put administrator credentials in source code or frontend files.

## Start the website

For local development:

```powershell
python -m flask --app app run
```

Open `http://127.0.0.1:5000`. Flask debug mode is off by default. For production, use a production WSGI server behind HTTPS, set a strong secret and `PLAYZONE_COOKIE_SECURE=1`, configure a trusted host/proxy boundary, and do not expose Flask's development server. The built-in login and score rate limits are process-local; use a shared limiter/store such as Redis when running multiple workers.

## Data and administration

- Public catalog, categories, search, game details, leaderboard, and sitemap read SQLite data.
- Game starts increment a play count. Scores include the game, a display name (default `Guest`), score, and timestamp.
- `/admin` requires a session authenticated with the password hash. All state-changing admin forms require a session CSRF token.
- Admins can add/edit/delete games, add/remove categories, upload/remove thumbnails, set featured/popular/new/published flags, and reorder entries.
- Admins can upload a single self-contained HTML game file up to 10 MB, select an existing `games/*.html` file, or use an HTTPS embed hosted on a domain listed in `PLAYZONE_EMBED_HOSTS`. Uploaded games are sandboxed; complex multi-file game bundles still need to be assembled into one HTML file or placed in `games/` by a developer.
- Thumbnail uploads are limited to 2 MB. Embed providers must be explicitly allowlisted in the private `.env` file; arbitrary domains and HTTP URLs are rejected.
- Admins can add new categories from the dashboard. A category with assigned games cannot be deleted until those games are moved or removed.
- Former empty ad boxes now contain real PlayZone game picks, instructions, category counts, or game stats. These are internal site links, not paid advertisements. Premium remains a future placeholder; no ad provider or payment flow is configured.

## Score limitations

The games execute in the browser. The server validates score types, size bounds, game publication, same-origin submissions when an Origin header is present, and submission rate, but it cannot independently prove gameplay or prevent a determined user from forging a plausible client score. Do not treat this leaderboard as fraud-resistant or prize-eligible without server-authoritative game logic and stronger abuse controls.

## Tests

Run the backend tests with:

```powershell
python -m unittest discover -s tests -v
```

The tests cover the database-backed catalog/search and game paths, score validation and persistence across app initialization, admin login and protection, CSRF rejection, and game add/edit/reorder/delete workflows.

## Project files

- `app.py`, `schema.sql`: Flask routes, authentication, API, and SQLite initialization.
- `templates/`: administrator pages rendered with Jinja.
- `css/`, `js/`, `games/`: original front end, three preserved games, and three added playable games, connected to the backend.
- `.env.example`: configuration template; keep the real `.env` private.
import re
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from werkzeug.security import generate_password_hash

from app import create_app, get_db


class PlayZoneTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp_dir.name) / "test.sqlite3")
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE": self.database,
            "SESSION_COOKIE_SECURE": False,
            "EMBED_HOSTS": ("games.example.test",),
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            get_db().execute(
                "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                ("test-admin", generate_password_hash("a-long-test-password")),
            )
            get_db().commit()

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf(self, response):
        token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(token)
        return token.group(1).decode()

    def login(self):
        page = self.client.get("/admin/login")
        return self.client.post("/admin/login", data={
            "csrf_token": self.csrf(page),
            "username": "test-admin",
            "password": "a-long-test-password",
        }, follow_redirects=True)

    def test_catalog_search_and_game_pages(self):
        response = self.client.get("/api/games?q=snake")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([game["slug"] for game in response.json], ["snake"])
        self.assertEqual(self.client.get("/api/games?category=arcade").json[0]["slug"], "snake")
        game_page = self.client.get("/game.html?id=snake")
        self.assertEqual(game_page.status_code, 200)
        game_page.close()
        game_file = self.client.get("/games/memory.html")
        self.assertEqual(game_file.status_code, 200)
        game_file.close()
        games = self.client.get("/api/games").json
        self.assertEqual(len(games), 6)
        self.assertEqual({game["slug"] for game in games}, {"snake", "memory-match", "whack-a-mole", "2048", "tic-tac-toe", "pong"})

    def test_seo_routes_and_security_headers(self):
        home = self.client.get("/")
        self.assertIn(b'rel="canonical" href="http://localhost/"', home.data)
        self.assertEqual(home.headers["X-Content-Type-Options"], "nosniff")
        home.close()
        robots = self.client.get("/robots.txt").get_data(as_text=True)
        self.assertIn("Disallow: /admin", robots)
        self.assertIn("http://localhost/sitemap.xml", robots)
        sitemap = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("game.html?id=snake", sitemap)
        self.assertIn("game.html?id=whack-a-mole", sitemap)
        self.assertIn("game.html?id=2048", sitemap)

    def test_score_validation_leaderboard_and_persistence(self):
        score = self.client.post("/api/scores", json={"game": "whack-a-mole", "player": "Player 1", "score": 24})
        self.assertEqual(score.status_code, 201)
        self.assertEqual(self.client.post("/api/scores", json={"game": "whack-a-mole", "score": 1001}).status_code, 400)
        self.assertEqual(self.client.post("/api/scores", json={"game": "snake", "score": True}).status_code, 400)
        self.assertEqual(self.client.post("/api/scores", json={"game": "tic-tac-toe", "score": 101}).status_code, 400)
        self.assertEqual(self.client.post("/api/scores", json={"game": "pong", "score": 6}).status_code, 400)
        self.assertEqual(self.client.post("/api/scores", json={"game": "2048", "score": 256}).status_code, 201)
        board = self.client.get("/api/leaderboard?game=whack-a-mole")
        self.assertEqual(board.json[0]["player_name"], "Player 1")
        restarted = create_app({"TESTING": True, "SECRET_KEY": "test-only-secret", "DATABASE": self.database})
        self.assertEqual(restarted.test_client().get("/api/leaderboard?game=whack-a-mole").json[0]["score"], 24)

    def test_admin_authentication_csrf_and_game_crud(self):
        self.assertEqual(self.client.get("/admin").status_code, 302)
        self.assertEqual(self.client.post("/admin/login", data={"username": "test-admin", "password": "bad"}).status_code, 400)
        dashboard = self.login()
        self.assertEqual(dashboard.status_code, 200)
        token = self.csrf(dashboard)
        category_id = next(row["id"] for row in self.client.get("/api/categories").json if row["slug"] == "arcade")
        payload = {
            "csrf_token": token,
            "slug": "test-snake",
            "title": "Test Snake",
            "description": "An admin-created catalog entry.",
            "category_id": str(category_id),
            "game_path": "games/snake.html",
            "popular": "on",
            "published": "on",
        }
        created = self.client.post("/admin/games/new", data=payload, follow_redirects=True)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(self.client.get("/api/games/test-snake").status_code, 200)
        with self.app.app_context():
            row = get_db().execute("SELECT id, sort_order FROM games WHERE slug='test-snake'").fetchone()
            game_id = row["id"]
        reordered = self.client.post("/admin/games/reorder", data={"csrf_token": token, "game_id": game_id, "direction": "up"})
        self.assertEqual(reordered.status_code, 302)
        payload.update({"csrf_token": token, "slug": "test-snake", "title": "Updated Snake"})
        payload.pop("published")
        edited = self.client.post(f"/admin/games/{game_id}/edit", data=payload, follow_redirects=True)
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(self.client.get("/api/games/test-snake").status_code, 404)
        self.assertEqual(self.client.post(f"/admin/games/{game_id}/delete", data={"csrf_token": token}).status_code, 302)
        self.assertEqual(self.client.get("/api/games/test-snake").status_code, 404)

    def test_admin_routes_reject_invalid_csrf(self):
        self.login()
        self.assertEqual(self.client.post("/admin/games/reorder", data={"game_id": 1, "direction": "up"}).status_code, 400)

    def test_admin_can_upload_html_game_and_delete_uploaded_file(self):
        self.login()
        dashboard = self.client.get("/admin")
        token = self.csrf(dashboard)
        self.assertIn(b"Categories", dashboard.data)
        game_form = self.client.get("/admin/games/new")
        self.assertEqual(game_form.status_code, 200)
        self.assertIn(b"Upload a single-file HTML5 game", game_form.data)
        self.assertIn(b"trusted HTTPS embed URL", game_form.data)
        category_id = next(row["id"] for row in self.client.get("/api/categories").json if row["slug"] == "arcade")
        response = self.client.post("/admin/games/new", data={
            "csrf_token": token,
            "slug": "uploaded-demo",
            "title": "Uploaded Demo",
            "description": "A test upload.",
            "category_id": str(category_id),
            "published": "on",
            "game_file": (BytesIO(b"<!doctype html><html><body><canvas>game</canvas></body></html>"), "demo.html"),
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        game = self.client.get("/api/games/uploaded-demo").json
        self.assertTrue(game["game_path"].startswith("game-uploads/"))
        file_response = self.client.get("/" + game["game_path"])
        self.assertEqual(file_response.status_code, 200)
        self.assertIn("sandbox allow-scripts", file_response.headers["Content-Security-Policy"])
        file_response.close()
        game_id = self.app.test_client().get("/api/games/uploaded-demo").status_code
        self.assertEqual(game_id, 200)
        with self.app.app_context():
            row = get_db().execute("SELECT id FROM games WHERE slug='uploaded-demo'").fetchone()
        deleted = self.client.post(f"/admin/games/{row['id']}/delete", data={"csrf_token": token})
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(self.client.get("/" + game["game_path"]).status_code, 404)

    def test_admin_can_manage_categories_and_reject_untrusted_embeds(self):
        self.login()
        dashboard = self.client.get("/admin")
        token = self.csrf(dashboard)
        created = self.client.post("/admin/categories/new", data={"csrf_token": token, "name": "Custom Mode"})
        self.assertEqual(created.status_code, 302)
        category = next(item for item in self.client.get("/api/categories").json if item["slug"] == "custom-mode")
        removed = self.client.post(f"/admin/categories/{category['id']}/delete", data={"csrf_token": token})
        self.assertEqual(removed.status_code, 302)
        self.assertNotIn("custom-mode", [item["slug"] for item in self.client.get("/api/categories").json])

        category_id = next(item["id"] for item in self.client.get("/api/categories").json if item["slug"] == "arcade")
        base = {"csrf_token": token, "slug": "remote-demo", "title": "Remote Demo", "description": "Trusted embed test.", "category_id": str(category_id), "published": "on"}
        rejected = self.client.post("/admin/games/new", data={**base, "embed_url": "https://untrusted.example/game"})
        self.assertEqual(rejected.status_code, 400)
        allowed = self.client.post("/admin/games/new", data={**base, "embed_url": "https://games.example.test/embed/demo"})
        self.assertEqual(allowed.status_code, 302)
        game = self.client.get("/api/games/remote-demo").json
        self.assertEqual(game["game_path"], "https://games.example.test/embed/demo")
        embedded_page = self.client.get("/game.html?id=remote-demo")
        self.assertEqual(embedded_page.status_code, 200)
        embedded_page.close()
        self.assertIn("https://games.example.test", allowed.headers.get("Content-Security-Policy", ""))
        with self.app.app_context():
            row = get_db().execute("SELECT id FROM games WHERE slug='remote-demo'").fetchone()
        self.client.post(f"/admin/games/{row['id']}/delete", data={"csrf_token": token})


if __name__ == "__main__":
    unittest.main()
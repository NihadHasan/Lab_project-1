PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    thumbnail_path TEXT,
    game_path TEXT NOT NULL,
    featured INTEGER NOT NULL DEFAULT 0 CHECK (featured IN (0, 1)),
    popular INTEGER NOT NULL DEFAULT 0 CHECK (popular IN (0, 1)),
    is_new INTEGER NOT NULL DEFAULT 0 CHECK (is_new IN (0, 1)),
    published INTEGER NOT NULL DEFAULT 1 CHECK (published IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    emoji TEXT NOT NULL DEFAULT '🎮',
    color_start TEXT NOT NULL DEFAULT '#11a8a1',
    color_end TEXT NOT NULL DEFAULT '#147d72',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    played_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    player_name TEXT NOT NULL DEFAULT 'Guest' CHECK (length(player_name) BETWEEN 1 AND 32),
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100000),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_games_public_order ON games(published, sort_order);
CREATE INDEX IF NOT EXISTS idx_games_category ON games(category_id, published);
CREATE INDEX IF NOT EXISTS idx_plays_game_date ON plays(game_id, played_at);
CREATE INDEX IF NOT EXISTS idx_scores_game_score ON scores(game_id, score DESC, created_at);
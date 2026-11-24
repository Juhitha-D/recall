"""SQLite storage. One file, no server, created automatically on first run."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from flask import current_app, g

from .srs import CardState

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decks (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    source_name TEXT,
    method      TEXT,            -- 'ai' | 'rules' | 'manual'
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    id         INTEGER PRIMARY KEY,
    deck_id    INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    front      TEXT NOT NULL,
    back       TEXT NOT NULL,
    ease       REAL NOT NULL DEFAULT 2.5,
    interval   INTEGER NOT NULL DEFAULT 0,
    reps       INTEGER NOT NULL DEFAULT 0,
    lapses     INTEGER NOT NULL DEFAULT 0,
    due        TEXT,             -- NULL = new card
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id             INTEGER PRIMARY KEY,
    card_id        INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating         TEXT NOT NULL,
    was_new        INTEGER NOT NULL,
    interval_after INTEGER NOT NULL,
    reviewed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cards_deck_due ON cards(deck_id, due);
CREATE INDEX IF NOT EXISTS idx_reviews_user_time ON reviews(user_id, reviewed_at);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)


def ts(dt: datetime) -> str:
    """Timestamps are stored as UTC ISO strings, which sort correctly as text."""
    return dt.isoformat(timespec="seconds")


def state_of(row: sqlite3.Row) -> CardState:
    due = datetime.fromisoformat(row["due"]) if row["due"] else None
    return CardState(ease=row["ease"], interval=row["interval"], reps=row["reps"], lapses=row["lapses"], due=due)

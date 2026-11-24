import io

from conftest import NOTES, Client


# ---------- accounts ----------
def test_register_login_logout(client):
    assert client.register().status_code == 302
    assert "Your decks" in client.get("/dashboard").get_data(as_text=True)
    client.post("/logout")
    assert client.get("/dashboard").status_code == 302  # back to login
    r = client.post("/login", {"email": "JUHITHA@example.com", "password": "correct-horse"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")


def test_registration_validation(client):
    assert "valid email" in client.post("/register", {"email": "nope", "password": "longenough"}).get_data(as_text=True)
    assert "at least 8" in client.post("/register", {"email": "a@b.co", "password": "short"}).get_data(as_text=True)
    client.register()
    client.post("/logout")
    assert "already exists" in client.register().get_data(as_text=True)


def test_wrong_password_does_not_reveal_which_part_was_wrong(client):
    client.register()
    client.post("/logout")
    a = client.post("/login", {"email": "juhitha@example.com", "password": "wrong-pass"}).get_data(as_text=True)
    b = client.post("/login", {"email": "nobody@example.com", "password": "wrong-pass"}).get_data(as_text=True)
    assert "Wrong email or password" in a and "Wrong email or password" in b


def test_passwords_are_hashed(app, client):
    client.register()
    import sqlite3
    row = sqlite3.connect(app.config["DATABASE"]).execute("SELECT password_hash FROM users").fetchone()
    assert "correct-horse" not in row[0] and row[0].startswith("scrypt:")


def test_login_next_cannot_redirect_offsite(client):
    client.register()
    client.post("/logout")
    r = client.post("/login?next=//evil.com", {"email": "juhitha@example.com", "password": "correct-horse"})
    assert r.headers["Location"].endswith("/dashboard")


def test_csrf_required(user):
    assert user.c.post("/decks/new", data={"text": NOTES}).status_code == 400
    assert user.c.post("/api/study/review", json={"card_id": 1, "rating": "good"}).status_code == 400


# ---------- decks & cards ----------
def test_create_deck_from_pasted_notes(user, deck_id):
    html = user.get(f"/decks/{deck_id}").get_data(as_text=True)
    assert "Networks" in html and "What is TCP?" in html


def test_create_deck_from_upload(user):
    data = {"file": (io.BytesIO(NOTES.encode()), "week-3-networks.md"), "count": "5"}
    r = user.post("/decks/new", data, content_type="multipart/form-data")
    assert r.status_code == 302
    assert "Week 3 Networks" in user.get(r.headers["Location"]).get_data(as_text=True)


def test_new_deck_errors(user):
    assert user.post("/decks/new", {"text": "too short"}).status_code == 400
    bad = {"file": (io.BytesIO(b"x"), "notes.exe")}
    assert user.post("/decks/new", bad, content_type="multipart/form-data").status_code == 400


def test_edit_add_delete_cards(user, deck_id, app):
    import sqlite3
    db = sqlite3.connect(app.config["DATABASE"])
    card_id, n = db.execute("SELECT MIN(id), COUNT(*) FROM cards").fetchone()
    user.post(f"/cards/{card_id}", {"front": "Edited Q", "back": "Edited A"})
    user.post(f"/decks/{deck_id}/cards", {"front": "Manual Q", "back": "Manual A"})
    user.post(f"/cards/{card_id}/delete")
    fronts = [r[0] for r in db.execute("SELECT front FROM cards")]
    assert "Manual Q" in fronts and "Edited Q" not in fronts and len(fronts) == n


def test_export_csv(user, deck_id):
    r = user.get(f"/decks/{deck_id}/export.csv")
    assert r.mimetype == "text/csv" and "What is TCP?" in r.get_data(as_text=True)


def test_delete_deck_removes_cards(user, deck_id, app):
    user.post(f"/decks/{deck_id}/delete")
    import sqlite3
    assert sqlite3.connect(app.config["DATABASE"]).execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0


def test_html_in_user_content_is_escaped(user, deck_id):
    user.post(f"/decks/{deck_id}/rename", {"title": "<script>alert(1)</script>"})
    html = user.get("/dashboard").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


# ---------- studying ----------
def test_study_flow(user, deck_id):
    first = user.get(f"/api/study/next?deck={deck_id}").get_json()
    assert first["done"] is False and first["card"]["is_new"]
    assert first["preview"]["good"] == "1d"
    new_before = first["counts"]["new"]

    r = user.api("/api/study/review", {"card_id": first["card"]["id"], "rating": "good"}).get_json()
    assert r["interval"] == 1
    after = user.get(f"/api/study/next?deck={deck_id}").get_json()
    assert after["counts"]["new"] == new_before - 1
    assert after["card"]["id"] != first["card"]["id"]


def test_again_brings_card_back_later_today(user, deck_id):
    card = user.get(f"/api/study/next?deck={deck_id}").get_json()["card"]
    user.api("/api/study/review", {"card_id": card["id"], "rating": "again"})
    html = user.get(f"/decks/{deck_id}").get_data(as_text=True)
    assert "0d" in html  # relearning, not pushed out to days


def test_daily_new_card_limit(app, user, deck_id):
    app.config["NEW_CARDS_PER_DAY"] = 2
    for _ in range(2):
        card = user.get("/api/study/next").get_json()["card"]
        user.api("/api/study/review", {"card_id": card["id"], "rating": "good"})
    assert user.get("/api/study/next").get_json()["done"] is True


def test_dashboard_stats_after_review(user, deck_id):
    card = user.get("/api/study/next").get_json()["card"]
    user.api("/api/study/review", {"card_id": card["id"], "rating": "good"})
    html = user.get("/dashboard").get_data(as_text=True)
    assert "day streak" in html and "1</b><span>reviews today" in html


def test_invalid_rating(user, deck_id):
    card = user.get("/api/study/next").get_json()["card"]
    assert user.api("/api/study/review", {"card_id": card["id"], "rating": "meh"}).status_code == 400


# ---------- privacy: users can't touch each other's data ----------
def test_users_cannot_access_each_others_decks(app, user, deck_id):
    import sqlite3
    card_id = sqlite3.connect(app.config["DATABASE"]).execute("SELECT MIN(id) FROM cards").fetchone()[0]
    other = Client(app.test_client())
    other.register("someone@example.com", "another-password")
    assert other.get(f"/decks/{deck_id}").status_code == 404
    assert other.get(f"/decks/{deck_id}/export.csv").status_code == 404
    assert other.get(f"/api/study/next?deck={deck_id}").status_code == 404
    assert other.post(f"/cards/{card_id}", {"front": "hacked", "back": "x"}).status_code == 404
    assert other.post(f"/decks/{deck_id}/delete").status_code == 404
    assert other.api("/api/study/review", {"card_id": card_id, "rating": "easy"}).status_code == 404
    assert other.get("/api/study/next").get_json()["done"] is True  # sees none of the first user's cards


def test_api_requires_login(client):
    assert client.get("/api/study/next").status_code == 401


def test_streak_counts_consecutive_local_days(app, user, deck_id):
    import sqlite3
    from datetime import timedelta

    from recall.db import ts
    from recall.srs import now
    db = sqlite3.connect(app.config["DATABASE"])
    card_id = db.execute("SELECT MIN(id) FROM cards").fetchone()[0]
    uid = db.execute("SELECT id FROM users").fetchone()[0]
    for days_ago in (0, 1, 2, 4):  # gap on day 3
        db.execute("INSERT INTO reviews (card_id, user_id, rating, was_new, interval_after, reviewed_at) "
                   "VALUES (?, ?, 'good', 0, 1, ?)", (card_id, uid, ts(now() - timedelta(days=days_ago))))
    db.commit()
    assert "<b>3</b><span>day streak" in user.get("/dashboard").get_data(as_text=True)

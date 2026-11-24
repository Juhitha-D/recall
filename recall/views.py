"""Pages and JSON endpoints: dashboard, decks, cards, studying, stats."""
from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from .auth import login_required
from .db import get_db, state_of, ts
from .extract import ExtractError, extract_text
from .generate import MAX_CARDS, generate_cards
from .generate import provider as ai_provider
from .srs import RATINGS, now, preview, review

bp = Blueprint("main", __name__)
MAX_FIELD = 2000


# ---------------------------------------------------------------- helpers
def owned_deck(deck_id: int):
    """Fetch a deck only if it belongs to the logged-in user; 404 otherwise."""
    deck = get_db().execute("SELECT * FROM decks WHERE id = ? AND user_id = ?", (deck_id, g.user["id"])).fetchone()
    if deck is None:
        abort(404)
    return deck


def owned_card(card_id: int):
    card = get_db().execute(
        "SELECT c.* FROM cards c JOIN decks d ON d.id = c.deck_id WHERE c.id = ? AND d.user_id = ?",
        (card_id, g.user["id"]),
    ).fetchone()
    if card is None:
        abort(404)
    return card


def _clean_field(name: str) -> str:
    return request.form.get(name, "").strip()[:MAX_FIELD]


def local_now() -> datetime:
    """'Today' follows this computer's clock, so days don't roll over at UTC midnight."""
    return now().astimezone()


def start_of_local_day() -> str:
    midnight = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    return ts(midnight.astimezone(timezone.utc))


def new_cards_left_today() -> int:
    start = start_of_local_day()
    done = get_db().execute(
        "SELECT COUNT(*) FROM reviews WHERE user_id = ? AND was_new = 1 AND reviewed_at >= ?", (g.user["id"], start)
    ).fetchone()[0]
    return max(0, current_app.config["NEW_CARDS_PER_DAY"] - done)


def stats() -> dict:
    db, uid, t = get_db(), g.user["id"], now()
    today = local_now().date()
    # Reviews are stored in UTC; group them by *local* calendar day.
    since = ts(t - timedelta(days=400))
    per_day = Counter(
        datetime.fromisoformat(r[0]).astimezone().date()
        for r in db.execute("SELECT reviewed_at FROM reviews WHERE user_id = ? AND reviewed_at >= ?", (uid, since))
    )
    # streak: consecutive days with at least one review, ending today (or yesterday, if not studied yet today)
    day = today if per_day[today] else today - timedelta(days=1)
    streak = 0
    while per_day[day]:
        streak += 1
        day -= timedelta(days=1)
    history = [{"day": (today - timedelta(days=i)).strftime("%a %d"), "count": per_day[today - timedelta(days=i)]}
               for i in range(13, -1, -1)]
    month = ts(t - timedelta(days=30))
    r = db.execute(
        "SELECT COUNT(*), SUM(rating != 'again') FROM reviews WHERE user_id = ? AND was_new = 0 AND reviewed_at >= ?",
        (uid, month)).fetchone()
    retention = round(100 * (r[1] or 0) / r[0]) if r[0] else None
    total = db.execute("SELECT COUNT(*) FROM reviews WHERE user_id = ?", (uid,)).fetchone()[0]
    peak = max((h["count"] for h in history), default=0)
    return {"streak": streak, "history": history, "peak": peak, "retention": retention, "total_reviews": total,
            "today": history[-1]["count"]}


# -------------------------------------------------------------- dashboard
@bp.get("/")
def index():
    return redirect(url_for("main.dashboard" if g.user else "auth.login"))


@bp.get("/dashboard")
@login_required
def dashboard():
    t = ts(now())
    decks = get_db().execute(
        """SELECT d.*, COUNT(c.id) AS total,
                  SUM(c.due IS NOT NULL AND c.due <= ?) AS due,
                  SUM(c.due IS NULL) AS new,
                  SUM(c.interval >= 21) AS mature
           FROM decks d LEFT JOIN cards c ON c.deck_id = d.id
           WHERE d.user_id = ? GROUP BY d.id ORDER BY d.created_at DESC""",
        (t, g.user["id"]),
    ).fetchall()
    return render_template("dashboard.html", decks=decks, stats=stats(), new_left=new_cards_left_today())


# ------------------------------------------------------------------ decks
@bp.route("/decks/new", methods=("GET", "POST"))
@login_required
def new_deck():
    if request.method == "POST":
        upload = request.files.get("file")
        pasted = request.form.get("text", "")
        title = _clean_field("title")
        try:
            limit = max(1, min(int(request.form.get("count", 20)), MAX_CARDS))
        except ValueError:
            limit = 20
        try:
            if upload and upload.filename:
                text, source = extract_text(upload.filename, upload.read()), upload.filename
            elif len(pasted.strip()) >= 50:
                text, source = pasted, "pasted notes"
            else:
                raise ExtractError("Upload a file or paste at least a few sentences of notes.")
        except ExtractError as e:
            flash(str(e), "error")
            return render_template("new_deck.html", ai=ai_provider(), max_cards=MAX_CARDS), 400

        cards, method = generate_cards(text, limit)
        if not cards:
            flash("Couldn't find anything to make cards from. Try longer notes, or add cards by hand.", "error")
            return render_template("new_deck.html", ai=ai_provider(), max_cards=MAX_CARDS), 400

        db = get_db()
        created = ts(now())
        title = title or source.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title()
        cur = db.execute("INSERT INTO decks (user_id, title, source_name, method, created_at) VALUES (?, ?, ?, ?, ?)",
                         (g.user["id"], title[:120], source[:200], method, created))
        db.executemany("INSERT INTO cards (deck_id, front, back, created_at) VALUES (?, ?, ?, ?)",
                       [(cur.lastrowid, c.front, c.back, created) for c in cards])
        db.commit()
        how = "AI" if method == "ai" else "the offline generator"
        flash(f"Made {len(cards)} cards with {how}. Check them over, edit anything that's off, then study!", "ok")
        return redirect(url_for("main.deck", deck_id=cur.lastrowid))
    return render_template("new_deck.html", ai=ai_provider(), max_cards=MAX_CARDS)


@bp.get("/decks/<int:deck_id>")
@login_required
def deck(deck_id: int):
    d = owned_deck(deck_id)
    cards = get_db().execute("SELECT * FROM cards WHERE deck_id = ? ORDER BY id", (deck_id,)).fetchall()
    due = sum(1 for c in cards if c["due"] and c["due"] <= ts(now()))
    return render_template("deck.html", deck=d, cards=cards, due=due)


@bp.post("/decks/<int:deck_id>/rename")
@login_required
def rename_deck(deck_id: int):
    owned_deck(deck_id)
    title = _clean_field("title")[:120]
    if title:
        get_db().execute("UPDATE decks SET title = ? WHERE id = ?", (title, deck_id))
        get_db().commit()
    return redirect(url_for("main.deck", deck_id=deck_id))


@bp.post("/decks/<int:deck_id>/delete")
@login_required
def delete_deck(deck_id: int):
    d = owned_deck(deck_id)
    get_db().execute("DELETE FROM decks WHERE id = ?", (deck_id,))
    get_db().commit()
    flash(f"Deleted “{d['title']}”.", "ok")
    return redirect(url_for("main.dashboard"))


@bp.get("/decks/<int:deck_id>/export.csv")
@login_required
def export_deck(deck_id: int):
    d = owned_deck(deck_id)
    rows = get_db().execute("SELECT front, back FROM cards WHERE deck_id = ? ORDER BY id", (deck_id,)).fetchall()
    buf = io.StringIO()
    csv.writer(buf).writerows([tuple(r) for r in rows])  # front,back: imports straight into Anki
    name = "".join(ch if ch.isalnum() else "-" for ch in d["title"]).strip("-").lower() or "deck"
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


# ------------------------------------------------------------------ cards
@bp.post("/decks/<int:deck_id>/cards")
@login_required
def add_card(deck_id: int):
    owned_deck(deck_id)
    front, back = _clean_field("front"), _clean_field("back")
    if front and back:
        get_db().execute("INSERT INTO cards (deck_id, front, back, created_at) VALUES (?, ?, ?, ?)",
                         (deck_id, front, back, ts(now())))
        get_db().commit()
    else:
        flash("A card needs both a question and an answer.", "error")
    return redirect(url_for("main.deck", deck_id=deck_id) + "#add")


@bp.post("/cards/<int:card_id>")
@login_required
def edit_card(card_id: int):
    card = owned_card(card_id)
    front, back = _clean_field("front"), _clean_field("back")
    if front and back:
        get_db().execute("UPDATE cards SET front = ?, back = ? WHERE id = ?", (front, back, card_id))
        get_db().commit()
    return redirect(url_for("main.deck", deck_id=card["deck_id"]) + f"#card-{card_id}")


@bp.post("/cards/<int:card_id>/delete")
@login_required
def delete_card(card_id: int):
    card = owned_card(card_id)
    get_db().execute("DELETE FROM cards WHERE id = ?", (card_id,))
    get_db().commit()
    return redirect(url_for("main.deck", deck_id=card["deck_id"]))


# --------------------------------------------------------------- studying
@bp.get("/study")
@bp.get("/study/<int:deck_id>")
@login_required
def study(deck_id: int | None = None):
    d = owned_deck(deck_id) if deck_id else None
    return render_template("study.html", deck=d)


def _next_card(deck_id: int | None):
    """Due reviews first (most overdue first), then new cards within today's limit."""
    db, t = get_db(), ts(now())
    scope, args = ("d.user_id = ?", [g.user["id"]])
    if deck_id:
        scope += " AND d.id = ?"
        args.append(deck_id)
    base = f"FROM cards c JOIN decks d ON d.id = c.deck_id WHERE {scope}"
    due_n = db.execute(f"SELECT COUNT(*) {base} AND c.due IS NOT NULL AND c.due <= ?", (*args, t)).fetchone()[0]
    new_total = db.execute(f"SELECT COUNT(*) {base} AND c.due IS NULL", args).fetchone()[0]
    new_n = min(new_total, new_cards_left_today())
    card = db.execute(f"SELECT c.*, d.title AS deck_title {base} AND c.due IS NOT NULL AND c.due <= ? "
                      "ORDER BY c.due LIMIT 1", (*args, t)).fetchone()
    if card is None and new_n:
        card = db.execute(f"SELECT c.*, d.title AS deck_title {base} AND c.due IS NULL ORDER BY c.id LIMIT 1",
                          args).fetchone()
    return card, {"due": due_n, "new": new_n}


@bp.get("/api/study/next")
@login_required
def api_next():
    deck_id = request.args.get("deck", type=int)
    if deck_id:
        owned_deck(deck_id)
    card, counts = _next_card(deck_id)
    if card is None:
        later = get_db().execute(
            "SELECT MIN(c.due) FROM cards c JOIN decks d ON d.id = c.deck_id WHERE d.user_id = ? AND c.due > ?",
            (g.user["id"], ts(now()))).fetchone()[0]
        return {"done": True, "counts": counts, "next_due": later}
    return {
        "done": False,
        "counts": counts,
        "card": {"id": card["id"], "front": card["front"], "back": card["back"], "deck": card["deck_title"],
                 "is_new": card["due"] is None},
        "preview": preview(state_of(card)),
    }


@bp.post("/api/study/review")
@login_required
def api_review():
    body = request.get_json(silent=True) or {}
    rating = body.get("rating")
    if rating not in RATINGS:
        return {"error": f"rating must be one of {sorted(RATINGS)}"}, 400
    card = owned_card(int(body.get("card_id", 0)))
    before = state_of(card)
    after = review(before, rating)
    db = get_db()
    db.execute("UPDATE cards SET ease = ?, interval = ?, reps = ?, lapses = ?, due = ? WHERE id = ?",
               (after.ease, after.interval, after.reps, after.lapses, ts(after.due), card["id"]))
    db.execute("INSERT INTO reviews (card_id, user_id, rating, was_new, interval_after, reviewed_at) "
               "VALUES (?, ?, ?, ?, ?, ?)",
               (card["id"], g.user["id"], rating, int(before.is_new), after.interval, ts(now())))
    db.commit()
    return {"ok": True, "interval": after.interval, "due": ts(after.due)}

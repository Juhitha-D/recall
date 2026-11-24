"""Accounts: register, log in, log out. Passwords are salted and hashed (scrypt)."""
from __future__ import annotations

import functools
import re

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, ts
from .srs import now

bp = Blueprint("auth", __name__)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


@bp.before_app_request
def load_user():
    uid = session.get("user_id")
    g.user = get_db().execute("SELECT id, email FROM users WHERE id = ?", (uid,)).fetchone() if uid else None


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return {"error": "Please log in"}, 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def _safe_next(target: str | None) -> str:
    # Only allow local paths, so ?next= can't send users to another site.
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.dashboard")


@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        error = None
        if not EMAIL.match(email):
            error = "Enter a valid email address."
        elif len(password) < MIN_PASSWORD:
            error = f"Password must be at least {MIN_PASSWORD} characters."
        elif get_db().execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            error = "An account with that email already exists."
        if error:
            flash(error, "error")
        else:
            db = get_db()
            cur = db.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, generate_password_hash(password), ts(now())),
            )
            db.commit()
            session.clear()
            session["user_id"] = cur.lastrowid
            return redirect(url_for("main.dashboard"))
    return render_template("auth.html", mode="register")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        # Same message either way, so the form doesn't reveal which emails exist.
        if user is None or not check_password_hash(user["password_hash"], request.form.get("password", "")):
            flash("Wrong email or password.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(_safe_next(request.args.get("next")))
    return render_template("auth.html", mode="login")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))

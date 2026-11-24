"""Recall: turn study notes into flashcards and remember them with spaced repetition."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import Flask, abort, request, session

from . import db
from .settings import load_dotenv

__version__ = "1.0.0"


def _secret_key(instance: Path) -> str:
    """Use SECRET_KEY from the environment, or create one and keep it in instance/."""
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    f = instance / "secret_key"
    if not f.exists():
        f.write_text(secrets.token_hex(32), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip()


def create_app(test_config: dict | None = None) -> Flask:
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    instance = Path(app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)
    app.config.update(
        DATABASE=str(instance / "recall.sqlite"),
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        NEW_CARDS_PER_DAY=int(os.getenv("NEW_CARDS_PER_DAY", 20)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    app.config.setdefault("SECRET_KEY", None)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = _secret_key(instance)

    db.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)

    # --- CSRF protection: every POST must carry the session's token ---
    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def check_csrf():
        if request.method == "POST" and not app.config.get("CSRF_DISABLED"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
                abort(400, "Your session expired - reload the page and try again.")

    from . import auth, views

    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)
    return app

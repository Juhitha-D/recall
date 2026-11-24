import re

import pytest

from recall import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite"), "SECRET_KEY": "test"})


class Client:
    """Test client that handles the CSRF token like a real browser would."""

    def __init__(self, flask_client):
        self.c = flask_client

    def token(self) -> str:
        html = self.c.get("/login").get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def get(self, *a, **kw):
        return self.c.get(*a, **kw)

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf_token", self.token())
        return self.c.post(url, data=data, **kw)

    def api(self, url, payload):
        return self.c.post(url, json=payload, headers={"X-CSRF-Token": self.token()})

    def register(self, email="juhitha@example.com", password="correct-horse"):
        return self.post("/register", {"email": email, "password": password})


@pytest.fixture
def client(app):
    return Client(app.test_client())


@pytest.fixture
def user(client):
    client.register()
    return client


NOTES = """TCP is a connection-oriented protocol that guarantees packets arrive in order.
UDP is a connectionless protocol that sends packets without checking whether they arrive.
DNS is the system that translates human-readable domain names into IP addresses.
Latency: the time it takes for a packet to travel from source to destination.
Before sending data, TCP performs a three-way handshake using SYN and ACK messages."""


@pytest.fixture
def deck_id(user):
    r = user.post("/decks/new", {"title": "Networks", "text": NOTES, "count": "10"})
    assert r.status_code == 302
    return int(r.headers["Location"].rsplit("/", 1)[1])

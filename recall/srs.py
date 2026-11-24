"""Spaced repetition scheduling: the SM-2 algorithm, implemented from scratch.

SM-2 (Piotr Wozniak, 1987) is the algorithm behind SuperMemo and, in a
modified form, Anki. Each card keeps:

    ease      how easy the card is for you (starts at 2.5, never below 1.3)
    interval  days until the next review
    reps      successful reviews in a row
    lapses    how many times you've forgotten it

After each review you rate your recall. A correct answer pushes the next
review further out (1 day, 6 days, then interval x ease). A failed answer
resets the streak and the card comes back in 10 minutes, so you relearn it
in the same session.

The four buttons map onto SM-2's 0-5 "quality" scale the way Anki does:
Again = 1 (forgot), Hard = 3, Good = 4, Easy = 5.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

RATINGS = {"again": 1, "hard": 3, "good": 4, "easy": 5}
MIN_EASE = 1.3
START_EASE = 2.5
RELEARN_DELAY = timedelta(minutes=10)
MAX_INTERVAL_DAYS = 365 * 3


@dataclass(frozen=True)
class CardState:
    ease: float = START_EASE
    interval: int = 0  # days
    reps: int = 0
    lapses: int = 0
    due: datetime | None = None  # None = new card, never studied

    @property
    def is_new(self) -> bool:
        return self.due is None


def now() -> datetime:
    return datetime.now(timezone.utc)


def _new_ease(ease: float, q: int) -> float:
    # The original SM-2 formula: q=5 raises ease by 0.1, q=4 keeps it,
    # q=3 lowers it by 0.14, failures lower it further.
    ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    return round(max(MIN_EASE, ease), 3)


def review(state: CardState, rating: str, at: datetime | None = None) -> CardState:
    """Return the card's new state after a review with the given rating."""
    if rating not in RATINGS:
        raise ValueError(f"rating must be one of {sorted(RATINGS)}")
    q = RATINGS[rating]
    at = at or now()
    ease = _new_ease(state.ease, q)

    if q < 3:  # forgot: reset streak, relearn soon
        return replace(state, ease=ease, interval=0, reps=0, lapses=state.lapses + 1, due=at + RELEARN_DELAY)

    if state.reps == 0:
        interval = 1 if q < 5 else 4  # "easy" on first sight skips ahead
    elif state.reps == 1:
        interval = 6
    else:
        interval = round(max(state.interval, 1) * ease)
        if q == 3:  # hard: grow more slowly than the formula
            interval = max(state.interval + 1, round(max(state.interval, 1) * 1.2))
    interval = min(interval, MAX_INTERVAL_DAYS)
    return replace(state, ease=ease, interval=interval, reps=state.reps + 1, due=at + timedelta(days=interval))


def preview(state: CardState) -> dict[str, str]:
    """Human label for when each button would schedule the card: {"good": "6d", ...}"""
    at = now()
    out = {}
    for rating in RATINGS:
        delta = review(state, rating, at).due - at
        out[rating] = humanize(delta)
    return out


def humanize(delta: timedelta) -> str:
    mins = delta.total_seconds() / 60
    if mins < 60:
        return f"{round(mins)}m"
    days = delta.days
    if days < 30:
        return f"{max(days, 1)}d"
    if days < 365:
        return f"{round(days / 30)}mo"
    return f"{days / 365:.1f}y"

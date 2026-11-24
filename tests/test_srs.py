from datetime import datetime, timedelta, timezone

import pytest

from recall.srs import MIN_EASE, CardState, humanize, preview, review

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def test_good_answers_follow_sm2_intervals():
    s = CardState()
    s = review(s, "good", T0)
    assert (s.interval, s.reps) == (1, 1) and s.due == T0 + timedelta(days=1)
    s = review(s, "good", s.due)
    assert s.interval == 6
    s = review(s, "good", s.due)
    assert s.interval == round(6 * s.ease) == 15  # "good" keeps ease at 2.5


def test_again_resets_and_relearns_in_minutes():
    s = review(review(review(CardState(), "good", T0), "good", T0), "good", T0)
    failed = review(s, "again", T0)
    assert failed.reps == 0 and failed.lapses == 1 and failed.interval == 0
    assert failed.due == T0 + timedelta(minutes=10)
    assert failed.ease < s.ease


def test_easy_raises_ease_and_skips_ahead():
    s = review(CardState(), "easy", T0)
    assert s.interval == 4 and s.ease == pytest.approx(2.6)


def test_hard_grows_slower_than_good():
    s = review(review(CardState(), "good", T0), "good", T0)  # interval 6
    assert review(s, "hard", T0).interval < review(s, "good", T0).interval


def test_ease_never_drops_below_minimum():
    s = CardState()
    for _ in range(20):
        s = review(s, "again", T0)
    assert s.ease == MIN_EASE


def test_rejects_unknown_rating():
    with pytest.raises(ValueError):
        review(CardState(), "maybe", T0)


def test_preview_labels():
    p = preview(CardState())
    assert p == {"again": "10m", "hard": "1d", "good": "1d", "easy": "4d"}


@pytest.mark.parametrize("delta,label", [
    (timedelta(minutes=10), "10m"), (timedelta(days=6), "6d"), (timedelta(days=60), "2mo"), (timedelta(days=730), "2.0y"),
])
def test_humanize(delta, label):
    assert humanize(delta) == label

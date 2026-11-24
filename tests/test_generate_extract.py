import io
from pathlib import Path

import pytest

from recall import generate
from recall.extract import ExtractError, chunks, clean, extract_text, split_sentences
from recall.generate import Card, dedupe, generate_cards, parse_cards, rule_cards

SAMPLE = (Path(__file__).parents[1] / "samples" / "how-the-internet-works.md").read_text(encoding="utf-8")


# ---------- extraction ----------
def test_clean_rejoins_hyphenated_words_and_drops_page_numbers():
    assert clean("connec-\ntion oriented\n\n12\n\nnext") == "connection oriented\n\nnext"


def test_split_sentences_handles_bullets_and_wrapped_lines():
    s = split_sentences("- First point is here.\n- Second point\ncontinues here. Third one.")
    assert s == ["First point is here.", "Second point continues here.", "Third one."]


def test_extract_txt_and_reject_others():
    assert extract_text("notes.txt", b"hello world") == "hello world"
    with pytest.raises(ExtractError):
        extract_text("notes.docx", b"data")
    with pytest.raises(ExtractError):
        extract_text("notes.txt", b"")


def test_extract_pdf():
    reportlab = pytest.importorskip("reportlab.pdfgen.canvas")
    buf = io.BytesIO()
    c = reportlab.Canvas(buf)
    c.drawString(72, 720, "TCP is a connection-oriented protocol.")
    c.save()
    assert "connection-oriented" in extract_text("lecture.pdf", buf.getvalue())


def test_bad_pdf_gives_friendly_error():
    with pytest.raises(ExtractError):
        extract_text("broken.pdf", b"%PDF-not really")


def test_chunks_split_long_text():
    text = "\n\n".join(["word " * 500] * 4)
    assert len(chunks(text, max_words=1200)) == 2


# ---------- rule-based cards ----------
def test_rule_cards_from_sample_notes():
    cards = rule_cards(clean(SAMPLE), 30)
    fronts = [c.front for c in cards]
    assert "What is TCP?" in fronts
    assert "What is the Internet?" in fronts
    assert "What is latency?" in fronts  # glossary line
    assert any("_____" in f for f in fronts)  # cloze cards too
    # no junk "terms" made from clauses
    assert not any(f.startswith(("What is If", "What is Data", "What is When")) for f in fronts)


def test_cloze_answers_are_specific_terms():
    for c in rule_cards(clean(SAMPLE), 30):
        if "_____" in c.front:
            assert c.back.lower() not in {"data", "network", "packet", "addresses", "destination"}


def test_dedupe_ignores_case_and_punctuation():
    assert len(dedupe([Card("What is TCP?", "a"), Card("what is tcp", "b")])) == 1


# ---------- AI cards ----------
def test_parse_cards_tolerates_fences_and_junk():
    raw = 'Here you go:\n```json\n[{"front": "Q1", "back": "A1"}, {"front": ""}, "junk", {"front": "Q2", "back": "A2"}]\n```'
    assert parse_cards(raw) == [Card("Q1", "A1"), Card("Q2", "A2")]


def test_generate_uses_ai_when_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(generate, "_call_llm", lambda p: '[{"front": "Why does TCP retransmit?", "back": "Lost packets."}]')
    cards, method = generate_cards(SAMPLE, 5)
    assert method == "ai" and cards[0].front == "Why does TCP retransmit?"


def test_generate_falls_back_when_ai_fails(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    def boom(_):
        raise ConnectionError

    monkeypatch.setattr(generate, "_call_llm", boom)
    cards, method = generate_cards(SAMPLE, 5)
    assert method == "rules" and 0 < len(cards) <= 5

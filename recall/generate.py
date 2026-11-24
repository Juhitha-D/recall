"""Generate flashcards from study notes.

With an API key (Claude, OpenAI, or any OpenAI-compatible server such as Groq
or a local Ollama) an LLM writes the cards. Without one, a rule-based
generator still produces useful cards:

- definition cards from sentences like "TCP is a protocol that ..."
- glossary cards from "Term: explanation" lines
- fill-in-the-blank (cloze) cards that hide a key term, chosen by TF-IDF
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import requests
from sklearn.feature_extraction.text import TfidfVectorizer

from .extract import chunks, split_sentences

MAX_CARDS = 60


@dataclass(frozen=True)
class Card:
    front: str
    back: str


# ---------------------------------------------------------------- LLM ----
SYSTEM = (
    "You write excellent flashcards for students. Rules: one fact per card; the question must "
    "make sense on its own, without the notes; answers short (under 25 words); prefer 'why' and "
    "'how' questions over trivia; use only facts stated in the notes; never invent facts."
)

PROMPT = """Write up to {n} flashcards from these study notes.
Return ONLY a JSON array like [{{"front": "question", "back": "answer"}}].

<notes>
{notes}
</notes>"""


def provider() -> str | None:
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return None


def _call_llm(prompt: str) -> str:
    if provider() == "anthropic":
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
            json={
                "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
                "max_tokens": 4000,
                "system": SYSTEM,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    r = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "temperature": 0.3,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def parse_cards(raw: str) -> list[Card]:
    """Pull a JSON array of cards out of model output, ignoring junk entries."""
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        raise ValueError("no JSON array in model output")
    cards = []
    for item in json.loads(m.group(0)):
        if isinstance(item, dict):
            front, back = str(item.get("front", "")).strip(), str(item.get("back", "")).strip()
            if front and back:
                cards.append(Card(front[:500], back[:1000]))
    return cards


def llm_cards(text: str, limit: int) -> list[Card]:
    pieces = chunks(text)
    per_piece = max(3, limit // len(pieces) + 1)
    cards: list[Card] = []
    for piece in pieces:
        cards += parse_cards(_call_llm(PROMPT.format(n=per_piece, notes=piece)))
        if len(cards) >= limit:
            break
    return cards


# ------------------------------------------------------- rule-based ----
_DEF = re.compile(
    r"^(?P<article>An?\s+|The\s+)?(?P<term>[A-Za-z][\w\-/() ]{1,60}?)\s+"
    r"(?P<verb>is|are|refers to|is defined as|means|describes)\s+(?P<rest>.+)$"
)
_GLOSSARY = re.compile(r"^(?P<term>[A-Z][\w\-/() ]{1,50}):\s+(?P<rest>.{10,})$")
_BAD_TERMS = {"it", "this", "that", "there", "these", "those", "they", "he", "she", "which", "what", "one", "here",
              "if", "when", "while", "because", "before", "after", "although", "since", "each", "every", "some"}
# Words that signal the "term" is really a clause ("Data sent across the Internet is ...")
_CLAUSE_WORDS = {"sent", "across", "by", "with", "from", "into", "for", "to", "when", "if", "that", "which", "using"}


def _ok_sentence(s: str) -> bool:
    words = len(s.split())
    return 5 <= words <= 45 and not s.endswith("?")


def _definition_card(s: str) -> Card | None:
    for pattern in (_GLOSSARY, _DEF):
        m = pattern.match(s)
        if not m:
            continue
        term = m.group("term").strip()
        rest = m.group("rest").strip().rstrip(".")
        words = term.split()
        if term.lower() in _BAD_TERMS or len(words) > 6 or len(rest.split()) < 3:
            continue
        if words[0].lower() in _BAD_TERMS or any(w.lower() in _CLAUSE_WORDS | {"is", "are", "was", "were"} for w in words):
            continue
        verb = m.groupdict().get("verb") or "is"
        # "X is a/an/the ..." reads as a definition; "X are 32 bits long" doesn't.
        if pattern is _DEF and verb in ("is", "are") and not re.match(r"(a|an|the|one)\b", rest, re.I):
            continue
        article = (m.groupdict().get("article") or "").strip().lower()
        if pattern is _GLOSSARY and not term.isupper():
            term = term[0].lower() + term[1:]  # "Latency:" -> "What is latency?"
        if article:
            term = f"{article} {term}"
        plural = verb == "are"
        q = f"What {'are' if plural else 'is'} {term}?" if verb in ("is", "are", "is defined as") else f"What does {term} {'mean' if verb == 'means' else 'refer to' if verb == 'refers to' else 'describe'}?"
        return Card(q, rest[0].upper() + rest[1:] + ".")
    return None


def _is_specific(term: str, text: str) -> bool:
    """Worth blanking out: a phrase, an acronym, a hyphenated or long technical word."""
    if " " in term or "-" in term:
        return True
    original = re.search(rf"\b{re.escape(term)}\b", text, re.I)
    return bool(original and re.search(r"[A-Z0-9]", original.group(0)[1:] or original.group(0)) and original.group(0) != original.group(0).capitalize())


def _key_terms(sentences: list[str], top: int) -> list[str]:
    if len(sentences) < 3:
        return []
    text = " ".join(sentences)
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), token_pattern=r"(?u)\b[A-Za-z][A-Za-z0-9\-]{2,}\b")
    m = vec.fit_transform(sentences)
    scores = m.sum(axis=0).A1
    terms = [t for _, t in sorted(zip(scores, vec.get_feature_names_out()), reverse=True)]
    # prefer 2-word terms, and drop single words that are part of a chosen phrase
    chosen: list[str] = []
    for t in terms:
        if not _is_specific(t, text) or any(t in c.split() or c in t.split() for c in chosen):
            continue
        chosen.append(t)
        if len(chosen) >= top:
            break
    return chosen


def rule_cards(text: str, limit: int) -> list[Card]:
    sentences = [s for s in split_sentences(text) if _ok_sentence(s) or _GLOSSARY.match(s)]
    cards: list[Card] = []
    used: set[int] = set()
    for i, s in enumerate(sentences):
        c = _definition_card(s)
        if c:
            cards.append(c)
            used.add(i)

    for term in _key_terms(sentences, top=limit):
        pat = re.compile(rf"\b{re.escape(term)}\b", re.I)
        for i, s in enumerate(sentences):
            if i in used or not _ok_sentence(s) or not s.endswith("."):
                continue
            m = pat.search(s)
            if m and m.start() > 0:  # blanking the first word makes a poor question
                cards.append(Card(pat.sub("_____", s, count=1), m.group(0)))
                used.add(i)
                break
    return cards[:limit]


# ------------------------------------------------------------ main ----
def dedupe(cards: list[Card]) -> list[Card]:
    seen, out = set(), []
    for c in cards:
        key = re.sub(r"\W+", " ", c.front.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(c)
    return out


def generate_cards(text: str, limit: int = 30) -> tuple[list[Card], str]:
    """Return (cards, method) where method is 'ai' or 'rules'."""
    limit = max(1, min(limit, MAX_CARDS))
    if provider():
        try:
            cards = dedupe(llm_cards(text, limit))[:limit]
            if cards:
                return cards, "ai"
        except Exception:
            pass  # network / quota / bad JSON: fall back to rules
    return dedupe(rule_cards(text, limit))[:limit], "rules"

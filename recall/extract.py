"""Turn uploaded study material (PDF, TXT, MD) into clean text."""
from __future__ import annotations

import io
import re

from pypdf import PdfReader

MAX_BYTES = 15 * 1024 * 1024
MAX_CHARS = 200_000  # roughly 60 pages of notes


class ExtractError(ValueError):
    pass


def extract_text(filename: str, data: bytes) -> str:
    if not data:
        raise ExtractError("The file is empty")
    if len(data) > MAX_BYTES:
        raise ExtractError("File is larger than 15 MB")
    name = filename.lower()
    if name.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            raise ExtractError(f"Could not read this PDF ({type(exc).__name__})") from exc
        text = "\n\n".join(pages)
        if len(text.strip()) < 20:
            raise ExtractError("This PDF has no selectable text. Is it a scanned image?")
    elif name.endswith((".txt", ".md", ".markdown")):
        text = data.decode("utf-8", errors="replace")
    else:
        raise ExtractError("Upload a .pdf, .txt or .md file")
    return clean(text)[:MAX_CHARS]


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join words hyphenated across lines
    text = re.sub(r"^\s*(page\s*)?\d+\s*(of\s*\d+)?\s*$", "", text, flags=re.I | re.M)  # page numbers
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    # Join lines inside a paragraph, but keep headings/bullets as their own lines.
    lines = []
    for para in re.split(r"\n\s*\n", text):
        para_lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        buf = ""
        for ln in para_lines:
            if re.match(r"^([-*•]|\d+[.)]|#)", ln) or (buf and buf.endswith((".", ":", "?", "!"))):
                if buf:
                    lines.append(buf)
                buf = ln
            else:
                buf = f"{buf} {ln}".strip()
        if buf:
            lines.append(buf)
    sentences = []
    for ln in lines:
        ln = re.sub(r"^([-*•]|\d+[.)]|#+)\s*", "", ln)
        sentences.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", ln) if s.strip())
    return sentences


def chunks(text: str, max_words: int = 1200) -> list[str]:
    """Split long notes into pieces an LLM can handle, on paragraph boundaries."""
    out, buf, count = [], [], 0
    for para in re.split(r"\n\s*\n", text):
        n = len(para.split())
        if buf and count + n > max_words:
            out.append("\n\n".join(buf))
            buf, count = [], 0
        buf.append(para)
        count += n
    if buf:
        out.append("\n\n".join(buf))
    return out

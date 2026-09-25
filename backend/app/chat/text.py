"""Plain-text helpers: scrubbing LLM text and e-mail detection."""

import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_TAG_RE = re.compile(r"<[^>\n]{0,80}>")
_MARKUP_CHARS = re.compile(r"[<>`{}\[\]\\|*#\x00-\x08\x0b-\x1f]")


def other_emails(message: str, own_email: str) -> list[str]:
    """E-mail addresses in ``message`` that are not the signed-in user's (case-insensitive)."""
    own = own_email.strip().casefold()
    return [m for m in EMAIL_RE.findall(message) if m.casefold() != own]


def scrub(text: str, max_len: int = 200) -> str:
    """Make model-written text safe to echo: no e-mail addresses, no markup, one line."""
    text = _TAG_RE.sub(" ", text)
    text = _MARKUP_CHARS.sub("", text)
    text = EMAIL_RE.sub("[email]", text)
    text = " ".join(text.split())
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def looks_like_plain_sentence(text: str, max_len: int) -> bool:
    """True when ``text`` is short, single-purpose plain prose (no markup, links or e-mail)."""
    if not text or len(text) > max_len:
        return False
    if _MARKUP_CHARS.search(text) or EMAIL_RE.search(text) or "http" in text.lower():
        return False
    return "\n" not in text

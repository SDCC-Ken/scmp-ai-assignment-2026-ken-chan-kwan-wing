"""Currency wording shared by the providers and the backend (HKD is the only accepted currency).

The company is in Hong Kong, so a bare ``$``, ``HK$``, ``HKD$``, "dollars" and "HK dollars" all
mean HKD. ``USD``, ``US$``, "US dollars" and every other explicit currency are returned as an
ISO-like code and rejected later by claim validation (no conversion, the user is asked for an
HKD amount).
"""

from __future__ import annotations

import re

HKD = "HKD"
USD = "USD"

_ALIASES = {
    "$": HKD,
    "HK$": HKD,
    "HKD$": HKD,
    "HK DOLLAR": HKD,
    "HK DOLLARS": HKD,
    "HONG KONG DOLLAR": HKD,
    "HONG KONG DOLLARS": HKD,
    "DOLLAR": HKD,
    "DOLLARS": HKD,
    "US$": USD,
    "USD$": USD,
    "US DOLLAR": USD,
    "US DOLLARS": USD,
    "AMERICAN DOLLAR": USD,
    "AMERICAN DOLLARS": USD,
    "RMB": "CNY",
}

_USD_WORDS = re.compile(r"\b(usd|us\$|u\.s\.|us dollars?|american dollars?)", re.IGNORECASE)
_HKD_WORDS = re.compile(r"\bhkd\b|hk\s?\$|hong kong dollars?|\bhk\s+dollars?", re.IGNORECASE)
_DOLLAR_WORDS = re.compile(r"\$|dollar", re.IGNORECASE)


def normalise_currency(value: object) -> str | None:
    """``"hk$"`` -> ``"HKD"``, ``"$"`` -> ``"HKD"``, ``"US dollars"`` -> ``"USD"``; anything else
    is upper-cased as written (``"eur"`` -> ``"EUR"``). Empty or non-text -> ``None``."""
    if value is None or isinstance(value, bool):
        return None
    text = " ".join(str(value).strip().upper().split())
    if not text:
        return None
    return _ALIASES.get(text, text)


def says_usd(message: str) -> bool:
    """The message explicitly names US dollars (``USD``, ``US$``, "US dollars")."""
    return _USD_WORDS.search(message) is not None


def says_hkd(message: str) -> bool:
    return _HKD_WORDS.search(message) is not None


def mentions_dollars(message: str) -> bool:
    """A ``$`` sign or the word "dollar(s)" (a bare one means HKD)."""
    return _DOLLAR_WORDS.search(message) is not None

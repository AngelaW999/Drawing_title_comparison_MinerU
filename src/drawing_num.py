from __future__ import annotations

import re
from typing import Optional

# Common dash characters seen in OCR/PDF text.
_DASH_CHARS = r"\-\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uFE63\uFF0D"

# Drawing number pattern (shared by index + drawing).
# Examples:
# - 50-S05791Z-T0101-024
# - 50-S06331(陕1)Z-T0101-001
_DRAWING_NUM_RE = re.compile(
    rf"\b50[{_DASH_CHARS}]"
    rf"(?:[0-9A-Za-z{_DASH_CHARS}]+|\([^()\s]+\))+"
    rf"\b",
    re.IGNORECASE,
)

_DASH_FIX_RE = re.compile(rf"[{_DASH_CHARS}]+")
_WS_RE = re.compile(r"\s+")


def normalize_drawing_num(s: str) -> str:
    """
    Normalize drawing number:
    - remove spaces
    - unify dashes to "-"
    """
    t = (s or "").strip()
    if not t:
        return ""
    t = _WS_RE.sub("", t)
    t = _DASH_FIX_RE.sub("-", t)
    return t


def extract_drawing_num(text: str | None) -> Optional[str]:
    """
    Find and normalize the first drawing number in text.
    """
    if not text:
        return None
    m = _DRAWING_NUM_RE.search(text)
    if not m:
        return None
    return normalize_drawing_num(m.group(0))


def is_drawing_num(text: str | None) -> bool:
    """
    True if the text is (only) a drawing number.
    """
    if not text:
        return False
    t = _WS_RE.sub("", text.strip())
    return bool(_DRAWING_NUM_RE.fullmatch(t))

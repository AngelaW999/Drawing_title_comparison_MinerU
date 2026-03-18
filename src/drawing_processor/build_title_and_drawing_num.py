# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import List, Tuple

from src.drawing_num import extract_drawing_num, is_drawing_num, normalize_drawing_num

__all__ = [
    "build_title_and_drawing_num_from_lines",
    "build_structured_title_from_lines",
    "split_title_marker_text",
]

_LABEL_RE = re.compile(r"(?:图\s*号|dwg\s*\.?\s*no\.?)", re.IGNORECASE)
_MD_PREFIX_RE = re.compile(r"^\s*(?:#+|\*+|-+|>+)\s*")
_TRAILING_INVIS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u00a0\u3000]+$")
_CIRCLED_MARK_RE = re.compile(r"([①②③④⑤⑥⑦⑧⑨])\s*$")
_TRAILING_MARKER_RE = re.compile(r"(?:(?<=\))|(?<=）))\s*([0-9]{1,3})\s*$")
_TRAILING_PAREN_MARKER_RE = re.compile(r"\((\d{1,3}|P\d{1,3})\)\s*$", re.IGNORECASE)

_CIRCLED_TO_INT = {
    "①": 1,
    "②": 2,
    "③": 3,
    "④": 4,
    "⑤": 5,
    "⑥": 6,
    "⑦": 7,
    "⑧": 8,
    "⑨": 9,
}


def _clean_line(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    t = _MD_PREFIX_RE.sub("", t).strip()
    t = _TRAILING_INVIS_RE.sub("", t).strip()
    return t.strip(" ,，；;")


def split_title_marker_text(text: str | None) -> Tuple[str | None, str | None]:
    t = (text or "").strip()
    if not t:
        return None, None

    m = _CIRCLED_MARK_RE.search(t)
    if m:
        marker = str(_CIRCLED_TO_INT.get(m.group(1)))
        title_main = t[: m.start()].rstrip()
        return title_main or None, marker

    m = _TRAILING_PAREN_MARKER_RE.search(t)
    if m:
        marker = m.group(1).upper()
        return t[: m.start()].rstrip() or None, marker

    m = _TRAILING_MARKER_RE.search(t)
    if m:
        marker = m.group(1)
        if marker.isdigit():
            value = int(marker)
            if 1 <= value <= 500:
                return t[: m.start()].rstrip() or None, str(value)

    return t, None


def build_structured_title_from_lines(lines: List[str]) -> Tuple[str | None, str | None, str | None]:
    cleaned = [_clean_line(x) for x in lines]
    cleaned = [x for x in cleaned if x]

    if not cleaned:
        return None, None, None

    drawing_num = None
    dn_idx = None

    for i, ln in enumerate(cleaned):
        dn = extract_drawing_num(ln)
        if dn:
            drawing_num = dn
            dn_idx = i
            break

    if drawing_num is None:
        cands = [ln for ln in cleaned if not _LABEL_RE.search(ln)]
        best = max(cands, key=len) if cands else cleaned[0]
        title_main, marker = split_title_marker_text(best)
        return None, title_main, marker

    title_lines: List[str] = []
    if dn_idx is not None:
        for j in range(dn_idx - 1, -1, -1):
            ln = cleaned[j]
            if not ln or _LABEL_RE.search(ln) or is_drawing_num(ln):
                continue
            title_lines.append(ln)
            if len(title_lines) >= 3:
                break
        title_lines.reverse()

    if not title_lines:
        cands = [
            ln for ln in cleaned if not _LABEL_RE.search(ln) and drawing_num not in normalize_drawing_num(ln)
        ]
        if cands:
            title_lines = [max(cands, key=len)]

    title = "".join(title_lines).strip() if title_lines else None
    title_main, marker = split_title_marker_text(title)
    return drawing_num, title_main, marker


def build_title_and_drawing_num_from_lines(lines: List[str]) -> Tuple[str | None, str | None]:
    drawing_num, title_main, marker = build_structured_title_from_lines(lines)
    if title_main and marker:
        return drawing_num, f"{title_main}({marker})"
    return drawing_num, title_main

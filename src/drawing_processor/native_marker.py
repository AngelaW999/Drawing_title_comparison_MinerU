from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import fitz  # PyMuPDF

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
_CIRCLED_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨]")
_DIGIT_RE = re.compile(r"\d{1,3}")
_P_MARKER_RE = re.compile(r"P\s*(\d{1,3})", re.IGNORECASE)
_FRACTION_RE = re.compile(r"\d+\s*/\s*\d+")


def _normalize_marker(text: str | None) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    m = re.fullmatch(r"P\s*(\d{1,3})", t, re.IGNORECASE)
    if m:
        value = int(m.group(1))
        if 1 <= value <= 500:
            return f"P{value}"
    if t.isdigit():
        value = int(t)
        if 1 <= value <= 500:
            return str(value)
    if len(t) == 1 and t in _CIRCLED_TO_INT:
        return str(_CIRCLED_TO_INT[t])
    return None


def _inner_clip(clip: fitz.Rect) -> fitz.Rect:
    return fitz.Rect(
        clip.x0 + clip.width * 0.15,
        clip.y0 + clip.height * 0.08,
        clip.x1 - clip.width * 0.20,
        clip.y1 - clip.height * 0.08,
    )


def _iter_word_candidates(page: fitz.Page, clip: fitz.Rect) -> List[Tuple[str, float, float, float, float, float]]:
    items: List[Tuple[str, float, float, float, float, float]] = []
    inner = _inner_clip(clip)
    for word in page.get_text("words", clip=clip) or []:
        x0, y0, x1, y1, text = word[:5]
        cx = (float(x0) + float(x1)) / 2.0
        cy = (float(y0) + float(y1)) / 2.0
        if not inner.contains(fitz.Point(cx, cy)):
            continue
        token = str(text or "").strip()
        if token:
            items.append((token, float(x0), float(y0), float(x1), float(y1), cy))
    return items


def _iter_char_candidates(page: fitz.Page, clip: fitz.Rect) -> List[Tuple[str, float, float, float, float, float]]:
    items: List[Tuple[str, float, float, float, float, float]] = []
    inner = _inner_clip(clip)
    raw = page.get_text("rawdict", clip=clip) or {}
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    bbox = ch.get("bbox")
                    text = str(ch.get("c") or "").strip()
                    if not bbox or not text:
                        continue
                    x0, y0, x1, y1 = [float(v) for v in bbox]
                    cx = (x0 + x1) / 2.0
                    cy = (y0 + y1) / 2.0
                    if inner.contains(fitz.Point(cx, cy)):
                        items.append((text, x0, y0, x1, y1, cy))
    return items


def _combine_adjacent_char_tokens(
    tokens: List[Tuple[str, float, float, float, float, float]]
) -> List[Tuple[str, float, float, float, float, float]]:
    if not tokens:
        return []

    ordered = sorted(tokens, key=lambda item: (round(item[5], 1), item[1], item[3]))
    combined: List[Tuple[str, float, float, float, float, float]] = []
    current_text = ""
    current_x0 = 0.0
    current_y0 = 0.0
    current_x1 = 0.0
    current_y1 = 0.0
    current_y = 0.0

    def flush() -> None:
        nonlocal current_text, current_x0, current_y0, current_x1, current_y1, current_y
        if current_text:
            combined.append((current_text, current_x0, current_y0, current_x1, current_y1, current_y))
        current_text = ""
        current_x0 = 0.0
        current_y0 = 0.0
        current_x1 = 0.0
        current_y1 = 0.0
        current_y = 0.0

    for text, x0, y0, x1, y1, cy in ordered:
        token = str(text or "").strip()
        if not token:
            continue
        if len(token) != 1 or not re.fullmatch(r"[0-9Pp]", token):
            flush()
            combined.append((token, x0, y0, x1, y1, cy))
            continue

        if not current_text:
            current_text = token
            current_x0 = x0
            current_y0 = y0
            current_x1 = x1
            current_y1 = y1
            current_y = cy
            continue

        same_line = abs(cy - current_y) <= 3.0
        gap = x0 - current_x1
        if same_line and gap <= 8.0:
            current_text += token
            current_x1 = x1
            current_y0 = min(current_y0, y0)
            current_y1 = max(current_y1, y1)
        else:
            flush()
            current_text = token
            current_x0 = x0
            current_y0 = y0
            current_x1 = x1
            current_y1 = y1
            current_y = cy

    flush()
    return combined


def _extract_candidates(
    tokens: List[Tuple[str, float, float, float, float, float]]
) -> List[Tuple[str, str, float, float, float, float]]:
    out: List[Tuple[str, str, float, float, float, float]] = []
    for token, x0, y0, x1, y1, _cy in tokens:
        if _FRACTION_RE.search(token):
            continue

        for ch in _CIRCLED_RE.findall(token):
            value = _normalize_marker(ch)
            if value:
                out.append((value, "circled", x0, y0, x1, y1))

        p_found = False
        for p_match in _P_MARKER_RE.findall(token):
            value = _normalize_marker(f"P{p_match}")
            if value:
                out.append((value, "p", x0, y0, x1, y1))
                p_found = True
        if p_found:
            continue

        if re.search(r"[A-Za-z]", token) and "P" not in token.upper():
            continue
        if "/" in token:
            continue
        for number in _DIGIT_RE.findall(token):
            value = _normalize_marker(number)
            if value:
                out.append((value, "number", x0, y0, x1, y1))
    return out


def _pick_best_candidate(
    candidates: List[Tuple[str, str, float, float, float, float]]
) -> Tuple[str, str, float, float, float, float] | None:
    if not candidates:
        return None
    priority = {"circled": 3, "p": 2, "number": 1}
    candidates.sort(key=lambda item: (priority.get(item[1], 0), item[4], len(item[0]), item[2]))
    return candidates[-1]


def extract_native_marker_info_from_pdf(pdf_path: Path, region: dict) -> Dict[str, float | str] | None:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return None

    try:
        with fitz.open(str(pdf_path)) as doc:
            if doc.page_count <= 0:
                return None
            page = doc[0]
            clip = fitz.Rect(
                float(region.get("x0", 0.0)),
                float(region.get("y0", 0.0)),
                float(region.get("x1", page.rect.width)),
                float(region.get("y1", page.rect.height)),
            )
            if clip.is_empty or clip.width <= 0 or clip.height <= 0:
                return None

            picked = _pick_best_candidate(_extract_candidates(_iter_word_candidates(page, clip)))
            if picked is None:
                picked = _pick_best_candidate(
                    _extract_candidates(_combine_adjacent_char_tokens(_iter_char_candidates(page, clip)))
                )
            if picked is None:
                return None

            value, kind, x0, y0, x1, y1 = picked
            return {
                "value": value,
                "kind": kind,
                "x0": round(x0, 2),
                "y0": round(y0, 2),
                "x1": round(x1, 2),
                "y1": round(y1, 2),
            }
    except Exception:
        return None

    return None


def extract_native_marker_from_pdf(pdf_path: Path, region: dict) -> str | None:
    info = extract_native_marker_info_from_pdf(pdf_path, region)
    if info is None:
        return None
    return str(info.get("value") or "").strip() or None

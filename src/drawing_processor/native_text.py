from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import fitz  # PyMuPDF


def _clip_from_region(page: fitz.Page, region: Dict[str, float | str]) -> fitz.Rect:
    return fitz.Rect(
        float(region.get("x0", 0.0)),
        float(region.get("y0", 0.0)),
        float(region.get("x1", page.rect.width)),
        float(region.get("y1", page.rect.height)),
    )


def extract_native_lines_from_pdf_region(pdf_path: Path, region: Dict[str, float | str]) -> List[str]:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return []

    try:
        with fitz.open(str(pdf_path)) as doc:
            if doc.page_count <= 0:
                return []
            page = doc[0]
            clip = _clip_from_region(page, region)
            if clip.is_empty or clip.width <= 0 or clip.height <= 0:
                return []

            grouped: Dict[Tuple[int, int], List[Tuple[int, float, float, str]]] = {}
            for word in page.get_text("words", clip=clip) or []:
                x0, y0, x1, y1, text, block_no, line_no, word_no = word[:8]
                token = str(text or "").strip()
                if not token:
                    continue
                grouped.setdefault((int(block_no), int(line_no)), []).append(
                    (int(word_no), float(x0), float(y0), token)
                )

            lines: List[Tuple[float, str]] = []
            for _, parts in grouped.items():
                parts.sort(key=lambda item: (item[0], item[1]))
                text = "".join(token for _, _, _, token in parts).strip()
                if not text:
                    continue
                y = min(item[2] for item in parts)
                lines.append((y, text))

            lines.sort(key=lambda item: item[0])
            return [text for _, text in lines]
    except Exception:
        return []

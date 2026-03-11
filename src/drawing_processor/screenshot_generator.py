# -*- coding: utf-8 -*-
# src/drawing_text_processor/screenshot_generator.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Union

import fitz  # PyMuPDF

DEFAULT_DPI = 300


class DrawingScreenshotGenerator:
    def __init__(self, dpi: int = DEFAULT_DPI):
        self.dpi = int(dpi)

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[2]

    def _output_dir(self) -> Path:
        out_dir = self._project_root() / ".cache" / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    @staticmethod
    def _safe_region(region: Dict, page: fitz.Page) -> fitz.Rect:
        x0 = float(region.get("x0", 0.0))
        y0 = float(region.get("y0", 0.0))
        x1 = float(region.get("x1", page.rect.width))
        y1 = float(region.get("y1", page.rect.height))

        x0 = max(0.0, min(x0, float(page.rect.width)))
        x1 = max(0.0, min(x1, float(page.rect.width)))
        y0 = max(0.0, min(y0, float(page.rect.height)))
        y1 = max(0.0, min(y1, float(page.rect.height)))

        if x0 >= x1 or y0 >= y1:
            raise ValueError(f"Invalid region after clamp: x0={x0},y0={y0},x1={x1},y1={y1}")

        return fitz.Rect(x0, y0, x1, y1)

    @staticmethod
    def _is_up_to_date(out_path: Path, pdf_path: Optional[Path]) -> bool:
        try:
            if not out_path.exists() or pdf_path is None or not pdf_path.exists():
                return False
            return out_path.stat().st_mtime >= pdf_path.stat().st_mtime
        except Exception:
            return False

    def generate(
        self,
        pdf_path: Union[str, Path],
        region: Dict,
        *,
        page: Optional[fitz.Page] = None,
    ) -> str:
        """Generate (or reuse) a title-region screenshot.

        Optimization:
        - if caller already opened the PDF, pass `page=doc[0]` to avoid re-open.
        """
        try:
            pdf_path = Path(pdf_path).expanduser().resolve()
            if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
                return ""

            out_dir = self._output_dir()
            out_path = out_dir / f"{pdf_path.stem}_title.png"

            # Cache reuse
            if self._is_up_to_date(out_path, pdf_path):
                return str(out_path.resolve())

            zoom = self.dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)

            if page is not None:
                clip_rect = self._safe_region(region, page)
                pix = page.get_pixmap(matrix=mat, clip=clip_rect, alpha=False)
                pix.save(str(out_path))
                return str(out_path.resolve())

            # Fallback: open pdf
            with fitz.open(str(pdf_path)) as doc:
                if doc.page_count == 0:
                    return ""
                p0 = doc[0]
                clip_rect = self._safe_region(region, p0)
                pix = p0.get_pixmap(matrix=mat, clip=clip_rect, alpha=False)
                pix.save(str(out_path))
                return str(out_path.resolve())

        except Exception:
            return ""


screenshot_generator = DrawingScreenshotGenerator()
generate_title_screenshot = screenshot_generator.generate

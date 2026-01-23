# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Dict, Union

import fitz  # PyMuPDF

# Bottom-right crop size (PDF points). Adjust if needed.
CROP_W = 275.0
CROP_H = 123.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class PDFRegionFinder:
    @staticmethod
    def find_title_box_to_right_edge(page: fitz.Page) -> Dict[str, float | str]:
        w = float(page.rect.width)
        h = float(page.rect.height)

        x1 = w
        y1 = h
        x0 = _clamp(w - CROP_W, 0.0, w)
        y0 = _clamp(h - CROP_H, 0.0, h)

        return {
            "x0": round(x0, 2),
            "y0": round(y0, 2),
            "x1": round(x1, 2),
            "y1": round(y1, 2),
            "type": "fixed_bottom_right",
            "error": "",
        }

    @classmethod
    def get_title_region(cls, pdf_or_page: Union[str, Path, fitz.Page]) -> Dict[str, float | str]:
        result: Dict[str, float | str] = {
            "x0": 0.0,
            "y0": 0.0,
            "x1": 0.0,
            "y1": 0.0,
            "type": "",
            "error": "",
        }

        try:
            if isinstance(pdf_or_page, fitz.Page):
                result.update(cls.find_title_box_to_right_edge(pdf_or_page))
                return result

            p = Path(pdf_or_page)
            if not p.exists():
                raise FileNotFoundError("文件不存在")
            if p.suffix.lower() != ".pdf":
                raise ValueError("非PDF文件")

            with fitz.open(str(p)) as doc:
                if doc.page_count <= 0:
                    raise RuntimeError("PDF无页面")
                result.update(cls.find_title_box_to_right_edge(doc[0]))

        except Exception as e:
            result["error"] = str(e)

        return result


pdf_region_finder = PDFRegionFinder()
find_title_box_to_right_edge = pdf_region_finder.find_title_box_to_right_edge
get_title_region = pdf_region_finder.get_title_region

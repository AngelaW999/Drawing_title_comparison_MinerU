# -*- coding: utf-8 -*-
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import fitz  # PyMuPDF
from PIL import Image
from src.drawing_num import extract_drawing_num

from .native_marker import extract_native_marker_info_from_pdf

CROP_W = 275.0
CROP_H = 123.0
MARKER_W = 84.0
MARKER_H = 48.0
MARKER_RIGHT_MARGIN = 26.0
MARKER_TOP_MARGIN = 8.0
MARKER_LEFT_EXPAND = 26.0
INNER_MARGIN_X = 8.0
INNER_MARGIN_TOP = 4.0
INNER_MARGIN_BOTTOM = 6.0
TITLE_TEXT_RIGHT_MARGIN = 12.0
TITLE_TEXT_MARKER_OVERLAP = 18.0
TITLE_TO_MARKER_PADDING = 8.0
TITLE_RIGHT_BORDER_PADDING = 0.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _build_region(x0: float, y0: float, x1: float, y1: float, region_type: str) -> Dict[str, float | str]:
    return {
        "x0": round(x0, 2),
        "y0": round(y0, 2),
        "x1": round(x1, 2),
        "y1": round(y1, 2),
        "type": region_type,
        "error": "",
    }


def _rect_from_region(region: Dict[str, float | str], page: fitz.Page) -> fitz.Rect:
    return fitz.Rect(
        float(region.get("x0", 0.0)),
        float(region.get("y0", 0.0)),
        float(region.get("x1", page.rect.width)),
        float(region.get("y1", page.rect.height)),
    )


class PDFRegionFinder:
    _layout_cache: Dict[tuple[str, int], Dict[str, Dict[str, float | str]]] = {}

    @staticmethod
    def _find_right_border_x(
        page: fitz.Page,
        title_region: Dict[str, float | str],
    ) -> Optional[float]:
        clip = _rect_from_region(title_region, page)
        x_min = clip.x1 - min(32.0, clip.width * 0.18)
        best_x: Optional[float] = None
        best_len = 0.0

        for drawing in page.get_drawings():
            for item in drawing.get("items", []):
                if not item or item[0] != "l":
                    continue
                p1, p2 = item[1], item[2]
                x0 = min(float(p1.x), float(p2.x))
                x1 = max(float(p1.x), float(p2.x))
                y0 = min(float(p1.y), float(p2.y))
                y1 = max(float(p1.y), float(p2.y))
                dx = x1 - x0
                dy = y1 - y0
                if dx > 1.5 or dy < clip.height * 0.45:
                    continue
                cx = (x0 + x1) / 2.0
                if cx < x_min or cx > clip.x1 + 2.0:
                    continue
                if y0 > clip.y0 + clip.height * 0.1 or y1 < clip.y1 - clip.height * 0.2:
                    continue
                if dy > best_len:
                    best_len = dy
                    best_x = cx

        return best_x

    @staticmethod
    def _find_marker_component_bounds(
        page: fitz.Page,
        title_region: Dict[str, float | str],
        right_border_x: float,
    ) -> Optional[Tuple[float, float, float, float]]:
        clip = _rect_from_region(title_region, page)
        scan_clip = fitz.Rect(
            max(clip.x0, clip.x0 + clip.width * 0.55),
            clip.y0,
            min(clip.x1, right_border_x - 2.0),
            min(clip.y1, clip.y0 + clip.height * 0.55),
        )
        if scan_clip.is_empty or scan_clip.width < 12 or scan_clip.height < 12:
            return None

        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=scan_clip, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("L")
        except Exception:
            return None

        width, height = img.size
        if width < 12 or height < 12:
            return None

        px = img.load()

        # Drop the thick right border first.
        crop_right = width
        for x in range(width - 1, max(width // 2, width - 48), -1):
            dark = 0
            for y in range(height):
                if px[x, y] < 80:
                    dark += 1
            if dark >= int(height * 0.75):
                crop_right = x
            else:
                break

        if crop_right < width - 2:
            img = img.crop((0, 0, max(1, crop_right - 2), height))
            width, height = img.size
            px = img.load()

        binary = img.point(lambda p: 0 if p < 210 else 255, mode="1").convert("L")
        bp = binary.load()
        visited = set()
        best_box = None
        best_score = None

        for y in range(height):
            for x in range(width):
                if bp[x, y] != 0 or (x, y) in visited:
                    continue
                stack = [(x, y)]
                visited.add((x, y))
                min_x = max_x = x
                min_y = max_y = y
                count = 0
                while stack:
                    cx, cy = stack.pop()
                    count += 1
                    min_x = min(min_x, cx)
                    max_x = max(max_x, cx)
                    min_y = min(min_y, cy)
                    max_y = max(max_y, cy)
                    for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                        if nx < 0 or ny < 0 or nx >= width or ny >= height:
                            continue
                        if bp[nx, ny] != 0 or (nx, ny) in visited:
                            continue
                        visited.add((nx, ny))
                        stack.append((nx, ny))

                box_w = max_x - min_x + 1
                box_h = max_y - min_y + 1
                if count < 20 or box_w < 8 or box_h < 8:
                    continue
                if box_h > height * 0.9 and box_w < width * 0.12:
                    continue

                # Prefer rounded, compact objects near the right side.
                area = box_w * box_h
                fill_ratio = count / max(1, area)
                aspect = box_w / max(1.0, box_h)
                cx = (min_x + max_x) / 2.0
                rightness = cx / max(1.0, width)
                score = (1.0 - abs(aspect - 1.0)) * 2.2 + rightness - abs(fill_ratio - 0.18) * 1.5
                if best_score is None or score > best_score:
                    best_score = score
                    best_box = (min_x, min_y, max_x, max_y)

        if best_box is None:
            return None

        min_x, min_y, max_x, max_y = best_box
        return (
            round(scan_clip.x0 + min_x / 2.0, 2),
            round(scan_clip.y0 + min_y / 2.0, 2),
            round(scan_clip.x0 + max_x / 2.0, 2),
            round(scan_clip.y0 + max_y / 2.0, 2),
        )

    @staticmethod
    def find_title_box_to_right_edge(page: fitz.Page) -> Dict[str, float | str]:
        w = float(page.rect.width)
        h = float(page.rect.height)

        x1 = w
        y1 = h
        x0 = _clamp(w - CROP_W, 0.0, w)
        y0 = _clamp(h - CROP_H, 0.0, h)
        return _build_region(x0, y0, x1, y1, "fixed_bottom_right")

    @staticmethod
    def find_marker_region_from_title_region(
        title_region: Dict[str, float | str],
        page: fitz.Page,
    ) -> Dict[str, float | str]:
        tx0 = float(title_region.get("x0", 0.0))
        ty0 = float(title_region.get("y0", 0.0))
        tx1 = float(title_region.get("x1", page.rect.width))
        ty1 = float(title_region.get("y1", page.rect.height))

        border_x = PDFRegionFinder._find_right_border_x(page, title_region)
        right_anchor = border_x if border_x is not None else tx1
        marker_bounds = PDFRegionFinder._find_marker_component_bounds(page, title_region, right_anchor)
        if marker_bounds is not None:
            marker_left_edge, marker_top_edge, marker_right_edge, marker_bottom_edge = marker_bounds
            x1 = _clamp(marker_right_edge + 4.0, tx0, min(tx1, right_anchor - 2.0))
            x0 = _clamp(marker_left_edge - 4.0, tx0, x1)
            x0 = _clamp(min(x0, x1 - 18.0), tx0, x1)
            y0 = _clamp(marker_top_edge - 4.0, ty0, ty1)
            y1 = _clamp(marker_bottom_edge + 4.0, y0, ty1)
        else:
            x1 = _clamp(right_anchor - MARKER_RIGHT_MARGIN, tx0, tx1)
            x0 = _clamp(x1 - MARKER_W, tx0, tx1)
            y0 = _clamp(ty0 + MARKER_TOP_MARGIN, ty0, ty1)
            y1 = _clamp(y0 + MARKER_H, ty0, ty1)
        return _build_region(x0, y0, x1, y1, "title_marker")

    @staticmethod
    def _find_title_divider(
        page: fitz.Page,
        title_region: Dict[str, float | str],
    ) -> Optional[Tuple[float, float, float]]:
        clip = _rect_from_region(title_region, page)
        min_len = clip.width * 0.45
        y_min = clip.y0 + clip.height * 0.08
        y_max = clip.y0 + clip.height * 0.45
        best: Optional[Tuple[float, float, float, float]] = None

        for drawing in page.get_drawings():
            for item in drawing.get("items", []):
                if not item or item[0] != "l":
                    continue
                p1, p2 = item[1], item[2]
                x0 = min(float(p1.x), float(p2.x))
                x1 = max(float(p1.x), float(p2.x))
                y0 = min(float(p1.y), float(p2.y))
                y1 = max(float(p1.y), float(p2.y))
                dx = x1 - x0
                dy = y1 - y0
                cy = (y0 + y1) / 2.0
                if dy > 1.2 or dx < min_len:
                    continue
                if x0 < clip.x0 or x1 > clip.x1:
                    continue
                if not (y_min <= cy <= y_max):
                    continue
                score = dx
                if best is None or score > best[3]:
                    best = (x0, cy, x1, score)

        if best is None:
            return None
        return best[0], best[1], best[2]

    @staticmethod
    def _find_drawing_num_bbox(
        page: fitz.Page,
        title_region: Dict[str, float | str],
    ) -> Optional[fitz.Rect]:
        clip = _rect_from_region(title_region, page)
        best: Optional[fitz.Rect] = None
        for word in page.get_text("words", clip=clip) or []:
            x0, y0, x1, y1, text = word[:5]
            if not extract_drawing_num(str(text or "").strip()):
                continue
            rect = fitz.Rect(float(x0), float(y0), float(x1), float(y1))
            if best is None or rect.width > best.width:
                best = rect
        return best

    @classmethod
    def find_layout_regions(
        cls,
        page: fitz.Page,
    ) -> Dict[str, Dict[str, float | str]]:
        title_region = cls.find_title_box_to_right_edge(page)
        marker_region = cls.find_marker_region_from_title_region(title_region, page)
        marker_info = None
        try:
            marker_info = extract_native_marker_info_from_pdf(Path(page.parent.name), marker_region)
        except Exception:
            marker_info = None
        clip = _rect_from_region(title_region, page)
        divider = cls._find_title_divider(page, title_region)
        drawing_num_bbox = cls._find_drawing_num_bbox(page, title_region)
        right_border_x = cls._find_right_border_x(page, title_region) or clip.x1

        if drawing_num_bbox is not None:
            drawing_top = max(clip.y0, drawing_num_bbox.y0 - INNER_MARGIN_BOTTOM)
        else:
            drawing_top = clip.y1 - clip.height * 0.28

        if divider is None:
            marker_left_hint = None
            if marker_info:
                try:
                    marker_left_hint = float(marker_info.get("x0", 0.0))
                except Exception:
                    marker_left_hint = None
            marker_guess = marker_region
            text_right = max(clip.x0 + 40.0, right_border_x - TITLE_RIGHT_BORDER_PADDING)
            if marker_left_hint:
                text_right = min(text_right, marker_left_hint - TITLE_TO_MARKER_PADDING)
            text_bottom = max(clip.y0 + 16.0, drawing_top - 4.0)
            return {
                "title_region": title_region,
                "title_part1_region": _build_region(
                    clip.x0 + INNER_MARGIN_X,
                    clip.y0 + INNER_MARGIN_TOP,
                    text_right,
                    text_bottom,
                    "title_part1_fallback",
                ),
                "title_part2_region": _build_region(0.0, 0.0, 0.0, 0.0, "empty"),
                "title_text_region": _build_region(
                    clip.x0 + INNER_MARGIN_X,
                    clip.y0 + INNER_MARGIN_TOP,
                    text_right,
                    text_bottom,
                    "title_text_fallback",
                ),
                "marker_region": marker_guess,
                "drawing_num_region": _build_region(
                    clip.x0 + INNER_MARGIN_X,
                    drawing_top,
                    clip.x1 - INNER_MARGIN_X,
                    clip.y1 - INNER_MARGIN_BOTTOM,
                    "drawing_num_fallback",
                ),
            }

        line_x0, line_y, line_x1 = divider
        text_x0 = clip.x0 + INNER_MARGIN_X
        top_y0 = clip.y0 + INNER_MARGIN_TOP
        top_y1 = max(top_y0 + 12.0, line_y - 4.0)
        bottom_y0 = min(max(line_y + 4.0, top_y1 + 2.0), drawing_top - 8.0)
        bottom_y1 = max(bottom_y0 + 12.0, drawing_top)
        marker_right = right_border_x - MARKER_RIGHT_MARGIN
        marker_left = max(
            line_x1 + 2.0,
            marker_right - MARKER_W,
        )
        text_x1_max = right_border_x - TITLE_RIGHT_BORDER_PADDING
        if marker_info:
            try:
                marker_left_real = float(marker_info.get("x0", 0.0))
                marker_right_real = float(marker_info.get("x1", 0.0))
            except Exception:
                marker_left_real = 0.0
                marker_right_real = 0.0
            if marker_left_real > 0.0:
                text_x1_max = min(text_x1_max, marker_left_real - TITLE_TO_MARKER_PADDING)
                marker_left = max(clip.x0, marker_left_real - 10.0)
            if marker_right_real > marker_left_real:
                marker_right = min(right_border_x - 8.0, marker_right_real + 10.0)
        else:
            marker_left = max(marker_left, marker_right - MARKER_W)
        text_x1 = max(text_x0 + 30.0, text_x1_max)

        adaptive_marker = _build_region(
            max(text_x1 + 2.0, marker_left),
            top_y0,
            marker_right,
            min(bottom_y1, top_y0 + MARKER_H + 10.0),
            "title_marker_adaptive",
        )

        return {
            "title_region": title_region,
            "title_part1_region": _build_region(text_x0, top_y0, text_x1, top_y1, "title_part1"),
            "title_part2_region": _build_region(text_x0, bottom_y0, text_x1, bottom_y1, "title_part2"),
            "title_text_region": _build_region(text_x0, top_y0, text_x1, bottom_y1, "title_text"),
            "marker_region": adaptive_marker,
            "drawing_num_region": _build_region(
                clip.x0 + INNER_MARGIN_X,
                drawing_top,
                clip.x1 - INNER_MARGIN_X,
                clip.y1 - INNER_MARGIN_BOTTOM,
                "drawing_num",
            ),
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
                raise FileNotFoundError("file does not exist")
            if p.suffix.lower() != ".pdf":
                raise ValueError("not a pdf file")

            with fitz.open(str(p)) as doc:
                if doc.page_count <= 0:
                    raise RuntimeError("pdf has no pages")
                result.update(cls.find_title_box_to_right_edge(doc[0]))

        except Exception as e:
            result["error"] = str(e)

        return result

    @classmethod
    def get_marker_region(cls, pdf_or_page: Union[str, Path, fitz.Page]) -> Dict[str, float | str]:
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
                result.update(cls.find_layout_regions(pdf_or_page)["marker_region"])
                return result

            p = Path(pdf_or_page)
            if not p.exists():
                raise FileNotFoundError("file does not exist")
            if p.suffix.lower() != ".pdf":
                raise ValueError("not a pdf file")

            with fitz.open(str(p)) as doc:
                if doc.page_count <= 0:
                    raise RuntimeError("pdf has no pages")
                result.update(cls.find_layout_regions(doc[0])["marker_region"])

        except Exception as e:
            result["error"] = str(e)

        return result

    @classmethod
    def get_layout_regions(cls, pdf_or_page: Union[str, Path, fitz.Page]) -> Dict[str, Dict[str, float | str]]:
        empty = {
            "title_region": _build_region(0.0, 0.0, 0.0, 0.0, "empty"),
            "title_part1_region": _build_region(0.0, 0.0, 0.0, 0.0, "empty"),
            "title_part2_region": _build_region(0.0, 0.0, 0.0, 0.0, "empty"),
            "title_text_region": _build_region(0.0, 0.0, 0.0, 0.0, "empty"),
            "marker_region": _build_region(0.0, 0.0, 0.0, 0.0, "empty"),
            "drawing_num_region": _build_region(0.0, 0.0, 0.0, 0.0, "empty"),
        }

        try:
            if isinstance(pdf_or_page, fitz.Page):
                return cls.find_layout_regions(pdf_or_page)

            p = Path(pdf_or_page)
            if not p.exists():
                raise FileNotFoundError("file does not exist")
            if p.suffix.lower() != ".pdf":
                raise ValueError("not a pdf file")

            try:
                key = (str(p.resolve()), int(p.stat().st_mtime_ns))
            except Exception:
                key = None
            if key is not None and key in cls._layout_cache:
                return deepcopy(cls._layout_cache[key])

            with fitz.open(str(p)) as doc:
                if doc.page_count <= 0:
                    raise RuntimeError("pdf has no pages")
                layout = cls.find_layout_regions(doc[0])
                if key is not None:
                    cls._layout_cache[key] = deepcopy(layout)
                return layout
        except Exception as e:
            for region in empty.values():
                region["error"] = str(e)
            return empty


pdf_region_finder = PDFRegionFinder()
find_title_box_to_right_edge = pdf_region_finder.find_title_box_to_right_edge
get_title_region = pdf_region_finder.get_title_region
get_marker_region = pdf_region_finder.get_marker_region
get_layout_regions = pdf_region_finder.get_layout_regions

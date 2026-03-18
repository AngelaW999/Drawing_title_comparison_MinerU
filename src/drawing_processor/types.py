from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DrawingResult:
    pdf_path: str
    drawing_num: str | None
    title: str | None
    title_main: str | None = None
    title_source: str | None = None
    marker: str | None = None
    title_image_path: str | None = None
    marker_image_path: str | None = None
    marker_source: str | None = None
    marker_native_result: str | None = None
    marker_mineru_result: str | None = None
    marker_mineru_raw: str | None = None
    marker_local_result: str | None = None
    mineru_used: bool = True
    ocr_count: int = 0
    ocr_steps: tuple[str, ...] = ()

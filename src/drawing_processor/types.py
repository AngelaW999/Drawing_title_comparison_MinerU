from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DrawingResult:
    pdf_path: str
    drawing_num: str | None
    title: str | None

    # 便于 debug（可选）
    title_image_path: str | None = None
    mineru_used: bool = True
# src/drawing_processor/extract_drawing_title.py（只贴需要替换/新增的部分）
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List

from src.ocr import MinerUClient, MinerUConfig, MinerUDocumentParser
from .types import DrawingResult
from .normalize_title import normalize_title
from src.ocr.token_provider import get_mineru_token

_DRAWING_NUM_RE = re.compile(r"\b50[-－—][A-Z0-9\-－—]+(?:-\d{3})?\b", re.IGNORECASE)
_DASH_FIX_RE = re.compile(r"[-－—]+")

def _normalize_dashes(s: str) -> str:
    return _DASH_FIX_RE.sub("-", s)

# ✅ 模块级缓存（关键）
_DRAWING_PARSER: MinerUDocumentParser | None = None

def _get_mineru_parser_for_drawing() -> MinerUDocumentParser:
    global _DRAWING_PARSER
    if _DRAWING_PARSER is not None:
        return _DRAWING_PARSER

    token = get_mineru_token()
    if not token:
        raise RuntimeError("MINERU_TOKEN is not set.")

    cfg = MinerUConfig(
        token=token,
        model_version="vlm",
        enable_table=False,
        enable_formula=False,
        language="ch",
        # ✅ 可选：适当放大 timeout（截图OCR通常快，但网络波动时更稳）
        timeout_sec=300.0,
        request_timeout_sec=60.0,
        max_retries=5,
        retry_backoff_sec=1.5,
        throttle_sec=0.15,
    )
    _DRAWING_PARSER = MinerUDocumentParser(MinerUClient(cfg))
    return _DRAWING_PARSER

def _pick_text_source(markdown: str | None, json_text: str | None) -> str:
    if markdown and markdown.strip():
        return markdown
    if json_text and json_text.strip():
        return json_text
    return ""

def _extract_lines(text: str) -> List[str]:
    raw_lines = [ln.strip() for ln in (text or "").splitlines()]
    return [ln for ln in raw_lines if ln and len(ln) > 1]

def generate_title_screenshot_compat(pdf_path: Path) -> Path:
    from . import region_selector
    from . import screenshot_generator
    region = region_selector.get_title_region(pdf_path)
    png_path = screenshot_generator.generate_title_screenshot(pdf_path, region)
    return Path(png_path)

def extract_drawing_title(pdf_path: Path) -> DrawingResult:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    title_png = generate_title_screenshot_compat(pdf_path)

    # ✅ 复用 parser（关键）
    parser = _get_mineru_parser_for_drawing()
    res = parser.parse_file(title_png)

    text = _pick_text_source(res.markdown, res.json_text)
    lines = _extract_lines(text)

    from .build_title_and_drawing_num import build_title_and_drawing_num_from_lines
    drawing_num, title = build_title_and_drawing_num_from_lines(lines)

    # ✅ trim：你说 drawing title 空格要去掉
    title = normalize_title((title or "").strip())

    return DrawingResult(
        pdf_path=str(pdf_path),
        drawing_num=(drawing_num or "").strip(),
        title=title,
        title_image_path=str(title_png),
        mineru_used=True,
    )
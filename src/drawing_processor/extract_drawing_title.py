from __future__ import annotations

import re
from pathlib import Path
from typing import List

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageStat

from src.drawing_num import extract_drawing_num
from src.ocr import MinerUClient, MinerUConfig, MinerUDocumentParser
from src.ocr.token_provider import get_mineru_token
from src.process_cache import register_cache_file

from .build_title_and_drawing_num import build_structured_title_from_lines, split_title_marker_text
from .native_marker import extract_native_marker_info_from_pdf
from .native_text import extract_native_lines_from_pdf_region
from .normalize_title import normalize_title
from .types import DrawingResult

_DRAWING_PARSER: MinerUDocumentParser | None = None
_TRAILING_JUNK_RE = re.compile(r"([A-Za-z]?\d{1,4})$")
_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_MD_PREFIX_RE = re.compile(r"^\s*(?:#+|\*+|-+|>+)\s*")
_LABEL_RE = re.compile(r"(?:图\s*号|dwg\s*\.?\s*no\.?)", re.IGNORECASE)
_LEADING_DOT_RE = re.compile(r"^[.。·•]+")
_SUSPECT_TEXT_RE = re.compile(r"[�]")
_CIRCLED_MARKER_RE = re.compile(r"[①-⑳]")
_P_MARKER_RE = re.compile(r"P\s*(\d{1,3})", re.IGNORECASE)
_DIGIT_MARKER_RE = re.compile(r"\d{1,3}")
_FRACTION_RE = re.compile(r"\((\d+)\s*/\s*(\d+)\)\s*$")
_LPAREN_COUNT_RE = re.compile(r"\(")
_RPAREN_COUNT_RE = re.compile(r"\)")
_MARKER_CANVAS = (84, 84)
_MARKER_TEMPLATE_CACHE: dict[str, Image.Image] = {}


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
    out: List[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = _IMAGE_REF_RE.sub("", line).strip()
        line = _MD_PREFIX_RE.sub("", line).strip()
        line = _LEADING_DOT_RE.sub("", line).strip()
        if not line:
            continue
        if line.startswith("images/") or line.startswith("./images/"):
            continue
        out.append(line)
    return out


def _normalize_marker(marker: str | None) -> str | None:
    if marker is None:
        return None
    t = str(marker).strip().upper()
    if not t:
        return None
    if t.startswith("P") and t[1:].isdigit():
        value = int(t[1:])
        if 1 <= value <= 500:
            return f"P{value}"
        return None
    if t.isdigit():
        value = int(t)
        if 1 <= value <= 500:
            return str(value)
    circled_map = {
        "①": "1",
        "②": "2",
        "③": "3",
        "④": "4",
        "⑤": "5",
        "⑥": "6",
        "⑦": "7",
        "⑧": "8",
        "⑨": "9",
        "⑩": "10",
        "⑪": "11",
        "⑫": "12",
        "⑬": "13",
        "⑭": "14",
        "⑮": "15",
        "⑯": "16",
        "⑰": "17",
        "⑱": "18",
        "⑲": "19",
        "⑳": "20",
    }
    if t in circled_map:
        return circled_map[t]
    return None


def _collect_title_candidate_lines(lines: List[str]) -> List[str]:
    cleaned: List[str] = []
    for line in lines:
        text = (line or "").strip()
        if not text or extract_drawing_num(text):
            continue
        text = _IMAGE_REF_RE.sub("", text).strip()
        text = _MD_PREFIX_RE.sub("", text).strip()
        text = _LEADING_DOT_RE.sub("", text).strip()
        if _LABEL_RE.search(text):
            continue
        if not text or text.startswith("images/") or text.startswith("./images/"):
            continue
        cleaned.append(text)
    return cleaned


def _pick_best_title_line(lines: List[str]) -> str | None:
    candidates = _collect_title_candidate_lines(lines)
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item.replace(" ", "")))


def _build_title_main_from_parts(part1_lines: List[str], part2_lines: List[str]) -> str | None:
    part1 = _pick_best_title_line(part1_lines)
    part2 = _pick_best_title_line(part2_lines)
    joined = "".join(item for item in [part1, part2] if item)
    if not joined:
        return None
    title_main, _marker = split_title_marker_text(joined)
    return title_main or joined


def _build_title_main_from_lines(lines: List[str]) -> str | None:
    cleaned = _collect_title_candidate_lines(lines)
    if not cleaned:
        return None
    joined = "".join(cleaned)
    title_main, _marker = split_title_marker_text(joined)
    return title_main or joined


def _clean_title_main_noise(title_main: str | None) -> str | None:
    t = (title_main or "").strip()
    if not t:
        return None
    t = _LEADING_DOT_RE.sub("", t).strip()

    m = _TRAILING_JUNK_RE.search(t)
    if m:
        junk = m.group(1)
        if any(ch.isdigit() for ch in junk):
            cleaned = t[: m.start()].rstrip()
            if cleaned:
                t = cleaned

    return normalize_title(t) or t


def _compose_title(title_main: str | None, marker: str | None) -> str | None:
    if title_main and marker:
        return normalize_title(f"{title_main}({marker})")
    return normalize_title(title_main)


def _ocr_image(
    parser: MinerUDocumentParser,
    image_path: Path,
    ocr_steps: List[str],
    step_name: str,
) -> List[str]:
    if not image_path or not image_path.is_file():
        return []
    ocr_steps.append(step_name)
    res = parser.parse_file(image_path)
    text = _pick_text_source(res.markdown, res.json_text)
    return _extract_lines(text)


def _ocr_raw_text(
    parser: MinerUDocumentParser,
    image_path: Path,
    ocr_steps: List[str],
    step_name: str,
) -> str:
    if not image_path or not image_path.is_file():
        return ""
    ocr_steps.append(step_name)
    res = parser.parse_file(image_path)
    return _pick_text_source(res.markdown, res.json_text)


def _prepare_marker_ocr_image(image_path: Path) -> Path:
    if not image_path or not image_path.is_file():
        return image_path

    try:
        with Image.open(image_path) as img:
            gray = img.convert("L")
            width, height = gray.size
            if width <= 8 or height <= 8:
                return image_path

            pixels = gray.load()

            crop_right = width
            scan_start = max(width // 2, width - 48)
            for x in range(width - 1, scan_start - 1, -1):
                dark = 0
                for y in range(height):
                    if pixels[x, y] < 80:
                        dark += 1
                if dark >= int(height * 0.75):
                    crop_right = x
                else:
                    break

            if crop_right < width - 2:
                gray = gray.crop((0, 0, max(1, crop_right - 2), height))
                width, height = gray.size
                pixels = gray.load()

            bbox = None
            for y in range(height):
                for x in range(width):
                    if pixels[x, y] < 220:
                        if bbox is None:
                            bbox = [x, y, x, y]
                        else:
                            bbox[0] = min(bbox[0], x)
                            bbox[1] = min(bbox[1], y)
                            bbox[2] = max(bbox[2], x)
                            bbox[3] = max(bbox[3], y)

            if bbox is None:
                return image_path

            pad_x = 10
            pad_y = 10
            x0 = max(0, bbox[0] - pad_x)
            y0 = max(0, bbox[1] - pad_y)
            x1 = min(width, bbox[2] + pad_x + 1)
            y1 = min(height, bbox[3] + pad_y + 1)
            cropped = gray.crop((x0, y0, x1, y1))

            scale = 3
            enlarged = cropped.resize((cropped.width * scale, cropped.height * scale), Image.Resampling.LANCZOS)

            out_path = image_path.with_name(f"{image_path.stem}_prep{image_path.suffix}")
            enlarged.save(out_path)
            register_cache_file(out_path)
            return out_path
    except Exception:
        return image_path


def _fallback_marker_region(title_region: dict) -> dict:
    tx0 = float(title_region.get("x0", 0.0))
    ty0 = float(title_region.get("y0", 0.0))
    tx1 = float(title_region.get("x1", tx0))
    ty1 = float(title_region.get("y1", ty0))
    width = max(24.0, tx1 - tx0)
    height = max(24.0, ty1 - ty0)
    x1 = tx1 - 18.0
    x0 = max(tx0 + width * 0.68, x1 - min(74.0, width * 0.24))
    y0 = ty0 + height * 0.06
    y1 = min(ty1, y0 + min(52.0, height * 0.42))
    return {"x0": round(x0, 2), "y0": round(y0, 2), "x1": round(x1, 2), "y1": round(y1, 2), "type": "marker_fallback"}


def _generate_marker_screenshot(pdf_path: Path, marker_region: dict, title_region: dict) -> Path:
    marker_png = generate_region_screenshot_compat(pdf_path, marker_region, "marker")
    if marker_png and marker_png.is_file():
        return marker_png
    fallback_region = _fallback_marker_region(title_region)
    return generate_region_screenshot_compat(pdf_path, fallback_region, "marker")


def _load_marker_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_candidates = [
        r"C:\Windows\Fonts\times.ttf",
        r"C:\Windows\Fonts\timesbd.ttf",
        r"C:\Windows\Fonts\cambria.ttc",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for font_path in font_candidates:
        try:
            return ImageFont.truetype(font_path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _normalize_marker_glyph(image: Image.Image) -> Image.Image | None:
    gray = image.convert("L")
    width, height = gray.size
    if width <= 8 or height <= 8:
        return None

    base_binary = gray.point(lambda p: 0 if p < 215 else 255, mode="1").convert("L")
    base_bbox = ImageOps.invert(base_binary).getbbox()
    if base_bbox is None:
        return None

    bx0, by0, bx1, by1 = base_bbox
    bw = max(2, bx1 - bx0)
    bh = max(2, by1 - by0)

    # Crop to the interior of the detected circle so outer ring and nearby noise do not dominate matching.
    inset_x = max(2, int(round(bw * 0.20)))
    inset_y = max(2, int(round(bh * 0.20)))
    ix0 = min(bx0 + inset_x, width - 2)
    iy0 = min(by0 + inset_y, height - 2)
    ix1 = max(ix0 + 2, min(bx1 - inset_x, width))
    iy1 = max(iy0 + 2, min(by1 - inset_y, height))
    inner = gray.crop((ix0, iy0, ix1, iy1))

    binary = inner.point(lambda p: 0 if p < 215 else 255, mode="1").convert("L")
    inverted = ImageOps.invert(binary)
    bbox = inverted.getbbox()
    if bbox is None:
        return None

    glyph = binary.crop(bbox)
    if glyph.width <= 1 or glyph.height <= 1:
        return None

    scale = min(
        (_MARKER_CANVAS[0] - 8) / max(1, glyph.width),
        (_MARKER_CANVAS[1] - 8) / max(1, glyph.height),
    )
    resized = glyph.resize(
        (max(1, int(round(glyph.width * scale))), max(1, int(round(glyph.height * scale)))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("L", _MARKER_CANVAS, 255)
    off_x = (_MARKER_CANVAS[0] - resized.width) // 2
    off_y = (_MARKER_CANVAS[1] - resized.height) // 2
    canvas.paste(resized, (off_x, off_y))
    return canvas


def _marker_template(label: str) -> Image.Image:
    cached = _MARKER_TEMPLATE_CACHE.get(label)
    if cached is not None:
        return cached

    canvas = Image.new("L", (180, 120), 255)
    draw = ImageDraw.Draw(canvas)
    font = _load_marker_font(72 if len(label) <= 2 else 60)
    try:
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        text_w = right - left
        text_h = bottom - top
        draw.text(((180 - text_w) / 2 - left, (120 - text_h) / 2 - top), label, fill=0, font=font)
    except Exception:
        draw.text((30, 20), label, fill=0, font=font)

    normalized = _normalize_marker_glyph(canvas) or Image.new("L", _MARKER_CANVAS, 255)
    _MARKER_TEMPLATE_CACHE[label] = normalized
    return normalized


def _marker_candidate_labels() -> List[str]:
    labels = [str(i) for i in range(1, 501)]
    labels.extend(f"P{i}" for i in range(1, 11))
    return labels


def _extract_marker_from_local_image(image_path: Path) -> str | None:
    if not image_path or not image_path.is_file():
        return None

    try:
        with Image.open(image_path) as img:
            glyph = _normalize_marker_glyph(img)
    except Exception:
        return None

    if glyph is None:
        return None

    best_label = None
    best_score = None
    for label in _marker_candidate_labels():
        template = _marker_template(label)
        diff = ImageChops.difference(glyph, template)
        stat = ImageStat.Stat(diff)
        score = stat.mean[0] / 255.0
        if best_score is None or score < best_score:
            best_score = score
            best_label = label

    if best_label is None or best_score is None:
        return None
    if best_score > 0.24:
        return None
    return _normalize_marker(best_label)


def _extract_marker_from_mineru_image(
    parser: MinerUDocumentParser,
    image_path: Path,
    ocr_steps: List[str] | None = None,
) -> tuple[str | None, str]:
    steps = ocr_steps if ocr_steps is not None else []
    raw_text = _ocr_raw_text(parser, image_path, steps, "marker")
    lines = _extract_lines(raw_text)
    return _extract_marker_from_lines(lines), raw_text


def _is_suspicious_native_line(text: str) -> bool:
    if not text:
        return True
    if _SUSPECT_TEXT_RE.search(text):
        return True
    if "images/" in text or "dwg.no" in text.lower():
        return True
    return False


def _native_title_available(lines: List[str], expected_count: int) -> bool:
    candidates = _collect_title_candidate_lines(lines)
    if len(candidates) < expected_count:
        return False
    return not any(_is_suspicious_native_line(line) for line in candidates[:expected_count])


def _has_unclosed_paren(text: str | None) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return len(_LPAREN_COUNT_RE.findall(t)) > len(_RPAREN_COUNT_RE.findall(t))


def _expand_region_right(region: dict, new_x1: float) -> dict:
    grown = dict(region)
    grown["x1"] = round(max(float(region.get("x1", 0.0)), float(new_x1)), 2)
    return grown


def _title_region_with_marker(region: dict, marker_region: dict) -> dict:
    marker_x1 = float(marker_region.get("x1", 0.0))
    if marker_x1 <= 0.0:
        return dict(region)
    return _expand_region_right(region, marker_x1)


def _extract_native_title_with_retry(
    pdf_path: Path,
    title_region: dict,
    part1_region: dict,
    part2_region: dict,
    title_text_region: dict,
    marker_region: dict,
    has_divider: bool,
) -> str | None:
    if has_divider:
        native_part1_lines = extract_native_lines_from_pdf_region(pdf_path, part1_region)
        native_part2_lines = extract_native_lines_from_pdf_region(
            pdf_path,
            _title_region_with_marker(part2_region, marker_region),
        )
        if _native_title_available(native_part1_lines, 1) and _native_title_available(native_part2_lines, 1):
            title_main = _build_title_main_from_parts(native_part1_lines, native_part2_lines)
            if title_main and not _has_unclosed_paren(title_main):
                return title_main

            marker_left = float(marker_region.get("x0", 0.0))
            expanded_x1 = max(float(part2_region.get("x1", 0.0)), marker_left - 2.0)
            if expanded_x1 > float(part2_region.get("x1", 0.0)):
                retry_part2_lines = extract_native_lines_from_pdf_region(
                    pdf_path,
                    _expand_region_right(part2_region, expanded_x1),
                )
                retry_title_main = _build_title_main_from_parts(native_part1_lines, retry_part2_lines)
                if retry_title_main and not _has_unclosed_paren(retry_title_main):
                    return retry_title_main
        return None

    native_title_lines = extract_native_lines_from_pdf_region(
        pdf_path,
        _title_region_with_marker(title_text_region, marker_region),
    )
    if not _native_title_available(native_title_lines, 1):
        return None

    title_main = _build_title_main_from_lines(native_title_lines)
    if title_main and not _has_unclosed_paren(title_main):
        return title_main

    marker_left = float(marker_region.get("x0", 0.0))
    expanded_x1 = max(float(title_text_region.get("x1", 0.0)), marker_left - 2.0)
    if expanded_x1 > float(title_text_region.get("x1", 0.0)):
        retry_lines = extract_native_lines_from_pdf_region(
            pdf_path,
            _expand_region_right(title_text_region, expanded_x1),
        )
        retry_title_main = _build_title_main_from_lines(retry_lines)
        if retry_title_main and not _has_unclosed_paren(retry_title_main):
            return retry_title_main
    return None


def _extract_marker_from_lines(lines: List[str]) -> str | None:
    for line in lines:
        text = (line or "").strip()
        if not text:
            continue
        circled = _CIRCLED_MARKER_RE.findall(text)
        if circled:
            marker = _normalize_marker(circled[-1])
            if marker:
                return marker

        p_matches = _P_MARKER_RE.findall(text)
        if p_matches:
            marker = _normalize_marker(f"P{p_matches[-1]}")
            if marker:
                return marker

        if "/" in text:
            continue
        digit_matches = _DIGIT_MARKER_RE.findall(text)
        if digit_matches:
            marker = _normalize_marker(digit_matches[-1])
            if marker:
                return marker
    return None


def generate_region_screenshot_compat(pdf_path: Path, region: dict, suffix: str) -> Path:
    from . import screenshot_generator

    png_path = screenshot_generator.generate_title_screenshot(pdf_path, region, suffix=suffix)
    return Path(png_path)


def collect_marker_diagnostics(pdf_path: Path) -> dict:
    pdf_path = Path(pdf_path)
    from . import region_selector

    layout = region_selector.get_layout_regions(pdf_path)
    marker_region = layout["marker_region"]
    marker_png = _generate_marker_screenshot(pdf_path, marker_region, layout["title_region"])
    marker_prep_png = _prepare_marker_ocr_image(marker_png)

    native_info = extract_native_marker_info_from_pdf(pdf_path, marker_region)
    native_value = None
    if native_info:
        native_value = _normalize_marker(str(native_info.get("value") or ""))

    mineru_value = None
    try:
        parser = _get_mineru_parser_for_drawing()
        mineru_value, mineru_raw = _extract_marker_from_mineru_image(parser, marker_prep_png)
    except Exception:
        mineru_value = None
        mineru_raw = ""

    return {
        "marker_image_path": str(marker_png) if marker_png else "",
        "marker_native_result": native_value or "",
        "marker_mineru_result": mineru_value or "",
        "marker_mineru_raw": mineru_raw or "",
        "marker_local_result": "",
    }


def extract_drawing_title(pdf_path: Path) -> DrawingResult:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    from . import region_selector

    layout = region_selector.get_layout_regions(pdf_path)
    title_region = layout["title_region"]
    part1_region = layout["title_part1_region"]
    part2_region = layout["title_part2_region"]
    title_text_region = layout["title_text_region"]
    marker_region = layout["marker_region"]
    drawing_num_region = layout["drawing_num_region"]

    parser = _get_mineru_parser_for_drawing()
    ocr_steps: List[str] = []

    has_divider = str(part2_region.get("type", "")) not in {"", "empty"}

    native_title_main = _extract_native_title_with_retry(
        pdf_path,
        title_region,
        part1_region,
        part2_region,
        title_text_region,
        marker_region,
        has_divider,
    )

    title_main = native_title_main
    title_source = "native" if native_title_main else None
    title_png = generate_region_screenshot_compat(pdf_path, title_region, "title")

    if not title_main:
        title_text_png = generate_region_screenshot_compat(
            pdf_path,
            _title_region_with_marker(title_text_region, marker_region),
            "title_text",
        )
        title_text_lines = _ocr_image(parser, title_text_png, ocr_steps, "title_text")
        title_main = _build_title_main_from_lines(title_text_lines)
        if title_main:
            title_source = "ocr"

        if has_divider and len(_collect_title_candidate_lines(title_text_lines)) < 2:
            part1_png = generate_region_screenshot_compat(pdf_path, part1_region, "title_part1")
            part2_png = generate_region_screenshot_compat(
                pdf_path,
                _title_region_with_marker(part2_region, marker_region),
                "title_part2",
            )
            part1_lines = _ocr_image(parser, part1_png, ocr_steps, "title_part1")
            part2_lines = _ocr_image(parser, part2_png, ocr_steps, "title_part2")
            split_title_main = _build_title_main_from_parts(part1_lines, part2_lines)
            if split_title_main:
                title_main = split_title_main
                title_source = "ocr"

    drawing_num = None
    marker = None
    marker_source = None
    marker_kind = None

    if not title_main:
        title_lines = _ocr_image(parser, title_png, ocr_steps, "title")
        drawing_num, fallback_title_main, marker = build_structured_title_from_lines(title_lines)
        title_main = fallback_title_main
        if title_main:
            title_source = "ocr"
        marker = _normalize_marker(marker)
        marker_source = "title_ocr" if marker else None

    title_main = _clean_title_main_noise(title_main)

    native_dn_lines = extract_native_lines_from_pdf_region(pdf_path, drawing_num_region)
    for line in native_dn_lines:
        drawing_num = extract_drawing_num(line) or drawing_num
        if drawing_num:
            break

    if not drawing_num:
        drawing_num_png = generate_region_screenshot_compat(pdf_path, drawing_num_region, "drawing_num")
        drawing_num_lines = _ocr_image(parser, drawing_num_png, ocr_steps, "drawing_num")
        for line in drawing_num_lines:
            drawing_num = extract_drawing_num(line)
            if drawing_num:
                break

    native_marker_info = extract_native_marker_info_from_pdf(pdf_path, marker_region)
    if native_marker_info:
        native_marker = _normalize_marker(str(native_marker_info.get("value") or ""))
        if native_marker:
            marker = native_marker
            marker_kind = str(native_marker_info.get("kind") or "").strip() or None
            marker_source = "marker_native"

    marker_native_result = None
    marker_mineru_result = None
    marker_mineru_raw = None
    marker_local_result = None

    if native_marker_info:
        marker_native_result = native_marker

    marker_png = _generate_marker_screenshot(pdf_path, marker_region, title_region)

    if marker_source != "marker_native" and marker_png and Path(marker_png).is_file():
        marker_ocr_png = _prepare_marker_ocr_image(marker_png)
        mineru_marker, mineru_raw = _extract_marker_from_mineru_image(parser, marker_ocr_png, ocr_steps)
        marker_mineru_result = mineru_marker
        marker_mineru_raw = (mineru_raw or "").strip() or None
        if mineru_marker:
            marker = mineru_marker
            marker_source = "marker_ocr"

    marker = marker if marker_source in {"marker_native", "marker_ocr"} else None
    marker_source = marker_source if marker else None

    title = _compose_title((title_main or "").strip() or None, marker)

    return DrawingResult(
        pdf_path=str(pdf_path),
        drawing_num=(drawing_num or "").strip(),
        title=title,
        title_main=(title_main or "").strip() or None,
        title_source=title_source,
        marker=marker,
        title_image_path=str(title_png),
        marker_image_path=str(marker_png) if marker_png else None,
        marker_source=marker_source,
        marker_native_result=marker_native_result,
        marker_mineru_result=marker_mineru_result,
        marker_mineru_raw=marker_mineru_raw,
        marker_local_result=marker_local_result,
        mineru_used=True,
        ocr_count=len(ocr_steps),
        ocr_steps=tuple(ocr_steps),
    )

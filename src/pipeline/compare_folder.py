from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from openpyxl import Workbook

from src.drawing_processor.extract_drawing_title import extract_drawing_title
from src.drawing_processor.normalize_title import normalize_title
from src.index_page_processor.extract_index_pairs import extract_index_pairs

LogCB = Callable[[str], None]


@dataclass
class ReviewItem:
    key: str
    diff_type: str
    pdf_path: str
    drawing_num: str
    index_title: str
    index_marker: str
    drawing_title: str
    drawing_marker: str
    title_source: str
    screenshot_path: str
    marker_screenshot_path: str = ""
    auto_selected: bool = False


_TRAILING_MARKER_TOKEN_RE = re.compile(r"\((P?\d{1,3})\)\s*$", re.IGNORECASE)
_INDEX_NOISE_CHAR_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff()./\-]+")


def _log(cb: LogCB | None, msg: str) -> None:
    if cb:
        cb(msg)


def _normalize_compare_text(text: str | None) -> str:
    return (normalize_title(text) or "").strip()


def _clean_index_title(title: str | None) -> str:
    text = (title or "").strip()
    if not text:
        return ""
    text = _INDEX_NOISE_CHAR_RE.sub("", text)
    return _normalize_compare_text(text)


def _split_last_marker_token(text: str | None) -> Tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "", ""
    m = _TRAILING_MARKER_TOKEN_RE.search(raw)
    if not m:
        return raw, ""
    marker = m.group(1).upper()
    main = raw[: m.start()].rstrip()
    return main, marker


def _pick_first_index_pdf(folder: Path) -> Tuple[Path, List[Path]]:
    pdfs = sorted([p for p in folder.glob("*.pdf") if p.is_file()], key=lambda p: p.name)
    if not pdfs:
        raise FileNotFoundError(f"No PDF files in folder: {folder}")
    return pdfs[0], pdfs[1:]


def build_review_items(
    folder: Path,
    max_drawings: Optional[int] = None,
    log_cb: LogCB | None = None,
) -> List[ReviewItem]:
    folder = Path(folder)
    index_pdf, drawing_pdfs = _pick_first_index_pdf(folder)

    _log(log_cb, f"[1/3] Index PDF: {index_pdf.name}")
    _log(log_cb, f"[1/3] Drawing PDFs: {len(drawing_pdfs)}")

    if max_drawings is not None:
        drawing_pdfs = drawing_pdfs[:max_drawings]
        _log(log_cb, f"[1/3] Max drawings applied: {len(drawing_pdfs)}")

    _log(log_cb, "[2/3] Extract index pairs (MinerU)...")
    pairs = extract_index_pairs(index_pdf)

    index_map: Dict[str, str] = {}
    for row in pairs:
        if not row or len(row) < 2:
            continue
        dn = (row[0] or "").strip()
        title = _clean_index_title(row[1] or "")
        if not dn:
            continue
        if dn not in index_map or len(title) > len(index_map[dn]):
            index_map[dn] = title

    _log(log_cb, f"[2/3] Index pairs: {len(index_map)}")
    _log(log_cb, "[3/3] Parse drawings...")

    items: List[ReviewItem] = []
    seen_dn: set[str] = set()
    for i, pdf in enumerate(drawing_pdfs, start=1):
        _log(log_cb, f"  - [{i}/{len(drawing_pdfs)}] {pdf.name}")
        dr = extract_drawing_title(pdf)
        ocr_count = int(getattr(dr, "ocr_count", 0) or 0)
        ocr_steps = list(getattr(dr, "ocr_steps", ()) or ())
        marker_source = (getattr(dr, "marker_source", "") or "").strip() or "none"
        _log(
            log_cb,
            f"    OCR: {ocr_count} time(s)"
            + (f" [{', '.join(ocr_steps)}]" if ocr_steps else "")
            + f"; marker={marker_source}",
        )

        pdf_path = (getattr(dr, "pdf_path", str(pdf)) or str(pdf)).strip()
        drawing_num = (getattr(dr, "drawing_num", "") or "").strip()
        screenshot_path = (getattr(dr, "title_image_path", "") or "").strip()
        marker_screenshot_path = (getattr(dr, "marker_image_path", "") or "").strip()
        drawing_title = _normalize_compare_text(getattr(dr, "title_main", "") or "")
        extracted_drawing_marker = (getattr(dr, "marker", "") or "").strip().upper()
        title_source = ((getattr(dr, "title_source", "") or "")).strip() or "unknown"
        diff_type = ""
        index_title = ""
        index_marker = ""
        drawing_marker = ""

        if not drawing_num:
            diff_type = "图纸未能提取"
        else:
            seen_dn.add(drawing_num)
            index_full = (index_map.get(drawing_num, "") or "").strip()
            if not index_full:
                diff_type = "目录缺失"
            else:
                index_title_raw, index_marker_raw = _split_last_marker_token(index_full)
                index_title = _normalize_compare_text(index_title_raw)
                index_marker = index_marker_raw.strip().upper()

                # If directory title has no marker, drawing defaults to no marker.
                drawing_marker = extracted_drawing_marker if index_marker else ""

                title_diff = index_title != drawing_title
                marker_diff = index_marker != drawing_marker
                if title_diff and marker_diff:
                    diff_type = "标题和marker不一致"
                elif title_diff:
                    diff_type = "标题不一致"
                elif marker_diff:
                    diff_type = "marker不一致"

        if diff_type:
            key = f"{drawing_num}||{Path(pdf_path).name}||{diff_type}"
            items.append(
                ReviewItem(
                    key=key,
                    diff_type=diff_type,
                    pdf_path=pdf_path,
                    drawing_num=drawing_num,
                    index_title=index_title,
                    index_marker=index_marker,
                    drawing_title=drawing_title,
                    drawing_marker=drawing_marker,
                    title_source=title_source,
                    screenshot_path=screenshot_path,
                    marker_screenshot_path=marker_screenshot_path if index_marker else "",
                    auto_selected=False,
                )
            )

    missing_drawings = sorted([dn for dn in index_map.keys() if dn not in seen_dn])
    for dn in missing_drawings:
        index_title_raw, index_marker_raw = _split_last_marker_token(index_map.get(dn, "") or "")
        key = f"{dn}||图纸缺失"
        items.append(
            ReviewItem(
                key=key,
                diff_type="图纸缺失",
                pdf_path="",
                drawing_num=dn,
                index_title=_normalize_compare_text(index_title_raw),
                index_marker=index_marker_raw.strip().upper(),
                drawing_title="",
                drawing_marker="",
                title_source="",
                screenshot_path="",
                marker_screenshot_path="",
                auto_selected=True,
            )
        )

    _log(log_cb, f"Diff items total: {len(items)}")
    return items


def write_final_excel(
    out_xlsx: Path,
    items: List[ReviewItem],
    selected_map: Dict[str, bool],
) -> int:
    out_xlsx = Path(out_xlsx)
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)

    header = [
        "PDF路径",
        "图号",
        "目录标题",
        "目录marker",
        "图纸标题",
        "图纸marker",
        "错误类型",
    ]

    rows: List[List[str]] = []
    for it in items:
        export_it = it.auto_selected or bool(selected_map.get(it.key, False))
        if not export_it:
            continue
        rows.append(
            [
                it.pdf_path,
                it.drawing_num,
                it.index_title,
                it.index_marker,
                it.drawing_title,
                it.drawing_marker,
                it.diff_type,
            ]
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "diffs"
    ws.append(header)
    for row in rows:
        ws.append(row)

    wb.save(out_xlsx)
    return len(rows)

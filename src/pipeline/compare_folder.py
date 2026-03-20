from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import fitz
from openpyxl import Workbook

from src.drawing_num import extract_drawing_num
from src.drawing_processor.extract_drawing_title import extract_drawing_title
from src.drawing_processor.normalize_title import normalize_title
from src.drawing_processor.region_selector import PDFRegionFinder
from src.index_page_processor.extract_index_pairs import extract_index_pairs
from src.process_cache import register_cache_file

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

@dataclass
class DrawingExportRecord:
    drawing_num: str
    title: str
    marker: str
    pdf_path: str


_LAST_EXPORT_RECORDS: List[DrawingExportRecord] = []



_TRAILING_MARKER_TOKEN_RE = re.compile(r"\(((?:P\d{1,4}|\d{1,4}[A-Z]?))\)\s*$", re.IGNORECASE)
_INDEX_NOISE_CHAR_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff()./\-、]+")


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


def _extract_drawing_num_from_page(page: fitz.Page) -> str:
    layout = PDFRegionFinder.get_layout_regions(page)
    region = layout["drawing_num_region"]
    clip = fitz.Rect(
        float(region.get("x0", 0.0)),
        float(region.get("y0", 0.0)),
        float(region.get("x1", page.rect.width)),
        float(region.get("y1", page.rect.height)),
    )
    if clip.is_empty or clip.width <= 0 or clip.height <= 0:
        return ""

    grouped: Dict[Tuple[int, int], List[Tuple[int, float, str]]] = {}
    for word in page.get_text("words", clip=clip) or []:
        x0, _y0, _x1, _y1, text, block_no, line_no, word_no = word[:8]
        token = str(text or "").strip()
        if not token:
            continue
        grouped.setdefault((int(block_no), int(line_no)), []).append((int(word_no), float(x0), token))

    for _, parts in grouped.items():
        parts.sort(key=lambda item: (item[0], item[1]))
        line = "".join(token for _, _, token in parts).strip()
        dn = extract_drawing_num(line)
        if dn:
            return dn
    return ""


def _detect_first_drawing_page(pdf_path: Path) -> int:
    with fitz.open(str(pdf_path)) as doc:
        if doc.page_count <= 1:
            raise ValueError("Single PDF mode requires at least 2 pages.")
        for page_index in range(doc.page_count):
            drawing_num = _extract_drawing_num_from_page(doc[page_index])
            if drawing_num:
                if page_index == 0:
                    raise ValueError("The first page looks like a drawing page; no leading index pages detected.")
                return page_index
    raise ValueError("Could not detect the first drawing page in the single PDF input.")


def _write_pdf_slice(src_pdf: Path, start_page: int, end_page: int, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(str(src_pdf)) as src:
        dst = fitz.open()
        dst.insert_pdf(src, from_page=start_page, to_page=end_page)
        dst.save(str(out_path))
        dst.close()
    register_cache_file(out_path)
    return out_path.resolve()


def _prepare_single_pdf_inputs(pdf_path: Path, log_cb: LogCB | None = None) -> Tuple[Path, List[Path]]:
    pdf_path = Path(pdf_path)
    drawing_start_page = _detect_first_drawing_page(pdf_path)
    with fitz.open(str(pdf_path)) as doc:
        total_pages = doc.page_count

    _log(log_cb, f"[1/3] Detected index pages: 1-{drawing_start_page}")
    _log(log_cb, f"[1/3] Detected drawing pages: {drawing_start_page + 1}-{total_pages}")

    base_dir = Path(".cache") / "session_inputs" / pdf_path.stem
    index_pdf = _write_pdf_slice(pdf_path, 0, drawing_start_page - 1, base_dir / f"{pdf_path.stem}__index.pdf")

    drawing_pdfs: List[Path] = []
    for page_index in range(drawing_start_page, total_pages):
        out_path = base_dir / f"{pdf_path.stem}__page_{page_index + 1:04d}.pdf"
        drawing_pdfs.append(_write_pdf_slice(pdf_path, page_index, page_index, out_path))

    return index_pdf, drawing_pdfs


def build_review_items(
    folder: Path,
    max_drawings: Optional[int] = None,
    log_cb: LogCB | None = None,
    input_mode: str = "folder",
) -> List[ReviewItem]:
    folder = Path(folder)
    if input_mode == "single_pdf":
        index_pdf, drawing_pdfs = _prepare_single_pdf_inputs(folder, log_cb=log_cb)
    else:
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
    export_records: List[DrawingExportRecord] = []
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

        if drawing_num:
            export_records.append(
                DrawingExportRecord(
                    drawing_num=drawing_num,
                    title=drawing_title,
                    marker=extracted_drawing_marker,
                    pdf_path=pdf_path,
                )
            )

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

    global _LAST_EXPORT_RECORDS
    _LAST_EXPORT_RECORDS = export_records

    _log(log_cb, f"Diff items total: {len(items)}")
    return items


def _export_first_col_value(pdf_path: str, input_mode: str) -> str:
    if input_mode != "single_pdf":
        return pdf_path
    name = Path(pdf_path).stem
    m = re.search(r"__page_(\d+)$", name)
    if m:
        return str(int(m.group(1)))
    return ""


def _compose_full_title(title: str, marker: str) -> str:
    title = (title or "").strip()
    marker = (marker or "").strip().upper()
    if title and marker:
        return f"{title}({marker})"
    return title


def _build_duplicate_rows(input_mode: str) -> List[List[str]]:
    rows: List[List[str]] = []

    drawing_num_groups: Dict[str, List[DrawingExportRecord]] = {}
    combo_groups: Dict[str, List[DrawingExportRecord]] = {}
    for rec in _LAST_EXPORT_RECORDS:
        if rec.drawing_num:
            drawing_num_groups.setdefault(rec.drawing_num, []).append(rec)
        combo = _compose_full_title(rec.title, rec.marker)
        if combo:
            combo_groups.setdefault(combo, []).append(rec)

    for drawing_num, group in drawing_num_groups.items():
        if len(group) < 2:
            continue
        row = [drawing_num, _compose_full_title(group[0].title, group[0].marker), "图号重复"]
        row.extend(_export_first_col_value(rec.pdf_path, input_mode) for rec in group)
        rows.append(row)

    for combo, group in combo_groups.items():
        if len(group) < 2:
            continue
        drawing_nums = " / ".join(rec.drawing_num for rec in group if rec.drawing_num)
        row = [drawing_nums, combo, "标题重复"]
        row.extend(_export_first_col_value(rec.pdf_path, input_mode) for rec in group)
        rows.append(row)

    return rows


def write_final_excel(
    out_xlsx: Path,
    items: List[ReviewItem],
    selected_map: Dict[str, bool],
    input_mode: str = "folder",
) -> int:
    out_xlsx = Path(out_xlsx)
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)

    first_col_title = "页码" if input_mode == "single_pdf" else "路径"
    header = [
        first_col_title,
        "图号",
        "目录标题",
        "目录分段号",
        "图纸标题",
        "图纸分段号",
        "错误类型",
    ]

    rows: List[List[str]] = []
    for it in items:
        export_it = it.auto_selected or bool(selected_map.get(it.key, False))
        if not export_it:
            continue
        rows.append(
            [
                _export_first_col_value(it.pdf_path, input_mode),
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

    duplicate_rows = _build_duplicate_rows(input_mode)
    if duplicate_rows:
        dup_ws = wb.create_sheet("重复")
        dup_ws.append(["重复图号", "标题", "重复类型", first_col_title, f"重复{first_col_title}"])
        for row in duplicate_rows:
            dup_ws.append(row)

    wb.save(out_xlsx)
    return len(rows)

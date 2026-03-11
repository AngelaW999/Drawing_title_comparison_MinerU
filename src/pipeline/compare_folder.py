from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from openpyxl import Workbook

from src.index_page_processor.extract_index_pairs import extract_index_pairs
from src.drawing_processor.extract_drawing_title import extract_drawing_title


LogCB = Callable[[str], None]


@dataclass
class ReviewItem:
    key: str
    diff_type: str  # 标题不一致 / 目录缺失 / 图纸未能提取 / 图纸缺失
    pdf_path: str
    drawing_num: str
    title_index: str
    title_drawing: str
    screenshot_path: str
    auto_selected: bool = False  # True => 不进人工复核，直接导出


def _log(cb: LogCB | None, msg: str) -> None:
    if cb:
        cb(msg)


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
    """
    生成“需要复核/导出”的条目集合：
      - 标题不一致 / 目录缺失 / 图纸未能提取 -> 进入人工复核（默认不勾）
      - 图纸缺失 -> 不用人工复核，auto_selected=True（直接导出）
    """
    folder = Path(folder)
    index_pdf, drawing_pdfs = _pick_first_index_pdf(folder)

    _log(log_cb, f"[1/3] Index PDF: {index_pdf.name}")
    _log(log_cb, f"[1/3] Drawing PDFs: {len(drawing_pdfs)}")

    if max_drawings is not None:
        drawing_pdfs = drawing_pdfs[:max_drawings]
        _log(log_cb, f"[1/3] Max drawings applied: {len(drawing_pdfs)}")

    # -------- index --------
    _log(log_cb, "[2/3] Extract index pairs (MinerU)...")
    pairs = extract_index_pairs(index_pdf)

    index_map: Dict[str, str] = {}
    for row in pairs:
        if not row or len(row) < 2:
            continue
        dn = (row[0] or "").strip()
        title = (row[1] or "").strip()
        if not dn:
            continue
        if dn not in index_map or len(title) > len(index_map[dn]):
            index_map[dn] = title

    _log(log_cb, f"[2/3] Index pairs: {len(index_map)}")

    # -------- drawings --------
    _log(log_cb, "[3/3] Parse drawings...")

    items: List[ReviewItem] = []
    seen_dn: set[str] = set()

    for i, pdf in enumerate(drawing_pdfs, start=1):
        _log(log_cb, f"  - [{i}/{len(drawing_pdfs)}] {pdf.name}")

        dr = extract_drawing_title(pdf)

        pdf_path = (getattr(dr, "pdf_path", str(pdf)) or str(pdf)).strip()
        drawing_num = (getattr(dr, "drawing_num", "") or "").strip()
        title_drawing = (getattr(dr, "title", "") or "").strip()
        screenshot_path = (getattr(dr, "title_image_path", "") or "").strip()

        # ✅ trim：把 drawing title 里的多余空白压掉（避免“看起来一样但不相等”）
        title_drawing = " ".join(title_drawing.split())

        diff_type = ""
        title_index = ""

        if not drawing_num:
            diff_type = "图纸未能提取"
        else:
            seen_dn.add(drawing_num)
            title_index = (index_map.get(drawing_num, "") or "").strip()
            if not title_index:
                diff_type = "目录缺失"
            elif title_index != title_drawing:
                diff_type = "标题不一致"

        if diff_type:
            key = f"{drawing_num}||{Path(pdf_path).name}||{diff_type}"
            items.append(
                ReviewItem(
                    key=key,
                    diff_type=diff_type,
                    pdf_path=pdf_path,
                    drawing_num=drawing_num,
                    title_index=title_index,
                    title_drawing=title_drawing,
                    screenshot_path=screenshot_path,
                    auto_selected=False,
                )
            )

    # -------- reverse diff: index has but drawings missing --------
    图纸缺失 = sorted([dn for dn in index_map.keys() if dn not in seen_dn])
    for dn in 图纸缺失:
        key = f"{dn}||图纸缺失"
        items.append(
            ReviewItem(
                key=key,
                diff_type="图纸缺失",
                pdf_path="",
                drawing_num=dn,
                title_index=index_map.get(dn, "") or "",
                title_drawing="",
                screenshot_path="",
                auto_selected=True,  # ✅ 不用人工复核，直接导出
            )
        )

    _log(log_cb, f"Diff items total: {len(items)}")
    return items


def write_final_excel(
    out_xlsx: Path,
    items: List[ReviewItem],
    selected_map: Dict[str, bool],
) -> int:
    """
    只输出一个 CSV：final_diffs.csv
    导出规则：
      - auto_selected=True 的（图纸缺失）必导出
      - 其他条目：selected_map[key]==True 才导出（勾选=不一致=导出）
    """
    out_xlsx = Path(out_xlsx)
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)

    header = [
        "PDF路径",
        "图号",
        "目录页标题",
        "图纸标题",
        "错误类型",
    ]

    rows: List[List[str]] = []
    for it in items:
        if it.auto_selected:
            export_it = True
        else:
            export_it = bool(selected_map.get(it.key, False))

        if not export_it:
            continue

        rows.append(
            [
                it.pdf_path,
                it.drawing_num,
                it.title_index,
                it.title_drawing,
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

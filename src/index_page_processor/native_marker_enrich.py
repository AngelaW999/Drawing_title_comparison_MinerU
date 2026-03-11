from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.drawing_num import extract_drawing_num

# ============================================================
# Patterns (native marker extraction)
# ============================================================

# 图号 anchor：如 50-S05791Z-T0101-024
# marker：支持 i11 / p1（允许空格、允许撇号）
# 例：i11, i 11', p1, p 1
MARKER_RE = re.compile(r"\b([ip])\s*(\d{1,4})\s*'?\b", re.IGNORECASE)


def _norm_text(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    t = t.replace("’", "'").replace("′", "'")
    return t


# ============================================================
# Step 1) PDF -> native_lines.csv
# ============================================================

def _default_native_csv_path(pdf_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{pdf_path.stem}_native_lines.csv"


def export_pdf_native_lines_to_csv(
    pdf_path: Path,
    output_dir: Path,
    max_pages: Optional[int] = None,
) -> Path:
    """
    把每页原生 text 按行导出到 CSV
    """
    # 延迟 import：避免没装 PyMuPDF 时 import 阶段炸
    import fitz  # PyMuPDF

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_csv = _default_native_csv_path(pdf_path, output_dir)

    doc = fitz.open(str(pdf_path))
    try:
        limit = doc.page_count if max_pages is None else min(max_pages, doc.page_count)

        with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["page_index", "line_index", "text"])
            writer.writeheader()

            for p in range(limit):
                page = doc.load_page(p)
                text = page.get_text("text") or ""
                lines = text.splitlines() if text else []

                for li, line in enumerate(lines, start=1):
                    writer.writerow(
                        {"page_index": p + 1, "line_index": li, "text": line.rstrip("\n")}
                    )
    finally:
        doc.close()

    return out_csv


# ============================================================
# Step 2) Read native_lines.csv -> pages(lines)
# ============================================================

def _read_native_lines_csv(native_lines_csv: Path) -> Dict[int, List[str]]:
    """
    返回：
      { page_index: [text_line_1, text_line_2, ...] }
    保持行顺序（line_index）——因为 anchor 范围切分依赖顺序。
    """
    by_page: Dict[int, List[Tuple[int, str]]] = {}

    with Path(native_lines_csv).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")

        fields = {name.strip().lower(): name for name in reader.fieldnames}
        for need in ["page_index", "line_index", "text"]:
            if need not in fields:
                raise ValueError(
                    f"CSV must contain columns page_index, line_index, text; got {reader.fieldnames}"
                )

        page_col = fields["page_index"]
        line_col = fields["line_index"]
        text_col = fields["text"]

        for row in reader:
            if not row:
                continue
            try:
                page_idx = int((row.get(page_col) or "").strip())
                line_idx = int((row.get(line_col) or "").strip())
            except ValueError:
                continue

            txt = _norm_text(row.get(text_col) or "")
            by_page.setdefault(page_idx, []).append((line_idx, txt))

    pages: Dict[int, List[str]] = {}
    for p, pairs in by_page.items():
        pairs.sort(key=lambda x: x[0])
        pages[p] = [t for _, t in pairs]

    return pages


# ============================================================
# Step 3) Parser (anchor-span marker search)
# ============================================================

def _find_marker_in_span(span_lines: List[str]) -> Optional[str]:
    """
    在 anchor span 里找 marker，返回标准化字符串：
      - i11
      - p1
    """
    for ln in span_lines:
        if not ln:
            continue
        m = MARKER_RE.search(ln)
        if m:
            tag = m.group(1).lower()
            num = m.group(2)
            return f"{tag}{num}"
    return None


def _parse_markers_from_pages(pages: Dict[int, List[str]]) -> Dict[str, str]:
    result: Dict[str, str] = {}

    for page_idx in sorted(pages.keys()):
        lines = pages[page_idx]

        anchors: List[Tuple[int, str]] = []
        for i, ln in enumerate(lines):
            dn = extract_drawing_num(ln or "")
            if dn:
                anchors.append((i, dn))

        if not anchors:
            continue

        for k, (a_pos, drawing_no) in enumerate(anchors):
            if drawing_no in result:
                continue

            b_pos = anchors[k + 1][0] if k + 1 < len(anchors) else len(lines)
            span = lines[a_pos:b_pos]

            marker = _find_marker_in_span(span)
            if marker:
                result[drawing_no] = marker

    return result


def parse_native_markers_from_pdf(
    pdf_path: Path,
    output_dir: Path,
    max_pages: Optional[int] = None,
) -> Tuple[Path, Dict[str, str]]:
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)

    csv_path = export_pdf_native_lines_to_csv(
        pdf_path=pdf_path,
        output_dir=output_dir,
        max_pages=max_pages,
    )
    pages = _read_native_lines_csv(csv_path)
    markers = _parse_markers_from_pages(pages)
    return csv_path, markers


# ============================================================
# Enrichment / Normalization
# ============================================================

# ①-⑳ -> 数字
_CIRCLED_TO_INT = {
    "①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5,
    "⑥": 6, "⑦": 7, "⑧": 8, "⑨": 9, "⑩": 10,
    "⑪": 11, "⑫": 12, "⑬": 13, "⑭": 14, "⑮": 15,
    "⑯": 16, "⑰": 17, "⑱": 18, "⑲": 19, "⑳": 20,
}

# 末尾圆圈字符
_TRAILING_CIRCLED_RE = re.compile(r"([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*$")
# 末尾已有 (xxx)
_TRAILING_PAREN_TOKEN_RE = re.compile(r"\(\s*([A-Za-z]?\d{1,4})\s*\)\s*$")

# 末尾脏格式：P(1) / p(2)
_TRAILING_P_NUM_STYLE_RE = re.compile(r"\bP\s*\(\s*(\d{1,4})\s*\)\s*$", re.IGNORECASE)

# 尾部可能出现的不可见/特殊空白
_TRAILING_INVIS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u00a0\u3000]+$")

# 末尾裸 P1 / P12（必须加括号）；这里不要 \b，避免 NBSP/全角空格影响边界
_TRAILING_BARE_P_RE = re.compile(r"P\s*(\d{1,4})\s*$", re.IGNORECASE)

# 清理重复：40(40), P1(P1), 73(73) 等
_DUPLICATE_TRAILING_TOKEN_RE = re.compile(
    r"""
    (.*?)                 # body
    \s*
    ([A-Za-z]?\d{1,4})    # token，例如 40 / P1
    \s*
    \(\s*\2\s*\)          # (同 token)
    \s*$
    """,
    re.VERBOSE,
)


def _strip_trailing_invisible(s: str) -> str:
    """
    去掉尾部常见不可见字符/特殊空白（NBSP/全角空格/零宽/UTF-8 BOM）
    """
    if not s:
        return s
    t = s.rstrip()
    t = _TRAILING_INVIS_RE.sub("", t).rstrip()
    return t


def _strip_trailing_circled(title: str) -> str:
    t = _strip_trailing_invisible(title or "")
    return _TRAILING_CIRCLED_RE.sub("", t).rstrip()


def _extract_trailing_circled_int(title: str) -> Optional[int]:
    t = _strip_trailing_invisible(title or "")
    m = _TRAILING_CIRCLED_RE.search(t)
    if not m:
        return None
    return _CIRCLED_TO_INT.get(m.group(1))


def _marker_to_tag_num(marker: str) -> Optional[Tuple[str, int]]:
    """
    marker: i11 / p1 -> (tag, num)
    """
    if not marker:
        return None
    mk = marker.strip().lower()
    m = re.fullmatch(r"([ip])(\d{1,4})", mk)
    if m:
        return (m.group(1), int(m.group(2)))

    m2 = re.search(r"([ip])\s*(\d{1,4})\s*$", mk)
    if not m2:
        return None
    return (m2.group(1), int(m2.group(2)))


def cleanup_trailing_p_num_style(title: str) -> str:
    """
    把末尾 P(1) 归一成 (P1)
    例：...图P(1) -> ...图(P1)
    """
    t = _strip_trailing_invisible(title or "")
    m = _TRAILING_P_NUM_STYLE_RE.search(t)
    if not m:
        return t
    num = m.group(1)
    body = _TRAILING_P_NUM_STYLE_RE.sub("", t).rstrip()
    return f"{body}(P{num})"


def cleanup_trailing_bare_p(title: str) -> str:
    """
    把末尾裸露的 P1 / P12 统一成 (P1)/(P12)
    （对尾部不可见字符也鲁棒）
    """
    t = _strip_trailing_invisible(title or "")
    m = _TRAILING_BARE_P_RE.search(t)
    if not m:
        return t

    num = m.group(1)
    body = _TRAILING_BARE_P_RE.sub("", t).rstrip()
    return f"{body}(P{num})"


def _ensure_suffix_marker(title: str, tag: str, num: int) -> str:
    """
    强制末尾为：
      - i11 -> (11)
      - p1  -> (P1)

    同时清掉末尾圆圈、末尾已有(...)、末尾 P(1) / 裸P1
    """
    t = _strip_trailing_invisible(title or "")

    # 先把脏的 P(1) -> (P1)
    t = cleanup_trailing_p_num_style(t)
    # 再把裸 P1 -> (P1)
    t = cleanup_trailing_bare_p(t)
    # 去掉末尾圆圈
    t = _strip_trailing_circled(t)
    # 去掉末尾已有的 (xxx)
    t = _TRAILING_PAREN_TOKEN_RE.sub("", t).rstrip()

    if tag.lower() == "p":
        return f"{t}(P{num})"
    return f"{t}({num})"


def _convert_mineru_suffix_to_paren(title: str) -> str:
    """
    原生没有 marker：保留 MinerU 信息，但统一成括号格式：
      - ①-⑳ -> (n)（仅末尾）
      - 末尾 P(1) -> (P1)
      - 末尾 P1   -> (P1)
    """
    t = _strip_trailing_invisible(title or "").strip()

    # 先处理 P(1)
    t = cleanup_trailing_p_num_style(t)
    # 再处理裸 P1
    t = cleanup_trailing_bare_p(t)

    # 再把末尾圆圈字符 -> (n)
    n = _extract_trailing_circled_int(t)
    if n is not None:
        t = _ensure_suffix_marker(t, "i", n)  # i 规则就是 (n)

    return t


def cleanup_duplicate_trailing_marker(title: str) -> str:
    """
    清理：
      xxx40(40) -> xxx(40)
      xxxP1(P1) -> xxx(P1)
    """
    t = _strip_trailing_invisible(title or "")
    m = _DUPLICATE_TRAILING_TOKEN_RE.match(t.rstrip())
    if not m:
        return t
    body = m.group(1).rstrip()
    token = m.group(2)
    return f"{body}({token})"


def apply_native_markers_to_pairs(
    pairs: List[List[str]],
    markers: Dict[str, str],
) -> List[List[str]]:
    """
    规则：
      - 原生有 marker：
          i11 -> 强制 ...(11)
          p1  -> 强制 ...(P1)
        并移除 MinerU 的圆圈/旧括号/末尾P(1)/裸P1
      - 原生无 marker：
          ①-⑳ -> (n)
          P(1) -> (P1)
          P1   -> (P1)
      - 最后清理重复尾巴：40(40)、P1(P1)…
    """
    out: List[List[str]] = []

    for drawing_no, title in pairs:
        marker = markers.get(drawing_no)

        if marker:
            tag_num = _marker_to_tag_num(marker)
            if tag_num:
                tag, num = tag_num
                new_title = _ensure_suffix_marker(title, tag, num)
            else:
                new_title = _convert_mineru_suffix_to_paren(title)
        else:
            new_title = _convert_mineru_suffix_to_paren(title)

        # 再兜一遍：P1 -> (P1)
        new_title = cleanup_trailing_bare_p(new_title)

        # 清理重复：40(40)、P1(P1)
        new_title = cleanup_duplicate_trailing_marker(new_title)

        out.append([drawing_no, new_title])

    return out
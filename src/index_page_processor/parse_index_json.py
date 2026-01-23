from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any, List, Optional, Tuple

# 只要行里出现 50- 就算候选；图号提取更宽松（允许 OCR 插空格）
DRAWING_NO_RE = re.compile(r"(50-\s*[A-Z0-9\-]+\s*-\s*\d{2,4})")

def _looks_like_title(s: str) -> bool:
    if not s:
        return False
    # 有中文一般就是图名
    if any("\u4e00" <= ch <= "\u9fff" for ch in s):
        return True
    # 没中文但比较长，也可能是图名
    return len(s) >= 10


class _HTMLTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_td = False
        self._buf: list[str] = []
        self._cur: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._cur = []
        elif tag == "td":
            self._in_td = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "td":
            self._in_td = False
            self._cur.append("".join(self._buf).strip())
        elif tag == "tr":
            if self._cur:
                self.rows.append(self._cur)

    def handle_data(self, data):
        if self._in_td:
            self._buf.append(data)


def _parse_table_html(html: str) -> List[List[str]]:
    p = _HTMLTableParser()
    p.feed(html)
    return p.rows


def _iter_table_blocks(obj: Any) -> List[dict]:
    out: List[dict] = []
    if isinstance(obj, dict):
        if obj.get("type") == "table":
            out.append(obj)
        for v in obj.values():
            out.extend(_iter_table_blocks(v))
    elif isinstance(obj, list):
        for x in obj:
            out.extend(_iter_table_blocks(x))
    return out


def _extract_from_row(row: List[str]) -> Optional[Tuple[str, str]]:
    """
    从一行里抽 (drawing_no, title)
    - drawing_no: 该行第一个匹配 50-... 的片段（去空格）
    - title: 去掉图号后，挑“最像标题”的 cell（最长且符合 looks_like_title）
    """
    joined = " ".join(row)
    m = DRAWING_NO_RE.search(joined)
    if not m:
        return None

    drawing_no = m.group(1).replace(" ", "")

    candidates: List[str] = []
    for cell in row:
        s = (cell or "").strip()
        if not s:
            continue
        if drawing_no in s:
            s = s.replace(drawing_no, "").strip()
        if _looks_like_title(s):
            candidates.append(s)

    if not candidates:
        return None

    title = max(candidates, key=len)
    return drawing_no, title


def extract_pairs_from_json(json_text: str, *, debug: bool = False) -> List[List[str]]:
    """
    返回：[[drawing_no, title], ...]
    """
    try:
        data = json.loads(json_text)
    except Exception:
        return []

    tables = _iter_table_blocks(data)

    if debug:
        pdf_info = data.get("pdf_info", [])
        print("DEBUG page count(pdf_info):", len(pdf_info) if isinstance(pdf_info, list) else "N/A")
        print("DEBUG table blocks:", len(tables))

    out: List[Tuple[str, str]] = []
    for t in tables:
        html = t.get("html")
        if not isinstance(html, str) or "<table" not in html:
            continue

        rows = _parse_table_html(html)
        for row in rows:
            hit = _extract_from_row(row)
            if hit:
                out.append(hit)

    # 去重：按 drawing_no
    seen = set()
    dedup: List[List[str]] = []
    for no, title in out:
        if no in seen:
            continue
        seen.add(no)
        dedup.append([no, title])

    return dedup
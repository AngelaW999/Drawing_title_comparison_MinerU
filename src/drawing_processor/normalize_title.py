from __future__ import annotations

import re

# ①-⑳ -> 数字
_CIRCLED_TO_INT = {
    "①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5,
    "⑥": 6, "⑦": 7, "⑧": 8, "⑨": 9, "⑩": 10,
    "⑪": 11, "⑫": 12, "⑬": 13, "⑭": 14, "⑮": 15,
    "⑯": 16, "⑰": 17, "⑱": 18, "⑲": 19, "⑳": 20,
}

# 末尾圆圈字符
_TRAILING_CIRCLED_RE = re.compile(r"([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*$")

# P(1) -> (P1)
_TRAILING_P_NUM_STYLE_RE = re.compile(r"\bP\s*\(\s*(\d{1,4})\s*\)\s*$", re.IGNORECASE)

# 末尾裸 P1 -> (P1)（允许空白）
_TRAILING_BARE_P_RE = re.compile(r"P\s*(\d{1,4})\s*$", re.IGNORECASE)

# 末尾裸数字：12 -> (12)
_TRAILING_BARE_NUM_RE = re.compile(r"(\d{1,3})\s*$")

# 末尾已有 (...)（数字或 P1）
_TRAILING_PAREN_TOKEN_RE = re.compile(r"\(\s*([A-Za-z]?\d{1,4})\s*\)\s*$")

# 末尾不可见字符/特殊空白
_TRAILING_INVIS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u00a0\u3000]+$")

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

# 修复缺右括号：...(2/2 -> ...(2/2)
_MISSING_RPAREN_RE = re.compile(r"\((\d+\s*/\s*\d+)\s*$")

# 全角括号转半角
_FULLWIDTH_PARENS = str.maketrans({"（": "(", "）": ")"})


def _strip_trailing_invisible(s: str) -> str:
    if not s:
        return s
    t = s.rstrip()
    t = _TRAILING_INVIS_RE.sub("", t).rstrip()
    return t


def _extract_trailing_circled_int(title: str) -> int | None:
    m = _TRAILING_CIRCLED_RE.search(_strip_trailing_invisible(title))
    if not m:
        return None
    return _CIRCLED_TO_INT.get(m.group(1))


def _strip_trailing_circled(title: str) -> str:
    t = _strip_trailing_invisible(title)
    return _TRAILING_CIRCLED_RE.sub("", t).rstrip()


def cleanup_trailing_p_num_style(title: str) -> str:
    t = _strip_trailing_invisible(title)
    m = _TRAILING_P_NUM_STYLE_RE.search(t)
    if not m:
        return t
    num = m.group(1)
    body = _TRAILING_P_NUM_STYLE_RE.sub("", t).rstrip()
    return f"{body}(P{num})"


def cleanup_trailing_bare_p(title: str) -> str:
    t = _strip_trailing_invisible(title)
    m = _TRAILING_BARE_P_RE.search(t)
    if not m:
        return t
    num = m.group(1)
    body = _TRAILING_BARE_P_RE.sub("", t).rstrip()
    return f"{body}(P{num})"


def cleanup_trailing_bare_num(title: str) -> str:
    t = _strip_trailing_invisible(title)

    if _TRAILING_PAREN_TOKEN_RE.search(t):
        return t
    if _TRAILING_BARE_P_RE.search(t) or _TRAILING_P_NUM_STYLE_RE.search(t):
        return t

    m = _TRAILING_BARE_NUM_RE.search(t)
    if not m:
        return t

    num = m.group(1)
    body = _TRAILING_BARE_NUM_RE.sub("", t).rstrip()
    return f"{body}({num})"


def cleanup_duplicate_trailing_marker(title: str) -> str:
    t = _strip_trailing_invisible(title)
    m = _DUPLICATE_TRAILING_TOKEN_RE.match(t)
    if not m:
        return t
    body = m.group(1).rstrip()
    token = m.group(2)
    return f"{body}({token})"


# ✅ 新增：全局空白压缩（把 MinerU/截图 OCR 产生的空格清掉）
_ALL_WS_RE = re.compile(r"[\s\u00a0\u3000\u200b\u200c\u200d\ufeff]+")


def trim_title_whitespace(title: str | None) -> str | None:
    """
    - 去首尾空白
    - 中间所有空白压成“无空格”
      （中文标题一般不需要空格；你要保留一个空格就把 "" 改成 " "）
    """
    if title is None:
        return None
    t = title.strip()
    if not t:
        return t
    return _ALL_WS_RE.sub("", t)


def normalize_title(title: str | None) -> str | None:
    if not title:
        return title

    t = title.translate(_FULLWIDTH_PARENS)
    t = _strip_trailing_invisible(t)

    if _MISSING_RPAREN_RE.search(t):
        t = t + ")"

    t = cleanup_trailing_p_num_style(t)
    t = cleanup_trailing_bare_p(t)

    t = cleanup_trailing_bare_num(t)

    n = _extract_trailing_circled_int(t)
    if n is not None:
        t = _strip_trailing_circled(t).rstrip()
        if not _TRAILING_PAREN_TOKEN_RE.search(t):
            t = f"{t}({n})"

    t = cleanup_duplicate_trailing_marker(t)
    t = _strip_trailing_invisible(t)
    t = t.strip()

    # ✅ 最后统一 trim 空白（解决你说的 drawing title 里各种空格）
    t = trim_title_whitespace(t)

    return t
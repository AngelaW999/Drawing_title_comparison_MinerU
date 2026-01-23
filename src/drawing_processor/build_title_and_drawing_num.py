# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import List, Tuple

__all__ = ["build_title_and_drawing_num_from_lines"]

# drawing num（允许各种横杠，最终会统一成 -）
_DRAWING_NUM_ANY_RE = re.compile(r"\b50[-－—][0-9A-Za-z\-－—]+\b")

# “图号 / Dwg.No”这类标签行（常出现在图号旁边）
_LABEL_RE = re.compile(r"(?:图\s*号|dwg\s*\.?\s*no\.?|wg\s*\.?\s*no\.?|g\s*\.?\s*no\.?)", re.IGNORECASE)

# markdown 前缀符号
_MD_PREFIX_RE = re.compile(r"^\s*(?:#+|\*+|-+|>+)\s*")

# 末尾不可见字符/特殊空白
_TRAILING_INVIS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u00a0\u3000]+$")

# 把各种横杠统一成 "-"
_DASH_FIX_RE = re.compile(r"[-－—]+")


def _clean_line(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    t = _MD_PREFIX_RE.sub("", t).strip()
    t = _TRAILING_INVIS_RE.sub("", t).strip()
    # 常见噪声：首尾逗号/分号
    t = t.strip(" ,，;；")
    return t


def _norm_drawing_num(s: str) -> str:
    return _DASH_FIX_RE.sub("-", s)


def build_title_and_drawing_num_from_lines(lines: List[str]) -> Tuple[str | None, str | None]:
    """
    输入：MinerU 输出的“行”（已经是按阅读顺序的文本）
    输出：
      - drawing_num
      - title（优先取 drawing_num 所在行的上方 1~3 行拼接）

    策略（稳定适配你这类标题栏）：
      1) 在所有行中找 drawing_num，记录命中的行 index
      2) title 候选 = drawing_num 行上方最近的 1~3 行
         - 过滤掉含“图号/Dwg.No”等标签的行
      3) 把候选行按原顺序直接拼接（不加空格，符合你标题栏的排版）
      4) 如果上方不足，退回取“最长的非标签行”
    """
    cleaned = [_clean_line(x) for x in lines]
    cleaned = [x for x in cleaned if x]

    if not cleaned:
        return None, None

    drawing_num = None
    dn_idx = None

    for i, ln in enumerate(cleaned):
        m = _DRAWING_NUM_ANY_RE.search(ln)
        if m:
            drawing_num = _norm_drawing_num(m.group(0))
            dn_idx = i
            break

    # 找不到图号：就只做 title 兜底
    if drawing_num is None:
        # 选最长一行且不是标签
        cands = [ln for ln in cleaned if not _LABEL_RE.search(ln)]
        if not cands:
            return None, cleaned[0]
        best = max(cands, key=len)
        return None, best

    # title：优先取图号上一到三行
    title_lines: List[str] = []
    if dn_idx is not None:
        # 从图号行往上看
        for j in range(dn_idx - 1, -1, -1):
            ln = cleaned[j]
            if not ln:
                continue
            # 过滤标签行
            if _LABEL_RE.search(ln):
                continue
            # 也过滤“纯图号那种行”（万一重复出现）
            if _DRAWING_NUM_ANY_RE.fullmatch(ln):
                continue

            title_lines.append(ln)
            if len(title_lines) >= 3:
                break

        title_lines.reverse()

    # 若上方没抓到（特殊版式），兜底：选最长的非标签行
    if not title_lines:
        cands = [ln for ln in cleaned if not _LABEL_RE.search(ln) and drawing_num not in _norm_drawing_num(ln)]
        if cands:
            title_lines = [max(cands, key=len)]

    title = "".join(title_lines).strip() if title_lines else None
    return drawing_num, title
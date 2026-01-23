from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class IndexRow:
    """
    一行目录记录：你后面可以按需要再加字段
    """
    drawing_no: Optional[str] = None
    title: Optional[str] = None
    page: Optional[str] = None
    raw: Optional[str] = None  # 方便调试：保留原始行文本
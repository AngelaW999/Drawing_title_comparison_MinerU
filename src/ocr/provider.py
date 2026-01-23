from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParseResult:
    """
    通用解析结果：MinerU 会返回 zip，我们在 parser 里抽出 markdown/json。
    """
    markdown: str | None = None
    json_text: str | None = None
    raw_zip_bytes: bytes | None = None


class DocumentParser:
    """
    OCR/解析 provider 的统一接口。
    上层（index / drawing）只依赖这个接口，不依赖具体供应商。
    """
    def parse_file(self, file_path: Path) -> ParseResult:
        raise NotImplementedError
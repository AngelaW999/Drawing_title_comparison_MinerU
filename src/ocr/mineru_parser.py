from __future__ import annotations

import io
import zipfile
from pathlib import Path

from .mineru_client import MinerUClient
from .provider import DocumentParser, ParseResult


def _pick_best_json(names: list[str]) -> str | None:
    """
    MinerU zip 内 json 可能不止一个：尽量挑“结构化结果”那个。
    规则（从高到低）：
      1) 文件名包含 structured/result/extract
      2) 路径更短
      3) 文件名更短
    """
    if not names:
        return None

    def score(n: str) -> tuple[int, int, int]:
        low = n.lower()
        hit = 0
        if "structured" in low:
            hit += 3
        if "extract" in low or "result" in low:
            hit += 2
        # hit 越大越优先，所以用 -hit
        return (-hit, len(n.split("/")), len(n))

    return sorted(names, key=score)[0]


def _pick_best_md(names: list[str], prefer_name: str) -> str | None:
    """
    md 通常就一个，但也做一下偏好：包含 prefer_name 更优先。
    """
    if not names:
        return None

    def score(n: str) -> tuple[int, int, int]:
        # prefer 命中更优先
        prefer_hit = 0 if (prefer_name and prefer_name in n) else 1
        return (prefer_hit, len(n.split("/")), len(n))

    return sorted(names, key=score)[0]


class MinerUDocumentParser(DocumentParser):
    """
    DocumentParser 实现：文件 -> MinerU -> zip -> (md/json)
    """
    def __init__(self, client: MinerUClient):
        self.client = client

    def parse_file(self, file_path: Path) -> ParseResult:
        zip_bytes = self.client.parse_single_file(file_path)
        md, js = self._extract_md_json(zip_bytes, prefer_name=file_path.stem)
        return ParseResult(markdown=md, json_text=js, raw_zip_bytes=zip_bytes)

    def _extract_md_json(self, zip_bytes: bytes, prefer_name: str) -> tuple[str | None, str | None]:
        md: str | None = None
        js: str | None = None

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            names = z.namelist()

            md_name = _pick_best_md([n for n in names if n.lower().endswith(".md")], prefer_name)
            js_name = _pick_best_json([n for n in names if n.lower().endswith(".json")])

            if md_name:
                md = z.read(md_name).decode("utf-8", errors="replace")
            if js_name:
                js = z.read(js_name).decode("utf-8", errors="replace")

        return md, js
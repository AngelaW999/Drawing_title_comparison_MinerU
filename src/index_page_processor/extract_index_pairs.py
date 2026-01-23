from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.ocr import MinerUClient, MinerUConfig, MinerUDocumentParser
from src.index_page_processor.native_marker_enrich import (
    apply_native_markers_to_pairs,
    parse_native_markers_from_pdf,
)
from src.index_page_processor.parse_index_json import extract_pairs_from_json
from src.ocr.token_provider import get_mineru_token


def _get_index_parser(token: Optional[str] = None) -> MinerUDocumentParser:
    """
    index 目录解析专用 parser（enable_table=True）
    """
    t = token or get_mineru_token()
    if not t:
        raise RuntimeError("MINERU_TOKEN is not set in environment variables.")

    cfg = MinerUConfig(
        token=t,
        model_version="vlm",
        enable_table=True,
        enable_formula=False,
        language="ch",
    )
    return MinerUDocumentParser(MinerUClient(cfg))


def extract_index_pairs(
    pdf_path: Path,
    *,
    token: Optional[str] = None,
    native_out_dir: Optional[Path] = None,
) -> List[List[str]]:
    """
    完整流程：
      1) MinerU OCR 目录表
      2) 行级规则提取 [drawing_no, title]
      3) 原生 PDF 提取 marker（i11 / p1）
      4) 统一 title 圆圈/marker 为括号格式，原生优先（原生无则保留 MinerU，但也归一）
      5) 清理重复尾缀：...(1/2)40(40) -> ...(1/2)(40)

    参数：
      - token: 可选；不传则读 env MINERU_TOKEN
      - native_out_dir: 原生抽取输出目录（默认 .cache/native）
        （测试里可以传 tests/output）
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    # ---------- MinerU ----------
    parser = _get_index_parser(token=token)
    res = parser.parse_file(pdf_path)

    if not res.json_text:
        return []

    # ---------- Step 1: MinerU -> pairs ----------
    pairs = extract_pairs_from_json(res.json_text)
    if not pairs:
        return []

    # ---------- Step 2: native PDF markers ----------
    out_dir = Path(native_out_dir) if native_out_dir else (Path(".cache") / "native")
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        _, markers = parse_native_markers_from_pdf(
            pdf_path=pdf_path,
            output_dir=out_dir,
        )
    except Exception as e:
        # 原生解析失败不影响主流程（比如没装 PyMuPDF/某些PDF原生抽不到）
        print(f"[WARN] native marker parse failed: {e}")
        markers = {}

    # ---------- Step 3: merge & normalize ----------
    pairs = apply_native_markers_to_pairs(pairs, markers)
    return pairs


def main() -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", help="index/table pdf path")
    ap.add_argument("--out", help="write pairs to a json file")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    pairs = extract_index_pairs(pdf_path)

    print(f"Pairs: {len(pairs)}")
    for p in pairs[:30]:
        print(p)

    if args.out:
        Path(args.out).write_text(
            json.dumps(pairs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()
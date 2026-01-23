from __future__ import annotations

import csv
import os
import re
from pathlib import Path

import pytest


_CIRCLED_ANY_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]")
_PAREN_NUM_RE = re.compile(r"\(\s*\d{1,4}\s*\)")


@pytest.mark.integration
def test_mineru_extract_index_pairs_export_csv(monkeypatch, capsys):
    """
    真实调用 MinerU 解析整份 PDF，并导出 CSV 到 tests/output。
    同时验证：title 里圆圈字符已被归一化为 (n)，且不再出现 ①-⑳。

    运行条件：
      - env: MINERU_TOKEN
      - env: INDEX_PDF_PATH (目录PDF路径)
    """
    token = os.environ.get("MINERU_TOKEN")
    pdf_path_s = os.environ.get("INDEX_PDF_PATH")

    if not token:
        pytest.skip("MINERU_TOKEN not set; skip integration test")
    if not pdf_path_s:
        pytest.skip("INDEX_PDF_PATH not set; skip integration test")

    pdf_path = Path(pdf_path_s)
    if not pdf_path.exists():
        pytest.skip(f"INDEX_PDF_PATH not found: {pdf_path}")

    import src.index_page_processor.extract_index_pairs as m

    # 1) 直接调用函数拿真实 pairs（这里已经包含 native marker enrich + (n) 归一化）
    pairs = m.extract_index_pairs(pdf_path)
    assert isinstance(pairs, list)
    assert len(pairs) > 0, "MinerU returned empty pairs"

    # 2) 导出 CSV（每个 PDF 一个文件，避免覆盖）
    out_dir = Path("tests") / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"{pdf_path.stem}_index_pairs.csv"

    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["drawing_no", "title"])
        for row in pairs:
            drawing_no = row[0] if len(row) > 0 else ""
            title = row[1] if len(row) > 1 else ""
            w.writerow([drawing_no, title])

    assert out_csv.exists()
    assert out_csv.stat().st_size > 10

    # 3) ✅ 关键断言：不再出现 ①-⑳；并且至少有一些 (n)
    titles = [r[1] for r in pairs if len(r) > 1 and r[1]]
    assert len(titles) > 0

    # 不允许任何圆圈字符残留
    assert not any(_CIRCLED_ANY_RE.search(t) for t in titles), "Found circled chars still in titles"

    # 至少有一条包含 (n)（如果你的这份目录确实有 marker/圆圈）
    assert any(_PAREN_NUM_RE.search(t) for t in titles), "No (n) found in any title; check normalization"

    # 4) 再跑 main() 验证入口（不改 main）
    monkeypatch.setattr("sys.argv", ["extract_index_pairs.py", str(pdf_path)])
    m.main()

    captured = capsys.readouterr()
    assert "Pairs:" in captured.out
from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.index_page_processor import extract_index_pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-pdf", required=True, help="目录PDF路径")
    args = ap.parse_args()

    token = os.environ.get("MINERU_TOKEN")
    if not token:
        raise RuntimeError("Missing env var: MINERU_TOKEN")

    pairs = extract_index_pairs(Path(args.index_pdf))
    print(f"Pairs: {len(pairs)}")
    for p in pairs[:30]:
        print(p)


if __name__ == "__main__":
    main()
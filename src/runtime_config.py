from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict


def _app_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _load_json(p: Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def init_runtime_env() -> None:
    """
    优先读取 exe 同目录 config.json 的 MINERU_TOKEN。
    没有就走系统环境变量。
    """
    cfg_path = _app_dir() / "config.json"
    if cfg_path.exists():
        cfg = _load_json(cfg_path)
        token = (cfg.get("MINERU_TOKEN") or "").strip()
        if token and not os.environ.get("MINERU_TOKEN"):
            os.environ["MINERU_TOKEN"] = token
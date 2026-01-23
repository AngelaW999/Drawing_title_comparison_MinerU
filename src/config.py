from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _app_dir() -> Path:
    # Windows: %APPDATA%/DrawingTitleComparison
    # macOS/Linux: ~/.drawing_title_comparison
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
        return base / "DrawingTitleComparison"
    return Path.home() / ".drawing_title_comparison"


def config_path() -> Path:
    d = _app_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


@dataclass
class AppConfig:
    mineru_token: str = ""


def load_config() -> AppConfig:
    p = config_path()
    if not p.exists():
        return AppConfig()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return AppConfig(mineru_token=str(data.get("mineru_token", "") or ""))
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"mineru_token": cfg.mineru_token}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
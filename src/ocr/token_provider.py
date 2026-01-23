from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


class MinerUTokenError(RuntimeError):
    pass


# -------- internal in-memory cache (preferred) --------
_TOKEN_CACHE: str | None = None


def _config_dir() -> Path:
    """
    Windows EXE 友好：使用 %APPDATA%。
    没有 APPDATA 时退回到用户目录。
    """
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / "DrawingTitleComparisonMinerU"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _config_path() -> Path:
    return _config_dir() / "config.json"


def _load_from_config() -> str:
    p = _config_path()
    if not p.exists():
        return ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return (data.get("MINERU_TOKEN") or "").strip()
    except Exception:
        return ""


def _save_to_config(token: str) -> None:
    p = _config_path()
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["MINERU_TOKEN"] = (token or "").strip()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_mineru_token(token: str, *, persist: bool = True) -> None:
    """
    给全项目设置 token：
      1) 写内存 cache
      2) 写环境变量（方便老代码）
      3) 可选写 config.json（exe 场景）
    """
    global _TOKEN_CACHE
    t = (token or "").strip()
    if not t:
        raise MinerUTokenError("Empty MinerU token")

    _TOKEN_CACHE = t
    os.environ["MINERU_TOKEN"] = t

    if persist:
        _save_to_config(t)


def get_mineru_token() -> str:
    """
    取 token 的优先级：
      1) 内存 cache（set_mineru_token 写入）
      2) config.json（exe 保存）
      3) 环境变量 MINERU_TOKEN
    """
    if _TOKEN_CACHE and _TOKEN_CACHE.strip():
        return _TOKEN_CACHE.strip()

    t = _load_from_config()
    if t:
        # 同步到 cache + env，避免后续重复读取文件
        set_mineru_token(t, persist=False)
        return t

    t2 = (os.environ.get("MINERU_TOKEN") or "").strip()
    if t2:
        set_mineru_token(t2, persist=False)
        return t2

    raise MinerUTokenError("MinerU token not configured")
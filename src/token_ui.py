from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from src.config import AppConfig, load_config, save_config


def prompt_token(master: tk.Tk, *, reason: str = "") -> str | None:
    """
    弹窗让用户输入 MinerU token。
    返回 token（用户点取消则返回 None）。
    """
    cfg = load_config()

    win = tk.Toplevel(master)
    win.title("MinerU Token 设置")
    win.geometry("620x220")
    win.transient(master)
    win.grab_set()

    tip = "请输入 MinerU Token（每 15 天更新一次）。"
    if reason:
        tip += f"\n原因：{reason}"

    ttk.Label(win, text=tip, font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=12, pady=(12, 8))

    var = tk.StringVar(value=cfg.mineru_token or "")
    ent = ttk.Entry(win, textvariable=var, width=80)
    ent.pack(fill="x", padx=12, pady=(0, 10))
    ent.focus_set()

    btn_row = ttk.Frame(win)
    btn_row.pack(fill="x", padx=12, pady=(6, 12))

    result: dict[str, str | None] = {"token": None}

    def on_save():
        token = (var.get() or "").strip()
        if not token:
            messagebox.showerror("错误", "Token 不能为空")
            return
        cfg2 = AppConfig(mineru_token=token)
        save_config(cfg2)
        result["token"] = token
        win.destroy()

    def on_cancel():
        result["token"] = None
        win.destroy()

    ttk.Button(btn_row, text="保存", command=on_save).pack(side="right")
    ttk.Button(btn_row, text="取消", command=on_cancel).pack(side="right", padx=8)

    master.wait_window(win)
    return result["token"]  
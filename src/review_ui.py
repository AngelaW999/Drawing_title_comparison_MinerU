# src/review_ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import tkinter as tk
from tkinter import ttk

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None


@dataclass
class ReviewItem:
    key: str
    diff_type: str
    pdf_path: str
    drawing_num: str
    title_index: str
    title_drawing: str
    screenshot_path: str
    auto_selected: bool = False


def _norm(s: str) -> str:
    return (s or "").strip()


def _build_left_text(it: ReviewItem) -> str:
    file_name = Path(it.pdf_path).name if it.pdf_path else ""
    head = f"{it.diff_type} | 图号={it.drawing_num} | {file_name}".strip()
    idx = _norm(it.title_index)
    drw = _norm(it.title_drawing)
    return f"{head}\n目录 : {idx}\n图纸: {drw}"


class ReviewWindow(tk.Toplevel):
    """
    三列比例（更偏向“左列更宽”）：
      - 左：文本（更宽）
      - 中：截图
      - 右：checkbox
    """
    def __init__(self, master: tk.Tk, items: List[ReviewItem], title: str = "差异复核（勾选=导出）"):
        super().__init__(master)
        self.title(title)
        self.geometry("1280x720")

        self.items = items
        self.selected: Dict[str, bool] = {it.key: False for it in items}

        self._img_refs: Dict[str, object] = {}

        self._build_ui()
        self._render_rows()

    def _build_ui(self) -> None:
        self.var_tip = tk.StringVar(value=f"共 {len(self.items)} 条（默认不勾；勾选=不一致=导出）")
        ttk.Label(self, textvariable=self.var_tip, font=("Microsoft YaHei UI", 11, "bold")).pack(
            anchor="w", padx=12, pady=(10, 6)
        )

        hdr = ttk.Frame(self)
        hdr.pack(fill="x", padx=12)

        # ✅ 左列更宽：比例如 5 : 3 : 1
        hdr.columnconfigure(0, weight=5)
        hdr.columnconfigure(1, weight=3)
        hdr.columnconfigure(2, weight=1)

        ttk.Label(hdr, text="目录/图纸标题").grid(row=0, column=0, sticky="w")
        ttk.Label(hdr, text="截图").grid(row=0, column=1)
        ttk.Label(hdr, text="不一致").grid(row=0, column=2)

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=12, pady=(6, 10))

        self.canvas = tk.Canvas(wrap, highlightthickness=0)
        self.vbar = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.inner = ttk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        bot = ttk.Frame(self)
        bot.pack(fill="x", padx=12, pady=(0, 12))

        style = ttk.Style(self)
        style.configure("Big.TButton", font=("Microsoft YaHei UI", 11), padding=(18, 10))

        def big_btn(**kw):
            return ttk.Button(bot, style="Big.TButton", **kw)

        big_btn(text="全不选", command=self._select_none).pack(side="left")
        big_btn(text="全选", command=self._select_all).pack(side="left", padx=10)
        big_btn(text="保存并关闭", command=self._finish).pack(side="right")

    def _on_inner_configure(self, _evt=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, evt=None) -> None:
        if evt is not None:
            self.canvas.itemconfigure(self.inner_id, width=evt.width)

    def _on_mousewheel(self, evt) -> None:
        try:
            self.canvas.yview_scroll(int(-1 * (evt.delta / 120)), "units")
        except Exception:
            pass

    def _render_rows(self) -> None:
        for c in self.inner.winfo_children():
            c.destroy()
        self._img_refs.clear()

        if not self.items:
            ttk.Label(self.inner, text="没有需要复核的条目").pack(anchor="w")
            return

        for it in self.items:
            row = ttk.Frame(self.inner)
            row.pack(fill="x", pady=6)

            # ✅ 左更宽：5 : 3 : 1
            row.columnconfigure(0, weight=5)
            row.columnconfigure(1, weight=3)
            row.columnconfigure(2, weight=1)

            left_txt = _build_left_text(it)
            lbl_left = ttk.Label(row, text=left_txt, justify="left", anchor="w")
            lbl_left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

            img_cell = ttk.Frame(row)
            img_cell.grid(row=0, column=1, sticky="nsew", padx=(0, 10))

            img_lbl = ttk.Label(img_cell, text="", anchor="center")
            img_lbl.pack(fill="both", expand=True)
            self._set_image(img_lbl, it.key, it.screenshot_path)

            var = tk.BooleanVar(value=self.selected.get(it.key, False))

            def _on_toggle(k=it.key, v=var):
                self.selected[k] = bool(v.get())

            chk = ttk.Checkbutton(row, variable=var, command=_on_toggle)
            chk.grid(row=0, column=2, sticky="n")

            sep = ttk.Separator(self.inner, orient="horizontal")
            sep.pack(fill="x", pady=(2, 0))

            self.after(0, lambda lab=lbl_left: self._update_wrap(lab))

    def _update_wrap(self, label: ttk.Label) -> None:
        try:
            w = self.canvas.winfo_width()
            if w <= 0:
                return
            # ✅ 左列更宽：大约 55% 宽
            target = max(360, int(w * 0.55) - 40)
            label.configure(wraplength=target)
        except Exception:
            pass

    def _set_image(self, label: ttk.Label, key: str, img_path: str) -> None:
        if Image is None or ImageTk is None:
            label.configure(text="（未安装 Pillow）")
            return
        if not img_path:
            label.configure(text="（无截图）")
            return

        p = Path(img_path)
        if not p.exists():
            label.configure(text="（截图不存在）")
            return

        try:
            im = Image.open(str(p))
            # ✅ 中列更像“2/4”：尺寸给大一点，但不把行高撑爆
            max_w = 560
            max_h = 160
            im.thumbnail((max_w, max_h))

            ph = ImageTk.PhotoImage(im)
            self._img_refs[key] = ph
            label.configure(image=ph, text="")
        except Exception:
            label.configure(text="（截图加载失败）")

    def _select_all(self) -> None:
        for it in self.items:
            self.selected[it.key] = True
        self._render_rows()

    def _select_none(self) -> None:
        for it in self.items:
            self.selected[it.key] = False
        self._render_rows()

    def _finish(self) -> None:
        self.destroy()


def review_items(master: tk.Tk, items: List[ReviewItem]) -> Dict[str, bool]:
    win = ReviewWindow(master, items)
    master.wait_window(win)
    return win.selected
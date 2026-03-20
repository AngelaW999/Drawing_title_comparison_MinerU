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
    index_title: str
    index_marker: str
    drawing_title: str
    drawing_marker: str
    title_source: str
    screenshot_path: str
    marker_screenshot_path: str = ""
    auto_selected: bool = False


def _norm(text: str) -> str:
    return (text or "").strip()


def _display_diff_type(diff_type: str) -> str:
    return (diff_type or "").replace("marker", "分段号")


def _build_left_text(it: ReviewItem) -> str:
    file_name = Path(it.pdf_path).name if it.pdf_path else ""
    lines = [
        f"{_display_diff_type(it.diff_type)} | 图号={it.drawing_num} | {file_name}".strip(),
        f"目录标题：{_norm(it.index_title)}",
        f"目录分段号：{_norm(it.index_marker)}",
        f"图纸标题：{_norm(it.drawing_title)}",
        f"图纸分段号：{_norm(it.drawing_marker)}",
    ]
    return "\n".join(lines)


class ReviewWindow(tk.Toplevel):
    def __init__(self, master: tk.Tk, items: List[ReviewItem], title: str = "差异复核"):
        super().__init__(master)
        self.title(title)
        self.geometry("1380x760")
        self.configure(bg="#eef6ff")

        self.items = items
        self.selected: Dict[str, bool] = {it.key: False for it in items}
        self._img_refs: Dict[str, object] = {}
        self._configure_theme()
        self._build_ui()
        self._render_rows()

    def _configure_theme(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        bg = "#eef6ff"
        panel = "#fbfdff"
        border = "#1f5f9e"
        text = "#16324f"
        muted = "#4f6b88"
        button_bg = "#f2f5f9"
        button_active = "#e5edf7"

        style.configure(".", background=bg, foreground=text)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=text)
        style.configure("TCheckbutton", background=bg, foreground=text)
        style.configure(
            "TScrollbar",
            background="#dcecff",
            troughcolor=panel,
            bordercolor=border,
            arrowcolor=text,
        )
        style.configure(
            "Big.TButton",
            font=("Microsoft YaHei UI", 11),
            padding=(18, 10),
            background=button_bg,
            foreground=text,
            bordercolor="#9db4cc",
            lightcolor=button_bg,
            darkcolor=button_active,
            focusthickness=1,
            focuscolor=border,
        )
        style.map(
            "Big.TButton",
            background=[("active", button_active), ("disabled", "#dfe7f1")],
            foreground=[("disabled", muted)],
        )

    def _build_ui(self) -> None:
        self.var_tip = tk.StringVar(value=f"共 {len(self.items)} 条（默认不勾选；勾选后导出）")
        ttk.Label(self, textvariable=self.var_tip, font=("Microsoft YaHei UI", 11, "bold")).pack(
            anchor="w", padx=12, pady=(10, 6)
        )

        hdr = ttk.Frame(self)
        hdr.pack(fill="x", padx=12)
        hdr.columnconfigure(0, weight=5)
        hdr.columnconfigure(1, weight=3)
        hdr.columnconfigure(2, weight=1)

        ttk.Label(hdr, text="目录/图纸对比").grid(row=0, column=0, sticky="w")
        ttk.Label(hdr, text="截图").grid(row=0, column=1)
        ttk.Label(hdr, text="不一致").grid(row=0, column=2)

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True, padx=12, pady=(6, 10))

        self.canvas = tk.Canvas(wrap, highlightthickness=0, bg="#eef6ff")
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
        ttk.Button(bot, text="全不选", style="Big.TButton", command=self._select_none).pack(side="left")
        ttk.Button(bot, text="全选", style="Big.TButton", command=self._select_all).pack(side="left", padx=10)
        ttk.Button(bot, text="保存并关闭", style="Big.TButton", command=self._finish).pack(side="right")

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
        for child in self.inner.winfo_children():
            child.destroy()
        self._img_refs.clear()

        if not self.items:
            ttk.Label(self.inner, text="没有需要复核的条目").pack(anchor="w")
            return

        for it in self.items:
            row = ttk.Frame(self.inner)
            row.pack(fill="x", pady=6)
            row.columnconfigure(0, weight=5)
            row.columnconfigure(1, weight=3)
            row.columnconfigure(2, weight=1)

            lbl_left = ttk.Label(row, text=_build_left_text(it), justify="left", anchor="w")
            lbl_left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

            img_cell = ttk.Frame(row)
            img_cell.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
            title_diff = "标题" in _display_diff_type(it.diff_type)
            marker_only = _display_diff_type(it.diff_type) == "marker不一致"
            if title_diff or not marker_only:
                title_wrap = ttk.Frame(img_cell)
                title_wrap.pack(fill="both", expand=True)
                ttk.Label(title_wrap, text="标题截图", anchor="w").pack(side="left", padx=(0, 10))
                title_lbl = ttk.Label(title_wrap, text="", anchor="center")
                title_lbl.pack(side="left", fill="both", expand=True)
                self._set_image(title_lbl, f"{it.key}_title", it.screenshot_path, (560, 180))

            if marker_only and it.marker_screenshot_path:
                marker_wrap = ttk.Frame(img_cell)
                marker_wrap.pack(fill="both", expand=True, pady=(6, 0))
                ttk.Label(marker_wrap, text="marker截图", anchor="w").pack(side="left", padx=(0, 10))
                marker_lbl = ttk.Label(marker_wrap, text="", anchor="center")
                marker_lbl.pack(side="left", fill="both", expand=True)
                self._set_image(marker_lbl, f"{it.key}_marker", it.marker_screenshot_path, (280, 160))

            var = tk.BooleanVar(value=self.selected.get(it.key, False))

            def _on_toggle(k=it.key, v=var):
                self.selected[k] = bool(v.get())

            check_wrap = ttk.Frame(row)
            check_wrap.grid(row=0, column=2, sticky="nsew")
            tk.Checkbutton(
                check_wrap,
                variable=var,
                command=_on_toggle,
                bg="#eef6ff",
                activebackground="#eef6ff",
                selectcolor="#fbfdff",
                highlightthickness=0,
                bd=0,
                padx=6,
                pady=6,
                indicatoron=True,
                relief="flat",
                font=("Microsoft YaHei UI", 13),
            ).pack(expand=True)
            ttk.Separator(self.inner, orient="horizontal").pack(fill="x", pady=(2, 0))

            self.after(0, lambda lab=lbl_left: self._update_wrap(lab))

    def _update_wrap(self, label: ttk.Label) -> None:
        try:
            w = self.canvas.winfo_width()
            if w <= 0:
                return
            label.configure(wraplength=max(420, int(w * 0.52) - 40))
        except Exception:
            pass

    def _set_image(self, label: ttk.Label, key: str, img_path: str, max_size: tuple[int, int]) -> None:
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
            im.thumbnail(max_size)
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

# src/app_gui.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
import ctypes
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import END, IntVar, StringVar, Text, Tk, filedialog, messagebox, ttk
import fitz

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

from src.ocr.token_provider import MinerUTokenError, get_mineru_token, set_mineru_token
from src.pipeline.compare_folder import build_review_items, write_final_excel
from src.process_cache import cleanup_generated_cache_files
from src.review_ui import review_items


def _runtime_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[1]


def _icon_candidates() -> list[Path]:
    runtime_root = _runtime_root()
    project_root = Path(__file__).resolve().parents[1]
    return [
        runtime_root / "assets" / "icon.ico",
        runtime_root / "assets" / "icon.png",
        project_root / "assets" / "icon.ico",
        project_root / "assets" / "icon.png",
    ]


def _apply_icon_to_window(window: tk.Tk | tk.Toplevel) -> None:
    for icon_path in _icon_candidates():
        if not icon_path.exists():
            continue
        try:
            if icon_path.suffix.lower() == ".ico":
                window.iconbitmap(default=str(icon_path))
                return
            image = tk.PhotoImage(file=str(icon_path))
            window.iconphoto(True, image)
            setattr(window, "_icon_image", image)
            return
        except Exception:
            continue


def _find_token_help_pdf() -> Path | None:
    runtime_root = _runtime_root()
    project_root = Path(__file__).resolve().parents[1]
    candidates = [
        runtime_root / "assets" / "Token获取方法.pdf",
        project_root / "assets" / "Token获取方法.pdf",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _open_pdf_viewer(master: tk.Tk | tk.Toplevel, pdf_path: Path, title: str) -> None:
    win = tk.Toplevel(master)
    win.title(title)
    win.geometry("920x760")
    win.configure(bg="#eef6ff")
    _apply_icon_to_window(win)

    header = ttk.Frame(win)
    header.pack(fill="x", padx=12, pady=(12, 6))
    ttk.Label(header, text=title, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")

    wrap = ttk.Frame(win)
    wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    canvas = tk.Canvas(wrap, bg="#eef6ff", highlightthickness=0)
    vbar = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vbar.set)
    vbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    inner = ttk.Frame(canvas)
    inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_configure(_evt=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(evt=None) -> None:
        if evt is not None:
            canvas.itemconfigure(inner_id, width=evt.width)

    inner.bind("<Configure>", _on_inner_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    if Image is None or ImageTk is None:
        ttk.Label(inner, text="当前环境未安装 Pillow，无法预览 PDF。").pack(anchor="w")
        return

    try:
        doc = fitz.open(str(pdf_path))
        photo_refs: list[object] = []
        for page_index in range(doc.page_count):
            page = doc[page_index]
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            photo = ImageTk.PhotoImage(image)
            photo_refs.append(photo)

            page_wrap = ttk.Frame(inner)
            page_wrap.pack(fill="x", pady=(0, 12))
            ttk.Label(page_wrap, text=f"第 {page_index + 1} 页", foreground="#4f6b88").pack(anchor="w", pady=(0, 4))
            ttk.Label(page_wrap, image=photo).pack(anchor="center")
        setattr(win, "_photo_refs", photo_refs)
        doc.close()
    except Exception as exc:
        ttk.Label(inner, text=f"PDF 预览失败：{exc}").pack(anchor="w")


def _set_windows_app_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DrawingTitleCompareTool")
    except Exception:
        pass


INPUT_MODE_OPTIONS = {
    "\u6587\u4ef6\u5939\uff08\u7b2c\u4e00\u4e2a\u6587\u4ef6\u662f\u76ee\u5f55\uff09": "folder",
    "\u5355\u4e00\u5408\u5e76\u6587\u6863": "single_pdf",
}


def build_unique_output_path(out_dir: Path, input_dir: Path) -> Path:
    """
    输出文件名：
      {输入文件夹名}_diff.xlsx
      如果已存在则自动递增：
      {输入文件夹名}_diff_2.xlsx / _3.xlsx ...
    """
    out_dir = Path(out_dir)
    input_path = Path(input_dir)
    base_name = (input_path.stem if input_path.is_file() else input_path.name).strip() or "output"

    i = 1
    while True:
        suffix = "" if i == 1 else f"_{i}"
        p = out_dir / f"{base_name}_问题{suffix}.xlsx"
        if not p.exists():
            return p
        i += 1


def prompt_token(master: tk.Tk, reason: str = "") -> str:
    win = tk.Toplevel(master)
    win.title("\u8bbe\u7f6e MinerU Token")
    win.geometry("760x280")
    win.grab_set()
    win.configure(bg="#eef6ff")
    _apply_icon_to_window(win)

    tip = "请输入MinerU Token （会保存到本机，下次自动使用）。"

    style = ttk.Style(win)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Token.TFrame", background="#eef6ff")
    style.configure("Token.TLabel", background="#eef6ff", foreground="#16324f")
    style.configure(
        "Token.TEntry",
        fieldbackground="#f7fbff",
        foreground="#16324f",
        bordercolor="#1f5f9e",
        lightcolor="#1f5f9e",
        darkcolor="#1f5f9e",
        insertcolor="#16324f",
    )
    style.configure(
        "Token.TButton",
        background="#f2f5f9",
        foreground="#16324f",
        bordercolor="#9db4cc",
        lightcolor="#f2f5f9",
        darkcolor="#e5edf7",
        focusthickness=1,
        focuscolor="#1f5f9e",
        padding=(12, 6),
    )
    style.map(
        "Token.TButton",
        background=[("active", "#e5edf7"), ("disabled", "#dfe7f1")],
        foreground=[("disabled", "#6d86a1")],
    )

    container = ttk.Frame(win, style="Token.TFrame")
    container.pack(fill="both", expand=True, padx=16, pady=16)

    ttk.Label(
        container,
        text=tip,
        style="Token.TLabel",
        justify="left",
        anchor="w",
        wraplength=700,
    ).pack(fill="x", pady=(0, 10))

    var = tk.StringVar(value="")
    ent = ttk.Entry(container, textvariable=var, width=110, style="Token.TEntry")
    ent.pack(fill="x", pady=(0, 10))
    ent.focus_set()

    out = {"token": ""}

    def on_ok() -> None:
        token = (var.get() or "").strip()
        if not token:
            messagebox.showerror("\u9519\u8bef", "Token \u4e0d\u80fd\u4e3a\u7a7a")
            return
        out["token"] = token
        win.destroy()

    def on_cancel() -> None:
        out["token"] = ""
        win.destroy()

    def on_help() -> None:
        pdf_path = _find_token_help_pdf()
        if not pdf_path:
            messagebox.showerror("错误", "未找到 Token 获取说明 PDF。", parent=win)
            return
        _open_pdf_viewer(win, pdf_path, "如何获取 Token")

    btn_row = ttk.Frame(container, style="Token.TFrame")
    btn_row.pack(fill="x", pady=(6, 0))

    ttk.Button(btn_row, text="如何获取Token", style="Token.TButton", command=on_help).pack(side="left")
    ttk.Button(btn_row, text="\u4fdd\u5b58", style="Token.TButton", command=on_ok).pack(side="right")
    ttk.Button(btn_row, text="\u53d6\u6d88", style="Token.TButton", command=on_cancel).pack(side="right", padx=8)

    master.wait_window(win)
    return out["token"]


@dataclass
class AppState:
    input_path: Path
    output_dir: Path
    max_drawings: int | None
    input_mode: str


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command=None,
        width: int = 96,
        height: int = 34,
        radius: int = 12,
        bg_color: str = "#f2f5f9",
        bg_active: str = "#e5edf7",
        bg_disabled: str = "#dfe7f1",
        fg_color: str = "#16324f",
        fg_disabled: str = "#6d86a1",
        border_color: str = "#9db4cc",
        font: tuple[str, int] = ("Microsoft YaHei UI", 10),
        **kwargs,
    ) -> None:
        canvas_bg = self._resolve_master_bg(master)
        super().__init__(
            master,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=canvas_bg,
            **kwargs,
        )
        self._text = text
        self._command = command
        self._width = width
        self._height = height
        self._radius = min(radius, height // 2)
        self._bg_color = bg_color
        self._bg_active = bg_active
        self._bg_disabled = bg_disabled
        self._fg_color = fg_color
        self._fg_disabled = fg_disabled
        self._border_color = border_color
        self._font = font
        self._state = "normal"
        self._pressed = False

        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._hover = False
        self._redraw()

    @staticmethod
    def _resolve_master_bg(master: tk.Misc) -> str:
        try:
            return str(master.cget("bg"))
        except Exception:
            pass

        try:
            style = ttk.Style(master)
            bg = style.lookup(master.winfo_class(), "background")
            if bg:
                return str(bg)
        except Exception:
            pass

        return "#eef6ff"

    def _rounded_points(self, x1: int, y1: int, x2: int, y2: int, r: int) -> list[int]:
        return [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]

    def _current_bg(self) -> str:
        if self._state == "disabled":
            return self._bg_disabled
        if self._pressed or self._hover:
            return self._bg_active
        return self._bg_color

    def _current_fg(self) -> str:
        return self._fg_disabled if self._state == "disabled" else self._fg_color

    def _redraw(self) -> None:
        self.delete("all")
        points = self._rounded_points(1, 1, self._width - 2, self._height - 2, self._radius)
        self.create_polygon(
            points,
            smooth=True,
            splinesteps=24,
            fill=self._current_bg(),
            outline=self._border_color,
            width=1.5,
        )
        self.create_text(
            self._width // 2,
            self._height // 2,
            text=self._text,
            fill=self._current_fg(),
            font=self._font,
        )

    def _on_press(self, _event) -> None:
        if self._state == "disabled":
            return
        self._pressed = True
        self._redraw()

    def _on_release(self, event) -> None:
        if self._state == "disabled":
            return
        was_pressed = self._pressed
        self._pressed = False
        self._redraw()
        if was_pressed:
            item = self.find_withtag("current")
            if item or (0 <= event.x <= self._width and 0 <= event.y <= self._height):
                if self._command:
                    self._command()

    def _on_enter(self, _event) -> None:
        if self._state == "disabled":
            return
        self._hover = True
        self._redraw()

    def _on_leave(self, _event) -> None:
        self._hover = False
        self._pressed = False
        self._redraw()

    def config(self, **kwargs) -> None:
        if "state" in kwargs:
            self._state = kwargs.pop("state")
        if "text" in kwargs:
            self._text = kwargs.pop("text")
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        if kwargs:
            super().config(**kwargs)
        self._redraw()

    configure = config


class App(Tk):
    def __init__(self) -> None:
        _set_windows_app_id()
        super().__init__()
        self.title("目录图纸标题对比工具")
        self.geometry("980x620")
        self.configure(bg="#eef6ff")

        self._icon_image = None
        self._apply_window_icon()
        self._configure_theme()

        self._input_var = StringVar(value="")
        self._output_var = StringVar(value="")
        self._max_var = IntVar(value=0)
        self._input_mode_var = StringVar(value="\u6587\u4ef6\u5939\uff08\u7b2c\u4e00\u4e2a\u6587\u4ef6\u662f\u76ee\u5f55\uff09")

        self._running = False
        self._worker_done = False
        self._log_queue: queue.SimpleQueue[str] = queue.SimpleQueue()

        self._btn_run: RoundedButton | None = None
        self._btn_open_out: RoundedButton | None = None
        self._btn_token: RoundedButton | None = None
        self._progress: ttk.Progressbar | None = None
        self._log: Text | None = None

        self._done_payload: dict | None = None
        self._error_payload: str | None = None

        self._build_ui()

    def _apply_window_icon(self) -> None:
        for icon_path in _icon_candidates():
            if not icon_path.exists():
                continue
            try:
                if icon_path.suffix.lower() == ".ico":
                    self.iconbitmap(default=str(icon_path))
                    return
                image = tk.PhotoImage(file=str(icon_path))
                self.iconphoto(True, image)
                self._icon_image = image
                return
            except Exception:
                continue

    def _configure_theme(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        bg = "#eef6ff"
        panel = "#f7fbff"
        border = "#1f5f9e"
        accent = "#6fb4f5"
        accent_active = "#58a6ee"
        text = "#16324f"
        muted = "#4f6b88"

        style.configure(".", background=bg, foreground=text)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=text)
        style.configure(
            "TEntry",
            fieldbackground=panel,
            foreground=text,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            insertcolor=text,
        )
        style.configure(
            "TCombobox",
            fieldbackground=panel,
            foreground=text,
            bordercolor=border,
            lightcolor=border,
            darkcolor=border,
            arrowsize=14,
            arrowcolor=text,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", panel)],
            selectbackground=[("readonly", panel)],
            selectforeground=[("readonly", text)],
        )
        style.configure(
            "TButton",
            background=accent,
            foreground=text,
            bordercolor=border,
            lightcolor=accent,
            darkcolor=accent_active,
            focusthickness=1,
            focuscolor=accent_active,
            padding=(10, 6),
        )
        style.map(
            "TButton",
            background=[("active", accent_active), ("disabled", "#d9e8f7")],
            foreground=[("disabled", muted)],
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#dcecff",
            background="#39a0ed",
            bordercolor=border,
            lightcolor="#8ec9fb",
            darkcolor="#39a0ed",
        )

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 8}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, **pad)

        label_width = 32
        input_padx = 8

        row0 = ttk.Frame(frm)
        row0.pack(fill="x", pady=(10, 0))
        ttk.Label(row0, text="输入方式:", width=label_width).pack(side="left")
        ttk.Combobox(
            row0,
            textvariable=self._input_mode_var,
            state="readonly",
            width=28,
            values=tuple(INPUT_MODE_OPTIONS.keys()),
        ).pack(side="left", padx=input_padx)

        row1 = ttk.Frame(frm)
        row1.pack(fill="x")
        ttk.Label(
            row1,
            text="输入路径:",
            width=label_width,
        ).pack(side="left")
        ttk.Entry(row1, textvariable=self._input_var).pack(side="left", fill="x", expand=True, padx=input_padx)
        RoundedButton(row1, text="选择...", command=self._pick_input, width=84, height=31, radius=11).pack(
            side="left"
        )

        row2 = ttk.Frame(frm)
        row2.pack(fill="x", pady=(0, 8))
        ttk.Label(row2, text="输出文件夹:", width=label_width).pack(side="left")
        ttk.Entry(row2, textvariable=self._output_var).pack(side="left", fill="x", expand=True, padx=input_padx)
        RoundedButton(row2, text="选择...", command=self._pick_output, width=84, height=31, radius=11).pack(
            side="left"
        )

        ttk.Label(
            frm,
            text="\u63d0\u793a\uff1a\u56fe\u50cf\u8bc6\u522b\u4e0d\u80fd\u4fdd\u8bc1 100% \u7684\u6b63\u786e\u7387\uff0c\u8bf7\u6838\u5bf9\u539f\u59cb\u76ee\u5f55\u548c\u56fe\u7eb8\u3002",
            foreground="#4f6b88",
        ).pack(anchor="w", pady=(0, 8))

        row4 = ttk.Frame(frm)
        row4.pack(fill="x", pady=(10, 0))

        self._btn_run = RoundedButton(row4, text="\u5f00\u59cb", command=self._on_run_clicked, width=84, height=34, radius=12)
        self._btn_run.pack(side="left")

        self._btn_open_out = RoundedButton(
            row4,
            text="\u6253\u5f00\u8f93\u51fa\u76ee\u5f55",
            command=self._open_output,
            width=110,
            height=34,
            radius=12,
        )
        self._btn_open_out.config(state="disabled")
        self._btn_open_out.pack(side="left", padx=10)

        self._btn_token = RoundedButton(
            row4,
            text="\u8bbe\u7f6e/\u66f4\u65b0 Token",
            command=self._on_set_token,
            width=132,
            height=34,
            radius=12,
        )
        self._btn_token.pack(side="left")

        row5 = ttk.Frame(frm)
        row5.pack(fill="x", pady=(10, 0))
        self._progress = ttk.Progressbar(row5, mode="indeterminate")
        self._progress.pack(fill="x", expand=True)

        ttk.Label(frm, text="日志:").pack(anchor="w", pady=(12, 0))
        self._log = Text(frm, height=22)
        self._log.configure(
            bg="#fbfdff",
            fg="#16324f",
            insertbackground="#16324f",
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#b8d4f0",
            highlightcolor="#7db7ee",
        )
        self._log.pack(fill="both", expand=True, pady=(6, 0))

        ttk.Label(
            frm,
            text="\u63d0\u793a\uff1aToken \u8fc7\u671f\u6216\u672a\u914d\u7f6e\u65f6\u4f1a\u5f39\u7a97\u8981\u6c42\u91cd\u65b0\u8f93\u5165\u3002",
            foreground="#555555",
        ).pack(anchor="w", pady=(8, 0))

    def _pick_input(self) -> None:
        input_mode = INPUT_MODE_OPTIONS.get(self._input_mode_var.get().strip(), "folder")
        if input_mode == "single_pdf":
            path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        else:
            path = filedialog.askdirectory()
        if path:
            self._input_var.set(path)

    def _pick_output(self) -> None:
        path = filedialog.askdirectory()
        if path:
            self._output_var.set(path)

    def _open_output(self) -> None:
        out = self._output_var.get().strip()
        if not out:
            return
        try:
            os.startfile(out)  # type: ignore[attr-defined]
        except Exception:
            messagebox.showinfo("\u63d0\u793a", f"\u8bf7\u624b\u52a8\u6253\u5f00\uff1a{out}")

    def _append_log(self, msg: str) -> None:
        if not self._log:
            return
        self._log.insert(END, msg + "\n")
        self._log.see(END)
        self.update_idletasks()

    def _queue_log(self, msg: str) -> None:
        self._log_queue.put(msg)

    def _flush_log_queue(self) -> None:
        while True:
            try:
                msg = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(msg)

    def _clear_log(self) -> None:
        if self._log:
            self._log.delete("1.0", END)

    def _set_running(self, running: bool) -> None:
        self._running = running
        if self._btn_run and self._btn_open_out and self._progress:
            if running:
                self._btn_run.config(state="disabled")
                self._btn_open_out.config(state="disabled")
                self._progress.start(10)
            else:
                self._btn_run.config(state="normal")
                self._btn_open_out.config(state="normal")
                self._progress.stop()

    def _validate(self) -> AppState:
        inp = self._input_var.get().strip()
        out = self._output_var.get().strip()
        input_mode = INPUT_MODE_OPTIONS.get(self._input_mode_var.get().strip(), "folder")
        if not inp:
            raise ValueError("\u8bf7\u9009\u62e9\u8f93\u5165\u8def\u5f84")
        if not out:
            raise ValueError("\u8bf7\u9009\u62e9\u8f93\u51fa\u6587\u4ef6\u5939")

        input_path = Path(inp)
        output_dir = Path(out)
        if input_mode == "single_pdf":
            if not input_path.exists() or not input_path.is_file() or input_path.suffix.lower() != ".pdf":
                raise ValueError(f"\u8f93\u5165 PDF \u4e0d\u5b58\u5728\u6216\u4e0d\u662f PDF \u6587\u4ef6\uff1a{input_path}")
        else:
            if not input_path.exists() or not input_path.is_dir():
                raise ValueError(f"\u8f93\u5165\u6587\u4ef6\u5939\u4e0d\u5b58\u5728\uff1a{input_path}")

        return AppState(input_path=input_path, output_dir=output_dir, max_drawings=None, input_mode=input_mode)

    def _ensure_token(self) -> bool:
        try:
            _ = get_mineru_token()
            return True
        except MinerUTokenError:
            new_token = prompt_token(self, reason="\u672a\u68c0\u6d4b\u5230 MinerU Token")
            if not new_token:
                return False
            set_mineru_token(new_token, persist=True)
            return True

    def _on_set_token(self) -> None:
        new_token = prompt_token(self, reason="\u8bf7\u8f93\u5165\u65b0\u7684 MinerU Token\uff08\u4f1a\u4fdd\u5b58\u5230\u672c\u673a\u914d\u7f6e\uff09")
        if not new_token:
            return
        try:
            set_mineru_token(new_token, persist=True)
            messagebox.showinfo("\u5b8c\u6210", "Token \u5df2\u66f4\u65b0\u5e76\u4fdd\u5b58\u3002")
        except Exception as exc:
            messagebox.showerror("\u5931\u8d25", str(exc))

    def _on_run_clicked(self) -> None:
        if self._running:
            return

        try:
            state = self._validate()
        except Exception as exc:
            messagebox.showerror("\u53c2\u6570\u9519\u8bef", str(exc))
            return

        if not self._ensure_token():
            messagebox.showinfo("\u5df2\u53d6\u6d88", "\u672a\u8bbe\u7f6e Token\uff0c\u4efb\u52a1\u7ec8\u6b62\u3002")
            return

        self._clear_log()
        self._set_running(True)
        self._done_payload = None
        self._error_payload = None
        self._worker_done = False

        def worker() -> None:
            try:
                self._queue_log("开始处理...")
                items = build_review_items(
                    folder=state.input_path,
                    max_drawings=state.max_drawings,
                    log_cb=self._queue_log,
                    input_mode=state.input_mode,
                )
                self._done_payload = {"state": state, "items": items}
            except Exception as exc:
                msg = str(exc).lower()
                if "401 client error: unauthorized" in msg or (
                    "unauthorized" in msg and "file-urls/batch" in msg
                ):
                    self._error_payload = "Token 需要更新，请点击“设置/更新 Token”后重试。"
                else:
                    self._error_payload = traceback.format_exc()
                if "token not configured" in msg or "unauthorized" in msg or "401" in msg or "403" in msg:
                    self._done_payload = {"need_token_refresh": True}
            finally:
                self._worker_done = True

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_worker)

    def _poll_worker(self) -> None:
        self._flush_log_queue()
        if self._worker_done:
            self._on_worker_done()
            return
        if self._running:
            self.after(100, self._poll_worker)

    def _on_worker_done(self) -> None:
        try:
            self._flush_log_queue()

            if self._error_payload:
                self._append_log(self._error_payload)
                messagebox.showerror("运行失败", self._error_payload)
                return

            payload = self._done_payload or {}
            if payload.get("need_token_refresh"):
                token = prompt_token(self, reason="Token 需要更新，请粘贴新的 Token 后重试。")
                if token:
                    set_mineru_token(token, persist=True)
                    messagebox.showinfo("\u63d0\u793a", "Token \u5df2\u66f4\u65b0\u3002\u8bf7\u91cd\u65b0\u70b9\u51fb\u201c\u5f00\u59cb\u201d\u3002")
                return

            state: AppState = payload["state"]
            items = payload.get("items", [])

            if not items:
                self._append_log("\u6ca1\u6709\u9700\u8981\u590d\u6838/\u5bfc\u51fa\u7684\u6761\u76ee\uff08\u65e0\u5dee\u5f02\u6216\u65e0\u95ee\u9898\uff09\u3002")
                messagebox.showinfo("\u5b8c\u6210", "\u6ca1\u6709\u9700\u8981\u590d\u6838/\u5bfc\u51fa\u7684\u6761\u76ee\uff08\u65e0\u5dee\u5f02\u6216\u65e0\u95ee\u9898\uff09\u3002")
                return

            review_list = [it for it in items if not getattr(it, "auto_selected", False)]
            auto_count = len(items) - len(review_list)

            self._append_log("")
            self._append_log(f"\u9700\u8981\u4eba\u5de5\u590d\u6838\uff1a{len(review_list)} \u6761\uff1b\u81ea\u52a8\u5bfc\u51fa\uff1a{auto_count} \u6761\uff08\u56fe\u7eb8\u7f3a\u5931\uff09")

            selected_map: dict[str, bool] = {}
            if review_list:
                selected_map = review_items(self, review_list)

            out_xlsx = build_unique_output_path(state.output_dir, state.input_path)
            exported = write_final_excel(out_xlsx, items, selected_map, input_mode=state.input_mode)
            cleaned_cache = cleanup_generated_cache_files()

            self._append_log("")
            self._append_log("\u5b8c\u6210")
            self._append_log(f"\u8f93\u51fa: {out_xlsx} \uff08\u884c\u6570 {exported}\uff09")
            self._append_log(f"\u6e05\u7406\u672c\u6b21\u8fdb\u7a0b\u751f\u6210\u7684 cache \u6587\u4ef6: {cleaned_cache}")

            messagebox.showinfo("\u5b8c\u6210", f"\u5df2\u5b8c\u6210\u3002\n\n\u8f93\u51fa\uff1a{out_xlsx}\n\u5bfc\u51fa\u884c\u6570\uff1a{exported}\n\u6e05\u7406 cache \u6587\u4ef6\uff1a{cleaned_cache}")
        finally:
            self._set_running(False)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

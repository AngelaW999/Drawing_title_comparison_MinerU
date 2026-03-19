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


def _set_windows_app_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DrawingTitleCompareTool")
    except Exception:
        pass


def build_unique_output_path(out_dir: Path, input_dir: Path) -> Path:
    """
    输出文件名：
      {输入文件夹名}_diff.xlsx
      如果已存在则自动递增：
      {输入文件夹名}_diff_2.xlsx / _3.xlsx ...
    """
    out_dir = Path(out_dir)
    base_name = Path(input_dir).name.strip() or "output"

    i = 1
    while True:
        suffix = "" if i == 1 else f"_{i}"
        p = out_dir / f"{base_name}_diff{suffix}.xlsx"
        if not p.exists():
            return p
        i += 1


def prompt_token(master: tk.Tk, reason: str = "") -> str:
    win = tk.Toplevel(master)
    win.title("设置 MinerU Token")
    win.geometry("760x240")
    win.grab_set()

    tip = "请输入 MinerU Token（会保存到本机，下次自动使用）。"
    if reason:
        tip = f"{reason}\n\n{tip}"

    tk.Label(win, text=tip, justify="left", anchor="w", wraplength=730).pack(
        fill="x", padx=12, pady=(12, 8)
    )

    var = tk.StringVar(value="")
    ent = tk.Entry(win, textvariable=var, width=110)
    ent.pack(fill="x", padx=12, pady=(0, 8))
    ent.focus_set()

    out = {"token": ""}

    def on_ok() -> None:
        token = (var.get() or "").strip()
        if not token:
            messagebox.showerror("错误", "Token 不能为空")
            return
        out["token"] = token
        win.destroy()

    def on_cancel() -> None:
        out["token"] = ""
        win.destroy()

    btn_row = tk.Frame(win)
    btn_row.pack(fill="x", padx=12, pady=10)

    tk.Button(btn_row, text="保存", command=on_ok, width=10).pack(side="right")
    tk.Button(btn_row, text="取消", command=on_cancel, width=10).pack(side="right", padx=8)

    master.wait_window(win)
    return out["token"]


@dataclass
class AppState:
    input_dir: Path
    output_dir: Path
    max_drawings: int | None


class App(Tk):
    def __init__(self) -> None:
        _set_windows_app_id()
        super().__init__()
        self.title("目录图纸标题对比工具")
        self.geometry("980x620")

        self._icon_image = None
        self._apply_window_icon()

        self._input_var = StringVar(value="")
        self._output_var = StringVar(value="")
        self._max_var = IntVar(value=0)

        self._running = False
        self._worker_done = False
        self._log_queue: queue.SimpleQueue[str] = queue.SimpleQueue()

        self._btn_run: ttk.Button | None = None
        self._btn_open_out: ttk.Button | None = None
        self._btn_token: ttk.Button | None = None
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

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 8}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, **pad)

        row0 = ttk.Frame(frm)
        row0.pack(fill="x")
        ttk.Label(
            row0,
            text="输入文件夹（第一个 PDF=目录页，其余=图纸）:",
            width=36,
        ).pack(side="left")
        ttk.Entry(row0, textvariable=self._input_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row0, text="选择...", command=self._pick_input).pack(side="left")

        row1 = ttk.Frame(frm)
        row1.pack(fill="x")
        ttk.Label(row1, text="输出文件夹:", width=36).pack(side="left")
        ttk.Entry(row1, textvariable=self._output_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row1, text="选择...", command=self._pick_output).pack(side="left")

        row2 = ttk.Frame(frm)
        row2.pack(fill="x")
        ttk.Label(row2, text="最多处理图纸张数（0=不限）:", width=36).pack(side="left")
        ttk.Entry(row2, textvariable=self._max_var, width=12).pack(side="left")
        ttk.Label(row2, text="").pack(side="left", fill="x", expand=True)

        row3 = ttk.Frame(frm)
        row3.pack(fill="x", pady=(10, 0))

        self._btn_run = ttk.Button(row3, text="开始", command=self._on_run_clicked)
        self._btn_run.pack(side="left")

        self._btn_open_out = ttk.Button(
            row3,
            text="打开输出目录",
            command=self._open_output,
            state="disabled",
        )
        self._btn_open_out.pack(side="left", padx=10)

        self._btn_token = ttk.Button(row3, text="设置/更新 Token", command=self._on_set_token)
        self._btn_token.pack(side="left")

        row4 = ttk.Frame(frm)
        row4.pack(fill="x", pady=(10, 0))
        self._progress = ttk.Progressbar(row4, mode="indeterminate")
        self._progress.pack(fill="x", expand=True)

        ttk.Label(frm, text="日志:").pack(anchor="w", pady=(12, 0))
        self._log = Text(frm, height=22)
        self._log.pack(fill="both", expand=True, pady=(6, 0))

        ttk.Label(
            frm,
            text="提示：Token 过期或未配置时会弹窗要求重新输入。",
            foreground="#555555",
        ).pack(anchor="w", pady=(8, 0))

    def _pick_input(self) -> None:
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
            messagebox.showinfo("提示", f"请手动打开：{out}")

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
        if not inp:
            raise ValueError("请选择输入文件夹")
        if not out:
            raise ValueError("请选择输出文件夹")

        input_dir = Path(inp)
        output_dir = Path(out)
        if not input_dir.exists():
            raise ValueError(f"输入文件夹不存在：{input_dir}")

        max_n = int(self._max_var.get())
        max_drawings = None if max_n <= 0 else max_n
        return AppState(input_dir=input_dir, output_dir=output_dir, max_drawings=max_drawings)

    def _ensure_token(self) -> bool:
        try:
            _ = get_mineru_token()
            return True
        except MinerUTokenError:
            new_token = prompt_token(self, reason="未检测到 MinerU Token")
            if not new_token:
                return False
            set_mineru_token(new_token, persist=True)
            return True

    def _on_set_token(self) -> None:
        new_token = prompt_token(self, reason="请输入新的 MinerU Token（会保存到本机配置）")
        if not new_token:
            return
        try:
            set_mineru_token(new_token, persist=True)
            messagebox.showinfo("完成", "Token 已更新并保存。")
        except Exception as exc:
            messagebox.showerror("失败", str(exc))

    def _on_run_clicked(self) -> None:
        if self._running:
            return

        try:
            state = self._validate()
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        if not self._ensure_token():
            messagebox.showinfo("已取消", "未设置 Token，任务终止。")
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
                    folder=state.input_dir,
                    max_drawings=state.max_drawings,
                    log_cb=self._queue_log,
                )
                self._done_payload = {"state": state, "items": items}
            except Exception as exc:
                self._error_payload = traceback.format_exc()
                msg = str(exc).lower()
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
                token = prompt_token(self, reason="Token 可能已过期或无效，请粘贴新 Token 后重试")
                if token:
                    set_mineru_token(token, persist=True)
                    messagebox.showinfo("提示", "Token 已更新。请重新点击“开始”。")
                return

            state: AppState = payload["state"]
            items = payload.get("items", [])

            if not items:
                self._append_log("没有需要复核/导出的条目（无差异/无问题）。")
                messagebox.showinfo("完成", "没有需要复核/导出的条目（无差异/无问题）。")
                return

            review_list = [it for it in items if not getattr(it, "auto_selected", False)]
            auto_count = len(items) - len(review_list)

            self._append_log("")
            self._append_log(f"需要人工复核：{len(review_list)} 条；自动导出：{auto_count} 条（图纸缺失）")

            selected_map: dict[str, bool] = {}
            if review_list:
                selected_map = review_items(self, review_list)

            out_xlsx = build_unique_output_path(state.output_dir, state.input_dir)
            exported = write_final_excel(out_xlsx, items, selected_map)
            cleaned_cache = cleanup_generated_cache_files()

            self._append_log("")
            self._append_log("完成")
            self._append_log(f"输出: {out_xlsx} （行数={exported}）")
            self._append_log(f"清理本次进程生成的 cache 文件: {cleaned_cache}")

            messagebox.showinfo("完成", f"已完成。\n\n输出：{out_xlsx}\n导出行数：{exported}\n清理 cache 文件：{cleaned_cache}")
        finally:
            self._set_running(False)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

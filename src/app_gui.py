# src/app_gui.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from tkinter import Tk, StringVar, IntVar, Text, END, filedialog, messagebox, ttk
import tkinter as tk

from src.pipeline.compare_folder import build_review_items, write_final_excel
from src.review_ui import review_items

from src.ocr.token_provider import get_mineru_token, set_mineru_token, MinerUTokenError


# ============================================================
# Output naming
# ============================================================
def build_unique_output_path(out_dir: Path, input_dir: Path) -> Path:
    """
    输出文件名：
      {输入文件夹名}_diff.xlsx
      若已存在则自动递增：
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


# ============================================================
# Token dialog (EXE friendly)
# ============================================================
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

    def on_ok():
        t = (var.get() or "").strip()
        if not t:
            messagebox.showerror("错误", "Token 不能为空")
            return
        out["token"] = t
        win.destroy()

    def on_cancel():
        out["token"] = ""
        win.destroy()

    btn_row = tk.Frame(win)
    btn_row.pack(fill="x", padx=12, pady=10)

    tk.Button(btn_row, text="保存", command=on_ok, width=10).pack(side="right")
    tk.Button(btn_row, text="取消", command=on_cancel, width=10).pack(side="right", padx=8)

    master.wait_window(win)
    return out["token"]


# ============================================================
# App
# ============================================================
@dataclass
class AppState:
    input_dir: Path
    output_dir: Path
    max_drawings: int | None


class App(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("目录图纸标题对比小程序")
        self.geometry("980x620")

        self._input_var = StringVar(value="")
        self._output_var = StringVar(value="")
        self._max_var = IntVar(value=0)  # 0 = 不限制

        self._running = False

        self._btn_run: ttk.Button | None = None
        self._btn_open_out: ttk.Button | None = None
        self._btn_token: ttk.Button | None = None
        self._progress: ttk.Progressbar | None = None
        self._log: Text | None = None

        self._done_payload: dict | None = None
        self._error_payload: str | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 8}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, **pad)

        # Input folder
        row0 = ttk.Frame(frm)
        row0.pack(fill="x")
        ttk.Label(row0, text="输入文件夹（第一个PDF=目录页，其余=图纸）:", width=36).pack(side="left")
        ttk.Entry(row0, textvariable=self._input_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row0, text="选择...", command=self._pick_input).pack(side="left")

        # Output folder
        row1 = ttk.Frame(frm)
        row1.pack(fill="x")
        ttk.Label(row1, text="输出文件夹:", width=36).pack(side="left")
        ttk.Entry(row1, textvariable=self._output_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row1, text="选择...", command=self._pick_output).pack(side="left")

        # Max drawings
        row2 = ttk.Frame(frm)
        row2.pack(fill="x")
        ttk.Label(row2, text="最多处理图纸张数（0=不限制）:", width=36).pack(side="left")
        ttk.Entry(row2, textvariable=self._max_var, width=12).pack(side="left")
        ttk.Label(row2, text="").pack(side="left", fill="x", expand=True)

        # Buttons
        row3 = ttk.Frame(frm)
        row3.pack(fill="x", pady=(10, 0))

        self._btn_run = ttk.Button(row3, text="开始", command=self._on_run_clicked)
        self._btn_run.pack(side="left")

        self._btn_open_out = ttk.Button(row3, text="打开输出目录", command=self._open_output, state="disabled")
        self._btn_open_out.pack(side="left", padx=10)

        self._btn_token = ttk.Button(row3, text="设置/更新 Token", command=self._on_set_token)
        self._btn_token.pack(side="left")

        # Progress
        row4 = ttk.Frame(frm)
        row4.pack(fill="x", pady=(10, 0))
        self._progress = ttk.Progressbar(row4, mode="indeterminate")
        self._progress.pack(fill="x", expand=True)

        # Log
        ttk.Label(frm, text="日志：").pack(anchor="w", pady=(12, 0))
        self._log = Text(frm, height=22)
        self._log.pack(fill="both", expand=True, pady=(6, 0))

        ttk.Label(
            frm,
            text="提示：Token 会周期更新；若未配置/失效，会弹窗让你粘贴新 Token。",
            foreground="#555555",
        ).pack(anchor="w", pady=(8, 0))

    def _pick_input(self) -> None:
        p = filedialog.askdirectory()
        if p:
            self._input_var.set(p)

    def _pick_output(self) -> None:
        p = filedialog.askdirectory()
        if p:
            self._output_var.set(p)

    def _open_output(self) -> None:
        out = self._output_var.get().strip()
        if not out:
            return
        try:
            import os
            os.startfile(out)  # type: ignore[attr-defined]
        except Exception:
            messagebox.showinfo("提示", f"请手动打开：{out}")

    def _append_log(self, msg: str) -> None:
        if not self._log:
            return
        self._log.insert(END, msg + "\n")
        self._log.see(END)
        self.update_idletasks()

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

    # ---------- Token ----------
    def _ensure_token(self) -> bool:
        try:
            _ = get_mineru_token()
            return True
        except MinerUTokenError:
            new_t = prompt_token(self, reason="未检测到 MinerU Token")
            if not new_t:
                return False
            set_mineru_token(new_t, persist=True)
            return True

    def _on_set_token(self) -> None:
        new_t = prompt_token(self, reason="请粘贴新的 MinerU Token（会保存到本机配置）")
        if new_t:
            try:
                set_mineru_token(new_t, persist=True)
                messagebox.showinfo("完成", "Token 已更新并保存。")
            except Exception as e:
                messagebox.showerror("失败", str(e))

    # ---------- Run ----------
    def _on_run_clicked(self) -> None:
        if self._running:
            return

        try:
            st = self._validate()
        except Exception as e:
            messagebox.showerror("参数错误", str(e))
            return

        if not self._ensure_token():
            messagebox.showinfo("已取消", "未设置 Token，任务终止。")
            return

        self._clear_log()
        self._set_running(True)
        self._done_payload = None
        self._error_payload = None

        def worker() -> None:
            try:
                self._append_log("开始处理...")

                items = build_review_items(
                    folder=st.input_dir,
                    max_drawings=st.max_drawings,
                    log_cb=self._append_log,
                )

                self._done_payload = {"state": st, "items": items}

            except Exception as e:
                tb = traceback.format_exc()
                self._error_payload = tb

                # 如果是 token 未配置/失效，提示用户更新
                msg = str(e).lower()
                if "token not configured" in msg or "unauthorized" in msg or "401" in msg or "403" in msg:
                    self._done_payload = {"need_token_refresh": True}

            finally:
                self.after(0, self._on_worker_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_worker_done(self) -> None:
        try:
            if self._error_payload:
                self._append_log(self._error_payload)
                messagebox.showerror("运行失败", self._error_payload)
                return

            payload = self._done_payload or {}
            if payload.get("need_token_refresh"):
                t = prompt_token(self, reason="Token 可能已过期/无效，请粘贴新 Token 后重试")
                if t:
                    set_mineru_token(t, persist=True)
                    messagebox.showinfo("提示", "Token 已更新。请重新点击“开始”。")
                return

            st: AppState = payload["state"]
            items = payload.get("items", [])

            if not items:
                self._append_log("没有需要复核/导出的条目（无差异/无问题）。")
                messagebox.showinfo("完成", "没有需要复核/导出的条目（无差异/无问题）。")
                return

            # 只 review auto_selected=False 的（missing_in_drawing 不进复核）
            review_list = [it for it in items if not getattr(it, "auto_selected", False)]
            auto_count = len(items) - len(review_list)

            self._append_log("")
            self._append_log(f"需要人工复核：{len(review_list)} 条；自动导出：{auto_count} 条（图纸缺失）")

            selected_map: dict[str, bool] = {}
            if review_list:
                # ✅ 关闭 Review 窗口后才会返回 selected_map
                selected_map = review_items(self, review_list)

            # ✅ 输出文件名：输入目录名_diff.xlsx（自动递增避免覆盖）
            out_xlsx = build_unique_output_path(st.output_dir, st.input_dir)

            exported = write_final_excel(out_xlsx, items, selected_map)

            self._append_log("")
            self._append_log("完成 ✅")
            self._append_log(f"输出: {out_xlsx} （行数={exported}）")

            messagebox.showinfo("完成", f"已完成。\n\n输出：{out_xlsx}\n导出行数：{exported}")

        finally:
            self._set_running(False)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
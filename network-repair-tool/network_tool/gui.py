"""图形界面 — 基于 tkinter（Python 标准库）。"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable, Optional

from . import __version__
from .detector import NetworkDetector, VALORANT_PROCESS_NAMES, format_report
from .repair import NetworkRepairer, format_repair_report
from .utils import IS_WINDOWS, require_admin, run_command


class NetworkRepairApp:
    """网络检测与修复工具 GUI。"""

    BG = "#1e1e2e"
    PANEL = "#2a2a3d"
    ACCENT = "#89b4fa"
    SUCCESS = "#a6e3a1"
    ERROR = "#f38ba8"
    WARNING = "#fab387"
    TEXT = "#cdd6f4"
    MUTED = "#9399b2"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"网络修复工具 v{__version__}")
        self.root.geometry("960x640")
        self.root.minsize(800, 520)
        self.root.configure(bg=self.BG)

        self.detector = NetworkDetector()
        self.repairer = NetworkRepairer()
        self._task_running = False
        self._monitor_stop = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._log_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        self._build_ui()
        self._poll_log_queue()
        self._update_admin_status()
        self.log("info", "网络修复工具已启动。")
        if not require_admin():
            self.log("warning", "当前未以管理员身份运行，部分修复功能可能失败。")
            self.log("info", "Windows 请右键「以管理员身份运行」启动本工具。")

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=self.BG, foreground=self.ACCENT, font=("Segoe UI", 16, "bold"))
        style.configure("Status.TLabel", background=self.PANEL, foreground=self.TEXT, font=("Segoe UI", 11))
        style.configure("TButton", font=("Segoe UI", 10), padding=6)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=8)

        header = ttk.Frame(self.root, style="TFrame")
        header.pack(fill=tk.X, padx=16, pady=(14, 8))

        ttk.Label(header, text="网络状态检测与修复", style="Title.TLabel").pack(side=tk.LEFT)
        self.status_label = tk.Label(
            header,
            text="● 状态未知",
            bg=self.BG,
            fg=self.MUTED,
            font=("Segoe UI", 11),
        )
        self.status_label.pack(side=tk.RIGHT, padx=8)

        body = ttk.Frame(self.root, style="TFrame")
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_control_panel(body)
        self._build_log_panel(body)

        footer = ttk.Frame(self.root, style="TFrame")
        footer.pack(fill=tk.X, padx=16, pady=(0, 12))
        self.admin_label = tk.Label(footer, text="", bg=self.BG, fg=self.MUTED, font=("Segoe UI", 9))
        self.admin_label.pack(side=tk.LEFT)
        ttk.Label(
            footer,
            text="适用于无畏契约断网场景",
            foreground=self.MUTED,
        ).pack(side=tk.RIGHT)

    def _build_control_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=12)
        panel.grid(row=0, column=0, sticky="nsw", padx=(0, 10))

        self._section_label(panel, "检测")
        ttk.Button(panel, text="检测网络状态", command=self.on_detect, style="Accent.TButton").pack(
            fill=tk.X, pady=(0, 10)
        )

        self._section_label(panel, "修复")
        for text, level in [
            ("自动修复（推荐）", "auto"),
            ("轻量修复", "light"),
            ("中度修复", "medium"),
            ("重度修复", "heavy"),
        ]:
            ttk.Button(panel, text=text, command=lambda lv=level: self.on_repair(lv)).pack(fill=tk.X, pady=2)

        self._section_label(panel, "监控")
        self.monitor_btn = ttk.Button(panel, text="开始无畏契约监控", command=self.on_toggle_monitor)
        self.monitor_btn.pack(fill=tk.X, pady=2)

        interval_frame = ttk.Frame(panel, style="Panel.TFrame")
        interval_frame.pack(fill=tk.X, pady=(4, 10))
        ttk.Label(interval_frame, text="间隔(秒)", background=self.PANEL).pack(side=tk.LEFT)
        self.interval_var = tk.StringVar(value="15")
        ttk.Entry(interval_frame, textvariable=self.interval_var, width=6).pack(side=tk.RIGHT)

        self._section_label(panel, "日志")
        ttk.Button(panel, text="清空日志", command=self.on_clear_log).pack(fill=tk.X, pady=2)
        ttk.Button(panel, text="导出日志", command=self.on_export_log).pack(fill=tk.X, pady=2)

    def _build_log_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        frame.grid(row=0, column=1, sticky="nsew")
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text="运行日志", background=self.PANEL, foreground=self.ACCENT, font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )

        self.log_text = scrolledtext.ScrolledText(
            frame,
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg="#11111b",
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief=tk.FLAT,
            padx=8,
            pady=8,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self.log_text.configure(state=tk.DISABLED)

        for tag, color in [
            ("info", self.TEXT),
            ("success", self.SUCCESS),
            ("error", self.ERROR),
            ("warning", self.WARNING),
            ("accent", self.ACCENT),
        ]:
            self.log_text.tag_configure(tag, foreground=color)

    def _section_label(self, parent: ttk.Frame, text: str) -> None:
        ttk.Label(
            parent,
            text=text,
            background=self.PANEL,
            foreground=self.MUTED,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(4, 4))

    def _update_admin_status(self) -> None:
        if require_admin():
            self.admin_label.configure(text="管理员权限: 已获取", foreground=self.SUCCESS)
        else:
            self.admin_label.configure(text="管理员权限: 未获取", foreground=self.WARNING)

    def log(self, level: str, message: str) -> None:
        """线程安全地写入日志（可从后台线程调用）。"""
        self._log_queue.put((level, message))

    def _poll_log_queue(self) -> None:
        while True:
            try:
                level, message = self._log_queue.get_nowait()
            except queue.Empty:
                break
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{timestamp}] ", "info")
            self.log_text.insert(tk.END, f"{message}\n", level)
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
        self.root.after(100, self._poll_log_queue)

    def _set_status(self, ok: Optional[bool], summary: str = "") -> None:
        if ok is True:
            self.status_label.configure(text=f"● 网络正常  {summary}", foreground=self.SUCCESS)
        elif ok is False:
            self.status_label.configure(text=f"● 网络异常  {summary}", foreground=self.ERROR)
        else:
            self.status_label.configure(text="● 状态未知", foreground=self.MUTED)

    def _set_buttons_state(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for widget in self.root.winfo_children():
            self._set_widget_state_recursive(widget, state, skip_monitor=not enabled)

    def _set_widget_state_recursive(self, widget: tk.Widget, state: str, skip_monitor: bool) -> None:
        if isinstance(widget, (ttk.Button, tk.Button)):
            if skip_monitor and widget is self.monitor_btn:
                return
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        for child in widget.winfo_children():
            self._set_widget_state_recursive(child, state, skip_monitor)

    def _run_async(self, name: str, func: Callable[[], None]) -> None:
        if self._task_running:
            messagebox.showinfo("提示", "已有任务正在运行，请稍候。")
            return

        def worker() -> None:
            self._task_running = True
            self.root.after(0, lambda: self._set_buttons_state(False))
            self.log("accent", f"--- 开始: {name} ---")
            try:
                func()
            except Exception as exc:  # noqa: BLE001
                self.log("error", f"任务异常: {exc}")
            finally:
                self.log("accent", f"--- 结束: {name} ---")
                self._task_running = False
                self.root.after(0, lambda: self._set_buttons_state(True))

        threading.Thread(target=worker, daemon=True).start()

    def on_detect(self) -> None:
        def task() -> None:
            self.log("info", "正在检测网络状态...")
            report = self.detector.run_all_checks()
            self.log("info", format_report(report, verbose=True))
            self.root.after(0, lambda: self._set_status(report.overall_ok, report.summary))

        self._run_async("网络检测", task)

    def on_repair(self, level: str) -> None:
        if level == "heavy":
            if not messagebox.askyesno(
                "确认重度修复",
                "重度修复将重置 Winsock 与 TCP/IP 协议栈，可能需要重启电脑。\n\n是否继续？",
            ):
                return

        def task() -> None:
            if not require_admin() and level != "light":
                self.log("warning", "缺少管理员权限，部分步骤可能失败。")

            self.log("info", f"正在执行修复 (级别: {level})...")
            report = self.repairer.run_repair(level=level, verify=True, log=lambda msg: self.log("info", msg))
            self.log("info", format_repair_report(report))
            if report.all_success:
                self.log("success", "修复步骤全部完成。")
            else:
                self.log("warning", "部分修复步骤失败，可尝试更高级别修复。")

            diag = self.detector.run_all_checks()
            self.root.after(0, lambda: self._set_status(diag.overall_ok, diag.summary))

        self._run_async(f"网络修复 ({level})", task)

    def on_toggle_monitor(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._stop_monitor()
            return
        self._start_monitor()

    def _start_monitor(self) -> None:
        try:
            interval = max(5, int(self.interval_var.get()))
        except ValueError:
            messagebox.showerror("参数错误", "检测间隔必须是整数。")
            return

        self._monitor_stop.clear()
        self.monitor_btn.configure(text="停止监控")
        self.log("info", f"无畏契约监控已启动，间隔 {interval} 秒。")

        def monitor_loop() -> None:
            failure_count = 0
            last_game = False
            while not self._monitor_stop.is_set():
                game_running = _valorant_running()
                if game_running != last_game:
                    if game_running:
                        self.log("warning", "检测到无畏契约/Vanguard 进程已启动。")
                    else:
                        self.log("info", "无畏契约相关进程已退出。")
                    last_game = game_running

                report = self.detector.run_all_checks()
                if report.overall_ok:
                    failure_count = 0
                    self.log("success", f"网络正常 — {report.timestamp}")
                    self.root.after(0, lambda s=report.summary: self._set_status(True, s))
                else:
                    failure_count += 1
                    self.log("error", f"网络异常 (连续 {failure_count} 次): {report.summary}")
                    self.root.after(0, lambda s=report.summary: self._set_status(False, s))
                    if failure_count >= 2:
                        level = "medium" if failure_count >= 4 else "light"
                        self.log("warning", f"触发自动修复 (级别: {level})...")
                        repair_report = self.repairer.run_repair(
                            level=level,
                            verify=True,
                            log=lambda msg: self.log("info", msg),
                        )
                        self.log("info", format_repair_report(repair_report))
                        failure_count = 0

                for _ in range(interval * 10):
                    if self._monitor_stop.is_set():
                        break
                    time.sleep(0.1)

            self.root.after(0, self._on_monitor_stopped)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _stop_monitor(self) -> None:
        self._monitor_stop.set()
        self.log("info", "正在停止监控...")

    def _on_monitor_stopped(self) -> None:
        self.monitor_btn.configure(text="开始无畏契约监控")
        self.log("info", "监控已停止。")

    def on_clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.log("info", "日志已清空。")

    def on_export_log(self) -> None:
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile=f"net-repair-{datetime.now():%Y%m%d-%H%M%S}.log",
        )
        if not path:
            return
        content = self.log_text.get("1.0", tk.END)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.log("success", f"日志已导出: {path}")
        except OSError as exc:
            self.log("error", f"导出失败: {exc}")


def _valorant_running() -> bool:
    if not IS_WINDOWS:
        return False
    code, stdout, _ = run_command(["tasklist", "/FO", "CSV", "/NH"], timeout=15)
    if code != 0:
        return False
    return any(name.lower() in stdout.lower() for name in VALORANT_PROCESS_NAMES)


def run_gui() -> None:
    root = tk.Tk()
    NetworkRepairApp(root)
    root.mainloop()

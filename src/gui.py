# -*- coding: utf-8 -*-
"""
海康威视 PTZ 全景图管理 GUI

功能:
  1. 全景合成实况 — 实时显示采集进度和最终全景图
  2. 合成历史查看 — 按日期浏览历史全景图

依赖: customtkinter, Pillow, opencv-python
"""

import os
import sys
import queue
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

import customtkinter as ctk
from PIL import Image, ImageTk

# 确保 src 在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.camera import CameraConfig
from src.panorama import PanoramaCapture

# ── 主题设置 ──
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── 常量 ──
IMG_BASE = Path(__file__).parent.parent / "img"
WINDOW_W = 1280
WINDOW_H = 760


class PanoramaApp(ctk.CTk):
    """主窗口"""

    def __init__(self):
        super().__init__()

        self.title("海康威视 PTZ 全景图管理 v0.13")
        self.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.minsize(1024, 600)

        # 加载摄像头配置
        try:
            self.config = CameraConfig()
        except Exception as e:
            self.config = None
            print(f"[WARN] 摄像头配置加载失败: {e}")

        # 工作线程相关
        self.worker: Optional[threading.Thread] = None
        self._stop_worker = False
        self.gui_queue = queue.Queue()

        # ── 布局: 菜单栏 ──
        self.tab_view = ctk.CTkTabview(self, corner_radius=8)
        self.tab_view.pack(fill="both", expand=True, padx=8, pady=8)

        # 创建两个菜单页
        self.tab_live = self.tab_view.add("全景合成实况")
        self.tab_history = self.tab_view.add("合成历史查看")

        # 初始化各页面
        self._setup_live_tab()
        self._setup_history_tab()

        # 定时检查队列消息
        self.after(100, self._process_queue)
        # 定时刷新历史列表（每5秒）
        self.after(5000, self._refresh_history_timer)

    # ────────────── 菜单1: 全景合成实况 ──────────────

    def _setup_live_tab(self):
        """布局「全景合成实况」页面"""
        # 左侧: 状态 + 控制 + 日志
        left = ctk.CTkFrame(self.tab_live, width=380)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)

        # --- 状态面板 ---
        status_frame = ctk.CTkFrame(left)
        status_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(status_frame, text="摄像头状态", font=("", 14, "bold")
                     ).pack(anchor="w", padx=8, pady=(5, 0))

        self.lbl_camera = ctk.CTkLabel(status_frame, text="● 待连接",
                                       text_color="gray")
        self.lbl_camera.pack(anchor="w", padx=8)

        self.lbl_status = ctk.CTkLabel(status_frame, text="状态: 空闲",
                                       text_color="gray")
        self.lbl_status.pack(anchor="w", padx=8)

        self.lbl_last = ctk.CTkLabel(status_frame, text="上次: -")
        self.lbl_last.pack(anchor="w", padx=8, pady=(0, 5))

        self.progress = ctk.CTkProgressBar(status_frame, mode="indeterminate")
        self.progress.pack(fill="x", padx=8, pady=5)
        self.progress.pack_forget()  # 隐藏

        # --- 控制按钮 ---
        btn_frame = ctk.CTkFrame(left)
        btn_frame.pack(fill="x", padx=10, pady=5)

        self.btn_start = ctk.CTkButton(btn_frame, text="▶ 开始采集",
                                       command=self._on_start,
                                       height=36, fg_color="green",
                                       hover_color="darkgreen")
        self.btn_start.pack(side="left", padx=(0, 5), fill="x", expand=True)

        self.btn_stop = ctk.CTkButton(btn_frame, text="■ 停止",
                                      command=self._on_stop,
                                      height=36, fg_color="red",
                                      hover_color="darkred", state="disabled")
        self.btn_stop.pack(side="left", padx=(5, 0), fill="x", expand=True)

        # --- 日志面板 ---
        log_frame = ctk.CTkFrame(left)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        ctk.CTkLabel(log_frame, text="运行日志", font=("", 13, "bold")
                     ).pack(anchor="w", padx=5, pady=(5, 0))

        self.txt_log = ctk.CTkTextbox(log_frame, font=("Consolas", 11),
                                      state="disabled", wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=5, pady=5)

        # 右侧: 实时预览
        right = ctk.CTkFrame(self.tab_live)
        right.pack(side="right", fill="both", expand=True)

        ctk.CTkLabel(right, text="实时预览", font=("", 14, "bold")
                     ).pack(anchor="n", padx=10, pady=(10, 5))

        # 图片预览区域
        self.lbl_preview = ctk.CTkLabel(right, text="等待采集...",
                                        fg_color=("gray20", "gray10"),
                                        corner_radius=8)
        self.lbl_preview.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # ────────────── 菜单2: 合成历史查看 ──────────────

    def _setup_history_tab(self):
        """布局「合成历史查看」页面"""
        # 左侧: 日期列表
        left = ctk.CTkFrame(self.tab_history, width=200)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)

        ctk.CTkLabel(left, text="采集日期", font=("", 14, "bold")
                     ).pack(anchor="w", padx=8, pady=(10, 5))

        self.date_listbox = ctk.CTkScrollableFrame(left)
        self.date_listbox.pack(fill="both", expand=True, padx=5, pady=5)

        # 右侧: 图片显示
        right = ctk.CTkFrame(self.tab_history)
        right.pack(side="right", fill="both", expand=True)

        # 顶部: 选中信息
        info_frame = ctk.CTkFrame(right, height=40)
        info_frame.pack(fill="x", padx=10, pady=(10, 5))
        info_frame.pack_propagate(False)

        self.lbl_history_info = ctk.CTkLabel(info_frame, text="请在左侧选择日期",
                                             font=("", 13))
        self.lbl_history_info.pack(side="left", padx=10)

        # 主要图片显示区域
        self.lbl_history_img = ctk.CTkLabel(right, text="",
                                            fg_color=("gray20", "gray10"),
                                            corner_radius=8)
        self.lbl_history_img.pack(fill="both", expand=True, padx=10, pady=5)

        # 底部: 缩略图列表
        thumb_frame = ctk.CTkFrame(right, height=120)
        thumb_frame.pack(fill="x", padx=10, pady=(0, 10))
        thumb_frame.pack_propagate(False)

        ctk.CTkLabel(thumb_frame, text="该日采集记录", font=("", 12, "bold")
                     ).pack(anchor="w", padx=5, pady=(2, 0))

        self.thumb_container = ctk.CTkScrollableFrame(thumb_frame, height=80)
        self.thumb_container.pack(fill="x", padx=5, pady=2)

        # 初始化日期列表
        self._scan_history()

    # ────────────── 按钮事件 ──────────────

    def _on_start(self):
        """开始全景图采集"""
        if self.config is None:
            self._log("摄像头未配置，请检查 config/camera.yaml")
            return

        if self.worker and self.worker.is_alive():
            self._log("采集正在进行中...")
            return

        self._stop_worker = False
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress.pack(fill="x", padx=8, pady=5)
        self.progress.start()
        self.lbl_status.configure(text="状态: 采集中...", text_color="orange")
        self.lbl_preview.configure(image="", text="采集中...")

        self.worker = threading.Thread(target=self._worker_run, daemon=True)
        self.worker.start()

    def _on_stop(self):
        """停止采集"""
        self._stop_worker = True
        self._log("用户请求停止...")
        self.btn_stop.configure(state="disabled")

    # ────────────── 工作线程 ──────────────

    def _worker_run(self):
        """工作线程：运行全景图采集"""
        pano = None
        try:
            pano = PanoramaCapture(
                self.config,
                callback=self._worker_callback,
                pan_steps=8,
                tilt_steps=3,
                pan_speed=100,
                step_duration=8.0,
            )
            pano.capture()
        except Exception as e:
            self._put_queue("log", f"[ERROR] {e}")
        finally:
            if pano:
                try:
                    pano.stop()
                except Exception:
                    pass
            self._put_queue("done")

    def _worker_callback(self, msg: dict):
        """工作线程的回调 -> 放入队列传给 GUI 线程"""
        msg_type = msg.get("type", "")
        if msg_type == "log":
            self._put_queue("log", msg.get("msg", ""))
        elif msg_type == "capture":
            self._put_queue("capture", msg.get("path", ""), msg.get("label", ""))
        elif msg_type == "panorama":
            self._put_queue("panorama", msg.get("path", ""))
        elif msg_type == "status":
            self._put_queue("status", msg.get("msg", ""))

    def _put_queue(self, type_, *args):
        """安全放入队列"""
        try:
            self.gui_queue.put_nowait((type_, *args))
        except queue.Full:
            pass

    # ────────────── 队列处理 ──────────────

    def _process_queue(self):
        """从队列中取出消息并更新 GUI（在主线程中执行）"""
        try:
            while True:
                msg = self.gui_queue.get_nowait()
                self._handle_message(msg)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_queue)

    def _handle_message(self, msg):
        """处理一条队列消息"""
        type_ = msg[0]

        if type_ == "log":
            self._log(msg[1] if len(msg) > 1 else "")

        elif type_ == "capture":
            path = msg[1] if len(msg) > 1 else ""
            label = msg[2] if len(msg) > 2 else ""
            self._update_preview(path, label)

        elif type_ == "panorama":
            path = msg[1] if len(msg) > 1 else ""
            self._log(f"\n[全景图完成] {path}")
            self._update_preview(path, "全景图")

        elif type_ == "status":
            status = msg[1] if len(msg) > 1 else ""
            self.lbl_status.configure(text=f"状态: {status}")

        elif type_ == "done":
            self._on_worker_done()

    def _on_worker_done(self):
        """工作线程结束"""
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.progress.stop()
        self.progress.pack_forget()
        self.lbl_status.configure(text="状态: 空闲", text_color="gray")
        self._scan_history()

    # ────────────── GUI 更新方法 ──────────────

    def _log(self, text: str):
        """追加日志"""
        self.txt_log.configure(state="normal")
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.txt_log.insert("end", f"[{timestamp}] {text}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _update_preview(self, image_path: str, label: str = ""):
        """更新预览图片"""
        try:
            if not os.path.exists(image_path):
                return

            pil_img = Image.open(image_path)
            # 缩放以适应预览区域
            max_w, max_h = 600, 400
            pil_img.thumbnail((max_w, max_h), Image.LANCZOS)

            ctk_img = ctk.CTkImage(pil_img, size=pil_img.size)
            self.lbl_preview.configure(image=ctk_img, text=label)
            self.lbl_preview.image = ctk_img  # 防止 GC
        except Exception as e:
            self._log(f"预览加载失败: {e}")

    # ────────────── 历史浏览 ──────────────

    def _scan_history(self):
        """扫描 img/ 目录，整理日期列表"""
        if not IMG_BASE.exists():
            return

        # 清除旧的日期按钮
        for w in self.date_listbox.winfo_children():
            w.destroy()

        # 按日期排序（最新的在上）
        dates = sorted([d.name for d in IMG_BASE.iterdir() if d.is_dir()],
                       reverse=True)

        if not dates:
            ctk.CTkLabel(self.date_listbox, text="暂无数据",
                         text_color="gray").pack(pady=20)
            return

        for date_str in dates:
            btn = ctk.CTkButton(
                self.date_listbox, text=date_str,
                command=lambda d=date_str: self._on_date_selected(d),
                anchor="w", height=32,
                fg_color="transparent",
                text_color=("black", "white"),
                hover_color=("gray80", "gray30"),
            )
            btn.pack(fill="x", padx=2, pady=1)

        # 默认选中第一个
        self._on_date_selected(dates[0])

    def _on_date_selected(self, date_str: str):
        """选中某个日期"""
        self._selected_date = date_str
        self.lbl_history_info.configure(text=f"📅 {date_str}")

        date_path = IMG_BASE / date_str
        if not date_path.exists():
            return

        # 查找该日期下的所有采集记录（按时间倒序）
        times = sorted([t.name for t in date_path.iterdir() if t.is_dir()],
                       reverse=True)

        # 清空缩略图
        for w in self.thumb_container.winfo_children():
            w.destroy()

        if not times:
            ctk.CTkLabel(self.thumb_container, text="该日无记录",
                         text_color="gray").pack(pady=10)
            self.lbl_history_img.configure(image="", text="无记录")
            return

        # 显示每个时间记录的缩略图
        for time_str in times:
            pano_path = date_path / time_str / "panorama.jpg"
            if not pano_path.exists():
                continue

            frame = ctk.CTkFrame(self.thumb_container, corner_radius=6)
            frame.pack(side="left", padx=4, pady=4)

            try:
                img = Image.open(pano_path)
                img.thumbnail((100, 70), Image.LANCZOS)
                ctk_img = ctk.CTkImage(img, size=img.size)
                btn = ctk.CTkButton(
                    frame, image=ctk_img, text="",
                    width=img.width + 10, height=img.height + 10,
                    command=lambda p=str(pano_path), t=time_str: self._show_history_image(p, t),
                )
                btn.image = ctk_img
                btn.pack()
            except Exception:
                pass

            ctk.CTkLabel(frame, text=time_str, font=("", 9)).pack()

        # 显示第一个全景图
        first_pano = date_path / times[0] / "panorama.jpg"
        if first_pano.exists():
            self._show_history_image(str(first_pano), times[0])

    def _show_history_image(self, img_path: str, time_str: str):
        """显示选中的历史全景图"""
        try:
            pil_img = Image.open(img_path)
            # 缩放到显示区域
            max_w, max_h = 700, 450
            pil_img.thumbnail((max_w, max_h), Image.LANCZOS)

            ctk_img = ctk.CTkImage(pil_img, size=pil_img.size)
            self.lbl_history_img.configure(image=ctk_img, text=time_str)
            self.lbl_history_img.image = ctk_img

            # 更新信息
            size = os.path.getsize(img_path) / 1024
            self.lbl_history_info.configure(
                text=f"📅 {self._selected_date}  ⏱ {time_str}  📄 {pil_img.width}x{pil_img.height}  ({size:.0f} KB)"
            )
        except Exception as e:
            self.lbl_history_img.configure(text=f"加载失败: {e}")

    def _refresh_history_timer(self):
        """定时刷新历史列表"""
        if hasattr(self, '_selected_date'):
            current_date = getattr(self, '_selected_date', None)
            self._scan_history()
            if current_date:
                self._on_date_selected(current_date)
        else:
            self._scan_history()
        self.after(5000, self._refresh_history_timer)

    # ────────────── 窗口关闭 ──────────────

    def destroy(self):
        """关闭窗口时清理"""
        self._stop_worker = True
        super().destroy()


# ── 启动 ──
if __name__ == "__main__":
    app = PanoramaApp()
    app.mainloop()

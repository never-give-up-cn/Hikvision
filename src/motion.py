# -*- coding: utf-8 -*-
"""
人员移动侦测模块

摄像头固定不动，实时抓拍检测画面中的人员移动，
检测到后弹出 Windows 通知。

原理:
  1. OpenCV MOG2 背景减除 → 提取运动区域
  2. 轮廓检测 → 按面积/宽高比过滤（排除小物体/非人形）
  3. 触发 → Windows Toast 通知

用法:
  python -m src.motion                    # 命令行运行
  python src/gui.py --tab motion          # GUI 中启动
"""

import os
import sys
import time
import json
import threading
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

# 确保 src 在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

from src.camera import CameraConfig
from src.isapi import ISAPIClient

logger = logging.getLogger("motion")


def windows_notify(title: str, message: str):
    """
    弹出 Windows Toast 通知（无需额外库）

    使用 PowerShell 调用 Windows.UI.Notifications API
    """
    # 转义特殊字符
    title = title.replace("'", "''").replace('"', '""')
    message = message.replace("'", "''").replace('"', '""')

    ps_script = f'''
$title = "{title}"
$message = "{message}"

[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null

$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName("text")
$textNodes.Item(0).AppendChild($template.CreateTextNode($title)) > $null
$textNodes.Item(1).AppendChild($template.CreateTextNode($message)) > $null

$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("海康摄像头监控").Show($toast)
'''
    try:
        subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception as e:
        logger.warning(f"通知发送失败: {e}")


class MotionDetector:
    """
    人员移动侦测器

    参数:
      config:          摄像头配置
      interval:        抓拍间隔（秒）
      min_area:        最小运动区域面积（像素），小于此忽略
      min_aspect:      最小宽高比（运动框），排除横移的小动物
      cooldown:        连续通知最小间隔（秒），防刷屏
      sensitivity:     灵敏度 (1-10)，越高越敏感
      callback:        可选回调，检测到人员时调用 callback(path)
    """

    def __init__(
        self,
        config: CameraConfig,
        interval: float = 0.5,
        min_area: int = 3000,
        min_aspect: float = 0.8,
        cooldown: float = 30.0,
        sensitivity: int = 5,
        callback: Optional[Callable] = None,
        frame_callback: Optional[Callable] = None,
    ):
        """
        Args:
            frame_callback: 每帧回调，用于 GUI 实时预览
                            frame_callback(jpeg_bytes, timestamp)
        """
        self.config = config
        self.isapi = ISAPIClient(config)
        self.interval = max(0.2, min(5.0, interval))
        self.min_area = min_area
        self.min_aspect = min_aspect
        self.cooldown = max(5.0, cooldown)
        self.callback = callback
        self.frame_callback = frame_callback

        # 灵敏度映射 (1-10 → 学习率 0.01-0.001)
        self._learning_rate = max(0.001, min(0.01, 0.011 - sensitivity * 0.001))

        # 背景减除器
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=36, detectShadows=False
        )

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_notify_time = 0
        self._last_frame: Optional[np.ndarray] = None
        self._frame_count = 0
        self._alerts = []

        # 触发计数器（调试/显示用）
        self.alert_count = 0

    # ===================== 外部接口 =====================

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        """启动侦测"""
        if self._running:
            logger.warning("侦测已运行")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="MotionDetector")
        self._thread.start()
        logger.info("人员移动侦测已启动")
        return self

    def stop(self):
        """停止侦测"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        logger.info("人员移动侦测已停止")

    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "running": self._running,
            "alerts": self.alert_count,
            "last_alert": self._alerts[-1] if self._alerts else None,
        }

    # ===================== 内部逻辑 =====================

    def _run_loop(self):
        """侦测主循环"""
        consecutive_errors = 0

        while self._running:
            try:
                # 抓拍
                img_data = self.isapi.get_snapshot()
                if img_data is None or len(img_data) < 100:
                    consecutive_errors += 1
                    if consecutive_errors > 10:
                        logger.error("连续 10 次抓拍失败，停止侦测")
                        break
                    time.sleep(1)
                    continue

                consecutive_errors = 0

                # 解码
                frame = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    time.sleep(self.interval)
                    continue

                self._frame_count += 1

                # 运动检测
                detected = self._detect_motion(frame)

                if detected:
                    self._on_detected(frame, img_data)

                # 实时预览回调（每 3 帧一次给 GUI）
                if self.frame_callback and self._frame_count % 3 == 0:
                    try:
                        self.frame_callback(img_data, datetime.now())
                    except Exception:
                        pass

                self._last_frame = frame

            except Exception as e:
                logger.error(f"侦测异常: {e}")
                time.sleep(1)

    def _detect_motion(self, frame: np.ndarray) -> bool:
        """
        检测画面中是否有人员移动

        Returns:
            True = 检测到人员移动
        """
        h, w = frame.shape[:2]

        # 1. 背景减除 → 运动掩码
        fg_mask = self._bg_subtractor.apply(frame, learningRate=self._learning_rate)

        # 2. 形态学降噪
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)

        # 3. 阈值化
        _, fg_mask = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)

        # 4. 轮廓检测
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.min_area:
                continue  # 太小，忽略

            x, y, bw, bh = cv2.boundingRect(cnt)
            aspect = bw / bh if bh > 0 else 0

            # 人形特征: 直立（高>宽）、面积适中
            if aspect < self.min_aspect or aspect > 3.0:
                continue  # 宽高比不符合人形

            # 面积不能超过画面的 80%（排除误报）
            if area > w * h * 0.8:
                continue

            return True

        return False

    def _on_detected(self, frame: np.ndarray, raw_data: bytes):
        """检测到人员移动时的处理"""
        now = time.time()

        # 冷却期检查
        if now - self._last_notify_time < self.cooldown:
            return

        self._last_notify_time = now
        self.alert_count += 1
        timestamp = datetime.now()

        # 保存抓拍快照
        snap_dir = Path("captures") / timestamp.strftime("%Y-%m-%d")
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_path = snap_dir / f"alert_{timestamp.strftime('%H%M%S')}.jpg"
        try:
            with open(snap_path, "wb") as f:
                f.write(raw_data)
        except Exception as e:
            logger.warning(f"保存快照失败: {e}")
            snap_path = None

        alert_info = {
            "time": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "snapshot": str(snap_path) if snap_path else "",
        }
        self._alerts.append(alert_info)

        # 日志
        logger.info(f"[ALERT] 检测到人员移动! #{self.alert_count}")

        # Windows 通知
        windows_notify(
            "🚶 人员移动告警",
            f"{timestamp.strftime('%H:%M:%S')}  检测到人员移动\n已保存快照: {snap_path.name if snap_path else 'N/A'}"
        )

        # 回调
        if self.callback:
            try:
                self.callback(alert_info)
            except Exception:
                pass


# ===================== 命令行入口 =====================

def main():
    """命令行运行"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [motion] %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 50)
    print("  海康威视 人员移动侦测")
    print("  摄像头固定，检测到人员移动时弹出 Windows 通知")
    print("  按 Ctrl+C 停止")
    print("=" * 50)

    config = CameraConfig()
    detector = MotionDetector(config)

    try:
        detector.start()
        while detector.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        detector.stop()
        print(f"侦测已停止，共触发 {detector.alert_count} 次告警")


if __name__ == "__main__":
    main()

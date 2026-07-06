# -*- coding: utf-8 -*-
"""
全景图采集与拼接模块

自动控制 PTZ 摄像头遍历多角度抓拍，使用 OpenCV 特征匹配拼接全景图。
输出到 img/YYYY-MM-DD/HHMMSS/ 目录。

工作流程:
  1. 定义采集网格（水平 N 列 × 垂直 M 行）
  2. 云台连续移动 + 定时停止，遍历网格每个位置
  3. 每个位置抓拍一张 JPEG
  4. OpenCV Stitcher 拼接所有图片
  5. 保存单帧 + 全景图到日期目录
"""

import cv2
import os
import json
import time
import logging
import threading
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

from .camera import CameraConfig
from .isapi import ISAPIClient, ISAPIError
from .ptz import PTZController

logger = logging.getLogger("panorama")


class PanoramaCapture:
    """
    全景图采集器

    参数:
      config: 摄像头配置
      output_base: 输出根目录（默认 ./img）

    采集网格:
      pan_steps:   水平方向步数（图像列数）
      tilt_steps:  垂直方向步数（图像行数）
      pan_speed:   水平移动速度 (1-100)
      tilt_speed:  垂直移动速度 (1-100)
      step_duration: 每次移动持续时间（秒），决定相邻位置角度间距
      settle_time: 移动到位后等待稳定的时间（秒）
    """

    def __init__(
        self,
        config: CameraConfig,
        output_base: str = "img",
        pan_steps: int = 6,
        tilt_steps: int = 2,
        pan_speed: int = 40,
        tilt_speed: int = 30,
        step_duration: float = 2.5,
        settle_time: float = 0.5,
    ):
        self.config = config
        self.isapi = ISAPIClient(config)
        self.ptz = PTZController(config)

        self.output_base = Path(output_base)
        self.pan_steps = pan_steps
        self.tilt_steps = max(1, tilt_steps)
        self.pan_speed = min(100, max(1, pan_speed))
        self.tilt_speed = min(100, max(1, tilt_speed))
        self.step_duration = max(0.5, step_duration)
        self.settle_time = max(0.1, settle_time)

        self._stop_flag = False

    # ===================== 外部接口 =====================

    def capture(self) -> Optional[Path]:
        """
        执行一次完整的全景图采集流程

        Returns:
          全景图文件路径，失败返回 None
        """
        self._stop_flag = False
        timestamp = datetime.now()
        date_str = timestamp.strftime("%Y-%m-%d")
        time_str = timestamp.strftime("%H%M%S")
        output_dir = self.output_base / date_str / time_str
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 50)
        logger.info("开始全景图采集")
        logger.info(f"  网格: {self.pan_steps}列 × {self.tilt_steps}行 = {self.pan_steps * self.tilt_steps}张")
        logger.info(f"  输出: {output_dir}")
        logger.info("=" * 50)

        # 第一步：采集所有位置的图片
        images = self._capture_grid(output_dir)
        if self._stop_flag:
            logger.warning("采集被中断")
            return None
        if not images:
            logger.error("未采集到任何有效图片")
            return None

        logger.info(f"采集完成: {len(images)} 张有效图片")

        # 第二步：拼接全景图
        panorama_path = self._stitch_and_save(images, output_dir, timestamp)

        # 第三步：保存采集日志
        self._save_log(output_dir, timestamp, len(images), panorama_path)

        return panorama_path

    def auto_loop(self, interval_minutes: int = 5):
        """
        自动循环模式，每隔 interval_minutes 分钟采集一次

        按 Ctrl+C 停止
        """
        logger.info(f"自动模式启动，每 {interval_minutes} 分钟采集一次")
        logger.info("按 Ctrl+C 停止")

        while not self._stop_flag:
            try:
                start_time = time.time()
                self.capture()
                elapsed = time.time() - start_time
                sleep_time = max(1, interval_minutes * 60 - elapsed)

                next_time = datetime.now().timestamp() + sleep_time
                next_dt = datetime.fromtimestamp(next_time)
                logger.info(f"下次采集: {next_dt.strftime('%H:%M:%S')} ({int(sleep_time)}秒后)")

                # 分段等待，支持中断
                wait_interval = 1.0  # 每秒检查一次中断
                while sleep_time > 0 and not self._stop_flag:
                    time.sleep(min(wait_interval, sleep_time))
                    sleep_time -= wait_interval

            except KeyboardInterrupt:
                logger.info("用户中断")
                self.stop()
                break
            except Exception as e:
                logger.error(f"采集异常: {e}")
                logger.info(f"{interval_minutes} 分钟后重试...")
                time.sleep(interval_minutes * 60)

    def stop(self):
        """安全停止"""
        self._stop_flag = True
        logger.info("正在停止...")
        try:
            self.ptz.stop()
            logger.info("云台已停止")
        except Exception:
            pass

    # ===================== 内部方法 =====================

    def _move_by_continuous(self, pan: float = 0, tilt: float = 0, duration: float = 1.0):
        """
        连续移动指定时间后停止

        Args:
            pan: 水平速度 (-100 ~ 100)，正=右，负=左
            tilt: 垂直速度 (-100 ~ 100)，正=上，负=下
            duration: 移动持续秒数
        """
        if self._stop_flag:
            return

        self.isapi.ptz_continuous_move(pan=int(pan), tilt=int(tilt), zoom=0)
        if duration > 0:
            # 分段等待以支持中断
            remaining = duration
            chunk = 0.1
            while remaining > 0 and not self._stop_flag:
                time.sleep(min(chunk, remaining))
                remaining -= chunk
            if not self._stop_flag:
                self.ptz.stop()

    def _capture_grid(self, output_dir: Path) -> List[Tuple[str, Path]]:
        """
        遍历网格位置并采集图片

        Returns:
            [(position_label, file_path), ...] 格式的列表
        """
        images = []

        # --- Step 1: 移动到起始位置（左上角）---
        # 先向左转，再向上转，到达起始区域
        logger.info("移动到起始位置...")
        self._move_left_pre()
        self._move_up_pre()

        # --- Step 2: Z 字形遍历网格 ---
        # 从左到右扫描一行，然后下移一行，再从右到左扫描
        for tilt_idx in range(self.tilt_steps):
            row_direction = 1 if tilt_idx % 2 == 0 else -1  # 偶数行→右，奇数行→左
            pan_range = range(self.pan_steps) if row_direction == 1 else range(self.pan_steps - 1, -1, -1)

            # 移动到本行起始位置
            if tilt_idx > 0:
                logger.info(f"下移一行 ({tilt_idx + 1}/{self.tilt_steps})")
                self._move_by_continuous(pan=0, tilt=-self.tilt_speed, duration=self.step_duration)
                # 如果奇数行，也左移一列（回到最左）
                if row_direction == -1:
                    self._move_by_continuous(pan=-self.pan_speed, tilt=0, duration=self.step_duration * (self.pan_steps - 1))

            for col_idx in pan_range:
                if self._stop_flag:
                    return images

                pos_label = f"r{tilt_idx + 1}_c{col_idx + 1}"

                # 非第一列：水平移动
                if col_idx != pan_range[0]:
                    # 确定方向（Z 字形）
                    if row_direction == 1:
                        self._move_by_continuous(pan=self.pan_speed, tilt=0, duration=self.step_duration)
                    else:
                        self._move_by_continuous(pan=-self.pan_speed, tilt=0, duration=self.step_duration)

                # 等待稳定
                time.sleep(self.settle_time)
                if self._stop_flag:
                    return images

                # 抓拍
                logger.info(f"  [{pos_label}] 采集...")
                img_path = output_dir / f"{pos_label}.jpg"
                success = self._capture_single(img_path)
                if success:
                    images.append((pos_label, img_path))
                else:
                    logger.warning(f"  [{pos_label}] 采集失败")

        # 回到中间位置
        logger.info("采集完成，停止云台")
        self.ptz.stop()

        return images

    def _move_left_pre(self):
        """向左移动到起始位置（约 2 秒）"""
        self._move_by_continuous(pan=-self.pan_speed, tilt=0, duration=2.5)
        self.ptz.stop()

    def _move_up_pre(self):
        """向上移动到起始位置（约 1 秒）"""
        self._move_by_continuous(pan=0, tilt=self.tilt_speed, duration=1.0)
        self.ptz.stop()

    def _capture_single(self, save_path: Path, retries: int = 3) -> bool:
        """抓拍并保存单张图片

        Args:
            save_path: 保存路径
            retries: 重试次数（摄像头繁忙时自动重试）
        """
        for attempt in range(1, retries + 1):
            if self._stop_flag:
                return False

            try:
                if attempt > 1:
                    wait = attempt * 1.0  # 递增等待: 1s, 2s, 3s
                    logger.info(f"  等待 {wait:.0f}s 后重试 ({attempt}/{retries})...")
                    time.sleep(wait)

                img_data = self.isapi.get_snapshot()

                if img_data is None or len(img_data) < 100:
                    logger.warning(f"  抓取结果为空 (尝试 {attempt}/{retries})")
                    continue

                # 检查是否返回了 XML 错误
                if img_data[:5] == b'<?xml' or img_data[:5] == b'<Resp':
                    logger.warning(f"  摄像头返回错误 (尝试 {attempt}/{retries})")
                    # 尝试解析错误原因
                    try:
                        text = img_data[:500].decode("utf-8", errors="ignore")
                        if "deviceBusy" in text or "Device Busy" in text:
                            logger.warning("  摄像头繁忙（可能有人在看画面）")
                    except Exception:
                        pass
                    continue

                # 保存图片
                with open(save_path, "wb") as f:
                    f.write(img_data)
                logger.info(f"  -> 已保存 ({len(img_data)} bytes)")
                return True

            except ISAPIError as e:
                logger.warning(f"  -> ISAPI异常: {e} (尝试 {attempt}/{retries})")
                continue
            except Exception as e:
                logger.warning(f"  -> 保存异常: {e} (尝试 {attempt}/{retries})")
                continue

        logger.error(f"  [失败] 经 {retries} 次重试仍无法获取图片")
        return False

    def _stitch_and_save(
        self, images: List[Tuple[str, Path]], output_dir: Path, timestamp: datetime
    ) -> Optional[Path]:
        """
        拼接全景图

        使用 OpenCV 内置 Stitcher，如果失败则尝试特征匹配回退方案。

        Args:
            images: [(label, path), ...]
            output_dir: 输出目录

        Returns:
            全景图路径，失败返回 None
        """
        if not images or len(images) < 2:
            logger.warning("图片不足 2 张，无法拼接")
            return None

        img_paths = [p for _, p in images]
        panorama_path = output_dir / "panorama.jpg"

        logger.info(f"正在拼接全景图 ({len(img_paths)} 张)...")

        # --- 方法1: OpenCV Stitcher ---
        pano = self._stitch_opencv(img_paths)
        if pano is not None:
            cv2.imwrite(str(panorama_path), pano)
            file_size = os.path.getsize(panorama_path) / 1024
            logger.info(f"全景图拼接成功! -> {panorama_path} ({file_size:.0f} KB)")
            return panorama_path

        # --- 方法2: 特征匹配拼接 ---
        logger.warning("Stitcher 失败，尝试特征匹配拼接...")
        pano = self._stitch_feature_match(img_paths)
        if pano is not None:
            cv2.imwrite(str(panorama_path), pano)
            file_size = os.path.getsize(panorama_path) / 1024
            logger.info(f"特征匹配拼接成功! -> {panorama_path} ({file_size:.0f} KB)")
            return panorama_path

        logger.error("所有拼接方法均失败")
        return None

    def _stitch_opencv(self, img_paths: List[Path]):
        """OpenCV Stitcher 拼接"""
        try:
            imgs = []
            for p in img_paths:
                img = cv2.imread(str(p))
                if img is not None:
                    imgs.append(img)

            if len(imgs) < 2:
                return None

            # OpenCV 5.x API
            try:
                stitcher = cv2.Stitcher.create(cv2.Stitcher_PANORAMA)
                status, pano = stitcher.stitch(imgs)
            except AttributeError:
                # OpenCV 4.x fallback
                stitcher = cv2.Stitcher.create()
                status, pano = stitcher.stitch(imgs)

            if status == cv2.Stitcher_OK:
                return pano

            logger.warning(f"  Stitcher 返回错误码: {status}")
            if status == cv2.Stitcher_ERR_NEED_MORE_IMGS:
                logger.warning("  -> 需要更多图片（FOV 重叠不够）")
            return None

        except Exception as e:
            logger.warning(f"  OpenCV Stitcher 异常: {e}")
            return None

    def _stitch_feature_match(self, img_paths: List[Path]):
        """
        特征匹配拼接（ORB + RANSAC）

        适用于图片数量较少或 Stitcher 失败的情况。
        按顺序两两拼接。
        """
        try:
            # 读取第一张
            result = cv2.imread(str(img_paths[0]))
            if result is None:
                return None

            orb = cv2.ORB_create(nfeatures=2000)
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

            for i in range(1, len(img_paths)):
                if self._stop_flag:
                    return None

                img_right = cv2.imread(str(img_paths[i]))
                if img_right is None:
                    continue

                # 检测特征
                kp1, des1 = orb.detectAndCompute(result, None)
                kp2, des2 = orb.detectAndCompute(img_right, None)

                if des1 is None or des2 is None or len(kp1) < 10 or len(kp2) < 10:
                    logger.warning(f"  第 {i+1} 张特征点不足，跳过")
                    continue

                # 特征匹配
                matches = bf.match(des1, des2)
                matches = sorted(matches, key=lambda x: x.distance)

                if len(matches) < 10:
                    logger.warning(f"  第 {i+1} 张匹配点不足 ({len(matches)}), 跳过")
                    continue

                # RANSAC 计算单应性矩阵
                src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
                dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

                H, mask = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 5.0)

                if H is None:
                    logger.warning(f"  第 {i+1} 张无法计算变换矩阵，跳过")
                    continue

                # 计算画布大小
                h1, w1 = result.shape[:2]
                h2, w2 = img_right.shape[:2]

                pts = np.float32([[0, 0], [0, h2], [w2, h2], [w2, 0]]).reshape(-1, 1, 2)
                dst = cv2.perspectiveTransform(pts, H)
                pts_all = np.concatenate((np.float32([[0, 0], [0, h1], [w1, h1], [w1, 0]]).reshape(-1, 1, 2), dst), axis=0)
                [x_min, y_min] = np.int32(pts_all.min(axis=0).ravel() - 0.5)
                [x_max, y_max] = np.int32(pts_all.max(axis=0).ravel() + 0.5)

                # 平移变换
                H_trans = np.array([[1, 0, -x_min], [0, 1, -y_min], [0, 0, 1]], dtype=np.float64)
                result = cv2.warpPerspective(
                    img_right, H_trans @ H,
                    (x_max - x_min, y_max - y_min)
                )
                result[-y_min:h1 - y_min, -x_min:w1 - x_min] = result[-y_min:h1 - y_min, -x_min:w1 - x_min].copy()

                warped_h = max(h1, h2) + abs(y_min)
                warped_w = max(w1, w2) + abs(x_min)
                # 确保画布大小
                canvas = np.zeros((max(result.shape[0], h1), max(result.shape[1], w1), 3), dtype=np.uint8)

                # 放左侧图
                canvas[-min(0, y_min):h1 - min(0, y_min), -min(0, x_min):w1 - min(0, x_min)] = result[-min(0, y_min):h1 - min(0, y_min), -min(0, x_min):w1 - min(0, x_min)]

            logger.info(f"  特征匹配拼接完成 ({len(img_paths)} 张)")
            return result

        except Exception as e:
            logger.warning(f"  特征匹配异常: {e}")
            return None

    def _save_log(self, output_dir: Path, timestamp: datetime, count: int, panorama_path: Optional[Path]):
        """保存采集日志"""
        log = {
            "time": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "grid": f"{self.pan_steps}×{self.tilt_steps}",
            "images_captured": count,
            "panorama": str(panorama_path) if panorama_path else "failed",
            "config": {
                "ip": self.config.ip,
                "model": "HK-Q3S5M-W",
                "pan_speed": self.pan_speed,
                "tilt_speed": self.tilt_speed,
                "step_duration": self.step_duration,
            }
        }
        log_path = output_dir / "capture_log.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        logger.info(f"采集日志: {log_path}")

# -*- coding: utf-8 -*-
"""
全景图采集与拼接模块 — v0.13 全角度覆盖

工作流程:
  1. 校准: 移动到左上极限（确保起始位置确定）
  2. 全范围扫描: Z字形遍历网格，速度100，每步长时间
  3. 特征匹配拼接: ORB + RANSAC 逐对拼接
  4. 输出到 img/YYYY-MM-DD/HHMMSS/

关键改进:
  - 满量程覆盖: 移动到极限位置再逐步扫描
  - 多特征拼接: ORB(3000点) + BFMatcher + RANSAC
  - 自动重试: 抓拍失败自动重试
"""

import cv2
import os
import json
import time
import logging
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
    全景图采集器 — 全角度覆盖版本

    参数:
      config:         摄像头配置
      output_base:    输出根目录（默认 ./img）
      pan_steps:      水平步数（越多覆盖越细）
      tilt_steps:     垂直行数
      pan_speed:      水平移动速度 1-100（建议 80-100）
      step_duration:  每步移动秒数（建议 6-10，越大相邻图片差异越大）
      settle_time:    到位后等待稳定的秒数
    """

    def __init__(
        self,
        config: CameraConfig,
        output_base: str = "img",
        pan_steps: int = 8,
        tilt_steps: int = 3,
        pan_speed: int = 100,
        pixel_shift: float = 40.0,
        settle_time: float = 0.5,
        callback=None,
    ):
        """
        Args:
            config:         摄像头配置
            output_base:    输出根目录
            pan_steps:      水平步数
            tilt_steps:     垂直行数
            pan_speed:      水平移动速度 1-100
            pixel_shift:    相邻两张图片的目标像素差异值（到达此值才停下拍照）
                             越大每次转动角度越大，建议 30-60
            settle_time:    到位后等待稳定的秒数
            callback:       回调函数
        """
        self.config = config
        self.isapi = ISAPIClient(config)
        self.ptz = PTZController(config)
        self.callback = callback

        self.output_base = Path(output_base)
        self.pan_steps = max(2, pan_steps)
        self.tilt_steps = max(1, tilt_steps)
        self.pan_speed = min(100, max(10, pan_speed))
        self.tilt_speed = min(100, max(10, int(pan_speed * 0.7)))
        self.pixel_shift = max(10.0, min(200.0, pixel_shift))
        self.settle_time = max(0.2, settle_time)

        # 移动控制参数
        self._burst_duration = 0.5       # 每次微调的持续时间（秒）
        self._max_bursts_per_step = 40   # 每步最多微调次数（防死循环）
        self._deadzone_threshold = 3.0   # 死限判定阈值

        # 长距离移动到极限的时间
        self._calibrate_duration = 20.0

        self._stop_flag = False
        self._latest_capture_path = None

    def _cb(self, type_, **kwargs):
        """触发回调"""
        if self.callback:
            try:
                self.callback({"type": type_, **kwargs})
            except Exception:
                pass

    # ===================== 外部接口 =====================

    def capture(self) -> Optional[Path]:
        """
        全角度拍照采集：旋转到每个角度并拍照，不拼接

        Returns:
          输出目录路径（包含所有抓拍图片），失败返回 None
        """
        self._stop_flag = False
        timestamp = datetime.now()
        date_str = timestamp.strftime("%Y-%m-%d")
        time_str = timestamp.strftime("%H%M%S")
        output_dir = self.output_base / date_str / time_str
        output_dir.mkdir(parents=True, exist_ok=True)

        total_images = self.pan_steps * self.tilt_steps
        estimated_time = (
            self._calibrate_duration * 2
            + total_images * self._max_bursts_per_step * self._burst_duration * 0.5
        )

        logger.info("=" * 55)
        logger.info(f"  全角度拍照采集（反馈式移动）")
        logger.info(f"  网格: {self.pan_steps}列 × {self.tilt_steps}行 = {total_images}张")
        logger.info(f"  速度: {self.pan_speed}  目标偏移: {self.pixel_shift}px")
        logger.info(f"  预计耗时: ≈{estimated_time:.0f}s ({estimated_time/60:.1f}min)")
        logger.info(f"  输出: {output_dir}")
        logger.info("=" * 55)
        self._cb("status", msg="开始采集...")

        # 1. 校准 + 全范围扫描
        images = self._scan_full_range(output_dir)
        if self._stop_flag:
            logger.warning("采集被中断")
            self._emergency_stop()
            return None
        if not images:
            logger.error("未采集到任何有效图片")
            self._cb("status", msg="采集失败: 无有效图片")
            self._emergency_stop()
            return None

        logger.info(f"\n采集完成: {len(images)} 张有效图片")
        self._cb("status", msg=f"采集完成: {len(images)} 张")

        # 2. 保存日志
        self._save_log(output_dir, timestamp, len(images), None)

        # 3. 通知完成
        self._cb("done", path=str(output_dir), count=len(images))

        return output_dir

    def auto_loop(self, interval_minutes: int = 5):
        """自动循环模式"""
        logger.info(f"\n{'='*55}")
        logger.info(f"  自动全景图模式启动")
        logger.info(f"  采集间隔: 每 {interval_minutes} 分钟")
        logger.info(f"  按 Ctrl+C 停止")
        logger.info(f"{'='*55}\n")

        while not self._stop_flag:
            try:
                start_time = time.time()
                self.capture()
                elapsed = time.time() - start_time
                sleep_time = max(10, interval_minutes * 60 - elapsed)

                next_dt = datetime.fromtimestamp(time.time() + sleep_time)
                logger.info(f"\n下次采集: {next_dt.strftime('%H:%M:%S')} ({int(sleep_time)}秒后)")

                # 分段等待，支持快速中断
                while sleep_time > 0 and not self._stop_flag:
                    time.sleep(min(0.5, sleep_time))
                    sleep_time -= 0.5

            except KeyboardInterrupt:
                logger.info("\n用户中断")
                self._emergency_stop()
                break
            except Exception as e:
                logger.error(f"采集异常: {e}")
                logger.info(f"{interval_minutes} 分钟后重试...")
                time.sleep(interval_minutes * 60)

    def stop(self):
        """安全停止"""
        self._stop_flag = True
        self._emergency_stop()

    # ===================== 内部方法 =====================

    def _emergency_stop(self):
        """紧急停止云台"""
        try:
            self.ptz.stop()
            logger.info("云台已停止")
        except Exception:
            pass

    # ---------- 全角度扫描 ----------

    def _scan_full_range(self, output_dir: Path) -> List[Tuple[str, Path]]:
        """
        全范围网格扫描

        策略:
          1. 移动到左上极限
          2. 从左到右逐列扫描（速度100，步长时间）
          3. 下移一行
          4. 从右到左扫描（Z字形）
          5. 重复直到所有行完成
        """
        images = []

        # === 阶段1: 校准 — 移动到左侧极限（不调整俯仰，保留俯仰行程）===
        logger.info("\n[校准] 移动到左侧极限...")
        self._move_by_continuous(pan=-self.pan_speed, tilt=0, duration=self._calibrate_duration)
        logger.info("[校准] 到位")

        # === 阶段2: Z字形网格扫描（反馈式移动）===
        total_captures = self.pan_steps * self.tilt_steps
        capture_index = 0

        for tilt_idx in range(self.tilt_steps):
            if self._stop_flag:
                return images

            row_dir = 1 if tilt_idx % 2 == 0 else -1  # 偶数行→右, 奇数行→左
            col_range = range(self.pan_steps) if row_dir == 1 else range(self.pan_steps - 1, -1, -1)
            hit_deadzone = False  # 本行是否已撞死限

            logger.info(f"\n--- 第 {tilt_idx + 1}/{self.tilt_steps} 行 {'→' if row_dir == 1 else '←'} ---")

            # 非第一行: 垂直移动（反馈式，撞死限后回退到定时移动）
            if tilt_idx > 0:
                logger.info(f"  下移一行 (目标偏移 {self.pixel_shift})...")
                moved = self._move_until_shift(pan=0, tilt=-self.tilt_speed,
                                               target_shift=self.pixel_shift * 0.8)
                if not moved:
                    # 反馈式失效（撞死限），改用定时移动确保能拍到
                    logger.warning(f"  [回退] 反馈式俯仰失效，改用定时移动 3s")
                    self._move_by_continuous(pan=0, tilt=-self.tilt_speed, duration=3.0)
                    time.sleep(0.3)
                time.sleep(self.settle_time)

            # 扫描本行各列
            for col_idx in col_range:
                if self._stop_flag or hit_deadzone:
                    return images

                pos_label = f"r{tilt_idx + 1}_c{col_idx + 1}"

                # 非本行第一列: 反馈式移动（转到画面偏移达标才停）
                if col_idx != col_range[0]:
                    pan_val = self.pan_speed if row_dir == 1 else -self.pan_speed

                    if row_dir == 1:
                        logger.info(f"  → 右移 (目标偏移 {self.pixel_shift})")
                    else:
                        logger.info(f"  ← 左移 (目标偏移 {self.pixel_shift})")

                    moved = self._move_until_shift(pan=pan_val, tilt=0)

                    if not moved:
                        # 撞到死限了
                        logger.warning(f"  [死限] 转到极限了！跳过本行剩余位置")
                        self._cb("status", msg=f"第 {tilt_idx+1} 行撞到死限，跳过")
                        hit_deadzone = True
                        # 跳过剩余位置（计数补上）
                        remaining = len(col_range) - list(col_range).index(col_idx) - 1
                        for skip_idx in range(remaining):
                            capture_index += 1
                            self._cb("progress", current=capture_index, total=total_captures)
                        for skip_col in list(col_range)[list(col_range).index(col_idx) + 1:]:
                            skip_label = f"r{tilt_idx + 1}_c{skip_col + 1}"
                            skip_path = output_dir / f"{skip_label}.jpg"
                            if images:
                                import shutil
                                shutil.copy(str(images[-1][1]), str(skip_path))
                                images.append((skip_label, skip_path))
                        break

                    time.sleep(self.settle_time)

                # 抓拍
                if self._stop_flag:
                    return images

                capture_index += 1
                img_path = output_dir / f"{pos_label}.jpg"
                label = f"[{pos_label}]"
                self._cb("progress", current=capture_index, total=total_captures)
                success = self._capture_single(img_path, label=label)
                if success:
                    images.append((pos_label, img_path))
                else:
                    logger.warning(f"  {label} 采集失败")

        # 停止云台
        self.ptz.stop()
        return images

    # ---------- 云台移动（反馈式）----------

    def _move_by_continuous(self, pan: float = 0, tilt: float = 0, duration: float = 1.0):
        """连续移动指定时间后停止（用于校准阶段）"""
        if self._stop_flag:
            return
        self.isapi.ptz_continuous_move(pan=int(pan), tilt=int(tilt), zoom=0)
        if duration > 0:
            remaining = duration
            chunk = 0.2
            while remaining > 0 and not self._stop_flag:
                time.sleep(min(chunk, remaining))
                remaining -= chunk
            if not self._stop_flag:
                self.ptz.stop()

    def _move_until_shift(self, pan: float = 0, tilt: float = 0,
                          target_shift: Optional[float] = None) -> bool:
        """
        反馈式移动：增量移动直到画面变化量达标

        不断重复: 移动小幅度(0.5s) → 抓拍对比 → 够了吗？
        确保无论速度快慢、角度大小，每次移动后画面变化量基本一致。

        Args:
            pan:   水平速度 -100~100
            tilt:  垂直速度 -100~100
            target_shift: 目标像素差异值，None 则用 self.pixel_shift

        Returns:
            True  = 到达目标位置（或超时结束）
            False = 撞到死限（画面不再变化）
        """
        if self._stop_flag:
            return False

        target = target_shift or self.pixel_shift

        # 移动前先抓一张参考图
        ref_data = self._quick_snapshot()
        if ref_data is None:
            # 抓不到参考图，就用固定时间移动
            self._move_by_continuous(pan=pan, tilt=tilt, duration=self._burst_duration * 4)
            return True

        no_change_count = 0
        total_shift = 0.0

        for burst in range(self._max_bursts_per_step):
            if self._stop_flag:
                return False

            # 移动一小步
            self.isapi.ptz_continuous_move(pan=int(pan), tilt=int(tilt), zoom=0)
            time.sleep(self._burst_duration)
            self.ptz.stop()
            time.sleep(0.1)

            # 抓拍检查
            check_data = self._quick_snapshot()
            if check_data is None:
                continue

            # 和参考图对比
            shift = self._image_diff(ref_data, check_data)
            total_shift += shift

            logger.info(f"    移动脉冲 {burst+1}: 累计偏移 {total_shift:.1f} (目标 {target})")

            if total_shift >= target:
                logger.info(f"    ✓ 目标达成! 累计偏移 {total_shift:.1f}")
                return True

            # 死限检测：连续几次偏移接近0
            if shift < self._deadzone_threshold:
                no_change_count += 1
                if no_change_count >= 3:
                    logger.warning(f"    [死限] 连续 {no_change_count} 次无变化, 撞到限位")
                    return False
            else:
                no_change_count = 0

        logger.info(f"    超时结束, 累计偏移 {total_shift:.1f} (目标 {target})")
        return True

    # ---------- 死限检测 ----------

    def _quick_snapshot(self) -> Optional[bytes]:
        """快速抓拍一张用于比较（无保存、无重试）"""
        try:
            return self.isapi.get_snapshot()
        except Exception:
            return None

    def _image_diff(self, img_a: bytes, img_b: bytes) -> float:
        """
        计算两张图片的平均像素差异值

        Args:
            img_a, img_b: JPEG 字节数据

        Returns:
            平均像素差异 (0~255)，越大表示画面变化越大
        """
        try:
            import cv2, numpy as np
            if len(img_a) < 100 or len(img_b) < 100:
                return 0.0

            a = cv2.imdecode(np.frombuffer(img_a, np.uint8), cv2.IMREAD_GRAYSCALE)
            b = cv2.imdecode(np.frombuffer(img_b, np.uint8), cv2.IMREAD_GRAYSCALE)
            if a is None or b is None:
                return 0.0

            a_small = cv2.resize(a, (64, 48))
            b_small = cv2.resize(b, (64, 48))
            return float(np.abs(a_small.astype(int) - b_small.astype(int)).mean())
        except Exception:
            return 0.0

    # ---------- 抓拍 ----------

    def _capture_single(self, save_path: Path, retries: int = 3,
                        label: str = "") -> bool:
        """抓拍并保存单张图片"""
        for attempt in range(1, retries + 1):
            if self._stop_flag:
                return False

            try:
                img_data = self.isapi.get_snapshot()

                if img_data is None or len(img_data) < 100:
                    logger.info(f"  {label} 结果为空 (重试 {attempt}/{retries})")
                    time.sleep(attempt)
                    continue

                # 检查是否返回 XML 错误（设备繁忙）
                if img_data[:5] == b'<?xml' or img_data[:5] == b'<Resp':
                    logger.info(f"  {label} 摄像头繁忙 (重试 {attempt}/{retries})")
                    time.sleep(attempt * 1.5)
                    continue

                # 保存
                with open(save_path, "wb") as f:
                    f.write(img_data)
                logger.info(f"  {label} ✓ ({len(img_data)} bytes)")
                self._latest_capture_path = str(save_path)
                self._cb("capture", path=str(save_path), label=label)
                return True

            except ISAPIError as e:
                logger.info(f"  {label} 异常: {e} (重试 {attempt}/{retries})")
                time.sleep(1)
                continue

        logger.warning(f"  {label} ✗ 经 {retries} 次重试仍失败")
        return False

    # ---------- 拼接 ----------

    def _stitch_and_save(
        self, images: List[Tuple[str, Path]], output_dir: Path, timestamp: datetime
    ) -> Optional[Path]:
        """拼接全景图（特征匹配为主）"""
        if not images or len(images) < 2:
            logger.warning("图片不足2张，无法拼接")
            return None

        img_paths = [p for _, p in images]
        panorama_path = output_dir / "panorama.jpg"

        logger.info(f"\n正在拼接全景图 ({len(img_paths)} 张)...")

        # 特征匹配拼接（已证明比 OpenCV Stitcher 更可靠）
        pano = self._stitch_feature_match(img_paths)
        if pano is not None:
            cv2.imwrite(str(panorama_path), pano)
            file_size = os.path.getsize(panorama_path) / 1024
            h, w = pano.shape[:2]
            logger.info(f"全景图拼接成功! {w}x{h} ({file_size:.0f} KB)")
            logger.info(f"  -> {panorama_path}")
            self._cb("panorama", path=str(panorama_path))
            self._cb("status", msg=f"全景图完成: {w}x{h} ({file_size:.0f}KB)")
            return panorama_path

        logger.error("全景图拼接失败")
        self._cb("status", msg="全景图拼接失败")
        return None

    def _stitch_feature_match(self, img_paths: List[Path]):
        """
        特征匹配拼接 — 按顺序两两拼接

        使用 ORB + BFMatcher + RANSAC 逐对拼接，
        支持大位移和小位移场景。
        """
        try:
            canvas = cv2.imread(str(img_paths[0]))
            if canvas is None:
                return None

            orb = cv2.ORB_create(nfeatures=3000)
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

            for i in range(1, len(img_paths)):
                if self._stop_flag:
                    return None

                img_right = cv2.imread(str(img_paths[i]))
                if img_right is None:
                    continue

                hL, wL = canvas.shape[:2]
                hR, wR = img_right.shape[:2]

                # --- 特征检测 ---
                kpL, desL = orb.detectAndCompute(canvas, None)
                kpR, desR = orb.detectAndCompute(img_right, None)

                if desL is None or desR is None or len(kpL) < 8 or len(kpR) < 8:
                    logger.info(f"   [{i+1}] 特征点不足, 跳过")
                    continue

                # --- 特征匹配 ---
                matches = bf.match(desL, desR)
                matches = sorted(matches, key=lambda x: x.distance)

                # 取优质匹配（前40%）
                good = matches[:max(20, int(len(matches) * 0.4))]
                if len(good) < 8:
                    logger.info(f"   [{i+1}] 优质匹配不足 ({len(good)}), 跳过")
                    canvas = img_right  # 重新开始
                    continue

                # --- 单应性矩阵 (右→左) ---
                src_pts = np.float32([kpR[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
                dst_pts = np.float32([kpL[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
                H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)

                if H is None:
                    logger.info(f"   [{i+1}] 无法计算变换矩阵, 跳过")
                    continue

                inliers = mask.sum()
                logger.info(f"   [{i+1}] 内点: {inliers}/{len(good)} ({inliers/max(1,len(good))*100:.0f}%)")

                # --- 计算画布 ---
                corners_R = np.float32([[0, 0], [wR, 0], [wR, hR], [0, hR]]).reshape(-1, 1, 2)
                corners_R_in_L = cv2.perspectiveTransform(corners_R, H)
                corners_L = np.float32([[0, 0], [wL, 0], [wL, hL], [0, hL]]).reshape(-1, 1, 2)
                all_corners = np.concatenate((corners_L, corners_R_in_L), axis=0)

                [x_min, y_min] = np.int32(all_corners.min(axis=0).ravel() - 0.5)
                [x_max, y_max] = np.int32(all_corners.max(axis=0).ravel() + 0.5)
                canvas_w = x_max - x_min
                canvas_h = y_max - y_min

                # 如果画布没有变大，说明图片几乎完全重叠
                if canvas_w <= wL and canvas_h <= hL:
                    logger.info(f"   [{i+1}] 图片完全重叠 (无位移)")
                    continue

                # --- 拼接 ---
                T = np.array([[1, 0, -x_min], [0, 1, -y_min], [0, 0, 1]], dtype=np.float64)

                # 创建新画布
                new_canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)

                # 放置左图（已有拼接结果）
                y_off = -y_min
                x_off = -x_min
                if y_off >= 0 and x_off >= 0 and y_off + hL <= canvas_h and x_off + wL <= canvas_w:
                    new_canvas[y_off:y_off + hL, x_off:x_off + wL] = canvas

                # 变换右图并叠加
                warped_right = cv2.warpPerspective(img_right, T @ H, (canvas_w, canvas_h))
                mask_right = (warped_right > 0).all(axis=2)
                new_canvas[mask_right] = warped_right[mask_right]

                canvas = new_canvas
                logger.info(f"   -> 画布: {canvas_w}x{canvas_h}")

            return canvas

        except Exception as e:
            logger.warning(f"  特征匹配异常: {e}")
            return None

    # ---------- 日志 ----------

    def _save_log(self, output_dir: Path, timestamp: datetime,
                  count: int, panorama_path: Optional[Path]):
        """保存采集日志"""
        log = {
            "time": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "grid": f"{self.pan_steps}×{self.tilt_steps}",
            "images_captured": count,
            "panorama": str(panorama_path) if panorama_path else "failed",
            "params": {
                "pan_speed": self.pan_speed,
                "pixel_shift": self.pixel_shift,
            }
        }
        log_path = output_dir / "capture_log.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        logger.info(f"采集日志: {log_path}")

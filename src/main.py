#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主入口 - 海康威视 PTZ 摄像头控制程序

用法:
  # 连接摄像头并查询状态
  python src/main.py --status

  # 云台控制
  python src/main.py --ptz up --speed 50
  python src/main.py --ptz stop

  # 变倍
  python src/main.py --ptz zoom_in

  # 预置位
  python src/main.py --preset list
  python src/main.py --preset set --id 1
  python src/main.py --preset goto --id 1

  # 抓拍
  python src/main.py --snapshot snapshot.jpg

  # 设备信息
  python src/main.py --info

  # 全景图采集（单次）
  python src/main.py --panorama

  # 全景图自动循环（每5分钟）
  python src/main.py --auto --interval 5
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# 确保 src 目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.camera import CameraConfig
from src.isapi import ISAPIClient, ISAPIError
from src.ptz import PTZController, PTZDirection, PTZAction
from src.panorama import PanoramaCapture


def cmd_status(client: ISAPIClient):
    """查询摄像头状态"""
    print("正在连接摄像头...")
    try:
        info = client.get_device_info()
        if not info:
            print("[FAIL] 无法获取设备信息，请检查网络和认证")
            return 1
        print("\n=== 设备信息 ===")
        print(f"  设备名称: {info.get('device_name', 'N/A')}")
        print(f"  设备型号: {info.get('model', 'N/A')}")
        print(f"  序列号:   {info.get('serial', 'N/A')}")
        print(f"  固件版本: {info.get('firmware', 'N/A')}")
        print(f"  MAC 地址: {info.get('mac', 'N/A')}")
        print("[OK] 连接成功")
        return 0
    except ISAPIError as e:
        print(f"[FAIL] {e}")
        return 1


def cmd_info(client: ISAPIClient):
    """获取详细设备信息"""
    return cmd_status(client)


def cmd_ptz(ptz: PTZController, action: str, speed: int, duration: int):
    """PTZ 云台控制"""
    action_map = {
        "up":       (PTZDirection.UP, None),
        "down":     (PTZDirection.DOWN, None),
        "left":     (PTZDirection.LEFT, None),
        "right":    (PTZDirection.RIGHT, None),
        "upleft":   (PTZDirection.UP_LEFT, None),
        "upright":  (PTZDirection.UP_RIGHT, None),
        "downleft": (PTZDirection.DOWN_LEFT, None),
        "downright":(PTZDirection.DOWN_RIGHT, None),
        "stop":     (None, "stop"),
        "zoom_in":  (None, PTZAction.ZOOM_IN),
        "zoom_out": (None, PTZAction.ZOOM_OUT),
    }

    if action not in action_map:
        print(f"[FAIL] 未知动作: {action}")
        print(f"  可选: {', '.join(action_map.keys())}")
        return 1

    direction, special = action_map[action]

    try:
        if special == "stop":
            result = ptz.stop()
        elif special:
            result = ptz.action(special, speed)
        else:
            result = ptz.move(direction, speed, duration)

        if result:
            act_name = action.replace("_", " ").title()
            print(f"[OK] 云台动作执行成功: {act_name}")
            return 0
        else:
            print("[FAIL] 云台控制失败，请检查摄像头连接")
            return 1
    except ISAPIError as e:
        print(f"[FAIL] {e}")
        return 1


def cmd_preset(ptz: PTZController, action: str, preset_id: int, name: str):
    """预置位管理"""
    try:
        if action == "list":
            presets = ptz.preset_list()
            if not presets:
                print("没有配置预置位")
                return 0
            print(f"\n=== 预置位列表 (共 {len(presets)} 个) ===")
            for p in presets:
                print(f"  ID: {p['id']:>3}  名称: {p['name'] or '(未命名)'}")
            return 0
        elif action == "set":
            result = ptz.preset_set(preset_id, name)
            if result:
                print(f"[OK] 预置位 {preset_id} 已保存 ({name or '未命名'})")
                return 0
        elif action == "goto":
            result = ptz.preset_goto(preset_id)
            if result:
                print(f"[OK] 正在转到预置位 {preset_id}")
                return 0
        elif action == "delete":
            result = ptz.preset_delete(preset_id)
            if result:
                print(f"[OK] 预置位 {preset_id} 已删除")
                return 0
        else:
            print(f"[FAIL] 未知预置位操作: {action}")
            return 1

        print("[FAIL] 操作失败")
        return 1
    except ISAPIError as e:
        print(f"[FAIL] {e}")
        return 1


def cmd_snapshot(client: ISAPIClient, output: str):
    """抓拍"""
    print("正在抓拍...")
    try:
        img_data = client.get_snapshot()
        if not img_data:
            print("[FAIL] 抓拍失败")
            return 1
        with open(output, "wb") as f:
            f.write(img_data)
        print(f"[OK] 抓拍已保存: {output} ({len(img_data)} bytes)")
        return 0
    except ISAPIError as e:
        print(f"[FAIL] {e}")
        return 1


def cmd_panorama(config, pan_steps, tilt_steps, speed, pixel_shift):
    """单次全景图采集"""
    print("\n=== 全景图采集 ===")
    print(f"网格: {pan_steps}列 × {tilt_steps}行 ({pan_steps * tilt_steps}张)")
    print(f"速度: {speed}  目标偏移: {pixel_shift}px")
    print("开始采集（按 Ctrl+C 停止）...\n")

    # 配置日志
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    pano = PanoramaCapture(
        config,
        pan_steps=pan_steps,
        tilt_steps=tilt_steps,
        pan_speed=speed,
        pixel_shift=pixel_shift,
    )
    try:
        result = pano.capture()
        if result:
            print(f"\n[OK] 全景图已生成: {result}")
            return 0
        else:
            print("\n[FAIL] 全景图采集失败")
            return 1
    except KeyboardInterrupt:
        print("\n用户中断")
        pano.stop()
        return 0


def cmd_auto(config, interval, pan_steps, tilt_steps, speed, pixel_shift):
    """自动循环全景图采集"""
    print(f"\n=== 自动全景图模式 ===")
    print(f"间隔: {interval} 分钟")
    print(f"网格: {pan_steps}列 × {tilt_steps}行")
    print("按 Ctrl+C 停止\n")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    pano = PanoramaCapture(
        config,
        pan_steps=pan_steps,
        tilt_steps=tilt_steps,
        pan_speed=speed,
        pixel_shift=pixel_shift,
    )
    try:
        pano.auto_loop(interval_minutes=interval)
        return 0
    except KeyboardInterrupt:
        print("\n用户中断")
        pano.stop()
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="海康威视 PTZ 摄像头控制程序 v0.12",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --status              查询摄像头状态
  %(prog)s --ptz up --speed 50   云台上仰
  %(prog)s --ptz stop            停止云台
  %(prog)s --ptz zoom_in         变倍放大
  %(prog)s --preset set --id 1   设置预置位 1
  %(prog)s --preset goto --id 1  转到预置位 1
  %(prog)s --snapshot out.jpg    抓拍

  # 全景图
  %(prog)s --panorama            单次全景图采集（6x2=12张）
  %(prog)s --panorama --pan-steps 8 --tilt-steps 3  自定义网格
  %(prog)s --auto --interval 5   每5分钟自动采集全景图
        """
    )

    parser.add_argument("--status", action="store_true", help="查询摄像头状态")
    parser.add_argument("--info", action="store_true", help="获取设备详细信息")

    parser.add_argument("--ptz", metavar="ACTION",
                        help="云台控制: up/down/left/right/upleft/upright/downleft/downright/stop/zoom_in/zoom_out")
    parser.add_argument("--speed", type=int, default=50, help="云台速度 1-100 (默认 50)")
    parser.add_argument("--duration", type=int, default=0,
                        help="运动持续时间 ms，0=持续运动（需手动 stop）")

    parser.add_argument("--preset", metavar="ACTION",
                        help="预置位操作: list/set/goto/delete")
    parser.add_argument("--id", type=int, default=1, help="预置位 ID (默认 1)")
    parser.add_argument("--name", type=str, default="", help="预置位名称")

    parser.add_argument("--snapshot", metavar="FILE", help="抓拍并保存到文件")

    # 全景图参数
    parser.add_argument("--panorama", action="store_true", help="单次全景图采集")
    parser.add_argument("--auto", action="store_true", help="自动循环全景图采集")
    parser.add_argument("--interval", type=int, default=5,
                        help="自动采集间隔（分钟，默认 5）")
    parser.add_argument("--pan-steps", type=int, default=8,
                        help="水平方向步数（默认 8，覆盖全角度）")
    parser.add_argument("--tilt-steps", type=int, default=3,
                        help="垂直方向行数（默认 3）")
    parser.add_argument("--pixel-shift", type=float, default=40.0,
                        help="每步画面偏移量，画面变化达标才停（默认 40）")

    args = parser.parse_args()

    # 如果没有参数，显示帮助
    if len(sys.argv) == 1:
        parser.print_help()
        return 0

    # 加载配置
    try:
        config = CameraConfig()
    except FileNotFoundError as e:
        print(f"[FAIL] {e}")
        return 1
    except Exception as e:
        print(f"[FAIL] 配置加载失败: {e}")
        return 1

    print(f"摄像头: {config.ip}:{config.port}")
    print(f"协议:   {config.protocol.upper()}")

    # 初始化客户端
    client = ISAPIClient(config)
    ptz = PTZController(config)

    # 执行命令
    try:
        if args.status or args.info:
            return cmd_status(client) if args.status else cmd_info(client)

        if args.ptz:
            return cmd_ptz(ptz, args.ptz, args.speed, args.duration)

        if args.preset:
            return cmd_preset(ptz, args.preset, args.id, args.name)

        if args.snapshot:
            return cmd_snapshot(client, args.snapshot)

        if args.panorama:
            return cmd_panorama(config, args.pan_steps, args.tilt_steps, args.speed, args.pixel_shift)

        if args.auto:
            return cmd_auto(config, args.interval, args.pan_steps, args.tilt_steps, args.speed, args.pixel_shift)

    except ISAPIError as e:
        print(f"[FAIL] ISAPI 错误: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n用户中断")
        ptz.stop()
        return 0
    except Exception as e:
        print(f"[FAIL] 未预期的错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

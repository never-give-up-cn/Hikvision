"""
PTZ 云台控制模块

提供高级 PTZ 控制接口，封装底层 ISAPI/SDK 调用。
支持方向控制、变倍聚焦、预置位、巡航等功能。
"""

from enum import Enum
from typing import Optional

from .camera import CameraConfig
from .isapi import ISAPIClient


class PTZDirection(Enum):
    """云台方向"""
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    UP_LEFT = "upleft"
    UP_RIGHT = "upright"
    DOWN_LEFT = "downleft"
    DOWN_RIGHT = "downright"


class PTZAction(Enum):
    """PTZ 动作类型"""
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    FOCUS_NEAR = "focus_near"
    FOCUS_FAR = "focus_far"
    IRIS_OPEN = "iris_open"
    IRIS_CLOSE = "iris_close"


class PTZController:
    """PTZ 云台控制器"""

    def __init__(self, config: CameraConfig):
        self.config = config
        self.client = ISAPIClient(config)
        self._default_speed = config.get_ptz_speed() / 100.0  # 转为 0-1 范围

    def _normalize_speed(self, speed: Optional[int]) -> float:
        """将 1-100 的速度转为 ISAPI 的 0-1 范围"""
        if speed is None:
            return self._default_speed
        return max(0.01, min(1.0, speed / 100.0))

    def move(self, direction: PTZDirection, speed: Optional[int] = None,
             duration_ms: int = 0) -> bool:
        """
        向指定方向移动云台

        Args:
            direction: 移动方向
            speed: 速度 (1-100)，None 使用默认
            duration_ms: 运动持续时间（ms），0 表示持续运动直到调用 stop()

        Returns:
            bool: 是否成功
        """
        s = self._normalize_speed(speed)
        moves = {
            PTZDirection.UP:        lambda: self.client.ptz_move_up(s),
            PTZDirection.DOWN:      lambda: self.client.ptz_move_down(s),
            PTZDirection.LEFT:      lambda: self.client.ptz_move_left(s),
            PTZDirection.RIGHT:     lambda: self.client.ptz_move_right(s),
            PTZDirection.UP_LEFT:   lambda: self.client.ptz_move_upleft(s, s),
            PTZDirection.UP_RIGHT:  lambda: self.client.ptz_move_upright(s, s),
            PTZDirection.DOWN_LEFT: lambda: self.client.ptz_move_downleft(s, s),
            PTZDirection.DOWN_RIGHT: lambda: self.client.ptz_move_downright(s, s),
        }

        action = moves.get(direction)
        if not action:
            return False

        result = action()

        # 如果指定了持续时间，自动停止
        if duration_ms > 0 and result:
            import threading
            threading.Timer(duration_ms / 1000.0, self.stop).start()

        return result

    def stop(self) -> bool:
        """停止所有云台运动"""
        return self.client.ptz_stop()

    def action(self, action: PTZAction, speed: Optional[int] = None) -> bool:
        """
        PTZ 特殊动作控制

        Args:
            action: 动作类型（变倍、聚焦、光圈）
            speed: 速度 (1-100)

        Returns:
            bool: 是否成功
        """
        s = self._normalize_speed(speed)
        actions = {
            PTZAction.ZOOM_IN:    lambda: self.client.ptz_zoom_in(s),
            PTZAction.ZOOM_OUT:   lambda: self.client.ptz_zoom_out(s),
        }
        act = actions.get(action)
        if not act:
            return False
        return act()

    # ========== 预置位管理 ==========

    def preset_set(self, preset_id: int = 1, name: str = "") -> bool:
        """设置当前位置为预置位"""
        return self.client.preset_set(preset_id, name)

    def preset_goto(self, preset_id: int = 1) -> bool:
        """转到预置位"""
        return self.client.preset_goto(preset_id)

    def preset_delete(self, preset_id: int = 1) -> bool:
        """删除预置位"""
        return self.client.preset_delete(preset_id)

    def preset_list(self) -> list:
        """列出所有预置位"""
        return self.client.preset_list()

    # ========== 巡航管理 ==========

    def tour_start(self, tour_id: int = 1) -> bool:
        """开始巡航"""
        return self.client.tour_start(tour_id)

    def tour_stop(self, tour_id: int = 1) -> bool:
        """停止巡航"""
        return self.client.tour_stop(tour_id)

    # ========== 便捷操作 ==========

    def move_with_steps(self, direction: PTZDirection, steps: int = 1,
                        speed: Optional[int] = None) -> bool:
        """
        步进移动（短促移动指定步数）

        每步约 200ms，适用于精确定位
        """
        s = self._normalize_speed(speed)
        for _ in range(steps):
            success = self.move(direction, speed=int(s * 100), duration_ms=200)
            if not success:
                return False
        return True

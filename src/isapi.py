# -*- coding: utf-8 -*-
"""
ISAPI 协议实现模块

海康威视 ISAPI (Intelligent Security API) 是基于 HTTP REST 的开放协议，
可直接与摄像头通信，无需安装 HCNetSDK DLL。

ISAPI PTZ 控制使用 Continuous 模式:
  - 发送运动命令后，摄像头持续运动
  - 发送停止命令后，摄像头停止
  - 运动参数: pan(水平)、tilt(垂直)、zoom(变倍)
"""

import xml.etree.ElementTree as ET
from typing import Optional, Tuple
import requests
from requests.auth import HTTPDigestAuth
from requests.exceptions import RequestException

from .camera import CameraConfig


# PTZ 控制命令 XML 模板
PTZ_CONTINUOUS_XML = """<?xml version="1.0" encoding="utf-8"?>
<PTZData version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">
  <pan>{pan}</pan>
  <tilt>{tilt}</tilt>
  <zoom>{zoom}</zoom>
</PTZData>"""


class ISAPIError(Exception):
    """ISAPI 通信异常"""
    pass


class ISAPIClient:
    """海康威视 ISAPI 客户端"""

    def __init__(self, config: CameraConfig):
        self.config = config
        self.auth = HTTPDigestAuth(config.username, config.password)
        self.base_url = config.base_url
        self.channel = config.channel
        self._timeout = 5

    def _request(self, method: str, path: str, data: Optional[str] = None,
                 timeout: Optional[int] = None) -> requests.Response:
        """发送 HTTP 请求到 ISAPI"""
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/xml"}
        timeout = timeout or self._timeout

        try:
            resp = requests.request(
                method=method,
                url=url,
                auth=self.auth,
                headers=headers,
                data=data.encode("utf-8") if data else None,
                timeout=timeout
            )
            return resp
        except RequestException as e:
            raise ISAPIError(f"ISAPI 请求失败: {e}") from e

    def _check_response(self, resp: requests.Response) -> bool:
        """检查响应状态"""
        if resp.status_code in (200, 201):
            return True
        elif resp.status_code == 401:
            raise ISAPIError("认证失败，请检查用户名和密码")
        elif resp.status_code == 404:
            raise ISAPIError("ISAPI 路径不存在，设备可能不支持此功能")
        else:
            raise ISAPIError(f"请求失败，HTTP {resp.status_code}: {resp.text[:200]}")

    # ========== PTZ 云台控制 ==========

    def ptz_continuous_move(self, pan: int = 0, tilt: int = 0,
                            zoom: int = 0) -> bool:
        """
        云台连续运动控制

        参数范围（海康 ISAPI 实际范围）:
          pan:   -100 (左)  ~ 100 (右)
          tilt:  -100 (下)  ~ 100 (上)
          zoom:  -100 (缩)  ~ 100 (放)

        注意: 值为 0 表示停止该方向运动
        """
        xml = PTZ_CONTINUOUS_XML.format(pan=int(pan), tilt=int(tilt), zoom=int(zoom))
        path = f"/ISAPI/PTZCtrl/channels/{self.channel}/continuous"
        resp = self._request("PUT", path, data=xml)
        return self._check_response(resp)

    def ptz_stop(self) -> bool:
        """停止云台运动"""
        return self.ptz_continuous_move(pan=0, tilt=0, zoom=0)

    def ptz_move_up(self, speed: int = 30) -> bool:
        """云台上仰 (speed: 1-100)"""
        return self.ptz_continuous_move(tilt=speed)

    def ptz_move_down(self, speed: int = 30) -> bool:
        """云台下俯 (speed: 1-100)"""
        return self.ptz_continuous_move(tilt=-speed)

    def ptz_move_left(self, speed: int = 30) -> bool:
        """云台左转 (speed: 1-100)"""
        return self.ptz_continuous_move(pan=-speed)

    def ptz_move_right(self, speed: int = 30) -> bool:
        """云台右转 (speed: 1-100)"""
        return self.ptz_continuous_move(pan=speed)

    def ptz_move_upleft(self, pan_speed: int = 30, tilt_speed: int = 30) -> bool:
        """云台左上"""
        return self.ptz_continuous_move(pan=-pan_speed, tilt=tilt_speed)

    def ptz_move_upright(self, pan_speed: int = 30, tilt_speed: int = 30) -> bool:
        """云台右上"""
        return self.ptz_continuous_move(pan=pan_speed, tilt=tilt_speed)

    def ptz_move_downleft(self, pan_speed: int = 30, tilt_speed: int = 30) -> bool:
        """云台左下"""
        return self.ptz_continuous_move(pan=-pan_speed, tilt=-tilt_speed)

    def ptz_move_downright(self, pan_speed: int = 30, tilt_speed: int = 30) -> bool:
        """云台右下"""
        return self.ptz_continuous_move(pan=pan_speed, tilt=-tilt_speed)

    def ptz_zoom_in(self, speed: int = 30) -> bool:
        """变倍放大"""
        return self.ptz_continuous_move(zoom=speed)

    def ptz_zoom_out(self, speed: int = 30) -> bool:
        """变倍缩小"""
        return self.ptz_continuous_move(zoom=-speed)

    # ========== 预置位管理 ==========

    def preset_set(self, preset_id: int = 1, name: str = "") -> bool:
        """设置预置位"""
        xml = f'''<?xml version="1.0" encoding="utf-8"?>
<PTZPreset version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">
  <id>{preset_id}</id>
  <presetName>{name}</presetName>
</PTZPreset>'''
        path = f"/ISAPI/PTZCtrl/channels/{self.channel}/presets/{preset_id}"
        resp = self._request("PUT", path, data=xml)
        return self._check_response(resp)

    def preset_goto(self, preset_id: int = 1) -> bool:
        """转到预置位"""
        xml = f'''<?xml version="1.0" encoding="utf-8"?>
<PTZGoto version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">
  <id>{preset_id}</id>
</PTZGoto>'''
        path = f"/ISAPI/PTZCtrl/channels/{self.channel}/presets/{preset_id}/goto"
        resp = self._request("PUT", path, data=xml)
        return self._check_response(resp)

    def preset_delete(self, preset_id: int = 1) -> bool:
        """删除预置位"""
        path = f"/ISAPI/PTZCtrl/channels/{self.channel}/presets/{preset_id}"
        resp = self._request("DELETE", path)
        return self._check_response(resp)

    def preset_list(self) -> list:
        """获取预置位列表"""
        path = f"/ISAPI/PTZCtrl/channels/{self.channel}/presets"
        resp = self._request("GET", path)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        presets = []
        for preset in root.findall(".//PTZPreset"):
            p_id = preset.findtext("id", "")
            p_name = preset.findtext("presetName", "")
            presets.append({"id": p_id, "name": p_name})
        return presets

    # ========== 巡航（自动扫描）==========

    def tour_start(self, tour_id: int = 1) -> bool:
        """开始巡航"""
        xml = f'''<?xml version="1.0" encoding="utf-8"?>
<PTZTour version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">
  <id>{tour_id}</id>
</PTZTour>'''
        path = f"/ISAPI/PTZCtrl/channels/{self.channel}/tours/{tour_id}/start"
        resp = self._request("PUT", path, data=xml)
        return self._check_response(resp)

    def tour_stop(self, tour_id: int = 1) -> bool:
        """停止巡航"""
        path = f"/ISAPI/PTZCtrl/channels/{self.channel}/tours/{tour_id}/stop"
        resp = self._request("PUT", path)
        return self._check_response(resp)

    # ========== 图像获取 ==========

    def get_snapshot(self) -> Optional[bytes]:
        """
        获取当前画面快照（JPEG）

        尝试多个通道号（1, 101），某些相机主码流为 101
        """
        channels_to_try = [102, self.channel, 101, 1]

        # 检查内容是否是 XML 错误
        def is_error_xml(data: bytes) -> bool:
            return data[:5] in (b'<?xml', b'<Resp')

        for ch in channels_to_try:
            try:
                path = f"/ISAPI/Streaming/channels/{ch}/picture"
                resp = self._request("GET", path, timeout=10)
                if resp.status_code == 200 and resp.content and not is_error_xml(resp.content):
                    return resp.content
                if resp.status_code == 503:
                    # 设备繁忙，不继续尝试其他通道
                    return None
            except Exception:
                continue

        return None

    def get_device_info(self) -> dict:
        """获取设备信息"""
        resp = self._request("GET", "/ISAPI/System/deviceInfo")
        if resp.status_code != 200:
            return {}
        root = ET.fromstring(resp.content)
        # 处理 Hikvision XML 命名空间
        ns = {"hk": "http://www.hikvision.com/ver20/XMLSchema"}
        return {
            "device_name": root.findtext("hk:deviceName", "", ns),
            "device_id": root.findtext("hk:deviceID", "", ns),
            "model": root.findtext("hk:model", "", ns),
            "serial": root.findtext("hk:serialNumber", "", ns),
            "firmware": root.findtext("hk:firmwareVersion", "", ns),
            "mac": root.findtext("hk:macAddress", "", ns),
        }

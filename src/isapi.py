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

    def ptz_continuous_move(self, pan: float = 0, tilt: float = 0,
                            zoom: float = 0) -> bool:
        """
        云台连续运动控制

        参数范围（ISAPI 标准）:
          pan:   -1.0 (左)  ~ 1.0 (右)
          tilt:  -1.0 (下)  ~ 1.0 (上)
          zoom:  -1.0 (缩)  ~ 1.0 (放)

        注意: 海康摄像头 pan/tilt 符号与标准可能不同
        """
        xml = PTZ_CONTINUOUS_XML.format(pan=pan, tilt=tilt, zoom=zoom)
        path = f"/ISAPI/PTZCtrl/channels/{self.channel}/continuous"
        resp = self._request("PUT", path, data=xml)
        return self._check_response(resp)

    def ptz_stop(self) -> bool:
        """停止云台运动"""
        return self.ptz_continuous_move(pan=0, tilt=0, zoom=0)

    def ptz_move_up(self, speed: float = 0.5) -> bool:
        """云台上仰"""
        return self.ptz_continuous_move(tilt=speed)

    def ptz_move_down(self, speed: float = 0.5) -> bool:
        """云台下俯"""
        return self.ptz_continuous_move(tilt=-speed)

    def ptz_move_left(self, speed: float = 0.5) -> bool:
        """云台左转"""
        return self.ptz_continuous_move(pan=-speed)

    def ptz_move_right(self, speed: float = 0.5) -> bool:
        """云台右转"""
        return self.ptz_continuous_move(pan=speed)

    def ptz_move_upleft(self, pan_speed: float = 0.5, tilt_speed: float = 0.5) -> bool:
        """云台左上"""
        return self.ptz_continuous_move(pan=-pan_speed, tilt=tilt_speed)

    def ptz_move_upright(self, pan_speed: float = 0.5, tilt_speed: float = 0.5) -> bool:
        """云台右上"""
        return self.ptz_continuous_move(pan=pan_speed, tilt=tilt_speed)

    def ptz_move_downleft(self, pan_speed: float = 0.5, tilt_speed: float = 0.5) -> bool:
        """云台左下"""
        return self.ptz_continuous_move(pan=-pan_speed, tilt=-tilt_speed)

    def ptz_move_downright(self, pan_speed: float = 0.5, tilt_speed: float = 0.5) -> bool:
        """云台右下"""
        return self.ptz_continuous_move(pan=pan_speed, tilt=-tilt_speed)

    def ptz_zoom_in(self, speed: float = 0.5) -> bool:
        """变倍放大"""
        return self.ptz_continuous_move(zoom=speed)

    def ptz_zoom_out(self, speed: float = 0.5) -> bool:
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
        """获取当前画面快照（JPEG）"""
        path = f"/ISAPI/Streaming/channels/{self.channel}/picture"
        resp = self._request("GET", path, timeout=10)
        if resp.status_code == 200 and resp.content:
            return resp.content
        return None

    def get_device_info(self) -> dict:
        """获取设备信息"""
        resp = self._request("GET", "/ISAPI/System/deviceInfo")
        if resp.status_code != 200:
            return {}
        root = ET.fromstring(resp.content)
        return {
            "device_name": root.findtext("deviceName", ""),
            "device_id": root.findtext("deviceID", ""),
            "model": root.findtext("model", ""),
            "serial": root.findtext("serialNumber", ""),
            "firmware": root.findtext("firmwareVersion", ""),
            "mac": root.findtext("macAddress", ""),
        }

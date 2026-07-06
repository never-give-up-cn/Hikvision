"""
摄像头连接与数据获取模块

提供摄像头连接管理、状态查询、视频流获取等功能。
支持两种通信方式:
  1. ISAPI (HTTP REST API) — 无需 SDK DLL，默认使用
  2. HCNetSDK — 需要官方 SDK DLL，功能更全面
"""

import os
import yaml
import base64
from pathlib import Path
from typing import Optional, Dict, Any


class CameraConfig:
    """摄像头配置管理"""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = self._find_config()
        self.config_path = config_path
        self.config = self._load_config()

    def _find_config(self) -> str:
        """查找配置文件，优先使用 local 配置"""
        base_dir = Path(__file__).parent.parent / "config"
        local_config = base_dir / "camera.local.yaml"
        default_config = base_dir / "camera.yaml"

        if local_config.exists():
            return str(local_config)
        return str(default_config)

    def _load_config(self) -> Dict[str, Any]:
        """加载 YAML 配置"""
        path = Path(self.config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @property
    def ip(self) -> str:
        return self.config["camera"]["ip"]

    @property
    def port(self) -> int:
        return self.config["camera"].get("port", 8000)

    @property
    def username(self) -> str:
        return self.config["camera"]["username"]

    @property
    def password(self) -> str:
        return self.config["camera"]["password"]

    @property
    def channel(self) -> int:
        return self.config["camera"].get("channel", 1)

    @property
    def protocol(self) -> str:
        return self.config["camera"].get("protocol", "isapi")

    @property
    def auth(self) -> str:
        """HTTP Basic Auth 头"""
        credentials = f"{self.username}:{self.password}"
        encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"

    @property
    def base_url(self) -> str:
        return f"http://{self.ip}:{self.port}"

    def get_ptz_speed(self) -> int:
        return self.config.get("ptz", {}).get("speed", 50)

    def get_ptz_step(self) -> int:
        return self.config.get("ptz", {}).get("step", 10)


class CameraConnection:
    """摄像头连接管理器"""

    def __init__(self, config: CameraConfig):
        self.config = config
        self._connected = False
        self._device_info: Optional[Dict[str, Any]] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        """建立与摄像头的连接"""
        # ISAPI 协议是 stateless 的，每次请求都携带认证
        # 这里只做连接验证
        if self.config.protocol == "isapi":
            return self._connect_isapi()
        else:
            return self._connect_sdk()

    def _connect_isapi(self) -> bool:
        """通过 ISAPI 验证连接"""
        import requests
        from requests.auth import HTTPDigestAuth

        url = f"{self.config.base_url}/ISAPI/System/deviceInfo"
        try:
            resp = requests.get(
                url,
                auth=HTTPDigestAuth(self.config.username, self.config.password),
                timeout=5
            )
            if resp.status_code == 200:
                self._connected = True
                # 解析设备信息
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.content)
                self._device_info = {
                    "device_name": root.findtext(".//deviceName", ""),
                    "device_id": root.findtext(".//deviceID", ""),
                    "model": root.findtext(".//model", ""),
                    "serial": root.findtext(".//serialNumber", ""),
                    "firmware": root.findtext(".//firmwareVersion", ""),
                }
                return True
            else:
                print(f"[ERROR] 连接失败，HTTP {resp.status_code}: {resp.text}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] 连接异常: {e}")
            return False

    def _connect_sdk(self) -> bool:
        """通过 HCNetSDK 连接（需要 DLL）"""
        # 将在 hiksdk.py 中实现
        print("[WARN] SDK 连接尚未实现，请使用 ISAPI 协议")
        return False

    def get_device_info(self) -> Dict[str, Any]:
        """获取设备信息"""
        return self._device_info or {}

    def get_status(self) -> Dict[str, Any]:
        """获取摄像头状态"""
        if self.config.protocol == "isapi":
            return self._get_status_isapi()
        return {}

    def _get_status_isapi(self) -> Dict[str, Any]:
        """通过 ISAPI 获取状态"""
        import requests
        from requests.auth import HTTPDigestAuth

        status = {}
        # 通道状态
        url = f"{self.config.base_url}/ISAPI/System/Video/inputs/channels/{self.config.channel}/status"
        try:
            resp = requests.get(
                url,
                auth=HTTPDigestAuth(self.config.username, self.config.password),
                timeout=5
            )
            if resp.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.content)
                status["online"] = root.findtext(".//online", "")
        except Exception as e:
            status["error"] = str(e)

        return status

    def disconnect(self):
        """断开连接"""
        self._connected = False
        self._device_info = None

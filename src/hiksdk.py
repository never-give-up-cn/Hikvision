# -*- coding: utf-8 -*-
"""
海康威视 HCNetSDK DLL 包装器

通过 ctypes 调用官方 HCNetSDK.dll，提供更完整的设备控制功能。
注意: 需要将 HCNetSDK.dll 等文件放入 sdk/ 目录。

此模块为可选功能，默认使用 ISAPI 协议。
"""

import ctypes
import os
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from ctypes import (
    c_int, c_uint, c_long, c_ulong, c_char_p, c_void_p,
    c_bool, c_byte, c_ushort, c_short, Structure, POINTER,
    byref, create_string_buffer, CFUNCTYPE, WINFUNCTYPE, c_uint32
)

from .camera import CameraConfig


# SDK 常量
NET_DVR_DEV_ADDRESS_MAX_LEN = 128
NET_DVR_LOGIN_INFO_LEN = 4000
NET_DVR_MAX_CHANNUM = 16

# 错误码
NET_DVR_NOERROR = 0
NET_DVR_PASSWORD_ERROR = 100
NET_DVR_USER_NOT_EXIST = 117


class NET_DVR_DEVICEINFO_V40(Structure):
    """设备信息结构体"""
    _fields_ = [
        ("struDeviceV30", c_byte * 100),  # 设备信息
        ("bySupportLock", c_byte),
        ("byRetryLoginTime", c_byte),
        ("byPasswordLevel", c_byte),
        ("byProxyType", c_byte),
        ("byRes", c_byte * 243),
    ]


class NET_DVR_USER_LOGIN_INFO(Structure):
    """登录信息结构体"""
    _fields_ = [
        ("sDeviceAddress", c_byte * NET_DVR_DEV_ADDRESS_MAX_LEN),
        ("byUseTransport", c_byte),
        ("wPort", c_ushort),
        ("sUserName", c_byte * 64),
        ("sPassword", c_byte * 64),
        ("byLoginMode", c_byte),
        ("byRes2", c_byte * 254),
    ]


class HikSDK:
    """海康 HCNetSDK DLL 包装器"""

    def __init__(self, config: CameraConfig):
        self.config = config
        self._dll: Optional[ctypes.CDLL] = None
        self._user_id: int = -1
        self._loaded = False

    def load_dll(self, dll_path: Optional[str] = None) -> bool:
        """
        加载 HCNetSDK DLL

        Args:
            dll_path: DLL 路径，None 则自动搜索 sdk/ 目录
        """
        if self._loaded:
            return True

        if dll_path is None:
            # 自动搜索
            base_dir = Path(__file__).parent.parent / "sdk"
            candidates = [
                base_dir / "HCNetSDK.dll",
                base_dir / "libhcnetsdk.so",
                base_dir / "libhcnetsdk.dylib",
            ]
            for path in candidates:
                if path.exists():
                    dll_path = str(path)
                    break

        if not dll_path or not os.path.exists(dll_path):
            print("[WARN] HCNetSDK DLL 未找到，请将 DLL 放入 sdk/ 目录")
            print("[WARN] 可前往 https://open.hikvision.com/ 下载设备网络SDK")
            return False

        try:
            if os.name == "nt":
                self._dll = ctypes.WinDLL(dll_path)
            else:
                self._dll = ctypes.CDLL(dll_path)
            self._loaded = True
            print(f"[INFO] HCNetSDK DLL 加载成功: {dll_path}")
            return True
        except Exception as e:
            print(f"[ERROR] DLL 加载失败: {e}")
            return False

    def login(self) -> bool:
        """登录设备"""
        if not self._loaded:
            return False

        login_info = NET_DVR_USER_LOGIN_INFO()
        device_info = NET_DVR_DEVICEINFO_V40()

        # 设置 IP
        ip_bytes = self.config.ip.encode("utf-8")
        for i, b in enumerate(ip_bytes):
            login_info.sDeviceAddress[i] = b

        # 设置端口
        login_info.wPort = self.config.port

        # 设置用户名
        user_bytes = self.config.username.encode("utf-8")
        for i, b in enumerate(user_bytes):
            login_info.sUserName[i] = b

        # 设置密码
        pass_bytes = self.config.password.encode("utf-8")
        for i, b in enumerate(pass_bytes):
            login_info.sPassword[i] = b

        # 调用登录
        login_func = self._dll.NET_DVR_Login_V40
        login_func.argtypes = [
            POINTER(NET_DVR_USER_LOGIN_INFO),
            POINTER(NET_DVR_DEVICEINFO_V40)
        ]
        login_func.restype = c_long

        self._user_id = login_func(byref(login_info), byref(device_info))

        if self._user_id < 0:
            err_code = self.get_last_error()
            print(f"[ERROR] 登录失败，错误码: {err_code}")
            return False

        print(f"[INFO] 登录成功! UserID: {self._user_id}")
        return True

    def logout(self) -> bool:
        """登出"""
        if self._user_id < 0:
            return True

        logout_func = self._dll.NET_DVR_Logout
        logout_func.restype = c_bool
        result = logout_func(self._user_id)
        self._user_id = -1
        return result

    def get_last_error(self) -> int:
        """获取最后错误码"""
        func = self._dll.NET_DVR_GetLastError
        func.restype = c_uint32
        return func()

    def cleanup(self):
        """释放 SDK 资源"""
        if self._dll:
            try:
                cleanup = self._dll.NET_DVR_Cleanup
                cleanup.restype = c_bool
                cleanup()
            except Exception:
                pass

    def __del__(self):
        self.logout()
        self.cleanup()

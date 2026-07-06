# Hikvision SDK

在此目录放置海康威视 HCNetSDK 动态库文件：

## 必需文件

- `HCNetSDK.dll` — 海康威视网络客户端 SDK（核心库）
- `HCCore.dll` — SDK 核心组件
- `HCNetSDKCom/` — SDK 组件目录

## 获取方式

1. 前往 [海康威视开放平台](https://open.hikvision.com/) 下载设备网络SDK
2. 选择适用于 Windows x64 的 SDK 包
3. 将 `bin/` 目录下的 DLL 文件复制到此文件夹

## 版本说明

本项目使用 ISAPI 协议（HTTP REST API）作为主要通信方式，无需 SDK DLL 即可运行。
SDK DLL 仅用于高级功能（如本地解码显示、录像回放等）。

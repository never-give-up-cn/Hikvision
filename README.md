# 海康威视 PTZ 摄像头控制工程
# Hikvision PTZ Camera Control Project

## 项目概述

基于海康威视 SDK/ISAPI 协议的 PTZ（云台）摄像头控制程序，支持摄像头连接、云台控制、预置位管理等功能。

**摄像头地址:** 192.168.1.8

## 项目结构

```
hikvision-ptz/
├── README.md              # 项目文档和版本历史
├── config/
│   └── camera.yaml         # 摄像头配置文件
├── src/                    # 源代码
│   ├── main.py             # 主入口
│   ├── camera.py           # 摄像头连接与数据获取
│   ├── ptz.py              # PTZ 云台控制
│   ├── isapi.py            # ISAPI 协议实现（HTTP API）
│   └── hiksdk.py           # HCNetSDK DLL 包装器
├── sdk/                    # 海康 SDK DLL 存放目录
│   └── README.md           # SDK 获取说明
├── ref/
│   └── hikvision/          # 参考仓库（submodule）
├── requirements.txt
└── .gitignore
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置摄像头

编辑 `config/camera.yaml` 中的摄像头参数。

### 3. 运行

```bash
python src/main.py
```

### 命令示例

```bash
# 连接摄像头并预览
python src/main.py --preview

# 控制云台：上、下、左、右
python src/main.py --ptz up --speed 50
python src/main.py --ptz down --speed 30
python src/main.py --ptz left
python src/main.py --ptz right

# 控制云台：变倍、聚焦、光圈
python src/main.py --ptz zoom_in
python src/main.py --ptz zoom_out
python src/main.py --ptz focus_near
python src/main.py --ptz iris_open

# 预置位操作
python src/main.py --preset set --id 1      # 设置预置位 1
python src/main.py --preset goto --id 1     # 转到预置位 1
python src/main.py --preset delete --id 1   # 删除预置位 1

# 巡航
python src/main.py --tour start --id 1      # 开始巡航
python src/main.py --tour stop              # 停止巡航

# 获取摄像头状态
python src/main.py --status

# 抓拍
python src/main.py --snapshot output.jpg
```

## ISAPI 协议说明

本程序默认使用 **ISAPI**（HTTP REST API）与摄像头通信，无需安装海康 SDK。
摄像头内置的 ISAPI 接口路径：

| 功能 | ISAPI 路径 |
|------|-----------|
| 设备信息 | `/ISAPI/System/deviceInfo` |
| 云台控制 | `/ISAPI/PTZCtrl/channels/1/continuous` |
| 预置位 | `/ISAPI/PTZCtrl/channels/1/presets` |
| 抓拍 | `/ISAPI/Streaming/channels/1/picture` |

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| v0.1 | 2026-07-06 | 项目初始化：创建工程结构，实现 ISAPI 协议 PTZ 云台控制（上下左右、变倍、聚焦、预置位），摄像头配置管理 |

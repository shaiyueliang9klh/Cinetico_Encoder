# DataStream Encoder

> 专为数字媒体创作者打造的自动化视频压制工具。
> A minimalist, high-performance video encoding automation tool.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.txt)
[![Python 3.x](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![Platform Windows](https://img.shields.io/badge/Platform-Windows-0078D6.svg)]()

**DataStream Encoder** 是一款基于 Python 和 FFmpeg 构建的现代化视频处理工具。它摒弃了繁琐的命令行参数，结合 `CustomTkinter` 的现代 UI 设计与底层系统优化，旨在提供“即拖即用”的流畅压制体验。

核心目标是解决创作流中繁琐的编码配置痛点，让技术更好地服务于艺术创作。

## ✨ 功能亮点 (Key Features)

* **⚡️ 零门槛环境部署 (Zero-Config Setup)**
    * **智能依赖管理**：内置环境自检模块，自动检测并安装 `customtkinter`、`tkinterdnd2` 等必要库。
    * **国内源加速**：自动识别网络环境，配置镜像源加速依赖下载，开箱即用。

* **🖱️ 极简交互流 (Minimalist Workflow)**
    * **拖拽支持 (Drag & Drop)**：原生支持文件拖拽输入，告别传统的文件选择窗口。
    * **现代化 UI**：基于深色模式设计的极简界面，专注内容，无干扰。

* **🛡️ 系统级稳定性保护 (System Stability)**
    * **动态内存熔断**：通过 `GlobalMemoryStatusEx` 实时监控系统物理内存，智能计算安全阈值，防止高负载压制导致系统卡死。
    * **功耗模式管理**：调用 Windows API (`ES_SYSTEM_REQUIRED`)，强制系统在渲染期间保持高性能运行，防止进入睡眠或“效率模式”降低编码速度。

* **🎬 专业内核**
    * 基于工业级标准的 **FFmpeg** 编码核心。
    * 防御性编程设计，自动校验编解码器完整性。

## 🛠️ 技术栈 (Tech Stack)

* **Language**: Python 3.10+
* **GUI Framework**: CustomTkinter, TkinterDnD2
* **Core Engine**: FFmpeg, FFprobe
* **System Integration**: `ctypes` (Windows API access)

## 🚀 快速开始 (Quick Start)

### 1. 获取代码
```bash
git clone [https://github.com/shaiyueliang9klh/DataStream_Encoder.git](https://github.com/shaiyueliang9klh/DataStream_Encoder.git)
cd DataStream_Encoder

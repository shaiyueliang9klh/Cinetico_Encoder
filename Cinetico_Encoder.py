"""
Project: Cinético Encoder
Description: High-performance video compression tool based on FFmpeg and CustomTkinter.
             Supports hardware acceleration (NVENC/VideoToolbox), batch processing, 
             and automatic theme adaptation (Light/Dark mode).
Author: Zheng Qixiang (Optimized by Assistant)
"""

import os
import sys
import shutil
import platform
import zipfile
import urllib.request
import subprocess
import importlib.util
import threading
import time
import ctypes
import uuid
import random
import http.server
import socketserver
import socket  # 用于单实例锁和端口安全
import string  # 用于磁盘盘符遍历
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from collections import deque
from http import HTTPStatus
import queue                       # [PyArchitect Fix] 提升为全局导入以解决作用域问题
from typing import Callable, Any   # [PyArchitect Fix] 补充类型提示所需依赖

# =========================================================================
# [Module 1] Environment Initialization & Dependency Management
# 功能：自动检测 Python 依赖库与 FFmpeg 二进制环境，缺失时自动下载/安装
# =========================================================================

# 全局常量定义
FFMPEG_PATH = "ffmpeg"
FFPROBE_PATH = "ffprobe"

from typing import Callable, Optional

def check_and_install_dependencies(status_cb: Optional[Callable[[str], None]] = None, 
                                   progress_cb: Optional[Callable[[float], None]] = None) -> None:
    """
    环境自检函数 (支持异步状态回调)。
    1. 检查并自动安装缺失的 Python 库。
    2. 检查 FFmpeg，若不存在则自动下载解压，并通过回调实时更新 UI。
    """
    global FFMPEG_PATH, FFPROBE_PATH
    
    def _report_status(msg: str) -> None:
        """内部状态报告器：同时输出到控制台与 UI 回调"""
        print(msg)
        if status_cb:
            status_cb(msg)

    # 1. 冻结环境检测 (打包模式)
    if getattr(sys, 'frozen', False):
        _report_status("Frozen env detected, skipping pip...")
        bundle_dir = sys._MEIPASS 
        target_ffmpeg = os.path.join(bundle_dir, "bin", "ffmpeg")
        if os.path.exists(target_ffmpeg):
            FFMPEG_PATH = target_ffmpeg
            try: os.chmod(target_ffmpeg, 0o755)
            except: pass
        return

    # 2. Python 依赖库检查
    required_packages = [
        ("customtkinter", "customtkinter"), ("tkinterdnd2", "tkinterdnd2"),
        ("PIL", "pillow"), ("packaging", "packaging"),
        ("uuid", "uuid"), ("darkdetect", "darkdetect") 
    ]
    
    _report_status("Checking Python Dependencies...")
    for import_name, package_name in required_packages:
        if importlib.util.find_spec(import_name) is None:
            _report_status(f"Installing {package_name}...")
            try:
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", package_name, 
                    "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"
                ])
            except subprocess.CalledProcessError:
                _report_status(f"ERR: Failed to install {package_name}")

    # 3. FFmpeg 二进制检查与下载
    _report_status("Checking Core Engine...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(base_dir, "bin")
    os.makedirs(bin_dir, exist_ok=True)

    system_name = platform.system()
    if system_name == "Windows":
        target_ffmpeg, target_ffprobe = os.path.join(bin_dir, "ffmpeg.exe"), os.path.join(bin_dir, "ffprobe.exe")
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    elif system_name == "Darwin":
        target_ffmpeg, target_ffprobe = os.path.join(bin_dir, "ffmpeg"), os.path.join(bin_dir, "ffprobe")
        url = "https://evermeet.cx/ffmpeg/ffmpeg-6.0.zip" 
    else:
        return

    # 路径判定
    if os.path.exists(target_ffmpeg):
        FFMPEG_PATH, FFPROBE_PATH = target_ffmpeg, target_ffprobe
        return
    elif shutil.which("ffmpeg"):
        FFMPEG_PATH, FFPROBE_PATH = "ffmpeg", "ffprobe"
        return

    # 下载逻辑
    _report_status("Downloading FFmpeg...")
    try:
        zip_path = os.path.join(bin_dir, "ffmpeg_temp.zip")
        
        # 核心：将 urllib 的进度钩子转化为 UI 的进度条与状态文字
        def progress_hook(count: int, block_size: int, total_size: int) -> None:
            if total_size > 0:
                percent = (count * block_size) / total_size
                final_pct = min(1.0, percent)
                # 更新 UI 状态文字与底部的物理进度条
                if status_cb: status_cb(f"DOWNLOADING FFMPEG... {int(final_pct * 100)}%")
                if progress_cb: progress_cb(final_pct)
        
        urllib.request.urlretrieve(url, zip_path, reporthook=progress_hook)
        
        _report_status("Extracting Engine...")
        if progress_cb: progress_cb(0.0) # 进度条重置，准备解压动画 (可选)
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file in zip_ref.namelist():
                filename = os.path.basename(file)
                if "ffmpeg" in filename and not filename.endswith(".html"):
                        source = zip_ref.open(file)
                        t_file = target_ffmpeg if "ffmpeg" in filename else target_ffprobe
                        if "ffmpeg" in filename.lower() or "ffprobe" in filename.lower():
                            with open(t_file, "wb") as f_out: shutil.copyfileobj(source, f_out)

        try: os.remove(zip_path)
        except: pass
        
        if system_name == "Darwin":
            os.chmod(target_ffmpeg, 0o755)
            if os.path.exists(target_ffprobe): os.chmod(target_ffprobe, 0o755)

        FFMPEG_PATH, FFPROBE_PATH = target_ffmpeg, target_ffprobe
        _report_status("Engine Deployed.")
        
    except Exception as e:
        _report_status(f"ERR: FFmpeg DL Failed - {e}")


# =========================================================================
# [Module 2] Core Application Logic & UI
# 功能：主程序逻辑，包含 GUI 构建、任务调度、硬件监控与 FFmpeg 封装
# =========================================================================

import customtkinter as ctk  
import tkinter as tk         
from tkinter import filedialog, messagebox

# --- GUI 配置与主题适配 ---
# 强制使用 System 模式，配合元组颜色定义实现 Light/Dark 自动切换
ctk.set_appearance_mode("System") 
ctk.set_default_color_theme("blue")

# [色彩系统] 定义双态颜色元组 (Light_Color, Dark_Color)
# 这种定义方式确保了应用在 macOS/Windows 的浅色和深色模式下均有良好的对比度
COLOR_BG_MAIN     = ("#F3F3F3", "#121212")    # 主背景
COLOR_PANEL_LEFT  = ("#FFFFFF", "#1a1a1a")    # 侧边栏
COLOR_PANEL_RIGHT = ("#F9F9F9", "#0f0f0f")    # 内容区
COLOR_CARD        = ("#F2F2F2", "#2d2d2d")    # 任务卡片 (将浅色模式下的纯白改为浅灰，确保与侧边栏区分)
COLOR_TEXT_MAIN   = ("#333333", "#FFFFFF")    # 主要文字
COLOR_TEXT_SUB    = ("#555555", "#888888")    # 次要文字
COLOR_TEXT_HINT   = ("#888888", "#AAAAAA")    # 提示/占位符
COLOR_ACCENT      = ("#3B8ED0", "#3B8ED0")    # 品牌强调色
COLOR_ACCENT_HOVER= ("#36719f", "#36719f")    # 强调色悬停
COLOR_BORDER      = ("#E0E0E0", "#333333")    # 边框/分割线

# 状态指示色 (通常不需要根据主题大幅变化，但在浅色下微调以保证可视性)
COLOR_SUCCESS     = ("#27AE60", "#2ECC71")    # 成功 (绿)
COLOR_ERROR       = ("#C0392B", "#FF4757")    # 错误 (红)
COLOR_SSD_CACHE   = ("#D35400", "#E67E22")    # 缓存写入 (橙)
COLOR_RAM         = ("#2980B9", "#3498DB")    # 内存读取 (蓝)
COLOR_READY_RAM   = ("#16A085", "#00B894")    # 内存就绪 (青)
COLOR_DIRECT      = ("#16A085", "#1ABC9C")    # 直读 (青)
COLOR_MOVING      = ("#F39C12", "#F1C40F")    # 回写中 (黄)
COLOR_READING     = ("#8E44AD", "#9B59B6")    # IO 读取 (紫)
COLOR_PAUSED      = ("#7F8C8D", "#7f8c8d")    # 暂停/停止 (灰)
COLOR_WAITING     = ("#95A5A6", "#555555")    # 等待中 (灰)

# 任务状态常量 (用于状态机控制)
STATUS_WAIT = 0      
STATUS_CACHING = 1   
STATUS_READY = 2     
STATUS_RUN = 3       
STATUS_DONE = 5      
STATUS_ERR = -1      

STATE_PENDING = 0        
STATE_QUEUED_IO = 1      
STATE_CACHING = 2        
STATE_READY = 3          
STATE_ENCODING = 4       
STATE_DONE = 5           
STATE_ERROR = -1         

# --- 系统工具函数 ---

def get_subprocess_args():
    """
    获取跨平台的 subprocess 启动参数。
    主要用于 Windows 下隐藏弹出的 CMD 窗口。
    """
    if platform.system() == "Windows":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}
    return {}

def get_free_ram_gb():
    """
    获取当前系统可用内存 (GB)。
    Windows: 使用 GlobalMemoryStatusEx API 获取精确值。
    Others: 返回默认保守值 (4GB)，防止非 Win 系统崩溃。
    """
    try:
        if platform.system() == "Windows":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), 
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), 
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), 
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), 
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullAvailPhys / (1024**3)
        else:
            return 4.0 
    except Exception:
        return 4.0

# 内存缓存策略配置
MAX_RAM_LOAD_GB = 48.0  # 最大内存占用限制
SAFE_RAM_RESERVE = 6.0  # 保留给系统的最小安全内存

# --- 拖拽功能兼容处理 ---
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    class DnDWindow(ctk.CTk, TkinterDnD.DnDWrapper):
        """支持文件拖拽的主窗口基类"""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
    HAS_DND = True 
except ImportError:
    # 优雅降级：如果库缺失，回退到普通窗口
    class DnDWindow(ctk.CTk): pass 
    HAS_DND = False 

def set_execution_state(enable=True):
    """
    Windows 电源管理控制。
    enable=True: 阻止系统进入睡眠（编码时）。
    enable=False: 恢复系统默认电源策略。
    """
    if platform.system() != "Windows": return
    try:
        if enable: 
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        else: 
            # ES_CONTINUOUS
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
    except Exception: pass

def check_ffmpeg():
    """验证 FFmpeg 二进制是否可执行"""
    try:
        subprocess.run([FFMPEG_PATH, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except Exception: return False

# [PyArchitect Fix] 恢复 Windows 底层磁盘类型检测
# 必须导入 ctypes 库 (如果在文件头部已导入，此处可省略，但建议保留以确保模块独立性)
import ctypes
from typing import Optional

# 磁盘类型缓存（避免重复调用耗时的 Win32 API）
drive_type_cache: dict[str, bool] = {}

import subprocess
import os
import platform
import string
import ctypes
from typing import List, Tuple, Optional, Dict

class DiskManager:
    """
    [Fixed] 跨平台磁盘管理器。
    macOS/Linux 下不再调用 Windows API，防止 ctypes.windll 报错。
    """
    _type_cache: Dict[str, bool] = {}

    @classmethod
    def is_ssd(cls, path: str) -> bool:
        """
        核心逻辑：检测磁盘是否为 SSD。
        Windows: 检查 SeekPenalty。
        macOS/Linux: 默认返回 True (现代 Mac 几乎全系 SSD，且无法通过简单命令判断)。
        """
        if platform.system() != "Windows":
            return True # 非 Windows 默认视为高速盘，避免调用 PowerShell

        # --- 以下为 Windows 专用逻辑 ---
        try:
            drive_letter = os.path.splitdrive(os.path.abspath(path))[0].upper()
            if not drive_letter: return False
            letter = drive_letter[0]

            if letter in cls._type_cache:
                return cls._type_cache[letter]

            ps_cmd = (
                f"$dn = (Get-Partition -DriveLetter {letter}).DiskNumber; "
                f"(Get-Disk -Number $dn | Get-StorageReliabilityCounter).SeekPenalty"
            )
            
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            output = subprocess.check_output(
                ["powershell", "-Command", ps_cmd],
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW,
                stderr=subprocess.DEVNULL
            ).decode().strip().lower()

            is_ssd_drive = (output == "false")
            if not output:
                is_ssd_drive = cls._spindle_fallback(letter)

            cls._type_cache[letter] = is_ssd_drive
            return is_ssd_drive

        except Exception:
            return False

    @classmethod
    def _spindle_fallback(cls, letter: str) -> bool:
        """Windows 备用方案"""
        try:
            cmd = f"(Get-PhysicalDisk | Where-Object {{ (Get-Partition -DriveLetter {letter}).DiskNumber -eq $_.DeviceId }}).SpindleSpeed"
            out = subprocess.check_output(["powershell", "-Command", cmd], creationflags=0x08000000).decode().strip()
            return out == "0"
        except:
            return False

    @staticmethod
    def get_windows_drives() -> List[str]:
        """获取所有盘符 (仅 Windows 有效，macOS 返回根目录)"""
        if platform.system() != "Windows":
            return ["/"] # macOS/Linux 返回根目录
            
        drives = []
        try:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1: drives.append(f"{letter}:\\")
                bitmask >>= 1
        except Exception:
            pass
        return drives

    @classmethod
    def get_best_cache_path(cls, source_file: Optional[str] = None) -> str:
        """
        [算法 v2.4] 智能缓存路径选择 (跨平台安全版)
        """
        # 非 Windows 环境直接返回用户主目录下的临时文件夹
        if platform.system() != "Windows":
            return os.path.expanduser("~/Downloads")

        candidates = []
        src_drive = os.path.splitdrive(os.path.abspath(source_file))[0].upper() if source_file else ""
        sys_drive = os.getenv("SystemDrive", "C:").upper()

        print("-" * 50)
        print("[DiskManager] 正在分析存储性能...")

        for drive in cls.get_windows_drives():
            try:
                free_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(drive), None, None, ctypes.pointer(free_bytes))
                free_gb = free_bytes.value / (1024**3)
                
                if free_gb < 10: continue 

                score = 0
                is_ssd_device = cls.is_ssd(drive)
                
                if is_ssd_device: score += 100000
                score += int(free_gb)

                if drive.startswith(sys_drive): score -= 1000
                if src_drive and drive.startswith(src_drive): score -= 2000

                candidates.append((score, drive))
            except: pass
        
        if not candidates: return "C:\\"
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    
# --- 全局内存文件服务器 ---
# 用于将内存中的视频数据 (Bytes) 通过 HTTP 协议喂给 FFmpeg，避免写盘。
GLOBAL_RAM_STORAGE = {} 
PATH_TO_TOKEN_MAP = {}

class GlobalRamHandler(http.server.SimpleHTTPRequestHandler):
    """自定义 HTTP 处理器，支持高并发分块链表传输，彻底解决超大内存对象的分配崩溃"""
    def log_message(self, format, *args): pass  
    
    def do_GET(self):
        try:
            token = self.path.lstrip('/')
            video_data_chunks = GLOBAL_RAM_STORAGE.get(token) # 现在获取到的是一个 list[bytes]
            if not video_data_chunks:
                self.send_error(404)
                return
                
            # 计算总长度
            total_length = sum(len(chunk) for chunk in video_data_chunks)
            
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4") 
            self.send_header("Content-Length", str(total_length))
            self.end_headers()
            
            # [PyArchitect Fix] 流式向 Socket 吐出数据块，内存零拷贝
            try: 
                for chunk in video_data_chunks:
                    self.wfile.write(chunk)
            except (ConnectionResetError, BrokenPipeError): 
                pass
        except Exception: 
            pass

def start_global_server():
    """启动本地回环 HTTP 服务器（安全加固版）"""
    # 强制绑定 loopback，拒绝局域网访问
    server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), GlobalRamHandler)
    server.daemon_threads = True
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port

# =========================================================================
# [Module 3] UI Components
# 功能：自定义的 UI 控件，支持 Light/Dark 主题切换
# =========================================================================

class InfinityScope(ctk.CTkCanvas):
    """
    动态示波器控件。
    用于显示编码时的 FPS 或数据流波动。
    特点：在绘制循环中实时检测系统主题，动态调整背景和线条颜色。
    """
    def __init__(self, master, **kwargs):
        super().__init__(master, highlightthickness=0, **kwargs)
        self.points = []
        self.display_max = 10.0  
        self.target_max = 10.0   
        self.running = True
        # 监听窗口尺寸变化以重绘
        self.bind("<Configure>", lambda e: self.draw()) 
        self.animate_loop()

    def add_point(self, val):
        """添加新数据点"""
        self.points.append(val)
        if len(self.points) > 100: self.points.pop(0)
        # 动态调整 Y 轴量程
        current_data_max = max(self.points) if self.points else 10
        self.target_max = max(current_data_max, 10) * 1.2

    def clear(self):
        self.points = []
        self.draw()

    def animate_loop(self):
        """动画主循环 (约 30 FPS)"""
        if self.winfo_exists() and self.running:
            # 平滑过渡 Y 轴最大值
            diff = self.target_max - self.display_max
            if abs(diff) > 0.01: self.display_max += diff * 0.1
            self.draw()
            self.after(33, self.animate_loop) 

    def draw(self):
        """绘制逻辑"""
        if not self.winfo_exists(): return
        
        # [关键] 实时获取当前外观模式 (Light/Dark)
        mode = ctk.get_appearance_mode()
        is_light = (mode == "Light")
        
        # 根据模式设定绘图颜色
        bg_color = "#F0F0F0" if is_light else "#0f0f0f"   # 浅灰 vs 深黑
        grid_color = "#D0D0D0" if is_light else "#2a2a2a" # 网格线
        line_color = "#00B894"                            # 波形线 (保持绿色)
        
        self.configure(bg=bg_color)
        self.delete("all")
        
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10: return
        
        # 绘制中心基准线
        self.create_line(0, h/2, w, h/2, fill=grid_color, dash=(4, 4))
        
        if not self.points: return
        
        # 计算波形坐标
        scale_y = (h - 20) / self.display_max
        n = len(self.points)
        if n < 2: return
        step_x = w / (n - 1) if n > 1 else w
        coords = []
        for i, val in enumerate(self.points):
            x = i * step_x
            y = h - (val * scale_y) - 10
            coords.extend([x, y])
            
        # 绘制平滑曲线
        if len(coords) >= 4:
            self.create_line(coords, fill=line_color, width=2, smooth=True)

class MonitorChannel(ctk.CTkFrame):
    """
    [PyArchitect Refactored] 监控通道卡片。
    修复了 UI 抖动问题 (Fixed-Layout) 和空闲时的幽灵刷新问题。
    """
    def __init__(self, master, ch_id, **kwargs):
        bg_color_tuple = ("#FFFFFF", "#181818")
        border_color_tuple = ("#D0D0D0", "#333333")
        
        super().__init__(master, fg_color=bg_color_tuple, corner_radius=10, border_width=1, border_color=border_color_tuple, **kwargs)
        
        # 头部：标题与状态
        head = ctk.CTkFrame(self, fg_color="transparent", height=25)
        head.pack(fill="x", padx=15, pady=(10,0))
        
        self.lbl_title = ctk.CTkLabel(head, text=f"通道 {ch_id} · 空闲", font=("微软雅黑", 12, "bold"), text_color=COLOR_TEXT_SUB)
        self.lbl_title.pack(side="left")
        self.lbl_info = ctk.CTkLabel(head, text="等待任务...", font=("Arial", 11), text_color=COLOR_TEXT_HINT)
        self.lbl_info.pack(side="right")
        
        # 中部：示波器
        self.scope = InfinityScope(self) 
        self.scope.pack(fill="both", expand=True, padx=2, pady=5)
        
        # 底部：数据区
        btm = ctk.CTkFrame(self, fg_color="transparent")
        btm.pack(fill="x", padx=15, pady=(5, 12))
        
        # [PyArchitect] Grid 布局调整：严格的底部基线对齐
        btm.grid_columnconfigure(0, weight=0) # FPS 数字
        btm.grid_columnconfigure(1, weight=0) # FPS 单位
        btm.grid_columnconfigure(2, weight=1) # 弹簧占位，推开两侧
        btm.grid_columnconfigure(3, weight=0) # ETA
        btm.grid_columnconfigure(4, weight=0) # 进度百分比
        
        # FPS 值：锚点设为 se (右下)，紧贴单位
        self.lbl_fps = ctk.CTkLabel(btm, text="--", font=("Impact", 20), text_color=COLOR_TEXT_HINT, width=42, anchor="se")
        self.lbl_fps.grid(row=0, column=0, sticky="s", pady=0) 
        
        # FPS 单位：微调 pady=(0, 4) 抬升小字，对齐大字的基线
        ctk.CTkLabel(btm, text="FPS", font=("Arial", 10, "bold"), text_color=COLOR_TEXT_HINT, anchor="sw").grid(row=0, column=1, sticky="s", padx=(4, 0), pady=(0, 4))
        
        # ETA 时间预估
        self.lbl_eta = ctk.CTkLabel(btm, text="ETA: --:--", font=("Consolas", 12), text_color=COLOR_TEXT_SUB, anchor="se")
        self.lbl_eta.grid(row=0, column=3, sticky="s", padx=(0, 15), pady=(0, 3))

        # 进度指示：锚点 se (右下)
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 16, "bold"), text_color=COLOR_TEXT_MAIN, anchor="se")
        self.lbl_prog.grid(row=0, column=4, sticky="s", pady=(0, 1))

        self.is_active = False
        self.last_update_time = time.time()
        self.after(500, self._heartbeat)

    def _heartbeat(self):
        """心跳检测"""
        if not self.winfo_exists(): return
        
        # [PyArchitect Fix] 空闲时彻底停止向示波器推数据，防止出现“幽灵图表”
        if self.is_active:
            now = time.time()
            # 如果运行中超过 3 秒没收到数据，说明卡住了，补 0
            if now - self.last_update_time > 3.0: 
                self.scope.add_point(0)
                self.lbl_fps.configure(text="0.0", text_color=COLOR_TEXT_HINT)
        else:
            # 空闲状态下，不添加任何点，让 scope 保持静止或清空
            pass
            
        self.after(500, self._heartbeat)

    def activate(self, filename, tag, task_uuid): # [修改] 新增 task_uuid 参数
        if not self.winfo_exists(): return
        self.current_task_uuid = task_uuid # [关键] 绑定当前任务令牌
        self.is_active = True
        self.scope.clear()
        self.lbl_title.configure(text=f"运行中: {filename[:10]}...", text_color=COLOR_ACCENT)
        self.lbl_info.configure(text=tag, text_color=COLOR_TEXT_HINT)
        self.lbl_fps.configure(text_color=COLOR_TEXT_MAIN)
        self.lbl_prog.configure(text_color=COLOR_ACCENT)
        self.lbl_eta.configure(text_color=COLOR_SUCCESS)
        self.last_update_time = time.time()

    def update_data(self, fps: float, prog: float, eta: str, task_uuid: str, est_size: str = "") -> None:
        """
        更新通道实时数据
        
        Args:
            fps: 当前处理帧率
            prog: 0.0~1.0 的进度
            eta: 剩余时间字符串
            task_uuid: 安全锁标识
            est_size: [新增] 预测的最终体积字符串
        """
        if not self.winfo_exists() or getattr(self, 'current_task_uuid', None) != task_uuid: 
            return 
            
        self.last_update_time = time.time() 
        self.scope.add_point(fps)
        self.lbl_fps.configure(text=f"{float(fps):.1f}", text_color=COLOR_TEXT_MAIN) 
        self.lbl_prog.configure(text=f"{int(prog*100)}%")
        
        # [优化] 拼装 ETA 与 预期体积
        display_text = eta if "ETA" in eta or "Final" in eta else f"ETA: {eta}"
        if est_size and "Final" not in display_text:
            display_text += f" | {est_size}"
            
        self.lbl_eta.configure(text=display_text)

    def reset(self) -> None:
        """重置通道为等待状态"""
        if not self.winfo_exists(): return
        self.current_task_uuid = None
        self.is_active = False
        self.lbl_title.configure(text="通道 · 空闲", text_color=COLOR_TEXT_SUB)
        self.lbl_info.configure(text="等待任务...", text_color=COLOR_TEXT_HINT)
        
        self.lbl_fps.configure(text="--", text_color=COLOR_TEXT_HINT)
        self.lbl_prog.configure(text="0%", text_color=COLOR_TEXT_HINT)
        self.lbl_eta.configure(text="ETA: --:--", text_color=COLOR_TEXT_HINT)
        self.scope.clear()

    def set_placeholder(self) -> None:
        """设置为未启用占位状态"""
        if not self.winfo_exists(): return
        self.is_active = False
        self.configure(border_color=COLOR_BORDER)
        self.lbl_title.configure(text="通道 · 未启用", text_color=COLOR_TEXT_HINT)
        self.lbl_info.configure(text="Channel Disabled", text_color=COLOR_TEXT_HINT)
        self.scope.clear()
        
        self.lbl_fps.configure(text="--", text_color=COLOR_TEXT_HINT)
        self.lbl_prog.configure(text="--", text_color=COLOR_TEXT_HINT)
        self.lbl_eta.configure(text="", text_color=COLOR_TEXT_HINT)

class ToastNotification(ctk.CTkFrame):
    """自定义 Toast 消息提示框，自下而上浮出"""
    def __init__(self, master, text, icon="ℹ️"):
        # 背景色：深色背景，确保在浅色模式下也有高对比度
        bg_tuple = ("#333333", "#1F1F1F") 
        text_color_tuple = ("#FFFFFF", "#EEEEEE")
        
        super().__init__(master, fg_color=bg_tuple, corner_radius=20, border_width=1, border_color="#555")
        self.place(relx=0.5, rely=0.88, anchor="center")
        
        self.lbl_icon = ctk.CTkLabel(self, text=icon, font=("Segoe UI Emoji", 16))
        self.lbl_icon.pack(side="left", padx=(15, 5), pady=8)
        
        self.lbl_text = ctk.CTkLabel(self, text=text, font=("微软雅黑", 12, "bold"), text_color=text_color_tuple)
        self.lbl_text.pack(side="left", padx=(0, 20), pady=8)
        self.lift()
        self.after(10, self.fade_in)

    def fade_in(self):
        # 简单模拟淡入，并在2.5秒后销毁
        self.after(2500, self.destroy_toast)
    def destroy_toast(self):
        self.destroy()

from collections import deque
import customtkinter as ctk
import os
import platform
import subprocess

class TaskCard(ctk.CTkFrame):
    """
    任务列表项卡片。
    显示文件名、状态、进度条，支持查看独立日志。
    """
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=10, border_width=0, **kwargs)
        
        self.grid_columnconfigure(1, weight=1)
        self.filepath = filepath
        self.status_code = STATE_PENDING 
        self.ram_data = None 
        self.ssd_cache_path = None
        self.source_mode = "PENDING"
        self.ui_max_progress = 0.0
        
        # [新增] 为每个任务维护独立的日志缓冲区（保留最后2000行，防内存溢出）
        self.log_data = deque(maxlen=2000)
        
        try: self.file_size_gb = os.path.getsize(filepath) / (1024**3)
        except: self.file_size_gb = 0.0
        
        # 序号
        self.lbl_index = ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 22), 
                                      text_color=COLOR_TEXT_HINT, width=50, anchor="center")
        self.lbl_index.grid(row=0, column=0, rowspan=2, padx=(5, 5), pady=0) 
        
        # 文件名
        name_frame = ctk.CTkFrame(self, fg_color="transparent")
        name_frame.grid(row=0, column=1, sticky="sw", padx=0, pady=(8, 0)) 
        ctk.CTkLabel(name_frame, text=os.path.basename(filepath), font=("微软雅黑", 12, "bold"), 
                     text_color=COLOR_TEXT_MAIN, anchor="w").pack(side="left")
        
        # 按钮区容器
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=0, column=2, padx=10, pady=(8,0), sticky="e")
        
        btn_bg = ("#E0E0E0", "#444444")
        btn_hover = ("#D0D0D0", "#555555")
        
        # [新增] 查看日志按钮
        self.btn_log = ctk.CTkButton(btn_frame, text="📄", width=28, height=22, fg_color=btn_bg, hover_color=btn_hover, 
                                     text_color=COLOR_TEXT_MAIN, font=("Segoe UI Emoji", 11), command=self.show_log)
        self.btn_log.pack(side="left", padx=(0, 5))

        # 打开文件夹按钮
        self.btn_open = ctk.CTkButton(btn_frame, text="📂", width=28, height=22, fg_color=btn_bg, hover_color=btn_hover, 
                                      text_color=COLOR_TEXT_MAIN, font=("Segoe UI Emoji", 11), command=self.open_location)
        self.btn_open.pack(side="left")
        
        # 状态文本
        self.lbl_status = ctk.CTkLabel(self, text="等待处理", font=("Arial", 10), text_color=COLOR_TEXT_HINT, anchor="nw")
        self.lbl_status.grid(row=1, column=1, sticky="nw", padx=0, pady=(0, 0)) 
        
        # 进度条
        self.progress = ctk.CTkProgressBar(self, height=6, corner_radius=3, progress_color=COLOR_ACCENT)
        self.progress.configure(fg_color=("#E0E0E0", "#444444")) 
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="new", padx=12, pady=(0, 10))
        self.final_output_path = None
    def set_status(self, text: str, text_color: tuple | str, code: int) -> None:
        """
        线程安全的卡片状态更新器。
        """
        if self.winfo_exists():
            self.lbl_status.configure(text=text, text_color=text_color)
            self.status_code = code

    def set_progress(self, val: float, color: tuple | str) -> None:
        """
        线程安全的卡片进度条更新器。
        """
        if self.winfo_exists():
            # 限制数值范围以防底层 Tkinter 渲染崩溃
            safe_val = max(0.0, min(1.0, float(val)))
            self.progress.set(safe_val)
            self.progress.configure(progress_color=color)

    def clean_memory(self) -> None:
        """
        清理当前卡片绑定的物理内存与全局引用，防止 OOM (Out Of Memory) 内存泄漏。
        [PyArchitect Fix] 引入深度清空与强制系统级内存回收。
        """
        self.ram_data = None
        
        # 安全移除全局字典中的巨型二进制对象，切断强引用
        token = PATH_TO_TOKEN_MAP.get(self.filepath)
        if token:
            data_list = GLOBAL_RAM_STORAGE.pop(token, None)
            if isinstance(data_list, list):
                data_list.clear() # 释放内部 chunk 引用
            PATH_TO_TOKEN_MAP.pop(self.filepath, None)
            
        # 如果释放了大量内存，立即踢醒垃圾回收器，交还 OS 物理内存
        import gc
        gc.collect()

    def update_index(self, new_index: int) -> None:
        """
        更新 UI 列表中的任务序号。
        
        Args:
            new_index (int): 重新排序后的任务队列序号。
        """
        if self.winfo_exists():
            self.lbl_index.configure(text=f"{new_index:02d}")

    def open_location(self) -> None:
        """
        跨平台打开文件所在目录，并尝试高亮选中目标文件。
        采用非阻塞异步子进程 (Popen) 防止 GUI 线程假死。
        防御性拦截文件丢失或系统调用失败的异常。
        """
        # 边界防御：如果文件路径为空或文件已被外部程序物理删除，则直接中断，避免抛出系统级错误
        if not self.filepath or not os.path.exists(self.filepath):
            print(f"[IO Warning] 目标文件已丢失，无法定位: {self.filepath}")
            return
            
        try:
            import platform
            import subprocess
            
            sys_plat = platform.system()
            target_path = os.path.normpath(self.filepath)
            
            if sys_plat == "Windows":
                # Windows: 唤起 Explorer 并通过 /select 参数精准高亮该文件
                subprocess.Popen(["explorer", "/select,", target_path])
            elif sys_plat == "Darwin":
                # macOS: 唤起 Finder 并通过 -R 参数揭示 (Reveal) 该文件
                subprocess.Popen(["open", "-R", target_path])
            else:
                # Linux (Fallback): 使用 xdg-open 打开该文件所在的父级目录
                subprocess.Popen(["xdg-open", os.path.dirname(target_path)])
                
        except Exception as e:
            # 捕获操作系统拒绝访问、进程树挂载失败等底层异常，保留堆栈信息但不阻断主程序
            print(f"[OS Subprocess Error] 唤起系统文件管理器失败: {e}")

    def show_log(self) -> None:
        """弹出当前任务的详细日志窗口"""
        log_win = ctk.CTkToplevel(self)
        log_win.title(f"日志诊断 - {os.path.basename(self.filepath)}")
        log_win.geometry("700x500")
        log_win.transient(self.winfo_toplevel())
        
        txt = ctk.CTkTextbox(log_win, font=("Consolas", 12), wrap="none", fg_color=("#FFFFFF", "#1E1E1E"))
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 将日志队列合并为文本并插入
        full_log = "\n".join(self.log_data) if self.log_data else "暂无日志产生..."
        txt.insert("1.0", full_log)
        txt.configure(state="disabled") # 只读模式

# =========================================================================
# [Module 3.5] Help Window (Ported from v0.9.6 & Optimized)
# [修复版] 已适配 Light/Dark 双色模式，并找回了丢失的技术细节文档
# =========================================================================
class HelpWindow(ctk.CTkToplevel):
    def __init__(self, master, info=None, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.geometry("1150x900") 
        self.title("Cinético - Technical Guide")
        self.lift()
        self.focus_force()
        
        # --- 字体配置 ---
        self.FONT_H1 = ("Segoe UI", 34, "bold") if platform.system() == "Windows" else ("Arial", 34, "bold")    
        self.FONT_H2 = ("微软雅黑", 18)              
        self.FONT_SEC = ("Segoe UI", 22, "bold")     
        self.FONT_SEC_CN = ("微软雅黑", 16, "bold")  
        self.FONT_ITEM = ("Segoe UI", 16, "bold")    
        self.FONT_BODY_EN = ("Segoe UI", 13)         
        self.FONT_BODY_CN = ("微软雅黑", 13)         
        
        # --- 颜色配置 (Light, Dark) ---
        self.COL_BG = ("#F3F3F3", "#121212")
        self.COL_CARD = ("#FFFFFF", "#1E1E1E")
        self.COL_TEXT_HI = ("#333333", "#FFFFFF")
        self.COL_TEXT_MED = ("#555555", "#CCCCCC")
        self.COL_TEXT_LOW = ("#666666", "#888888")
        self.COL_ACCENT = ("#3B8ED0", "#3B8ED0")
        self.COL_SEP = ("#E0E0E0", "#333333")

        self.configure(fg_color=self.COL_BG)

        # --- 顶部标题区 ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=50, pady=(45, 25))
        
        ctk.CTkLabel(header, text="Cinético Technical Overview", 
                     font=self.FONT_H1, text_color=self.COL_TEXT_HI, anchor="w").pack(fill="x")
        ctk.CTkLabel(header, text="Cinético 技术概览与操作指南", 
                     font=self.FONT_H2, text_color=self.COL_TEXT_LOW, anchor="w").pack(fill="x", pady=(8, 0))

        # --- 滚动内容区 ---
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=30, pady=(0, 30))

        # =======================
        # Part 0: Smart Hardware Advice (Dynamic)
        # =======================
        self.add_section_title("0. Smart Optimization Guide", "智能并发设置建议")
        self.add_desc_text("Based on your current hardware configuration.\n根据您当前的硬件配置，以下是推荐设置。")
        
        if info:
            self.add_item_block(
                "Detected Hardware / 检测结果", "",
                f"{info.get('cpu_desc_en', '')}\n{info.get('gpu_desc_en', '')}",
                f"{info.get('cpu_desc_cn', '')}\n{info.get('gpu_desc_cn', '')}"
            )
            self.add_item_block(
                "Recommendation / 推荐并发", "",
                f"Optimal Worker Count: {info.get('rec_worker', '2')}",
                f"建议将并发数设置为: {info.get('rec_worker', '2')}"
            )
        else:
             self.add_item_block("Info Unavailable", "信息不可用", "Hardware scan failed.", "无法检测硬件信息。")

        # =======================
        # Part I: Functional Modules
        # =======================
        self.add_section_title("I. Functional Modules Detail", "功能模块详解")
        self.add_desc_text("Cinético is designed to deliver industrial-grade video processing capabilities through minimalist interaction logic.\nCinético 旨在通过极简的交互逻辑提供工业级的视频处理能力。")

        # 1. Core Processing
        self.add_sub_header("1. Core Processing / 核心处理")
        self.add_item_block(
            "Hardware Acceleration / GPU ACCEL", "硬件加速",
            "Utilizes dedicated NVIDIA NVENC circuits for hardware encoding. Significantly improves throughput and reduces power consumption.",
            "调用 NVIDIA NVENC 专用电路进行硬件编码。显著提升吞吐量，降低能耗。仅在基准测试或排查兼容性问题时关闭。"
        )
        self.add_item_block(
            "Heterogeneous Offloading / HYBRID", "异构分流",
            "Force CPU Decoding + GPU Encoding. Optimizes pipeline efficiency during concurrent multi-tasking.",
            "负载均衡策略。开启后，将强制使用 CPU 解码，使用 GPU 编码。可优化多任务并发流水线效率。"
        )

        # 2. Codec Standards (Ported from v0.9.6)
        self.add_sub_header("2. Codec Standards / 编码标准")
        self.add_item_block(
            "H.264 (AVC)", "",
            "Extensive device support. Suitable for cross-platform distribution, client delivery, or playback on legacy hardware.",
            "广泛的设备支持。适用于跨平台分发、交付客户或在老旧硬件上播放。确保最大的兼容性。"
        )
        self.add_item_block(
            "H.265 (HEVC)", "",
            "High compression ratio. At equivalent image quality, bitrate is reduced by approximately 50% compared to H.264.",
            "高压缩比。在同等画质下，比特率较 H.264 降低约 50%。适用于 4K 高分辨率视频的存储与归档。"
        )
        self.add_item_block(
            "AV1", "",
            "Next-generation open-source coding format with superior compression efficiency. Encoding is slower and requires hardware support for playback.",
            "新一代开源编码格式，具备更优异的压缩效率。适用于对体积控制有极高要求的场景，编码耗时长，播放端需硬件支持。"
        )

        # 2.5 Color Depth (Ported from v0.9.6)
        self.add_separator()
        self.add_sub_header("2.5 Color Depth / 色彩深度")
        self.add_item_block(
            "8-BIT", "Standard / 标准色彩",
            "16.7 million colors. Standard for web streaming and compatibility.",
            "1670 万色。网络流媒体与兼容性的标准。建议用于社交媒体分享或老旧设备播放。"
        )
        self.add_item_block(
            "10-BIT", "High Color Depth / 高色深",
            "1.07 billion colors. Eliminates color banding and improves compression efficiency for gradients.",
            "10.7 亿色。彻底消除色彩断层，提升渐变色区域压缩效率。建议存档或追求高画质时务必开启。"
        )

        # 3. Rate Control (Ported from v0.9.6)
        self.add_sub_header("3. Rate Control & Quality / 码率控制与画质")
        self.add_desc_text("The quantization strategy adapts automatically based on the hardware selection.\n量化策略根据硬件选择自动适配。")
        self.add_item_block(
            "CPU Mode: CRF (Constant Rate Factor)", "基准值: 23",
            "Allocates bitrate dynamically according to motion complexity. Lower values yield higher quality.\nDefault: 23 (Balanced).",
            "基于心理视觉模型的恒定速率因子。根据画面运动复杂度动态分配码率。数值越小画质越高。\n默认值：23（平衡点）。"
        )
        self.add_item_block(
            "GPU Mode: CQ (Constant Quantization)", "基准值: 28",
            "Based on fixed mathematical quantization. Requires higher values to achieve file sizes comparable to CRF.\nDefault: 28 (Equivalent to CRF 23).",
            "基于固定数学算法的量化参数。由于缺乏深度运动预测，需设定比 CRF 更高的数值以控制体积。\n默认值：28（体积近似 CRF 23）。"
        )

        # 4. Scheduling (Ported from v0.9.6)
        self.add_sub_header("4. System Scheduling / 系统调度")
        self.add_item_block(
            "Retain Metadata / KEEP DATA", "保留元数据",
            "Retains original shooting parameters, timestamps, and camera information.",
            "封装时保留原片的拍摄参数、时间戳及相机信息。"
        )
        self.add_item_block(
            "Process Priority / PRIORITY", "进程优先级",
            "High: Aggressive scheduling. Allocates maximum CPU time slices to the encoding process.",
            "High：激进调度。向编码进程分配最大化的 CPU 时间片，加速压制，但可能影响其他应用响应速度。"
        )

        # =======================
        # Part II: Core Architecture (Ported from v0.9.6)
        # =======================
        self.add_separator()
        self.add_section_title("II. Core Architecture Analysis", "核心架构解析")
        self.add_desc_text("Cinético has reconstructed underlying data transmission and resource management.\nCinético 重构底层数据传输与资源管理，突破传统转码工具性能瓶颈。")

        self.add_item_block(
            "1. Zero-Copy Loopback", "零拷贝环回",
            "Maps video streams to RAM; the encoder bypasses the conventional file system to acquire data at memory bus speeds.",
            "将视频流映射至 RAM，编码器绕过常规文件系统，以内存总线速度获取数据，消除机械硬盘的寻道延迟。"
        )

        self.add_item_block(
            "2. Adaptive Storage Tiering", "自适应分层存储",
            "Small files reside in memory for instant reading. Large files are scheduled to SSD cache.",
            "根据文件体积与硬件环境动态分配缓存策略。小文件驻留内存即时读取，大文件调度至SSD确保读写稳定性。"
        )

        self.add_item_block(
            "3. Heuristic VRAM Guard", "显存启发式管理",
            "Automatically suspends operations when VRAM resources approach the threshold.",
            "针对高负载场景设计的保护机制。显存资源临近阈值自动挂起，确保极端工况稳定性。"
        )

        ctk.CTkFrame(self.scroll, height=60, fg_color="transparent").pack()

    # --- Helper Methods ---
    def add_separator(self):
        ctk.CTkFrame(self.scroll, height=2, fg_color=self.COL_SEP).pack(fill="x", padx=20, pady=50)
        
    def add_section_title(self, text_en, text_cn):
        f = ctk.CTkFrame(self.scroll, fg_color="transparent")
        f.pack(fill="x", padx=20, pady=(35, 15))
        ctk.CTkFrame(f, width=5, height=28, fg_color=self.COL_ACCENT).pack(side="left", padx=(0, 15))
        ctk.CTkLabel(f, text=text_en, font=self.FONT_SEC, text_color=self.COL_TEXT_HI).pack(side="left", anchor="sw")
        ctk.CTkLabel(f, text=f"  {text_cn}", font=self.FONT_SEC_CN, text_color=self.COL_TEXT_LOW).pack(side="left", anchor="sw", pady=(3,0))
        
    def add_sub_header(self, text):
        ctk.CTkLabel(self.scroll, text=text, font=self.FONT_SEC_CN, text_color=self.COL_TEXT_HI, anchor="w").pack(fill="x", padx=40, pady=(30, 12))
        
    def add_desc_text(self, text):
        ctk.CTkLabel(self.scroll, text=text, font=self.FONT_BODY_EN, text_color=self.COL_TEXT_MED, justify="left", anchor="w").pack(fill="x", padx=40, pady=(0, 20))
        
    def add_item_block(self, title_en, title_cn, body_en, body_cn):
        card = ctk.CTkFrame(self.scroll, fg_color=self.COL_CARD, corner_radius=8)
        card.pack(fill="x", padx=20, pady=10)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", padx=25, pady=20)
        title_box = ctk.CTkFrame(inner, fg_color="transparent")
        title_box.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(title_box, text=title_en, font=self.FONT_ITEM, text_color=self.COL_TEXT_HI).pack(side="left")
        if title_cn: ctk.CTkLabel(title_box, text=f"  {title_cn}", font=self.FONT_ITEM, text_color=self.COL_ACCENT).pack(side="left")
        ctk.CTkLabel(inner, text=body_en, font=self.FONT_BODY_EN, text_color=self.COL_TEXT_MED, justify="left", anchor="w", wraplength=950).pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(inner, text=body_cn, font=self.FONT_BODY_CN, text_color=self.COL_TEXT_LOW, justify="left", anchor="w", wraplength=950).pack(fill="x")


class ModernAlert(ctk.CTkToplevel):
    """
    [PyArchitect] 现代扁平化模态弹窗 (重构版：类原生左右分栏排版)
    """
    def __init__(self, master: ctk.CTk, title: str, message: str, type: str = "info") -> None:
        super().__init__(master)
        
        # Mac 下隐藏顶部的原生 Title 文字更显沉浸，Windows 则照常显示
        self.title(title if platform.system() == "Windows" else "")
        
        # 1. 扩容：尺寸调整为宽扁的黄金比例 (460x240)，彻底解决多行截断问题
        self.geometry("460x240")
        self.transient(master) 
        self.grab_set() 
        self.resizable(False, False)
        
        # 2. 居中计算 (根据新尺寸适配偏移量)
        try:
            x = master.winfo_rootx() + (master.winfo_width() // 2) - 230
            y = master.winfo_rooty() + (master.winfo_height() // 2) - 120
            self.geometry(f"+{x}+{y}")
        except Exception: 
            pass

        is_err = (type == "error")
        color = ("#C0392B", "#FF4757") if is_err else ("#3B8ED0", "#3B8ED0")
        
        # 智能上下文图标
        if is_err: icon = "❌"
        elif "报告" in title: icon = "📊"
        else: icon = "ℹ️"

        # 采用弱对比底色，模仿系统级弹窗的面板质感
        bg_frame = ctk.CTkFrame(self, fg_color=("gray95", "gray12"), corner_radius=0)
        bg_frame.pack(fill="both", expand=True)

        # 3. 采用左右分栏的经典排版 (左侧图标，右侧文字)
        content_frame = ctk.CTkFrame(bg_frame, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=30, pady=(35, 10))

        # 左侧：大号图标
        ctk.CTkLabel(content_frame, text=icon, font=("Arial", 46)).pack(side="left", anchor="nw", padx=(0, 25))

        # 右侧：文本区容器
        text_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        text_frame.pack(side="left", fill="both", expand=True)

        # 内部主标题
        ctk.CTkLabel(text_frame, text=title, font=("微软雅黑", 16, "bold"), text_color=color, anchor="w").pack(fill="x", pady=(0, 10))
        
        # [关键修复] 正文文本：强制左对齐 (justify="left")，彻底解决文字视觉未对齐问题
        ctk.CTkLabel(text_frame, text=message, font=("微软雅黑", 13), text_color=("gray30", "gray80"), justify="left", anchor="w", wraplength=310).pack(fill="x")

        # 4. 底部：按钮区 (靠右对齐)
        btn_frame = ctk.CTkFrame(bg_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=(0, 25))
        
        btn_hover = ("#E74C3C", "#A32B2B") if is_err else ("#36719f", "#36719f")
        ctk.CTkButton(btn_frame, text="OK", width=90, height=30, corner_radius=6, font=("微软雅黑", 12, "bold"), 
                      fg_color=color, hover_color=btn_hover, command=self.destroy).pack(side="right")

import customtkinter as ctk
import threading
import time
import random
import platform
import sys
# 注意：这里需要确保你已经导入了 check_and_install_dependencies, FFMPEG_PATH, DiskManager, COLOR_ACCENT
# 如果在主文件中，这些都已经存在。

class SplashScreen(ctk.CTkToplevel):
    """
    [PyArchitect Minimalist v10] 纯粹的启动页
    - 摒弃所有装饰性假加载，完全基于真实的回调进度。
    - 界面极度纯净，仅保留核心视觉锚点与右下角状态监视器。
    """
    def __init__(self, root_app):
        super().__init__(root_app)
        self.root = root_app
        self.root.withdraw()

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        
        w, h = 960, 540
        ws, hs = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f'{w}x{h}+{int((ws-w)/2)}+{int((hs-h)/2)}')
        self.configure(fg_color="#0B0B0B")
        
        raw_accent = COLOR_ACCENT
        self.accent_color = raw_accent[1] if isinstance(raw_accent, tuple) else raw_accent

        # --- 极简布局 (只保留左侧标题与右下角状态) ---
        
        # 1. 品牌色竖线
        self.anchor_line = ctk.CTkFrame(self, width=6, height=115, fg_color=self.accent_color, corner_radius=0)
        self.anchor_line.place(relx=0.08, rely=0.45, anchor="w") 
        
        # 2. 标题容器 (自适应大小)
        self.text_box = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.text_box.place(relx=0.1, rely=0.45, anchor="w")

        title_font = ("Segoe UI Black", 64) if platform.system() == "Windows" else ("Arial Black", 64)
        ctk.CTkLabel(self.text_box, text="CINÉTICO", font=title_font, text_color="#FFFFFF").pack(anchor="w")
        
        sub_font = ("Segoe UI", 14, "bold")
        ctk.CTkLabel(self.text_box, text="E  N  C  O  D  E  R     P  R  O", font=sub_font, text_color=self.accent_color).pack(anchor="w", padx=(5, 0))

        # [右下角] 真实状态监视器
        self.status_lbl = ctk.CTkLabel(self, text="INITIALIZING...", font=("Consolas", 11), text_color="#888888")
        self.status_lbl.place(relx=0.95, rely=0.92, anchor="se")

        # [底部] 真实进度条
        self.bar = ctk.CTkProgressBar(
            self, width=w, height=3, progress_color=self.accent_color, 
            fg_color="#1A1A1A", border_width=0, corner_radius=0
        )
        self.bar.place(relx=0, rely=0.99, anchor="sw", relwidth=1)
        self.bar.set(0)
        
        self.update()
        threading.Thread(target=self.run_boot_sequence, daemon=True).start()

    def update_status(self, text: str) -> None:
        """线程安全的 UI 文字更新"""
        self.after(0, lambda: self.status_lbl.configure(text=text.upper()))

    def update_progress(self, val: float) -> None:
        """线程安全的 UI 进度条更新"""
        self.after(0, lambda: self.bar.set(val))

    def _finish_boot(self) -> None:
        """安全切换回调"""
        if self.winfo_exists():
            self.root.deiconify()
            self.destroy()

    def run_boot_sequence(self) -> None:
        """100% 真实的启动序列"""
        try:
            # 真实检测
            self.update_status("VERIFYING DEPENDENCIES...")
            check_and_install_dependencies(status_cb=self.update_status, progress_cb=self.update_progress)
            
            # 硬件扫描
            self.update_status("SCANNING STORAGE ARCHITECTURE...")
            self.update_progress(0.8)
            DiskManager.get_windows_drives()
            
            # [优化点] 给予用户 0.3 秒的视觉确认时间
            self.update_status("SYSTEM READY.")
            self.update_progress(1.0)
            time.sleep(0.3) 
            
            self.after(0, self._finish_boot)
            
        except Exception as e:
            print(f"Boot Error: {e}")
            self.after(0, self._finish_boot)

# =========================================================================
# [Module 4] Main Application
# 功能：核心业务逻辑控制器
# =========================================================================

class UltraEncoderApp(DnDWindow):
    """主应用程序类"""

    def safe_update(self, func: Callable, *args: Any, **kwargs: Any) -> None:
        """
        高并发安全的 UI 更新网关。
        采用无锁队列 (Queue) 替代直接的跨线程 after 调用，防止事件循环阻塞与渲染丢包。
        
        Args:
            func (Callable): 需要在 UI 主线程安全执行的函数句柄。
            *args (Any): 透传给目标函数的位置参数。
            **kwargs (Any): 透传给目标函数的关键字参数。
        """
        if not hasattr(self, "_ui_event_queue"):
            # 初始化最大容量为 10000 的线程安全队列，并应用类型声明
            self._ui_event_queue: queue.Queue = queue.Queue(maxsize=10000)
            self._process_ui_events() # 惰性启动主线程消费者循环
            
        try:
            self._ui_event_queue.put_nowait((func, args, kwargs))
        except queue.Full:
            pass # 极高频拥塞情况下的防御性丢包策略，确保系统核心不会挂起

    def _process_ui_events(self) -> None:
        """
        运行于主线程的微秒级渲染帧消费者引擎。
        分摊总线队列积压压力，并执行聚合态的批量 UI 渲染帧刷新。
        """
        if not self.winfo_exists(): 
            return
            
        try:
            # 批量清空当前队列中累积的时序状态，阻断事件循环饥饿现象
            for _ in range(50): 
                func, args, kwargs = self._ui_event_queue.get_nowait()
                try:
                    if self.winfo_exists(): 
                        func(*args, **kwargs)
                except Exception as e: 
                    # 捕获并打印具体异常，保留现场可观测性，严禁盲目吞噬错误
                    print(f"[UI Event Error] 调度 {func.__name__} 时发生异常: {e}")
        except queue.Empty:
            pass
        finally:
            # 重新将消费者循环锚定至事件队尾，维持约 30 FPS 的人眼舒适刷新率
            self.after(33, self._process_ui_events)

    def scroll_to_card(self, widget):
        """滚动列表以显示当前处理的卡片"""
        try:
            target_file = None
            for f, card in self.task_widgets.items():
                if card == widget: target_file = f; break
            if not target_file: return
            if target_file in self.file_queue:
                index = self.file_queue.index(target_file) - 1 
                total = len(self.file_queue)               
                if total > 1:
                    target_pos = index / total
                    if index > 0: target_pos = max(0.0, target_pos - (1 / total) * 0.5)
                    self.scroll._parent_canvas.yview_moveto(target_pos)
                    self.after(100, lambda: self.scroll._parent_canvas.yview_moveto(target_pos))
        except: pass
    
    # [新增] 标题点击计数
    def on_title_click(self, event):
        self.title_click_count += 1
        # 可选：点击时给一点微弱的反馈（例如打印日志或控制台输出）
        # print(f"Clicks: {self.title_click_count}")

    # [新增] 处理问号按钮点击（彩蛋入口）
    # [修改] 增加 event=None 默认参数，使其兼容点击绑定和直接调用
    def handle_help_click(self, event=None):
        if self.title_click_count >= 10:
            self.toggle_test_mode()
            self.title_click_count = 0 
        else:
            self.show_help()

    # [新增] 切换测试模式
    def toggle_test_mode(self) -> None:
        """
        切换基准测试模式开关。
        更新 UI 视觉反馈以匹配专业的工程标准。
        """
        self.test_mode = not self.test_mode
        if self.test_mode:
            self.show_toast("Benchmark Mode Activated / 基准测试模式已激活", "⚙️")
            self.lbl_main_title.configure(text_color="#E67E22")
            self.btn_action.configure(text="EXECUTE BENCHMARK / 执行基准测试")
            self.test_stats = {"orig": 0, "new": 0}
        else:
            self.show_toast("Benchmark Mode Deactivated / 基准测试模式已解除", "⚙️")
            self.lbl_main_title.configure(text_color=COLOR_TEXT_MAIN)
            self.btn_action.configure(text="START ENCODE / 启动编码")

    def detect_hardware_limit(self):
        """
        [优化] 启动时检测硬件，返回推荐并发数。
        优化逻辑：准确识别 GPU 厂商，防止非 NVIDIA 环境默认开启 CUDA 导致崩溃。
        """
        recomm_workers = 2
        cpu_msg = ""
        gpu_msg = ""
        self.has_nvidia_gpu = False  # [新增] 明确的硬件标志位

        # --- CPU 检测 ---
        try:
            cpu_count = os.cpu_count() or 4
        except:
            cpu_count = 4

        if cpu_count >= 16:
            cpu_workers = 4 
            cpu_msg = f"High-End CPU ({cpu_count} threads)."
        elif cpu_count >= 8:
            cpu_workers = 3
            cpu_msg = f"Modern CPU ({cpu_count} threads)."
        else:
            cpu_workers = 2
            cpu_msg = f"Standard CPU ({cpu_count} threads)."

        # --- GPU 检测 ---
        gpu_workers = 2
        sys_plat = platform.system()
        
        if sys_plat == "Windows":
            try:
                # 尝试运行 nvidia-smi 只要成功返回即视为有 N 卡
                subprocess.run("nvidia-smi", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                self.has_nvidia_gpu = True
                gpu_workers = 3 
                gpu_msg = "NVIDIA GPU Detected (NVENC)."
            except:
                self.has_nvidia_gpu = False
                gpu_msg = "No NVIDIA GPU detected."
        elif sys_plat == "Darwin":
            # Mac 通常都支持 VideoToolbox
            self.has_nvidia_gpu = True # 这里复用标志位，意为“有可用硬解”
            gpu_msg = "Apple Silicon / Metal."
            gpu_workers = 3

        # 决策：如果有可用 GPU，则推荐 GPU 并发数
        if self.has_nvidia_gpu:
            recomm_workers = gpu_workers
        else:
            recomm_workers = cpu_workers

        self.hardware_info = {
            "rec_worker": str(recomm_workers),
            "cpu_desc_en": cpu_msg,
            "cpu_desc_cn": cpu_msg, 
            "gpu_desc_en": gpu_msg,
            "gpu_desc_cn": gpu_msg
        }
        
        return str(recomm_workers)

    def __init__(self):
        super().__init__()
        self.withdraw() # [PyArchitect Fix] 启动时立即隐藏，防止闪烁
        
        self.title("Cinético_Encoder")
        self.geometry("1300x900")
        self.configure(fg_color=COLOR_BG_MAIN)
        self.minsize(1200, 850) 
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 初始化界面颜色
        self.configure(fg_color=COLOR_BG_MAIN)
        self.minsize(1200, 850) 
        self.protocol("WM_DELETE_WINDOW", self.on_closing) 
        
        # 数据结构初始化
        self.file_queue = []       # 任务队列
        self.task_widgets = {}     # 文件路径 -> Widget 映射
        self.active_procs = []     # 活跃的 FFmpeg 进程
        self.running = False       
        self.stop_flag = False     
        
        # 线程同步锁
        self.queue_lock = threading.Lock() 
        self.slot_lock = threading.Lock()
        
        self.monitor_slots = []    
        self.available_indices = [] 
        self.current_workers = 2   
        self.executor = ThreadPoolExecutor(max_workers=16) # 计算任务线程池
        self.temp_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.manual_cache_path = None
        self.temp_files = set() 
        self.finished_tasks_count = 0

        # [新增] 测试模式相关变量
        self.title_click_count = 0     # 标题点击计数
        self.test_mode = False         # 测试模式开关
        self.test_stats = {"orig": 0, "new": 0} # 统计数据：原大小、新大小
        
        # [修改] 启动 UI 构建前，先计算推荐并发数
        rec_worker = self.detect_hardware_limit()

        # 启动 UI 构建
        self.setup_ui(default_worker=rec_worker) # 传递参数
        self.finished_tasks_count = 0

        # 启动本地内存文件流服务器
        self.global_server, self.global_port = start_global_server()
        
        # 阻止系统休眠
        set_execution_state(True)  
        
        # 延迟执行系统检查，避免阻塞 UI 启动
        self.after(200, self.sys_check)
        
        # 注册文件拖拽
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

        # 启动时在后台静默加载帮助窗口
        self.after(200, self.preload_help_window)

    # --- 帮助窗口逻辑 (移植自 v0.9.6) ---
    def preload_help_window(self):
        """预加载帮助窗口，避免第一次点击时卡顿"""
        try:
            # [修复] 传入 self.hardware_info
            # 注意：需确保 detect_hardware_limit() 已经在 __init__ 中运行过（当前代码逻辑是先运行的，所以没问题）
            self.help_window = HelpWindow(self, info=self.hardware_info) 
            self.help_window.withdraw()         # 立即隐藏
            # 劫持关闭事件：当用户点击关闭时，不销毁，而是隐藏
            self.help_window.protocol("WM_DELETE_WINDOW", self.hide_help_window)
        except Exception as e: 
            print(f"Help Window Error: {e}") # 建议加上错误打印，方便调试
            pass

    def hide_help_window(self):
        """隐藏而不是销毁，保留状态"""
        self.help_window.withdraw()

    def show_help(self):
        """显示帮助窗口"""
        # 如果窗口还没创建（比如刚启动还没来得及预加载），就现做
        if not hasattr(self, "help_window") or not self.help_window.winfo_exists():
            self.preload_help_window()
        
        # 显示并置顶
        self.help_window.deiconify()
        self.help_window.lift()

    def show_toast(self, message, icon="✨"):
        if hasattr(self, "current_toast") and self.current_toast.winfo_exists():
            self.current_toast.destroy()
        self.current_toast = ToastNotification(self, message, icon)

    def drop_file(self, event):
        """处理文件拖入事件"""
        self.auto_clear_completed()
        files = self.tk.splitlist(event.data)
        self.add_list(files)

    def auto_clear_completed(self):
        """如果有新文件拖入且之前的任务全部已完成，自动清理列表"""
        if self.running: return
        if not self.file_queue: return
        all_finished = True
        for f in self.file_queue:
            code = self.task_widgets[f].status_code
            if code != 5 and code != -1: 
                all_finished = False; break
        if all_finished: self.clear_all()

    def check_placeholder(self):
        """检查是否需要显示空状态占位图"""
        if not self.file_queue:
            self.scroll.pack_forget()
            # 将 padx 修改为 20，与下方参数配置区的 UNIFIED_PAD_X 严格对齐
            self.lbl_placeholder.pack(fill="both", expand=True, padx=15, pady=0)
        else:
            self.lbl_placeholder.pack_forget()
            # 将 padx 修改为 20，使滚动条的外边缘与下方区域的边缘处于同一垂线上
            self.scroll.pack(fill="both", expand=True, padx=15, pady=0)

    def add_list(self, files):
        """将文件添加到任务队列，并执行智能排序"""
        # [PyArchitect Fix] 拖入新文件时，如果当前是"完成"状态，重置为"压制"状态
        if not self.running:
            self.reset_ui_state()

        with self.queue_lock: 
            existing_paths = set(os.path.normpath(os.path.abspath(f)) for f in self.file_queue)
            new_added = False
            
            # 过滤非视频文件与重复文件
            for f in files:
                f_norm = os.path.normpath(os.path.abspath(f))
                if f_norm in existing_paths: continue 
                if f_norm.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.ts', '.flv', '.wmv')):
                    self.file_queue.append(f_norm) 
                    existing_paths.add(f_norm) 
                    if f_norm not in self.task_widgets:
                        card = TaskCard(self.scroll, 0, f_norm) 
                        self.task_widgets[f_norm] = card
                    new_added = True
            
            if not new_added: return
            
            # 队列排序逻辑：
            # 锁定已开始/已完成的任务位置，对等待中的任务按文件大小从小到大排序
            # 这有助于短任务优先完成，提升用户心理满足感
            LOCKED_STATES = [STATE_DONE, STATE_ERROR, STATE_ENCODING, STATE_QUEUED_IO, STATE_READY, STATE_CACHING]
            immutable_queue = []
            mutable_queue = [] 
            for f in self.file_queue:
                widget = self.task_widgets[f]
                if widget.status_code in LOCKED_STATES or widget.source_mode in ["RAM", "SSD_CACHE", "DIRECT"]:
                    immutable_queue.append(f)
                else:
                    mutable_queue.append(f)
            mutable_queue.sort(key=lambda x: os.path.getsize(x))
            self.file_queue = immutable_queue + mutable_queue
            
            # UI 重绘
            for widget in self.task_widgets.values():
                widget.pack_forget()

            for i, f in enumerate(self.file_queue):
                if f in self.task_widgets:
                    card = self.task_widgets[f]
                    card.pack(fill="x", pady=4)
                    card.update_index(i + 1)
            
            if self.running: 
                self.update_run_status()
                self.show_toast(f"已添加 {len(files)} 个任务 (智能排序完成)", "📥")
            else:
                self.check_placeholder()

    def update_run_status(self):
        if not self.running: return
        total = len(self.file_queue)
        current = min(self.finished_tasks_count + 1, total)
        if current > total and total > 0: current = total
        try: self.lbl_run_status.configure(text=f"任务队列: {current} / {total}") 
        except: pass
    
    def on_closing(self):
        """窗口关闭事件处理"""
        if self.running:
            if not messagebox.askokcancel("退出", "任务正在进行中，确定强制退出吗？"):
                return

        self.stop_flag = True
        self.running = False
        self.executor.shutdown(wait=False) 
        self.kill_all_procs() 
        self.destroy()
        set_execution_state(False)
        os._exit(0)
        
    def kill_all_procs(self) -> None:
        """
        终止所有挂起的子进程。
        [PyArchitect Fix] 摒弃裸 except，精准捕获操作系统层级的进程调度异常。
        """
        for p in list(self.active_procs): 
            try:
                p.terminate()
                if platform.system() != "Windows":
                    p.kill() 
            except OSError:
                pass # 进程句柄已失效或无权限
            except subprocess.SubprocessError:
                pass 
            
        self.active_procs.clear()
        
        try: 
            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe"], 
                             creationflags=subprocess.CREATE_NO_WINDOW, 
                             stderr=subprocess.DEVNULL,
                             check=False)
            else:
                subprocess.run(["pkill", "-9", "-f", "ffmpeg"], 
                               stderr=subprocess.DEVNULL,
                               check=False)
        except OSError:
            pass

    def sys_check(self):
        """启动时系统环境检查"""
        # check_ffmpeg() # 可以注释掉这行，前面已经查过了
        threading.Thread(target=self.scan_disk, daemon=True).start()
        self.update_monitor_layout()

    def scan_disk(self):
        """[Refactored] 使用新的评分系统"""
        if self.manual_cache_path:
            path = self.manual_cache_path
        else:
            # 传入当前队列的第一个文件作为参考源（如果有）
            ref_file = self.file_queue[0] if self.file_queue else None
            path = DiskManager.get_best_cache_path(ref_file)

        cache_dir = os.path.join(path, "_Ultra_Smart_Cache_")
        os.makedirs(cache_dir, exist_ok=True)
        self.temp_dir = cache_dir

        # 更新 UI
        self.safe_update(self.btn_cache.configure, text=f"缓存池: {path[:3]} (智能托管)")

    def select_cache_folder(self):
        """手动选择缓存目录"""
        d = filedialog.askdirectory(title="选择缓存盘")
        if d:
            self.manual_cache_path = d
            self.scan_disk() 

    def toggle_action(self):
        """开始/停止按钮回调"""
        if not self.running:
            if not self.file_queue:
                lambda: ModernAlert(self, "提示", "请先拖入或导入视频文件！", type="error")
                return
            self.run()
        else:
            self.stop()

    def get_quality_analysis(self, value: float, codec: str = "H.264") -> str:
        """
        [PyArchitect Refactored] 具备编码器上下文感知的画质评估器。
        将当前数值逆向归一化到 H.264 基准，以确保语义评价的准确性。
        """
        val = int(value)
        offsets = {"H.264": 0, "H.265": 2, "AV1": 12}
        normalized_val = val - offsets.get(codec, 0)

        if normalized_val <= 17: return "💎 Archival / 极高画质 (体积极大)"
        elif normalized_val <= 20: return "✨ High Fidelity / 高保真 (适合收藏)"
        elif normalized_val <= 24: return "⚖️ Balanced / 标准平衡 (默认推荐)"
        elif normalized_val <= 28: return "📱 Compact / 紧凑分布 (适合分享)"
        elif normalized_val <= 33: return "💾 Low Bitrate / 低码率 (节省空间)"
        else: return "🧱 Proxy / 预览代理 (画质损耗)"

    def _on_codec_change(self, new_codec: str) -> None:
        """
        处理编码器切换时的动态标尺映射，维持同等画质的视觉基准。
        """
        offsets = {"H.264": 0, "H.265": 2, "AV1": 12}
        old_codec = getattr(self, "last_codec", "H.264")
        if old_codec == new_codec: 
            return

        current_val = self.crf_var.get()
        # 剥离旧编码器的偏移量，加上新编码器的偏移量
        base_val = current_val - offsets.get(old_codec, 0)
        new_val = base_val + offsets.get(new_codec, 0)

        # 限制在合法的 FFmpeg 量化范围内
        new_val = max(10, min(51, new_val))

        self.crf_var.set(new_val)
        self.last_codec = new_codec
        self.lbl_quality_stats.configure(text=self.get_quality_analysis(new_val, new_codec))

    def setup_ui(self, default_worker="2"):
        """构建主界面 UI 布局"""
        SIDEBAR_WIDTH = 420 
        self.grid_columnconfigure(0, weight=0, minsize=SIDEBAR_WIDTH)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # [修改] 使用传入的推荐值初始化
        self.priority_var = ctk.StringVar(value="HIGH / 高优先") 
        # [修改 4] 使用传入的推荐值初始化变量
        self.worker_var = ctk.StringVar(value=default_worker) 
        self.crf_var = ctk.IntVar(value=28)
        self.codec_var = ctk.StringVar(value="H.264")
        
        # --- 左侧控制面板 ---
        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0, width=SIDEBAR_WIDTH)
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)
        
        UNIFIED_PAD_X = 20  
        ROW_SPACING = 6     
        
        # 字体适配
        FONT_TITLE = ("Segoe UI Black", 36) if platform.system() == "Windows" else ("Impact", 36)
        
        # 标题区域
        l_head = ctk.CTkFrame(left, fg_color="transparent")
        l_head.pack(fill="x", padx=UNIFIED_PAD_X, pady=(20, 5))
        
        # 使用容器来包裹标题和按钮，确保对齐
        title_box = ctk.CTkFrame(l_head, fg_color="transparent")
        title_box.pack(fill="x")
        
        # [修改] 标题部分：将 Label 赋值给 self.lbl_main_title 并绑定点击事件
        self.lbl_main_title = ctk.CTkLabel(title_box, text="Cinético", font=FONT_TITLE, text_color=COLOR_TEXT_MAIN)
        self.lbl_main_title.pack(side="left")

        # [新增] 绑定标题点击事件
        self.lbl_main_title.bind("<ButtonRelease-1>", self.on_title_click)

        # [问号按钮]
        # [修改] 问号按钮：修改 command 指向新的逻辑 wrapper
        self.btn_help = ctk.CTkButton(title_box, text="?", width=30, height=30, corner_radius=15, 
                                      font=("Arial", 16, "bold"),
                                      fg_color="#888888", 
                                      hover_color="#555555",
                                      text_color="#FFFFFF",
                                      command=self.handle_help_click)
        self.btn_help.pack(side="right")
        
        # 缓存按钮 (浅色下背景深一点)
        btn_cache_bg = ("#E0E0E0", "#252525")
        btn_cache_hover = ("#D0D0D0", "#333333")
        self.btn_cache = ctk.CTkButton(left, text="Checking Disk...", fg_color=btn_cache_bg, hover_color=btn_cache_hover, 
                                     text_color=COLOR_TEXT_HINT, font=("Consolas", 10), height=28, corner_radius=14, 
                                     command=self.select_cache_folder) 
        self.btn_cache.pack(fill="x", padx=UNIFIED_PAD_X, pady=(5, 5))
        
        # 工具按钮组 (导入/重置)
        tools = ctk.CTkFrame(left, fg_color="transparent")
        tools.pack(fill="x", padx=15, pady=5)
        
        btn_tools_bg = ("#E0E0E0", "#333333")
        btn_tools_hover = ("#D0D0D0", "#444444")
        
        ctk.CTkButton(tools, text="IMPORT / 导入", width=190, height=38, corner_radius=19, 
                     fg_color=btn_tools_bg, hover_color=btn_tools_hover, text_color=COLOR_TEXT_MAIN, font=("微软雅黑", 12, "bold"),
                     command=self.add_file).pack(side="left", padx=5)
        
        self.btn_clear = ctk.CTkButton(tools, text="RESET / 重置", width=190, height=38, corner_radius=19, 
                     fg_color="transparent", border_width=1, border_color=COLOR_BORDER, 
                     hover_color=("#F0F0F0", "#331111"), text_color=COLOR_TEXT_SUB, font=("微软雅黑", 12),
                     command=self.clear_all)
        self.btn_clear.pack(side="left", padx=5)
        
        # 参数配置区 (底部容器)
        l_btm_bg = ("#F2F2F2", "#222222") 
        l_btm = ctk.CTkFrame(left, fg_color=l_btm_bg, corner_radius=20)
        l_btm.pack(side="bottom", fill="x", padx=UNIFIED_PAD_X, pady=10)

        # 绑定变量
        default_gpu = getattr(self, 'has_nvidia_gpu', False)
        self.gpu_var = ctk.BooleanVar(value=default_gpu)
        self.keep_meta_var = ctk.BooleanVar(value=True)
        self.hybrid_var = ctk.BooleanVar(value=True) 
        self.depth_10bit_var = ctk.BooleanVar(value=False)
        
        # 开关按钮样式配置
        BTN_OFF_BG = ("#EEEEEE", "#333333") 
        BTN_OFF_TEXT = ("#888888", "#999999")
        BTN_ON_BG = COLOR_ACCENT
        BTN_ON_TEXT = ("#FFFFFF", "#FFFFFF")

        def update_btn_visuals():
            is_gpu = self.gpu_var.get()
            self.btn_gpu.configure(fg_color=BTN_ON_BG if is_gpu else BTN_OFF_BG, text_color=BTN_ON_TEXT if is_gpu else BTN_OFF_TEXT)
            
            is_meta = self.keep_meta_var.get()
            self.btn_meta.configure(fg_color=BTN_ON_BG if is_meta else BTN_OFF_BG, text_color=BTN_ON_TEXT if is_meta else BTN_OFF_TEXT)
            
            # [关键修复] Mac 系统下，强制禁用，不允许被 GPU 开关逻辑复活
            if platform.system() == "Darwin":
                self.btn_hybrid.configure(state="disabled", fg_color=("#F0F0F0", "#222222"), text_color=("#AAAAAA", "#555555"))
            else:
                # Windows 下才允许根据 GPU 状态切换
                is_hybrid = self.hybrid_var.get()
                if not is_gpu: 
                    self.btn_hybrid.configure(state="disabled", fg_color=("#F5F5F5", "#222222"), text_color=("#AAAAAA", "#555555"))
                else: 
                    self.btn_hybrid.configure(state="normal", fg_color=BTN_ON_BG if is_hybrid else BTN_OFF_BG, text_color=BTN_ON_TEXT if is_hybrid else BTN_OFF_TEXT)
            
            is_10bit = self.depth_10bit_var.get()
            self.btn_10bit.configure(fg_color=BTN_ON_BG if is_10bit else BTN_OFF_BG, text_color=BTN_ON_TEXT if is_10bit else BTN_OFF_TEXT)

        def on_toggle_gpu():
            """GPU 开关逻辑：自动调整 CRF 和异构分流状态"""
            target = not self.gpu_var.get()
            self.gpu_var.set(target)
            if not target: self.hybrid_var.set(False) 
            # GPU 模式通常需要较高的量化值来平衡体积
            if target: self.crf_var.set(min(40, self.crf_var.get() + 5))
            else: self.crf_var.set(max(16, self.crf_var.get() - 5))
            update_btn_visuals()
            self.lbl_quality_stats.configure(text=self.get_quality_analysis(self.crf_var.get()))
            update_labels()

        def on_toggle_10bit():
            self.depth_10bit_var.set(not self.depth_10bit_var.get())
            update_btn_visuals()

        def on_toggle_simple(var):
            var.set(not var.get())
            update_btn_visuals()

        def update_labels():
            if self.gpu_var.get(): self.lbl_quality_title.configure(text="QUALITY (CQ) / 固定量化")
            else: self.lbl_quality_title.configure(text="QUALITY (CRF) / 恒定速率")

        # 4个功能开关按钮
        f_toggles = ctk.CTkFrame(l_btm, fg_color="transparent")
        f_toggles.pack(fill="x", padx=UNIFIED_PAD_X, pady=(15, 5))
        for i in range(4): f_toggles.grid_columnconfigure(i, weight=1)
        
        btn_font = ("微软雅黑", 11, "bold")
        self.btn_gpu = ctk.CTkButton(f_toggles, text="GPU ACCEL\n硬件加速", font=btn_font, corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER, command=on_toggle_gpu)
        self.btn_gpu.grid(row=0, column=0, padx=(0, 3), sticky="ew")
        
        self.btn_meta = ctk.CTkButton(f_toggles, text="KEEP DATA\n保留信息", font=btn_font, corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER, command=lambda: on_toggle_simple(self.keep_meta_var))
        self.btn_meta.grid(row=0, column=1, padx=3, sticky="ew")
        
        self.btn_hybrid = ctk.CTkButton(f_toggles, text="HYBRID\n异构分流", font=btn_font, corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER, command=lambda: on_toggle_simple(self.hybrid_var))
        self.btn_hybrid.grid(row=0, column=2, padx=3, sticky="ew")
        
        # Mac 统一内存架构不需要异构分流
        if platform.system() == "Darwin":
            self.hybrid_var.set(False) 
            self.btn_hybrid.configure(state="disabled")

        self.btn_10bit = ctk.CTkButton(f_toggles, text="10-BIT\n高色深", font=btn_font, corner_radius=8, height=48, hover_color=COLOR_ACCENT_HOVER, command=on_toggle_10bit)
        self.btn_10bit.grid(row=0, column=3, padx=(3, 0), sticky="ew")
        
        update_btn_visuals()

        # 分段选择器样式
        seg_text_color = ("#333333", "#DDDDDD")
        seg_unselected_hover = ("#D0D0D0", "#444444")

        # 优先级
        rowP = ctk.CTkFrame(l_btm, fg_color="transparent")
        rowP.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        ctk.CTkLabel(rowP, text="PRIORITY / 系统优先级", font=btn_font, text_color=COLOR_TEXT_MAIN).pack(anchor="w", pady=(0,3))
        self.seg_priority = ctk.CTkSegmentedButton(rowP, values=["NORMAL / 常规", "ABOVE / 较高", "HIGH / 高优先"], variable=self.priority_var, 
                                                   selected_color=COLOR_ACCENT, corner_radius=8, height=30, 
                                                   text_color=seg_text_color, selected_hover_color=COLOR_ACCENT_HOVER, unselected_hover_color=seg_unselected_hover)
        self.seg_priority.pack(fill="x")

        # 并发数
        row3 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row3.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        ctk.CTkLabel(row3, text="CONCURRENCY / 并发任务", font=btn_font, text_color=COLOR_TEXT_MAIN).pack(anchor="w", pady=(0,3))
        self.seg_worker = ctk.CTkSegmentedButton(row3, values=["1", "2", "3", "4"], variable=self.worker_var, 
                                                 corner_radius=8, height=30, selected_color=COLOR_ACCENT, command=self.update_monitor_layout, 
                                                 text_color=seg_text_color, selected_hover_color=COLOR_ACCENT_HOVER, unselected_hover_color=seg_unselected_hover)
        self.seg_worker.pack(fill="x")

        # 画质滑块
        row2 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row2.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        self.lbl_quality_title = ctk.CTkLabel(row2, text="QUALITY (CRF) / 恒定速率", font=btn_font, text_color=COLOR_TEXT_MAIN)
        self.lbl_quality_title.pack(anchor="w", pady=(0,3))
        
        c_box = ctk.CTkFrame(row2, fg_color="transparent")
        c_box.pack(fill="x")
        
        def on_slider_change(value):
            self.crf_var.set(int(value))
            # 传入当前的编码器上下文
            self.lbl_quality_stats.configure(text=self.get_quality_analysis(value, self.codec_var.get()))

        # [PyArchitect Fix] 扩容量化参数物理极限，适配 AV1 特性
        self.slider = ctk.CTkSlider(c_box, from_=10, to=51, variable=self.crf_var, 
                                  height=20, progress_color=COLOR_ACCENT,
                                  command=on_slider_change) 
        self.slider.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.lbl_val = ctk.CTkLabel(c_box, textvariable=self.crf_var, width=35, 
                                    font=("Arial", 12, "bold"), text_color=COLOR_ACCENT)
        self.lbl_val.pack(side="right")
        
        self.lbl_quality_stats = ctk.CTkLabel(row2, text="", font=("微软雅黑", 11), anchor="w", text_color=COLOR_TEXT_HINT)
        self.lbl_quality_stats.pack(fill="x", pady=(2, 0))
        self.lbl_quality_stats.configure(text=self.get_quality_analysis(self.crf_var.get(), self.codec_var.get()))
        
        # 编码格式
        row1 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row1.pack(fill="x", pady=ROW_SPACING, padx=UNIFIED_PAD_X)
        ctk.CTkLabel(row1, text="CODEC / 编码格式", font=btn_font, text_color=COLOR_TEXT_MAIN).pack(anchor="w", pady=(0,3))
        
        # [PyArchitect Fix] 初始化状态跟踪，并绑定动态映射回调
        self.last_codec = "H.264"
        self.seg_codec = ctk.CTkSegmentedButton(row1, values=["H.264", "H.265", "AV1"], variable=self.codec_var, 
                                                selected_color=COLOR_ACCENT, corner_radius=8, height=30, 
                                                command=self._on_codec_change,
                                                text_color=seg_text_color, selected_hover_color=COLOR_ACCENT_HOVER, unselected_hover_color=seg_unselected_hover)
        self.seg_codec.pack(fill="x")
        
        # 压制按钮
        self.btn_action = ctk.CTkButton(l_btm, text="COMPRESS / 压制", height=55, corner_radius=12, 
                                        font=("微软雅黑", 18, "bold"), fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, 
                                        text_color="#FFFFFF", 
                                        command=self.toggle_action)
        self.btn_action.pack(fill="x", padx=UNIFIED_PAD_X, pady=20)
        
        # --- 右侧内容区 ---
        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.lbl_placeholder = ctk.CTkLabel(left, text="📂\n\nDrag & Drop Video Files Here\n拖入视频文件开启任务", 
                                            font=("微软雅黑", 16, "bold"), text_color=COLOR_TEXT_HINT, justify="center")
        self.check_placeholder()
        
        right = ctk.CTkFrame(self, fg_color=COLOR_PANEL_RIGHT, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        
        r_head = ctk.CTkFrame(right, fg_color="transparent")
        r_head.pack(fill="x", padx=30, pady=(25, 10))
        ctk.CTkLabel(r_head, text="LIVE MONITOR", font=("Microsoft YaHei UI", 20, "bold"), text_color=COLOR_TEXT_HINT).pack(side="left")
        self.lbl_run_status = ctk.CTkLabel(r_head, text="", font=("微软雅黑", 12, "bold"), text_color=COLOR_ACCENT)
        self.lbl_run_status.pack(side="left", padx=20, pady=2) 
        
        self.monitor_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.monitor_frame.pack(fill="both", expand=True, padx=25, pady=(0, 15))

    def clear_all(self):
        """
        [PyArchitect Nuclear Reset] 彻底重置软件状态
        修复: 点击重置后无法开始新任务的死锁问题
        """
        # 1. 先停止标志位，防止后台线程继续生成数据
        self.stop_flag = True
        self.running = False
        
        # 2. [关键] 立即杀死所有外部进程
        self.kill_all_procs()
        
        # 3. [关键] 暴力重置线程池和锁 (解决卡顿的根源)
        # 如果旧线程池还在跑，直接抛弃它，创建新的
        try: 
            self.executor.shutdown(wait=False)
        except Exception: 
            pass
        self.executor = ThreadPoolExecutor(max_workers=16)
        
        # 补充对 I/O 预读线程池的同步绞杀
        try:
            if hasattr(self, 'io_executor'):
                self.io_executor.shutdown(wait=False)
        except Exception:
            pass
            
        # 重置锁对象 (防止死锁)
        self.queue_lock = threading.Lock()
        self.slot_lock = threading.Lock()
        
        # 4. 清除 UI 数据
        for k, v in self.task_widgets.items(): v.destroy()
        self.task_widgets.clear()
        self.file_queue.clear()
        
        # 5. 重置内部计数器和缓存
        self.finished_tasks_count = 0
        self.temp_files.clear()
        self.active_procs.clear()
        
        # [PyArchitect Fix] 暴力解构链表并强制触发底层 GC 垃圾回收，逼迫 Python 释放物理内存给 OS
        for token in list(GLOBAL_RAM_STORAGE.keys()):
            data_list = GLOBAL_RAM_STORAGE.get(token)
            if isinstance(data_list, list):
                data_list.clear() # 深度击碎 64MB 内存块的连续指针
        GLOBAL_RAM_STORAGE.clear()
        PATH_TO_TOKEN_MAP.clear()
        
        import gc
        gc.collect() # 强制执行全量垃圾回收 (Full Collection)
        
        # 6. 重置 UI 视觉
        self.check_placeholder()
        try: self.scroll._parent_canvas.yview_moveto(0.0)
        except: pass
        
        self.reset_ui_state()
        
        # 7. 重置监控槽位索引
        try: n = int(self.worker_var.get())
        except: n = 2
        self.available_indices = list(range(n))
        
        # 8. 最后再发一次 Toast 确认
        self.show_toast("状态已完全重置", "♻️")

    def update_monitor_layout(self, val=None, force_reset=False):
        """
        根据并发数动态调整右侧监控卡片的布局。
        """
        if self.running and not force_reset:
            self.seg_worker.set(str(self.current_workers))
            return
            
        try: n = int(self.worker_var.get())
        except: n = 2
        self.current_workers = n
        
        # 清除旧布局
        for ch in self.monitor_slots: ch.destroy() 
        self.monitor_slots.clear()
        
        with self.slot_lock:
            self.available_indices = [i for i in range(n)] 
            for i in range(n):
                ch = MonitorChannel(self.monitor_frame, i+1)
                self.monitor_slots.append(ch)
            
            # [对称布局修正] 如果是奇数个卡片，添加一个隐形的占位卡片保持 Grid 对齐
            if n > 1 and n % 2 != 0:
                dummy = MonitorChannel(self.monitor_frame, n+1)
                dummy.set_placeholder() 
                dummy.is_dummy = True  
                self.monitor_slots.append(dummy)

        # 触发自适应重排
        if not hasattr(self, "_resize_bind_id"):
            self._resize_bind_id = self.monitor_frame.bind("<Configure>", self._trigger_adaptive_layout)
        
        # [PyArchitect Fix] 使用 uniform="equal_cols" 强制锁定两列宽度绝对均分，无视内部内容挤压
        self.monitor_frame.grid_columnconfigure(0, weight=1, uniform="equal_cols")
        self.monitor_frame.grid_columnconfigure(1, weight=1, uniform="equal_cols")
        self._trigger_adaptive_layout()

    def _trigger_adaptive_layout(self, event=None):
        """防抖动布局触发器"""
        if hasattr(self, "_layout_timer") and self._layout_timer:
            self.after_cancel(self._layout_timer)
        self._layout_timer = self.after(100, self._apply_adaptive_layout)

    def _apply_adaptive_layout(self):
        """实际执行布局计算（单列 vs 双列网格）"""
        if not self.monitor_slots: return
        
        viewport_height = self.monitor_frame.winfo_height()
        if viewport_height < 50: viewport_height = 750 # 启动时保护值
        
        real_slots = [ch for ch in self.monitor_slots if not getattr(ch, 'is_dummy', False)]
        real_count = len(real_slots)
        
        needed_height = real_count * 340 
        use_grid_mode = (viewport_height < needed_height) and (real_count > 1)

        for i, ch in enumerate(self.monitor_slots):
            ch.pack_forget()
            ch.grid_forget()
            
            if getattr(ch, 'is_dummy', False):
                if use_grid_mode:
                    row = i // 2
                    col = i % 2
                    # [PyArchitect Fix] 使用 nsew 填满整个单元格
                    ch.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
                continue

            if use_grid_mode:
                row = i // 2
                col = i % 2
                # [PyArchitect Fix] 使用 nsew 填满整个单元格
                ch.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
            else:
                ch.grid(row=i, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)

    def process_caching(self, src_path, widget, lock_obj=None, no_wait=False):
        """
        IO 预读取逻辑。
        将文件加载到 RAM 或 SSD 缓存中，以加速编码。
        """
        file_size = os.path.getsize(src_path)
        file_size_gb = file_size / (1024**3)
        
        # 1. 尝试内存加载
        if file_size_gb < MAX_RAM_LOAD_GB:
             wait_count = 0
             limit = 0 if no_wait else 60 
             # 等待可用内存释放
             while wait_count < limit: 
                 free_ram = get_free_ram_gb()
                 available = free_ram - SAFE_RAM_RESERVE
                 if available > file_size_gb: break 
                 if wait_count == 0: self.safe_update(widget.set_status, "Awaiting Memory Allocation / 等待内存分配", COLOR_WAITING, STATUS_WAIT)
                 if self.stop_flag: return False
                 time.sleep(0.5)
                 wait_count += 1
                 
        if lock_obj: lock_obj.acquire()
        try:
            free_ram = get_free_ram_gb()
            available_for_cache = free_ram - SAFE_RAM_RESERVE
            
            # 策略：RAM 充足时优先载入 RAM
            if available_for_cache > file_size_gb and file_size_gb < MAX_RAM_LOAD_GB:
                self.safe_update(widget.set_status, "Buffering to RAM / 缓冲至物理内存", COLOR_RAM, STATUS_CACHING)
                self.safe_update(widget.set_progress, 0, COLOR_RAM)
                try:
                    chunk_size = 64 * 1024 * 1024  # 64MB 切片
                    data_buffer = []               # [PyArchitect Fix] 改用 List 存储，彻底消除连续内存碎片化引发的 MemoryError
                    read_len = 0
                    
                    with open(src_path, 'rb') as f:
                        while True:
                            if self.stop_flag: return False
                            chunk = f.read(chunk_size)
                            if not chunk: break
                            data_buffer.append(chunk) # 以独立的内存页追加，而非扩展连续指针
                            read_len += len(chunk)
                            if file_size > 0:
                                prog = read_len / file_size
                                self.safe_update(widget.set_progress, prog, COLOR_READING)
                                
                    token = str(uuid.uuid4().hex) 
                    GLOBAL_RAM_STORAGE[token] = data_buffer
                    PATH_TO_TOKEN_MAP[src_path] = token
                    self.safe_update(widget.set_status, "Ready (RAM Cached) / 就绪 (内存缓存)", COLOR_READY_RAM, STATUS_READY)                    
                    self.safe_update(widget.set_progress, 1, COLOR_READY_RAM)
                    widget.source_mode = "RAM"
                    return True
                except Exception as e: 
                    print(f"[RAM Allocation Error] {e}")
                    widget.clean_memory() # 内存分配失败回退
            
            # 策略：RAM 不足时尝试写入 SSD 缓存
            self.safe_update(widget.set_status, "Writing Storage Cache / 写入存储缓存", COLOR_SSD_CACHE, STATUS_CACHING)
            self.safe_update(widget.set_progress, 0, COLOR_SSD_CACHE)
            try:
                fname = os.path.basename(src_path)
                cache_path = os.path.join(self.temp_dir, f"CACHE_{int(time.time())}_{fname}")
                copied = 0
                aborted_by_user = False
                
                # [PyArchitect Fix] 严格遵守 Context Manager 生命周期，绝不在持有句柄时进行跨级删除
                with open(src_path, 'rb') as fsrc, open(cache_path, 'wb') as fdst:
                    while True:
                        if self.stop_flag: 
                            aborted_by_user = True
                            break # 安全跳出循环，交由 with 块自动释放 OS 文件锁
                            
                        chunk = fsrc.read(32 * 1024 * 1024) 
                        if not chunk: break
                        fdst.write(chunk)
                        copied += len(chunk)
                        if file_size > 0:
                            self.safe_update(widget.set_progress, copied / file_size, COLOR_SSD_CACHE)
                            
                # 句柄已安全释放，此时可以放心执行系统级 I/O 销毁
                if aborted_by_user:
                    try: 
                        os.remove(cache_path)
                    except OSError: 
                        pass # 忽略无权限或文件不存在的系统异常
                    return False

                self.temp_files.add(cache_path)
                widget.ssd_cache_path = cache_path
                widget.source_mode = "SSD_CACHE"
                self.safe_update(widget.set_status, "Ready (Storage Cached) / 就绪 (存储缓存)", COLOR_SSD_CACHE, STATUS_READY)
                self.safe_update(widget.set_progress, 1, COLOR_SSD_CACHE)
                return True
                
            except OSError:
                # [PyArchitect Fix] 捕获具体的 OSError 而非裸奔的 Exception
                self.safe_update(widget.set_status, "Cache Allocation Failed / 缓存分配失败", COLOR_ERROR, STATUS_ERR)
                return False
        finally:
            if lock_obj: lock_obj.release()
        
    def run(self):
        """开始执行任务队列"""
        if not self.file_queue: return
        if self.running: return
        
        # [关键] 强制清理上一轮可能的僵尸进程
        self.kill_all_procs() 
        
        self.running = True
        self.stop_flag = False
        
        # UI 状态切换
        self.btn_action.configure(text="STOP / 停止", fg_color=("#C0392B", "#852222"), hover_color=("#E74C3C", "#A32B2B"), state="normal")
        self.btn_clear.configure(state="disabled")

        # 线程池重置
        self.executor.shutdown(wait=False)
        self.executor = ThreadPoolExecutor(max_workers=16)
        
        with self.slot_lock: self.available_indices = list(range(self.current_workers))
        self.update_monitor_layout()
        
        # 重置未完成任务状态
        with self.queue_lock:
            self.finished_tasks_count = 0 # [关键] 计数器归零
            for f in self.file_queue:
                card = self.task_widgets[f]
                # [关键] 只有真正完成的任务才跳过，其他的全部重置为等待
                if card.status_code == STATE_DONE: 
                    self.finished_tasks_count += 1
                else:
                    card.set_status("Pending / 等待处理", COLOR_TEXT_HINT, STATUS_WAIT)
                    # [PyArchitect Fix] 补齐缺失的 color 参数，使用系统强调色作为重置后的默认色彩
                    card.set_progress(0.0, COLOR_ACCENT)
                    card.clean_memory() 
                    if card.ssd_cache_path and os.path.exists(card.ssd_cache_path):
                        try: 
                            os.remove(card.ssd_cache_path)
                        except OSError: 
                            pass # 忽略底层文件系统级别的删除异常
                    card.ssd_cache_path = None
                    card.source_mode = "PENDING"
        
        threading.Thread(target=self.engine, daemon=True).start()

    def stop(self):
        """停止所有任务"""
        self.stop_flag = True
        self.kill_all_procs()
        self.btn_action.configure(text="正在停止...", state="disabled")

    def reset_ui_state(self) -> None:
        """
        恢复 UI 到初始空闲状态。
        """
        if not self.winfo_exists(): return
        
        self.btn_action.configure(
            text="START ENCODE / 启动编码", 
            fg_color=COLOR_ACCENT, 
            hover_color=COLOR_ACCENT_HOVER, 
            state="normal",
            command=self.toggle_action 
        )
        
        self.lbl_run_status.configure(text="") 
        self.btn_clear.configure(state="normal")
        self.update_monitor_layout(force_reset=True)

    def set_completion_state(self) -> None:
        """
        设置任务全部完成后的 UI 状态。
        """
        if not self.winfo_exists(): return
        
        self.btn_action.configure(
            text="EXECUTION FINISHED / 执行完成", 
            fg_color=COLOR_SUCCESS, 
            hover_color=COLOR_SUCCESS, 
            state="normal",
            command=self.reset_ui_state
        )
        
        self.btn_clear.configure(state="normal")
        self.lbl_run_status.configure(text="Queue Execution Concluded / 队列执行完毕")

    def get_dur(self, path: str) -> float:
        """
        安全获取视频流的物理时长 (秒)。
        引入超时与输出重定向机制，防止子进程管道死锁。
        
        Args:
            path (str): 目标视频文件的绝对路径。
            
        Returns:
            float: 视频时长秒数。若解析失败则返回 0.0。
        """
        try:
            cmd =[
                FFPROBE_PATH, "-v", "error", 
                "-show_entries", "format=duration", 
                "-of", "default=noprint_wrappers=1:nokey=1", path
            ]
            kwargs = get_subprocess_args()
            
            # stderr=subprocess.DEVNULL 避免错误日志填满系统管道导致主线程挂起
            # timeout=5.0 避免损坏的视频文件导致进程无限期阻塞
            out = subprocess.check_output(
                cmd, 
                stderr=subprocess.DEVNULL, 
                timeout=5.0, 
                **kwargs
            ).strip()
            return float(out)
        except (subprocess.SubprocessError, OSError, ValueError):
            # 精准捕获子进程异常与类型转换异常，严禁使用裸 except
            return 0.0

    def add_file(self):
        """添加文件对话框"""
        files = filedialog.askopenfilenames(title="选择视频文件", filetypes=[("Video Files", "*.mp4 *.mkv *.mov *.avi *.ts *.flv *.wmv")])
        if files: 
            self.auto_clear_completed()
            self.add_list(files)

    def launch_fireworks(self) -> None:
        """
        执行任务完成的视觉反馈。
        [PyArchitect Fix] 移除了强制全局置顶的侵入性行为，尊重操作系统的窗口 Z 轴层级。
        """
        if not self.winfo_exists(): return
        
        # [防卫性编程] 如果主窗口已被最小化，拒绝渲染动画，仅弹出状态通知
        if self.state() == "iconic":
            self.show_toast("Execution Concluded / 队列执行完毕", "🏆")
            return

        try:
            top = ctk.CTkToplevel(self)
            top.title("")
            w, h = self.winfo_width(), self.winfo_height()
            x, y = self.winfo_x(), self.winfo_y()
            top.geometry(f"{w}x{h}+{x}+{y}")
            top.overrideredirect(True) 
            top.transient(self)        # 仅吸附于主窗口，跟随主窗口的层级
            
            sys_plat = platform.system()
            canvas_bg = "black" 

            if sys_plat == "Windows":
                try:
                    top.attributes("-transparentcolor", "black")
                    # [修复] 彻底移除 top.attributes("-topmost", True)
                    canvas_bg = "black"
                except ctk.tkinter.TclError:
                    pass
            elif sys_plat == "Darwin":
                try:
                    top.attributes("-transparent", True)  
                    top.config(bg='systemTransparent')
                    canvas_bg = 'systemTransparent'
                except ctk.tkinter.TclError:
                    top.attributes("-alpha", 0.8)
                    canvas_bg = "black"
            else:
                top.attributes("-alpha", 0.9)
                canvas_bg = "black"

            canvas = ctk.CTkCanvas(top, bg=canvas_bg, highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            
            particles = []
            colors = [COLOR_ACCENT[1], "#F1C40F", "#E74C3C", "#2ECC71", "#9B59B6", "#00FFFF", "#FF00FF", "#FFFFFF"] 
            particle_count = 180 
            
            # 生成粒子
            for _ in range(particle_count):
                particles.append({
                    "x": random.uniform(-50, 100), 
                    "y": h + random.uniform(0, 30), 
                    "vx": random.gauss(18, 10), 
                    "vy": random.gauss(-45, 12), 
                    "grav": 2.0, "size": random.uniform(3, 8), 
                    "color": random.choice(colors), "life": 1.0, "decay": random.uniform(0.015, 0.030)
                })
            for _ in range(particle_count):
                particles.append({
                    "x": random.uniform(w-100, w+50), 
                    "y": h + random.uniform(0, 30), 
                    "vx": random.gauss(-18, 10), 
                    "vy": random.gauss(-45, 12), 
                    "grav": 1.6, "size": random.uniform(3, 8), 
                    "color": random.choice(colors), "life": 1.0, "decay": random.uniform(0.015, 0.030)
                })

            def animate():
                if not top.winfo_exists(): return
                try:
                    canvas.delete("all")
                    alive_count = 0
                    for p in particles:
                        if p["life"] > 0:
                            alive_count += 1
                            tail_x, tail_y = p["x"], p["y"]
                            p["x"] += p["vx"]
                            p["y"] += p["vy"]
                            p["vy"] += p["grav"] 
                            p["vx"] *= 0.96
                            p["life"] -= p["decay"]
                            
                            if p["life"] > 0.05:
                                canvas.create_line(
                                    tail_x, tail_y, p["x"], p["y"], 
                                    fill=p["color"], width=p["size"] * p["life"], capstyle="round"
                                )
                    if alive_count > 0: 
                        top.after(16, animate)
                    else: 
                        top.destroy()
                        self.show_toast("✨ 所有任务已完成 / All Tasks Finished! ✨", "🏆")
                except:
                    if top.winfo_exists(): top.destroy()
            animate()
        except:
            if 'top' in locals() and top.winfo_exists(): top.destroy()
            self.show_toast("✨ 所有任务已完成 / All Tasks Finished! ✨", "🏆")

    def engine(self):
        """
        [Fixed] 核心调度引擎。
        修复了任务自然完成后 UI 不重置、不播放动画的问题。
        """
        total_ram_limit = MAX_RAM_LOAD_GB 
        current_ram_usage = 0.0            
        is_cache_ssd = DiskManager.is_ssd(self.temp_dir) or (self.manual_cache_path and DiskManager.is_ssd(self.manual_cache_path))
        io_concurrency = self.current_workers if is_cache_ssd else 1
        self.io_executor = ThreadPoolExecutor(max_workers=io_concurrency)
        
        while not self.stop_flag:
            active_io_count = 0
            active_compute_count = 0
            current_ram_usage = 0.0
            
            # 1. 统计资源
            with self.queue_lock:
                for f in self.file_queue:
                    card = self.task_widgets[f]
                    if card.source_mode == "RAM" and card.status_code not in [STATE_DONE, STATE_ERROR]:
                        current_ram_usage += card.file_size_gb
                    if card.status_code in [STATE_QUEUED_IO, STATE_CACHING]: active_io_count += 1
                    elif card.status_code == STATE_ENCODING: active_compute_count += 1
            
            # 2. 调度 IO
            with self.queue_lock:
                for f in self.file_queue:
                    card = self.task_widgets[f]
                    if card.status_code == STATE_PENDING:
                        source_is_ssd = DiskManager.is_ssd(f)
                        if source_is_ssd:
                            card.source_mode = "DIRECT"
                            card.status_code = STATE_READY 
                            self.safe_update(card.set_status, "就绪 (SSD直读)", COLOR_DIRECT, STATE_READY)
                            self.safe_update(card.set_progress, 1.0, COLOR_DIRECT)
                            continue 
                        else:
                            if active_io_count >= 1: break 
                            predicted_usage = current_ram_usage + card.file_size_gb
                            if predicted_usage < total_ram_limit:
                                should_use_ram = True
                                current_ram_usage += card.file_size_gb 
                            else: should_use_ram = False 
                            card.source_mode = "RAM" if should_use_ram else "SSD_CACHE"
                            card.status_code = STATE_QUEUED_IO
                            active_io_count += 1
                            self.io_executor.submit(self._worker_io_task, f)
                            break
            
            # 3. 调度计算
            if active_compute_count < self.current_workers:
                with self.queue_lock:
                    for f in self.file_queue:
                        card = self.task_widgets[f]
                        if card.status_code == STATE_READY:
                            card.status_code = STATE_ENCODING
                            active_compute_count += 1
                            self.executor.submit(self._worker_compute_task, f)
                            self.safe_update(self.scroll_to_card, card)
                            if active_compute_count >= self.current_workers: break
            
            # 4. 检查完成状态
            all_done = True
            with self.queue_lock:
                for f in self.file_queue:
                    if self.task_widgets[f].status_code not in [STATE_DONE, STATE_ERROR]: all_done = False; break
            
            # 如果全部完成且没有活动的线程，退出循环
            if all_done and active_io_count == 0 and active_compute_count == 0: break
            time.sleep(0.1) 
            
        # --- 循环结束后的收尾工作 ---
        self.running = False
        
        # [PyArchitect Fix] 强制释放 I/O 线程池，阻断 Zombie Threads 内存泄漏链条
        if hasattr(self, 'io_executor'):
            self.io_executor.shutdown(wait=False)
        
        if not self.stop_flag:
            # 正常完成逻辑：播放动画 + 切换绿色完成状态
            self.safe_update(self.launch_fireworks)
            if self.test_mode:
                self.safe_update(self._show_test_report)
            self.safe_update(self.set_completion_state)
        else:
            # 用户强制停止逻辑：提示 + 重置回初始状态
            self.safe_update(self.show_toast, "任务已手动停止", "🛑")
            self.safe_update(self.reset_ui_state)

    def _show_test_report(self):
        """显示测试报告的辅助函数"""
        orig_total = self.test_stats["orig"]
        new_total = self.test_stats["new"]
        msg = "测试队列完成！\n\n"
        msg += f"原视频总大小: {orig_total / (1024**3):.2f} GB\n"
        msg += f"压制后总大小: {new_total / (1024**3):.2f} GB\n"
        if orig_total > 0:
            ratio = (new_total / orig_total) * 100
            save_rate = 100 - ratio
            msg += f"\n压缩比: {ratio:.2f}% (节省 {save_rate:.2f}% 空间)"
        else:
            msg += "\n数据异常：原视频大小为0"
        ModernAlert(self, "基准测试报告", msg, type="info")

    def _worker_io_task(self, task_file):
        """线程任务：IO 预读取"""
        card = self.task_widgets[task_file]
        try:
            self.safe_update(card.set_status, "Allocating I/O / 正在分配 I/O", COLOR_READING, STATE_CACHING)
            success = self.process_caching(task_file, card, lock_obj=None, no_wait=True)
            if success:
                self.safe_update(card.set_status, "Standby for Encoding / 编码待命", COLOR_READY_RAM if card.source_mode == "RAM" else COLOR_SSD_CACHE, STATE_READY)
            else: self.safe_update(card.set_status, "I/O Failure / I/O 失败", COLOR_ERROR, STATE_ERROR)
        except Exception as e:
            self.safe_update(card.set_status, "I/O Exception / I/O 异常", COLOR_ERROR, STATE_ERROR)

    def _worker_compute_task(self, task_file):
        """线程任务：视频编码计算 (PyArchitect Fixed: UUID Guard & Atomic State)"""
        card = self.task_widgets[task_file]
        fname = os.path.basename(task_file)
        slot_idx = -1
        ch_ui = None
        proc = None
        working_output_file = None 
        temp_audio_wav = os.path.join(self.temp_dir, f"TEMP_AUDIO_{uuid.uuid4().hex}.wav")
        input_size = 0
        duration = 1.0
        
        # [关键] 生成本次任务的唯一令牌
        task_token = uuid.uuid4().hex 
        
        # 用于崩溃时回溯日志
        log_buffer = deque(maxlen=30)
        
        # 获取显示槽位
        with self.slot_lock:
            if self.available_indices:
                slot_idx = self.available_indices.pop(0)
                if slot_idx < len(self.monitor_slots): ch_ui = self.monitor_slots[slot_idx]
        
        # 兜底 UI 对象，防止 ch_ui 为空导致崩溃
        if not ch_ui: 
            class DummyUI: 
                def activate(self, *a): pass
                def update_data(self, *a): pass
                def reset(self): pass
            ch_ui = DummyUI()
            
        try:
            # 激活通道，传入 Token
            self.safe_update(ch_ui.activate, fname, "Initializing Pipeline / 初始化处理管线", task_token)
            
            if os.path.exists(task_file):
                input_size = os.path.getsize(task_file)
                duration = self.get_dur(task_file)
                if duration <= 0: duration = 1.0

            # --- 像素格式预检 (防止 4:2:2 炸显卡) ---
            force_cpu_decode = False
            try:
                probe_cmd = [
                    FFPROBE_PATH, "-v", "error", "-select_streams", "v:0", 
                    "-show_entries", "stream=pix_fmt", "-of", "csv=p=0", task_file
                ]
                pixel_format_info = subprocess.check_output(probe_cmd, **get_subprocess_args()).decode().strip()
                if "422" in pixel_format_info: 
                    force_cpu_decode = True
            except Exception: pass

            # 1. 提取音频
            self.safe_update(ch_ui.activate, fname, "Demuxing Audio Stream / 解复用音频流", task_token)
            self.safe_update(card.set_status, "Demuxing Audio / 音频解复用", COLOR_READING, STATE_ENCODING)
            has_audio = False
            
            extract_cmd = [FFMPEG_PATH, "-y", "-i", task_file, "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", "-f", "wav", temp_audio_wav]
            audio_proc = subprocess.run(extract_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **get_subprocess_args())
            
            if audio_proc.returncode == 0 and os.path.exists(temp_audio_wav) and os.path.getsize(temp_audio_wav) > 1024: 
                has_audio = True

            self.safe_update(card.set_status, "Encoding in Progress / 编码进行中", COLOR_ACCENT, STATE_ENCODING)
            
            # 2. 构建编码命令 (逻辑保持不变，为节省篇幅省略中间构建 cmd 的代码，请保留原有的构建逻辑)
            # ... [此处保留原代码中构建 cmd 列表的逻辑] ...
            # 为了确保完整性，这里假设你保留了 cmd = [FFMPEG_PATH, ...] 的构建代码
            
            # --- 以下是 cmd 构建逻辑的简化占位，请务必保留原有逻辑 ---
            codec_sel = self.codec_var.get()
            using_gpu = self.gpu_var.get()
            allow_hw_decode_input = using_gpu
            if force_cpu_decode and platform.system() == "Windows": allow_hw_decode_input = False
            final_hw_encode = using_gpu
            
            input_video_source = task_file
            if not using_gpu and card.source_mode == "RAM":
                token = PATH_TO_TOKEN_MAP.get(task_file)
                if token: input_video_source = f"http://127.0.0.1:{self.global_port}/{token}"
            elif card.source_mode == "SSD_CACHE" and card.ssd_cache_path:
                input_video_source = os.path.abspath(card.ssd_cache_path)

            output_dir = os.path.dirname(task_file)
            f_name_no_ext = os.path.splitext(fname)[0]
            final_output_path = os.path.join(output_dir, f"{f_name_no_ext}_Compressed_{time.strftime('%Y%m%d')}.mp4")
            working_output_file = os.path.join(self.temp_dir, f"TEMP_ENC_{uuid.uuid4().hex}.mp4")

            cmd = [FFMPEG_PATH, "-y"]
            if allow_hw_decode_input:
                if platform.system() == "Darwin": cmd.extend(["-hwaccel", "videotoolbox"])
                else: cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])
            if not using_gpu and card.source_mode == "RAM": cmd.extend(["-probesize", "50M", "-analyzeduration", "100M"])
            cmd.extend(["-i", input_video_source])
            if has_audio: cmd.extend(["-i", temp_audio_wav])
            cmd.extend(["-map", "0:v:0"])
            if has_audio: cmd.extend(["-map", "1:a:0"])
            
            # 编码器选择部分 (保留原逻辑)
            if final_hw_encode:
                if platform.system() == "Darwin":
                    if "H.264" in codec_sel: v_codec = "h264_videotoolbox"
                    elif "H.265" in codec_sel: v_codec = "hevc_videotoolbox"
                    else: v_codec = "libsvtav1"; final_hw_encode = False
                else:
                    if "H.264" in codec_sel: v_codec = "h264_nvenc"
                    elif "H.265" in codec_sel: v_codec = "hevc_nvenc"
                    else: v_codec = "av1_nvenc"
                cmd.extend(["-c:v", v_codec])
            else:
                cmd.extend(["-c:v", "libx264"])

            # 码率控制与像素格式
            use_10bit = self.depth_10bit_var.get()
            if final_hw_encode and "H.264" in codec_sel and use_10bit: use_10bit = False 

            # [PyArchitect Fix] 贯彻 WYSIWYG 原则，直接透传前端已处理好的物理映射值
            target_crf = self.crf_var.get()

            if final_hw_encode:
                if platform.system() == "Darwin":
                    # Mac VideoToolbox 质量映射
                    mac_quality = int(100 - (target_crf * 2.2))
                    if mac_quality < 20: mac_quality = 20
                    cmd.extend(["-q:v", str(mac_quality)])
                    if use_10bit: cmd.extend(["-pix_fmt", "p010le"])
                    else: cmd.extend(["-pix_fmt", "yuv420p"])
                else:
                    # Windows NVENC 质量映射
                    if use_10bit:
                         if allow_hw_decode_input: cmd.extend(["-vf", "scale_cuda=format=p010le"])
                         else: cmd.extend(["-pix_fmt", "p010le"])
                    else:
                         if allow_hw_decode_input: cmd.extend(["-vf", "scale_cuda=format=yuv420p"])
                         else: cmd.extend(["-pix_fmt", "yuv420p"])
                    cmd.extend(["-rc", "vbr", "-cq", str(target_crf), "-b:v", "0"])
                    if "AV1" not in codec_sel: cmd.extend(["-preset", "p4"])
            else:
                # CPU 软解质量映射
                if use_10bit: cmd.extend(["-pix_fmt", "yuv420p10le"])
                else: cmd.extend(["-pix_fmt", "yuv420p"])
                cmd.extend(["-crf", str(target_crf), "-preset", "medium"])

            if has_audio: cmd.extend(["-c:a", "aac", "-b:a", "320k"])
            if self.keep_meta_var.get(): cmd.extend(["-map_metadata", "0"])
            cmd.extend(["-progress", "pipe:1", "-nostats", working_output_file])
            # --- cmd 构建结束 ---

            # 3. 启动 FFmpeg 子进程 (应用企业级安全加固，防止 OS 管道死锁)
            kwargs = get_subprocess_args()
            if platform.system() == "Windows":
                 proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace", bufsize=1,
                                       startupinfo=kwargs['startupinfo'], creationflags=kwargs['creationflags'])
            else:
                 proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace", bufsize=1)
            self.active_procs.append(proc)
            
            decode_mode = "GPU" if allow_hw_decode_input else "CPU"
            if force_cpu_decode: decode_mode = "CPU(4:2:2)"
            tag_info = f"Enc: {'GPU' if final_hw_encode else 'CPU'} | Dec: {decode_mode}"
            if card.source_mode == "RAM": tag_info += " | RAM"
            
            # [关键] 更新时传入 task_token
            self.safe_update(ch_ui.activate, fname, tag_info, task_token)
            
            # 4. 进度监听循环
            progress_stats = {}
            start_t = time.time()
            last_ui_update_time = 0 
            max_prog_reached = 0.0   
            is_finished_locally = False 
            
            # [关键] 清空上次的日志缓存
            card.log_data.clear()

            for line in proc.stdout:
                if self.stop_flag or is_finished_locally: break
                try: 
                    line_str = line.strip() 
                    if not line_str: continue
                    
                    # [新增] 实时写入卡片专有日志
                    card.log_data.append(line_str)
                    
                    if "=" in line_str:
                        parts = line_str.split("=", 1)
                        if len(parts) == 2:
                            key, value = parts
                            progress_stats[key.strip()] = value.strip()
                            
                            if key.strip() == "out_time_us":
                                now = time.time()
                                if now - last_ui_update_time > 0.1:
                                    fps = float(progress_stats.get("fps", "0")) if "fps" in progress_stats else 0.0
                                    try: current_us = int(value.strip())
                                    except: current_us = 0
                                    
                                    raw_prog = (current_us / 1000000.0) / duration
                                    if raw_prog > max_prog_reached: max_prog_reached = raw_prog
                                    final_prog = min(0.99, max_prog_reached) 
                                    
                                    eta = "--:--"
                                    elapsed = now - start_t
                                    if final_prog > 0.005:
                                        eta_sec = (elapsed / final_prog) - elapsed
                                        if eta_sec < 0: eta_sec = 0
                                        eta = f"{int(eta_sec//60):02d}:{int(eta_sec%60):02d}"
                                    
                                    # [新增] 核心数学逻辑：动态预测最终体积
                                    est_size_str = ""
                                    if final_prog > 0.05: # 进度大于 5% 后预测才趋于准确
                                        raw_size = progress_stats.get("total_size", "0").replace("N/A", "0")
                                        try:
                                            current_size_bytes = int(raw_size)
                                            if current_size_bytes > 0:
                                                est_mb = (current_size_bytes / final_prog) / (1024 * 1024)
                                                est_size_str = f"Est: {est_mb:.1f}MB"
                                        except ValueError:
                                            pass
                                    
                                    if not is_finished_locally:
                                        if final_prog >= 0.98:
                                            self.safe_update(ch_ui.update_data, fps, 0.99, "Finalizing...", task_token, "")
                                            self.safe_update(card.set_status, "📦 封装中...", COLOR_ACCENT, STATE_ENCODING)
                                            self.safe_update(card.set_progress, 0.99, COLOR_ACCENT)
                                        else:
                                            # [修改] 将预测体积传给监控通道
                                            self.safe_update(ch_ui.update_data, fps, final_prog, eta, task_token, est_size_str)
                                            self.safe_update(card.set_progress, final_prog, COLOR_ACCENT)
                                    
                                    last_ui_update_time = now
                except: pass
            
            proc.wait()
            is_finished_locally = True # [关键] 进程结束，立即上锁，禁止后续的进度条回滚
            
            # 立即释放通道
            self.safe_update(ch_ui.reset)
            
            if proc in self.active_procs: self.active_procs.remove(proc)
            if os.path.exists(temp_audio_wav):
                try: os.remove(temp_audio_wav)
                except: pass
            
            if self.stop_flag:
                self.safe_update(card.set_status, "Process Terminated / 进程已终止", COLOR_PAUSED, STATE_PENDING)
            elif proc.returncode == 0:
                # 成功分支
                self.safe_update(card.set_status, "Relocating Output / 迁移输出文件", COLOR_MOVING, STATE_DONE)
                
                if self.test_mode:
                     # (测试模式代码简略)
                     new_s = os.path.getsize(working_output_file)
                     self.test_stats["orig"] += input_size
                     self.test_stats["new"] += new_s
                     try: os.remove(working_output_file)
                     except: pass
                     self.safe_update(card.set_status, "Benchmark Complete / 基准测试完成", COLOR_SUCCESS, STATE_DONE)
                     self.safe_update(card.set_progress, 1.0, COLOR_SUCCESS)
                else:
                    if os.path.exists(working_output_file): 
                        shutil.move(working_output_file, final_output_path)
                    if self.keep_meta_var.get() and os.path.exists(final_output_path): 
                        try: shutil.copystat(task_file, final_output_path)
                        except: pass
                    
                    final_size_mb = 0
                    ratio_str = ""
                    try:
                        final_size_mb = os.path.getsize(final_output_path)
                        saved_percent = (1.0 - (final_size_mb / input_size)) * 100
                        ratio_str = f"(-{saved_percent:.1f}%)" if saved_percent >= 0 else f"(+{abs(saved_percent):.1f}%)"
                    except: pass
                    
                    # [关键] 最终状态更新，覆盖之前的 "Finalizing"
                    self.safe_update(card.set_status, f"Task Resolved / 任务已终结 {ratio_str}", COLOR_SUCCESS, STATE_DONE)
                    self.safe_update(card.set_progress, 1.0, COLOR_SUCCESS)
            else:
                err_summary = "\n".join(list(log_buffer))
                self.safe_update(card.set_status, "Encoding Exception / 编码异常", COLOR_ERROR, STATE_ERROR)
                
        except Exception as e:
            print(f"System Error: {e}")
            self.safe_update(card.set_status, "System Fault / 系统故障", COLOR_ERROR, STATE_ERROR)
        finally:
            # 清理全局缓存映射
            token = PATH_TO_TOKEN_MAP.get(task_file)
            if token and token in GLOBAL_RAM_STORAGE:
                 del GLOBAL_RAM_STORAGE[token]
                 del PATH_TO_TOKEN_MAP[task_file]
            if working_output_file and os.path.exists(working_output_file):
                try: os.remove(working_output_file)
                except: pass
            
            self.safe_update(ch_ui.reset)
            # [关键] 归还显示槽位，确保下个任务有窗口可用
            with self.slot_lock:
                if slot_idx != -1:
                    self.available_indices.append(slot_idx)
                    self.available_indices.sort()

if __name__ == "__main__":
    # --- [PyArchitect Fix] 控制台隐身术 ---
    # 这一步会在程序启动的瞬间，查找当前的控制台窗口并将其隐藏。
    # 这样在 VSCode 里你可以看到输出（因为 VSCode 捕获了 stdout），但不会弹出一个独立的黑框。
    try:
        if platform.system() == "Windows":
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd != 0:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

    # --- [PyArchitect Fix] 单实例锁 ---
    instance_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        instance_lock.bind(('127.0.0.1', 53333))
    except socket.error:
        # 如果锁失败，说明已经有一个实例在运行，直接静默退出
        sys.exit(0)

    # --- [PyArchitect Optimization] 预初始化主程序 ---
    # 现在的逻辑是：先创建主程序(App) -> 它是隐藏的 -> 然后创建启动页(Splash) -> 启动页初始化完毕后唤醒主程序
    # 这样就彻底消灭了“启动页消失后主程序还没出来”的尴尬间隙。
    
    app = UltraEncoderApp()
    
    # 将 app 传给 splash，splash 会负责在合适的时机展示 app
    splash = SplashScreen(root_app=app)
    
    # 进入主事件循环
    # 注意：这里我们运行 app.mainloop()，因为 splash 是 app 的 Toplevel，它会一并运行
    app.mainloop()
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import threading
import re
import os
import time
import shutil
import ctypes
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque
from functools import partial
import asyncio
import aiofiles

# === 全局视觉配置 ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

COLOR_BG_MAIN = "#121212"
COLOR_PANEL_LEFT = "#1a1a1a"
COLOR_PANEL_RIGHT = "#0f0f0f"
COLOR_CARD = "#2d2d2d"
COLOR_ACCENT = "#3B8ED0"
COLOR_ACCENT_HOVER = "#36719f"
COLOR_CHART_LINE = "#00E676"
COLOR_TEXT_WHITE = "#FFFFFF"
COLOR_TEXT_GRAY = "#888888"
COLOR_SUCCESS = "#2ECC71" 
COLOR_MOVING = "#F1C40F"  
COLOR_READING = "#9B59B6" 
COLOR_PAUSED = "#7f8c8d"  
COLOR_ERROR = "#FF4757"   
COLOR_TEMP_CACHE = "#1ABC9C"  # 新增缓存状态色

# 状态码定义
STATUS_WAIT = 0
STATUS_RUN = 1
STATUS_DONE = 2
STATUS_MOVE = 3
STATUS_READ = 4
STATUS_READY = 5
STATUS_ERR = -1

# 优先级常量
PRIORITY_NORMAL = 0x00000020
PRIORITY_ABOVE = 0x00008000
PRIORITY_HIGH = 0x00000080

# 拖拽支持检查
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    class DnDWindow(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
    HAS_DND = True
except ImportError:
    class DnDWindow(ctk.CTk): pass
    HAS_DND = False

# === 硬件底层优化 ===
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)
    ]

def get_free_ram_gb():
    """获取可用物理内存(GB)"""
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullAvailPhys / (1024**3)
    except:
        return 64.0  # 14900K+64GB配置默认值

def check_ffmpeg():
    """验证FFmpeg可用性"""
    try:
        subprocess.run(["ffmpeg", "-version"], 
                      stdout=subprocess.PIPE, 
                      stderr=subprocess.PIPE, 
                      creationflags=subprocess.CREATE_NO_WINDOW,
                      check=True)
        return True
    except Exception as e:
        print(f"FFmpeg check failed: {str(e)}")
        return False

def get_force_ssd_dir():
    """为14900K+4080配置优化：使用最快SSD"""
    # 优先检查企业级SSD (PCIe 4.0)
    drives = ["S", "T", "R", "D", "E"]  # 假设S/T/R为高速NVMe
    best_speed = 0
    best_drive = None
    
    for d in drives:
        root = f"{d}:\\"
        if os.path.exists(root):
            try:
                # 检查可用空间 (>50GB)
                usage = shutil.disk_usage(root)
                if usage.free > 50 * 1024**3:
                    # 简单速度测试 (创建1GB测试文件)
                    test_file = os.path.join(root, "speed_test.tmp")
                    start = time.time()
                    with open(test_file, 'wb') as f:
                        f.write(os.urandom(1024 * 1024 * 100))  # 100MB
                    elapsed = time.time() - start
                    speed = 100 / elapsed  # MB/s
                    
                    if speed > best_speed:
                        best_speed = speed
                        best_drive = root
                    
                    # 清理测试文件
                    os.remove(test_file)
            except Exception as e:
                print(f"Drive {d} test failed: {str(e)}")
    
    # 默认使用D盘 (通常为第二块高速SSD)
    if not best_drive:
        best_drive = "D:\\" if os.path.exists("D:\\") else "C:\\"
    
    path = os.path.join(best_drive, "_ULTRA_TEMP_CACHE_")
    os.makedirs(path, exist_ok=True)
    
    # 设置为TEMP目录 (优化NVMe寿命)
    os.environ["TEMP"] = path
    os.environ["TMP"] = path
    
    return path

# === 高性能组件 ===
class InfinityScope(ctk.CTkCanvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=COLOR_PANEL_RIGHT, highlightthickness=0, **kwargs)
        self.points = deque(maxlen=300)  # 限制历史点数
        self.max_val = 10.0
        self.bind("<Configure>", self.draw)
        
    def add_point(self, val):
        self.points.append(val)
        self.draw()
        
    def clear(self):
        self.points.clear()
        self.max_val = 10.0
        self.delete("all")
        
    def draw(self, event=None):
        self.delete("all")
        if not self.points: 
            return
            
        w = self.winfo_width()
        h = self.winfo_height()
        
        if w < 10 or h < 10:
            return
            
        data_max = max(self.points) if self.points else 10
        target_max = max(data_max * 1.2, 10.0)
        
        # 平滑缩放
        if target_max > self.max_val:
            self.max_val = min(target_max, self.max_val * 1.1)
        else:
            self.max_val = max(target_max, self.max_val * 0.99)
        
        scale_y = (h - 20) / self.max_val if self.max_val > 0 else 1
        
        # 中心线
        self.create_line(0, h/2, w, h/2, fill="#2a2a2a", dash=(4,4))
        
        if len(self.points) < 2:
            return
            
        # 优化绘图性能
        coords = []
        step_x = w / (len(self.points) - 1) if len(self.points) > 1 else 1
        
        for i, val in enumerate(self.points):
            x = i * step_x
            y = h - 10 - (val * scale_y)
            coords.extend([x, y])
        
        if len(coords) >= 4:
            self.create_line(coords, fill=COLOR_CHART_LINE, width=2, smooth=True)

class MonitorChannel(ctk.CTkFrame):
    def __init__(self, master, ch_id, **kwargs):
        super().__init__(master, fg_color="#181818", corner_radius=10, border_width=1, border_color="#333", **kwargs)
        head = ctk.CTkFrame(self, fg_color="transparent", height=25)
        head.pack(fill="x", padx=15, pady=(10,0))
        self.lbl_title = ctk.CTkLabel(head, text=f"GPU 通道 {ch_id} · 空闲", font=("微软雅黑", 12, "bold"), text_color="#555")
        self.lbl_title.pack(side="left")
        self.lbl_info = ctk.CTkLabel(head, text="RTX 4080 | NVENC", font=("Arial", 11), text_color="#444")
        self.lbl_info.pack(side="right")
        self.scope = InfinityScope(self)
        self.scope.pack(fill="both", expand=True, padx=2, pady=5)
        btm = ctk.CTkFrame(self, fg_color="transparent")
        btm.pack(fill="x", padx=15, pady=(0,10))
        self.lbl_fps = ctk.CTkLabel(btm, text="0", font=("Impact", 20), text_color="#333")
        self.lbl_fps.pack(side="left")
        ctk.CTkLabel(btm, text="FPS", font=("Arial", 10, "bold"), text_color="#444").pack(side="left", padx=(5,0), pady=(8,0))
        self.lbl_eta = ctk.CTkLabel(btm, text="ETA: --:--", font=("Consolas", 12), text_color="#666")
        self.lbl_eta.pack(side="right", padx=(10, 0))
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 14, "bold"), text_color="#333")
        self.lbl_prog.pack(side="right")

    def activate(self, filename, tag):
        self.lbl_title.configure(text=f"4080: {filename[:20]}...", text_color=COLOR_ACCENT)
        self.lbl_info.configure(text=tag, text_color="#AAA")
        self.lbl_fps.configure(text_color="#FFF")
        self.lbl_prog.configure(text_color=COLOR_ACCENT)
        self.lbl_eta.configure(text_color=COLOR_SUCCESS)
        self.scope.clear()

    def update_data(self, fps, prog, eta):
        self.scope.add_point(fps)
        self.lbl_fps.configure(text=f"{fps:.1f}")
        self.lbl_prog.configure(text=f"{int(prog*100)}%")
        self.lbl_eta.configure(text=f"ETA: {eta}")

    def reset(self):
        self.lbl_title.configure(text="GPU 通道 · 空闲", text_color="#555")
        self.lbl_info.configure(text="RTX 4080 | NVENC", text_color="#444")
        self.lbl_fps.configure(text="0", text_color="#333")
        self.lbl_prog.configure(text="0%", text_color="#333")
        self.lbl_eta.configure(text="ETA: --:--", text_color="#333")
        self.scope.clear()

class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=10, border_width=0, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self.status_code = STATUS_WAIT 
        self.filepath = filepath
        
        ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 20), text_color="#555").grid(row=0, column=0, rowspan=2, padx=15)
        filename = os.path.basename(filepath)
        ctk.CTkLabel(self, text=filename[:35] + "..." if len(filename) > 35 else filename, 
                    font=("微软雅黑", 12, "bold"), text_color="#EEE", anchor="w").grid(row=0, column=1, sticky="w", padx=5, pady=(8,0))
        self.lbl_status = ctk.CTkLabel(self, text="等待处理", font=("Arial", 10), text_color="#888", anchor="w")
        self.lbl_status.grid(row=1, column=1, sticky="w", padx=5, pady=(0,8))
        self.progress = ctk.CTkProgressBar(self, height=4, corner_radius=0, progress_color=COLOR_ACCENT, fg_color="#444")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=(0,5))

    def set_status(self, text, color="#888", code=None):
        try:
            if self.winfo_exists():
                self.lbl_status.configure(text=text, text_color=color)
                if code is not None: 
                    self.status_code = code
        except: 
            pass
    
    def set_progress(self, val, color=COLOR_ACCENT):
        try:
            if self.winfo_exists():
                self.progress.set(val)
                self.progress.configure(progress_color=color)
        except: 
            pass

# === 高性能主程序 (针对14900K+4080+64GB优化) ===
class UltraEncoderApp(DnDWindow):
    def __init__(self):
        super().__init__()
        
        self.title("Ultra Encoder v36 - 14900K+4080 Optimized Edition")
        self.geometry("1400x950")
        self.configure(fg_color=COLOR_BG_MAIN)
        self.minsize(1300, 900) 
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 14900K+4080专属配置
        self.MAX_WORKERS = 8  # 14900K 32线程 + 4080 8路NVENC
        self.MAX_CACHE_GB = 32  # 64GB内存分配32GB给缓存
        self.GPU_THREADS = 4  # 4080最佳并发数
        
        # 任务管理
        self.file_queue = [] 
        self.task_widgets = {}
        self.task_data = {}  # 新增: {filepath: {status, cache_data, ...}}
        self.active_procs = []
        self.temp_files = set()
        self.running = False
        self.stop_flag = threading.Event()  # 使用Event替代布尔值
        
        # 同步原语
        self.queue_lock = threading.Lock() 
        self.slot_semaphore = threading.Semaphore(self.GPU_THREADS)  # GPU槽位信号量
        self.io_lock = threading.Lock() 
        self.cache_lock = threading.Lock()
        self.move_lock = threading.Lock()  # 专属移动锁
        
        # 系统状态
        self.active_moves = 0 
        self.monitor_slots = []
        self.temp_dir = ""
        self.memory_cache = {}  # 内存缓存: {filepath: bytes}
        self.cache_size = 0  # 当前缓存大小(GB)
        
        # UI状态
        self.ui_update_queue = deque(maxlen=100)  # UI更新队列
        self.last_ui_update = 0
        
        self.setup_ui()
        self.after(200, self.sys_check)
        self.apply_system_priority("极速")  # 14900K专属
        
        # 启动UI更新线程
        self.ui_thread = threading.Thread(target=self.ui_update_worker, daemon=True)
        self.ui_thread.start()
        
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    # === [修复] 拖拽功能 ===
    def drop_file(self, event):
        files = self.tk.splitlist(event.data)
        self.add_list(files)

    def add_list(self, files):
        valid_files = []
        with self.queue_lock:
            for f in files:
                f = os.path.normpath(f)
                if (f not in self.file_queue and 
                    f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.mpg', '.mpeg', '.flv', '.webm')) and
                    os.path.exists(f)):
                    self.file_queue.append(f)
                    valid_files.append(f)
            
            # 创建UI卡片
            start_idx = len(self.file_queue) - len(valid_files) + 1
            for i, f in enumerate(valid_files, start=start_idx):
                card = TaskCard(self.scroll, i, f)
                card.pack(fill="x", pady=4, padx=5) 
                self.task_widgets[f] = card
                self.task_data[f] = {
                    'status': STATUS_WAIT,
                    'cache': None,
                    'orig_size': os.path.getsize(f)
                }
        
        if valid_files:
            self.set_status_bar(f"已添加 {len(valid_files)} 个文件到队列")

    # === [修复] 系统优先级 ===
    def apply_system_priority(self, level):
        mapping = {
            "常规": PRIORITY_NORMAL,
            "优先": PRIORITY_ABOVE,
            "极速": PRIORITY_HIGH  # 14900K专属
        }
        p_val = mapping.get(level, PRIORITY_HIGH)
        try:
            pid = os.getpid()
            handle = ctypes.windll.kernel32.OpenProcess(0x0200 | 0x0100, False, pid)  # PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION
            ctypes.windll.kernel32.SetPriorityClass(handle, p_val)
            ctypes.windll.kernel32.CloseHandle(handle)
            self.set_status_bar(f"性能模式: {level} (14900K+4080优化)")
        except Exception as e:
            print(f"Set priority failed: {str(e)}")

    # === [修复] 安全退出 ===
    def on_closing(self):
        if self.running:
            if not messagebox.askokcancel("退出", "任务正在进行中，确定要退出？\n(将安全停止所有任务)"):
                return
        
        # 触发停止
        self.stop_flag.set()
        self.running = False
        
        # 等待活动任务完成
        for p in self.active_procs:
            try:
                p.terminate()
                p.wait(timeout=2.0)
            except:
                try:
                    p.kill()
                except:
                    pass
        
        # 释放内存缓存
        with self.cache_lock:
            self.memory_cache.clear()
            self.cache_size = 0
        
        # 清理临时文件
        self.clean_junk()
        
        # 停止UI线程
        self.ui_update_queue.append(None)
        
        # 保存配置
        self.save_config()
        
        self.destroy()
        os._exit(0)

    # === [修复] 系统检查 ===
    def sys_check(self):
        if not check_ffmpeg():
            messagebox.showerror("错误", "找不到 FFmpeg！\n请将ffmpeg.exe放入系统PATH或程序目录")
            self.btn_run.configure(state="disabled")
            return
        
        # 检查GPU编码能力
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            has_nvenc = "hevc_nvenc" in result.stdout and "h264_nvenc" in result.stdout
            if not has_nvenc:
                messagebox.showwarning("警告", "未检测到NVIDIA NVENC编码器!\n将使用CPU编码(速度大幅下降)")
        except:
            pass
        
        # 初始化缓存目录
        threading.Thread(target=self.init_cache_system, daemon=True).start()
        
        # 预加载配置
        self.load_config()

    def init_cache_system(self):
        """14900K+4080专属: 初始化超高速缓存"""
        path = get_force_ssd_dir()
        self.temp_dir = path
        
        # 预分配缓存空间 (32GB)
        try:
            test_file = os.path.join(path, "prealloc.tmp")
            with open(test_file, 'wb') as f:
                f.seek(32 * 1024**3 - 1)  # 32GB
                f.write(b'\0')
            os.remove(test_file)
            self.after(0, lambda: self.set_status_bar(f"缓存系统初始化完成 (32GB @ {os.path.basename(path)}:)"))
        except Exception as e:
            print(f"Preallocation failed: {str(e)}")
            self.after(0, lambda: self.set_status_bar(f"缓存系统就绪 (空间受限)"))
        
        # 更新UI
        self.after(0, lambda: self.btn_cache.configure(text=f"⚡️ 4080 Cache: {path}"))

    # === [修复] 配置管理 ===
    def save_config(self):
        config = {
            "crf": self.crf_var.get(),
            "codec": self.codec_var.get(),
            "workers": self.worker_var.get(),
            "gpu_enabled": self.gpu_var.get(),
            "priority": self.priority_var.get()
        }
        try:
            with open("ultra_encoder_config.json", "w") as f:
                json.dump(config, f)
        except:
            pass

    def load_config(self):
        try:
            if os.path.exists("ultra_encoder_config.json"):
                with open("ultra_encoder_config.json", "r") as f:
                    config = json.load(f)
                
                self.crf_var.set(config.get("crf", 23))
                self.codec_var.set(config.get("codec", "H.264"))
                self.worker_var.set(str(config.get("workers", 4)))
                self.gpu_var.set(config.get("gpu_enabled", True))
                self.priority_var.set(config.get("priority", "极速"))
                
                # 应用配置
                self.apply_system_priority(self.priority_var.get())
                self.update_monitor_layout()
                
                self.set_status_bar("配置已加载")
        except Exception as e:
            print(f"Load config failed: {str(e)}")

    # === UI设置 ===
    def setup_ui(self):
        self.grid_columnconfigure(0, weight=0, minsize=350) 
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 左侧面板 (任务队列)
        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0, width=350)
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)
        
        l_head = ctk.CTkFrame(left, fg_color="transparent")
        l_head.pack(fill="x", padx=20, pady=(25, 10))
        ctk.CTkLabel(l_head, text="ULTRA ENCODER 4080", font=("Impact", 28, "bold"), text_color="#3B8ED0").pack(anchor="w")
        ctk.CTkLabel(l_head, text="i9-14900K • RTX 4080 • 64GB RAM", 
                    font=("Arial", 11), text_color="#777").pack(anchor="w", pady=(2,0))
        
        self.btn_cache = ctk.CTkButton(left, text="初始化缓存...", fg_color="#252525", hover_color="#333", 
                                     text_color=COLOR_TEMP_CACHE, font=("Consolas", 11, "bold"), height=30, corner_radius=14, 
                                     command=self.open_cache)
        self.btn_cache.pack(fill="x", padx=20, pady=(5, 10))
        
        # 工具栏
        tools = ctk.CTkFrame(left, fg_color="transparent")
        tools.pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(tools, text="📁 导入文件", width=130, height=40, corner_radius=20, 
                     fg_color="#333", hover_color="#444", font=("微软雅黑", 11, "bold"),
                     command=self.add_file).pack(side="left", padx=5)
        ctk.CTkButton(tools, text="🗑️ 清空队列", width=100, height=40, corner_radius=20, 
                     fg_color="transparent", border_width=1, border_color="#553333", hover_color="#331111", 
                     text_color="#FF6B6B", font=("微软雅黑", 11, "bold"),
                     command=self.clear_all).pack(side="left", padx=5)

        # 底部控制面板
        l_btm = ctk.CTkFrame(left, fg_color="#222", corner_radius=20)
        l_btm.pack(side="bottom", fill="x", padx=15, pady=20, ipadx=5, ipady=10)
        
        # 性能模式
        rowP = ctk.CTkFrame(l_btm, fg_color="transparent")
        rowP.pack(fill="x", pady=(10, 5), padx=10)
        ctk.CTkLabel(rowP, text="⚡ 系统性能模式", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        self.priority_var = ctk.StringVar(value="极速")
        self.seg_priority = ctk.CTkSegmentedButton(
            rowP, 
            values=["常规", "优先", "极速"], 
            variable=self.priority_var, 
            command=self.apply_system_priority,
            selected_color="#FF6B6B",
            selected_hover_color="#FF5252",
            unselected_color="#333",
            unselected_hover_color="#444",
            corner_radius=10
        )
        self.seg_priority.pack(fill="x", pady=(5, 0))

        # 并发控制
        row3 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row3.pack(fill="x", pady=(15, 5), padx=10)
        ctk.CTkLabel(row3, text="ParallelGroup (4080)", font=("微软雅黑", 13, "bold"), text_color="#DDD").pack(anchor="w")
        w_box = ctk.CTkFrame(row3, fg_color="transparent")
        w_box.pack(fill="x")
        self.worker_var = ctk.StringVar(value="4")  # 4080最佳值
        self.seg_worker = ctk.CTkSegmentedButton(
            w_box, 
            values=["2", "3", "4", "5", "6"],  # 4080最优范围
            variable=self.worker_var, 
            command=self.update_monitor_layout,
            selected_color="#3B8ED0",
            corner_radius=10
        )
        self.seg_worker.pack(side="left", fill="x", expand=True)
        self.gpu_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            w_box, 
            text="NVENC", 
            width=70, 
            variable=self.gpu_var, 
            progress_color="#3498db",
            button_color="#2980b9",
            font=("Arial", 11, "bold")
        ).pack(side="right", padx=(10,0))

        # 画质控制
        row2 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row2.pack(fill="x", pady=(15, 5), padx=10)
        ctk.CTkLabel(row2, text="🎨 画质 (CRF) • 4080优化", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        c_box = ctk.CTkFrame(row2, fg_color="transparent")
        c_box.pack(fill="x")
        self.crf_var = ctk.IntVar(value=20)  # 4080推荐值
        crf_slider = ctk.CTkSlider(
            c_box, 
            from_=0, 
            to=51, 
            variable=self.crf_var, 
            progress_color="#2ECC71",
            button_color="#27AE60",
            command=lambda v: self.crf_var.set(int(float(v)))
        )
        crf_slider.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            c_box, 
            textvariable=self.crf_var, 
            width=30, 
            font=("Arial", 14, "bold"), 
            text_color="#2ECC71"
        ).pack(side="right", padx=(5,0))
        
        # 编码格式
        row1 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row1.pack(fill="x", pady=(10, 5), padx=10)
        ctk.CTkLabel(row1, text="_CODEC • 4080加速", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        self.codec_var = ctk.StringVar(value="H.265")
        self.seg_codec = ctk.CTkSegmentedButton(
            row1, 
            values=["H.264", "H.265"], 
            variable=self.codec_var, 
            selected_color="#9B59B6",
            corner_radius=10
        )
        self.seg_codec.pack(fill="x", pady=(5, 0))

        # 启动/停止按钮
        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=20, pady=(0, 20))
        self.btn_run = ctk.CTkButton(
            btn_row, 
            text="🚀 启动4080引擎", 
            height=50, 
            corner_radius=25, 
            font=("微软雅黑", 16, "bold"), 
            fg_color="#FF6B6B", 
            hover_color="#FF5252", 
            text_color="#000",
            command=self.run
        )
        self.btn_run.pack(side="left", fill="x", expand=True, padx=(0, 10)) 
        self.btn_stop = ctk.CTkButton(
            btn_row, 
            text="🛑 停止", 
            height=50, 
            corner_radius=25, 
            width=100,
            fg_color="transparent", 
            border_width=2, 
            border_color="#FF6B6B", 
            text_color="#FF6B6B", 
            hover_color="#331111", 
            state="disabled", 
            command=self.stop
        )
        self.btn_stop.pack(side="right")

        # 滚动区域
        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # 监控面板 (右侧)
        right = ctk.CTkFrame(self, fg_color=COLOR_PANEL_RIGHT, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        
        # 顶部状态栏
        r_head = ctk.CTkFrame(right, fg_color="transparent")
        r_head.pack(fill="x", padx=30, pady=(25, 10))
        ctk.CTkLabel(r_head, text="GPU MONITOR • RTX 4080", font=("Impact", 22, "bold"), text_color="#3498db").pack(side="left")
        self.lbl_global_status = ctk.CTkLabel(r_head, text="状态: 就绪 (14900K+4080)", font=("微软雅黑", 11), text_color="#555")
        self.lbl_global_status.pack(side="right")
        
        # 监控框架
        self.monitor_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.monitor_frame.pack(fill="both", expand=True, padx=25, pady=(0, 25))
        
        # 初始化监控通道
        self.update_monitor_layout()

    # === [修复] 监控布局 ===
    def update_monitor_layout(self, val=None):
        """根据4080能力动态调整监控通道"""
        if self.running:
            self.seg_worker.set(str(self.GPU_THREADS))
            return
            
        # 获取新值
        try:
            n = int(self.worker_var.get())
        except:
            n = 4  # 4080推荐值
            
        # 限制在4080能力范围内
        n = max(2, min(n, 6))  # 4080最佳范围2-6
        
        # 重置信号量
        self.GPU_THREADS = n
        self.slot_semaphore = threading.Semaphore(n)
        
        # 重建UI
        for ch in self.monitor_slots:
            ch.destroy()
        self.monitor_slots.clear()
        
        for i in range(n):
            ch = MonitorChannel(self.monitor_frame, i+1)
            ch.pack(fill="both", expand=True, pady=8, padx=5)
            self.monitor_slots.append(ch)
            
        self.set_status_bar(f"GPU通道已配置: {n}路 (RTX 4080优化)")

    # === [修复] UI更新线程 ===
    def ui_update_worker(self):
        """专用UI更新线程，避免主线程阻塞"""
        while True:
            if not self.ui_update_queue:
                time.sleep(0.016)  # ~60fps
                continue
                
            item = self.ui_update_queue.popleft()
            if item is None:  # 退出信号
                break
                
            # 限流: 每秒最多60次更新
            now = time.time()
            if now - self.last_ui_update < 0.016:
                self.ui_update_queue.appendleft(item)  # 放回队列
                time.sleep(0.001)
                continue
                
            self.last_ui_update = now
            
            try:
                # 执行UI更新
                if callable(item):
                    item()
            except Exception as e:
                print(f"UI update error: {str(e)}")
                
            time.sleep(0.001)  # 让出CPU

    def queue_ui_update(self, func):
        """安全的UI更新队列"""
        if not self.stop_flag.is_set():
            self.ui_update_queue.append(func)

    # === [修复] 内存缓存系统 (14900K 64GB专属) ===
    async def preload_file_async(self, filepath, card):
        """异步预读文件到内存 (64GB RAM优化)"""
        if self.stop_flag.is_set() or not os.path.exists(filepath):
            return False
            
        file_size = os.path.getsize(filepath)
        cache_gb = file_size / (1024**3)
        
        # 检查缓存空间
        with self.cache_lock:
            if self.cache_size + cache_gb > self.MAX_CACHE_GB:
                # 清理旧缓存 (LRU策略)
                to_remove = []
                for f, data in self.memory_cache.items():
                    if f not in self.file_queue or self.task_data[f]['status'] in [STATUS_DONE, STATUS_ERR]:
                        to_remove.append(f)
                        self.cache_size -= len(data) / (1024**3)
                
                for f in to_remove:
                    self.memory_cache.pop(f, None)
            
            # 二次检查
            if self.cache_size + cache_gb > self.MAX_CACHE_GB:
                self.queue_ui_update(lambda: card.set_status("等待缓存空间", COLOR_PAUSED, STATUS_WAIT))
                return False
            
            # 标记正在缓存
            self.task_data[filepath]['status'] = STATUS_READ
        
        # 更新UI
        self.queue_ui_update(lambda: card.set_status("💿 高速缓存中...", COLOR_READING, STATUS_READ))
        
        try:
            # 异步读取大文件
            async with aiofiles.open(filepath, 'rb') as f:
                data = await f.read()
                
            # 检查是否被中断
            if self.stop_flag.is_set():
                return False
                
            # 更新缓存
            with self.cache_lock:
                self.memory_cache[filepath] = data
                self.cache_size += cache_gb
                self.task_data[filepath]['cache'] = data
                self.task_data[filepath]['status'] = STATUS_READY
            
            # 更新UI
            self.queue_ui_update(lambda: [
                card.set_status("✅ 缓存就绪 (RAM)", COLOR_SUCCESS, STATUS_READY),
                card.set_progress(1, COLOR_SUCCESS)
            ])
            
            return True
            
        except Exception as e:
            print(f"Preload failed for {filepath}: {str(e)}")
            with self.cache_lock:
                self.task_data[filepath]['status'] = STATUS_WAIT
            self.queue_ui_update(lambda: [
                card.set_status(f"缓存失败: {str(e)[:30]}...", COLOR_ERROR, STATUS_ERR),
                card.set_progress(0)
            ])
            return False

    def preload_worker(self):
        """预读工作线程 (14900K 64GB优化)"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while not self.stop_flag.is_set():
            if not self.running or self.stop_flag.is_set():
                time.sleep(0.5)
                continue
                
            # 检查空闲内存
            free_ram = get_free_ram_gb()
            if free_ram < 24:  # 保留24GB给系统
                time.sleep(1)
                continue
                
            # 查找待缓存任务
            task_found = False
            with self.queue_lock:
                for filepath in self.file_queue:
                    card = self.task_widgets.get(filepath)
                    if not card or self.task_data[filepath]['status'] != STATUS_WAIT:
                        continue
                    
                    # 获取文件信息
                    if filepath not in self.task_data:
                        self.task_data[filepath] = {
                            'status': STATUS_WAIT,
                            'orig_size': os.path.getsize(filepath)
                        }
                    
                    # 检查文件大小限制 (最大16GB)
                    file_size = self.task_data[filepath]['orig_size']
                    if file_size > 16 * 1024**3:
                        self.queue_ui_update(lambda f=filepath, c=card: [
                            c.set_status(f"文件过大 (>16GB)", COLOR_ERROR, STATUS_ERR),
                            self.task_data[f].update({'status': STATUS_ERR})
                        ])
                        continue
                    
                    # 启动异步预读
                    task_found = True
                    asyncio.run_coroutine_threadsafe(
                        self.preload_file_async(filepath, card), 
                        loop
                    )
                    break
            
            if not task_found:
                time.sleep(0.3)
        
        loop.close()

    # === [修复] 主引擎 ===
    def engine(self):
        """14900K+4080专属任务引擎"""
        self.stop_flag.clear()
        
        # 初始化槽位
        for i in range(self.GPU_THREADS):
            self.available_indices.append(i)
        
        # 创建固定线程池 (14900K 32线程优化)
        with ThreadPoolExecutor(
            max_workers=self.MAX_WORKERS,
            thread_name_prefix="EncoderWorker"
        ) as executor:
            futures = []
            
            while not self.stop_flag.is_set():
                # 检查待处理任务
                tasks_to_run = []
                with self.queue_lock:
                    for filepath in self.file_queue:
                        status = self.task_data[filepath]['status']
                        if status in [STATUS_READY, STATUS_WAIT] and len(tasks_to_run) < self.GPU_THREADS:
                            tasks_to_run.append(filepath)
                
                # 提交新任务
                for filepath in tasks_to_run:
                    # 等待GPU槽位
                    if not self.slot_semaphore.acquire(timeout=0.1):
                        break
                    
                    # 检查预读状态
                    if self.task_data[filepath]['status'] == STATUS_WAIT:
                        # 同步读取 (小文件)
                        self.queue_ui_update(lambda f=filepath: self.task_widgets[f].set_status("读取中...", COLOR_READING, STATUS_READ))
                        try:
                            with open(filepath, 'rb') as f:
                                data = f.read()
                            with self.cache_lock:
                                self.memory_cache[filepath] = data
                                self.cache_size += len(data) / (1024**3)
                                self.task_data[filepath]['cache'] = data
                                self.task_data[filepath]['status'] = STATUS_READY
                        except Exception as e:
                            self.queue_ui_update(lambda f=filepath, e=e: [
                                self.task_widgets[f].set_status(f"读取失败: {str(e)[:30]}...", COLOR_ERROR, STATUS_ERR),
                                self.task_data[f].update({'status': STATUS_ERR})
                            ])
                            self.slot_semaphore.release()
                            continue
                    
                    # 提交任务
                    future = executor.submit(self.process, filepath)
                    futures.append(future)
                
                # 清理完成的任务
                done_futures = [f for f in futures if f.done()]
                for future in done_futures:
                    futures.remove(future)
                    try:
                        future.result()
                    except Exception as e:
                        print(f"Task failed: {str(e)}")
                
                # 退出检查
                if not tasks_to_run and all(f.done() for f in futures):
                    break
                
                time.sleep(0.01)  # 减少CPU占用
        
        # 任务完成处理
        if not self.stop_flag.is_set():
            self.queue_ui_update(lambda: [
                messagebox.showinfo("完成", "所有任务已完成!"),
                self.reset_ui_state()
            ])

    # === [修复] 处理函数 ===
    def process(self, input_file):
        """处理单个文件 (4080优化)"""
        if self.stop_flag.is_set():
            return
            
        # 获取槽位索引
        slot_idx = -1
        for i in range(self.GPU_THREADS):
            if i in self.available_indices:
                slot_idx = i
                self.available_indices.remove(i)
                break
        
        if slot_idx == -1 or slot_idx >= len(self.monitor_slots):
            self.slot_semaphore.release()
            return
            
        try:
            card = self.task_widgets[input_file]
            ch_ui = self.monitor_slots[slot_idx]
            
            # UI更新
            self.queue_ui_update(lambda: [
                card.set_status("▶️ 4080压制中...", COLOR_ACCENT, STATUS_RUN),
                card.set_progress(0, COLOR_ACCENT),
                ch_ui.activate(os.path.basename(input_file), self.get_codec_tag())
            ])
            
            # 准备输出路径
            fname = os.path.basename(input_file)
            name, ext = os.path.splitext(fname)
            suffix = "_4080_H265" if "H.265" in self.codec_var.get() else "_4080_H264"
            temp_out = os.path.join(self.temp_dir, f"TMP_{name}{suffix}.mp4")
            final_out = os.path.join(os.path.dirname(input_file), f"{name}{suffix}.mp4")
            
            # 添加到临时文件集
            with self.io_lock:
                self.temp_files.add(temp_out)
            
            # 构建FFmpeg命令 (4080优化参数)
            cmd = self.build_ffmpeg_command(input_file, temp_out)
            
            # 执行压制
            start_t = time.time()
            duration = self.get_duration(input_file)
            last_update = 0
            fps_history = deque(maxlen=10)
            
            try:
                # 14900K专属: 设置进程亲和性
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0
                
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    encoding='utf-8',
                    errors='ignore',
                    startupinfo=si,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                
                self.active_procs.append(proc)
                
                # 实时监控
                while True:
                    line = proc.stdout.readline()
                    if not line and proc.poll() is not None:
                        break
                    
                    if self.stop_flag.is_set():
                        proc.terminate()
                        break
                    
                    # 解析进度
                    if "time=" in line and duration > 0:
                        time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                        fps_match = re.search(r"fps=\s*(\d+\.?\d*)", line)
                        
                        if time_match:
                            h, m, s = map(float, time_match.groups())
                            current_time = h * 3600 + m * 60 + s
                            progress = current_time / duration if duration > 0 else 0
                            
                            # 计算FPS
                            fps = float(fps_match.group(1)) if fps_match else 0.0
                            fps_history.append(fps)
                            avg_fps = sum(fps_history) / len(fps_history) if fps_history else 0
                            
                            # ETA计算
                            elapsed = time.time() - start_t
                            eta = "--:--"
                            if progress > 0.01 and elapsed > 1:
                                total_est = elapsed / progress
                                remaining = total_est - elapsed
                                eta = f"{int(remaining//60):02d}:{int(remaining%60):02d}"
                            
                            # 限流更新 (每100ms)
                            if time.time() - last_update > 0.1:
                                last_update = time.time()
                                self.queue_ui_update(partial(
                                    self.update_task_ui,
                                    card=card,
                                    ch_ui=ch_ui,
                                    progress=progress,
                                    fps=avg_fps,
                                    eta=eta
                                ))
                
                # 等待完成
                proc.wait(timeout=10)
                success = (proc.returncode == 0 and not self.stop_flag.is_set())
                
            except Exception as e:
                print(f"Processing error: {str(e)}")
                success = False
            finally:
                if proc in self.active_procs:
                    self.active_procs.remove(proc)
            
            # 处理结果
            if success and os.path.exists(temp_out):
                # 启动移动线程
                threading.Thread(
                    target=self.move_worker,
                    args=(temp_out, final_out, card, input_file),
                    daemon=True
                ).start()
            else:
                # 清理失败文件
                try:
                    if os.path.exists(temp_out):
                        os.remove(temp_out)
                except:
                    pass
                
                self.queue_ui_update(lambda: [
                    card.set_status("❌ 压制失败", COLOR_ERROR, STATUS_ERR),
                    ch_ui.reset()
                ])
        
        finally:
            # 释放槽位
            with self.queue_lock:
                if slot_idx not in self.available_indices:
                    self.available_indices.append(slot_idx)
                    self.available_indices.sort()
            self.slot_semaphore.release()

    def update_task_ui(self, card, ch_ui, progress, fps, eta):
        """安全的UI更新函数"""
        if card.winfo_exists() and ch_ui.winfo_exists():
            card.set_progress(progress, COLOR_ACCENT)
            ch_ui.update_data(fps, progress, eta)

    def get_codec_tag(self):
        """获取编码标签"""
        codec = self.codec_var.get()
        gpu = "NVENC" if self.gpu_var.get() else "CPU"
        return f"{'HEVC' if 'H.265' in codec else 'AVC'} | {gpu} | CRF{self.crf_var.get()}"

    def build_ffmpeg_command(self, input_file, output_file):
        """构建4080优化的FFmpeg命令"""
        codec = "hevc_nvenc" if "H.265" in self.codec_var.get() else "h264_nvenc"
        crf = self.crf_var.get()
        
        # 4080专属优化参数
        return [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",  # 启用CUDA加速
            "-hwaccel_output_format", "cuda",
            "-i", input_file,
            "-c:v", codec,
            "-preset", "p7",  # 4080最佳性能
            "-tune", "hq",    # 高质量
            "-rc", "vbr",
            "-b_ref_mode", "2",  # 双向参考
            "-spatial_aq", "1",  # 空域AQ
            "-temporal_aq", "1", # 时域AQ
            "-cq", str(crf),
            "-rc-lookahead", "32",  # 32帧前瞻
            "-surfaces", "64",      # 64个编码表面
            "-profile:v", "main10" if "H.265" in self.codec_var.get() else "high",
            "-pix_fmt", "p010le" if "H.265" in self.codec_var.get() else "yuv420p",
            "-c:a", "copy",  # 音频直通
            "-movflags", "+faststart",  # 网页优化
            output_file
        ]

    def get_duration(self, file_path):
        """获取视频时长"""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    file_path
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return float(result.stdout.strip())
        except:
            return 0

    # === [修复] 安全移动 ===
    def move_worker(self, temp_out, final_out, card, orig_file):
        """安全移动文件 (防损坏)"""
        if self.stop_flag.is_set():
            return
            
        # 事务性移动
        temp_final = final_out + ".tmp"
        success = False
        
        try:
            with self.move_lock:  # 专属移动锁
                self.active_moves += 1
                
                # 更新UI
                self.queue_ui_update(lambda: [
                    card.set_status("🚚 移动中 (安全事务)...", COLOR_MOVING, STATUS_MOVE),
                    card.set_progress(0, COLOR_MOVING)
                ])
                
                # 1. 复制到临时位置
                shutil.copy2(temp_out, temp_final)
                
                # 2. 验证文件完整性
                if os.path.getsize(temp_final) < os.path.getsize(temp_out) * 0.95:
                    raise Exception("文件大小验证失败")
                
                # 3. 原子重命名
                if os.path.exists(final_out):
                    backup = final_out + ".bak"
                    if os.path.exists(backup):
                        os.remove(backup)
                    os.rename(final_out, backup)
                
                os.rename(temp_final, final_out)
                success = True
                
                # 4. 清理缓存
                with self.cache_lock:
                    if orig_file in self.memory_cache:
                        cache_size_gb = len(self.memory_cache[orig_file]) / (1024**3)
                        self.cache_size -= cache_size_gb
                        del self.memory_cache[orig_file]
                    self.task_data[orig_file]['cache'] = None
                
        except Exception as e:
            print(f"Move failed: {str(e)}")
            # 回滚备份
            if os.path.exists(backup) and not os.path.exists(final_out):
                try:
                    os.rename(backup, final_out)
                except:
                    pass
            success = False
        finally:
            # 清理临时文件
            try:
                if os.path.exists(temp_out):
                    os.remove(temp_out)
                if os.path.exists(temp_final) and os.path.exists(final_out):
                    os.remove(temp_final)
                if success and os.path.exists(backup):
                    os.remove(backup)
            except:
                pass
            
            with self.io_lock:
                self.temp_files.discard(temp_out)
            
            with self.move_lock:
                self.active_moves -= 1
            
            # 更新UI
            if not self.stop_flag.is_set():
                if success:
                    orig_size = self.task_data[orig_file]['orig_size']
                    new_size = os.path.getsize(final_out)
                    save_percent = 100 - (new_size / orig_size * 100) if orig_size > 0 else 0
                    
                    self.queue_ui_update(lambda: [
                        card.set_status(f"✅ 完成 | 4080压制 | 节省: {save_percent:.1f}%", COLOR_SUCCESS, STATUS_DONE),
                        card.set_progress(1, COLOR_SUCCESS),
                        self.monitor_slots[0].reset()  # 重置第一个通道
                    ])
                else:
                    self.queue_ui_update(lambda: [
                        card.set_status("❌ 移动失败 (已回滚)", COLOR_ERROR, STATUS_ERR),
                        card.set_progress(0)
                    ])

    # === 控制函数 ===
    def run(self):
        if not self.file_queue:
            messagebox.showinfo("提示", "请先添加视频文件!")
            return
            
        # 验证GPU编码
        if self.gpu_var.get():
            try:
                subprocess.run(
                    ["ffmpeg", "-hide_banner", "-encoders"],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except:
                if not messagebox.askyesno("警告", "未检测到NVIDIA驱动。继续使用CPU编码?"):
                    return
        
        # 重置状态
        self.stop_flag.clear()
        self.running = True
        self.btn_run.configure(state="disabled", text="4080运行中...")
        self.btn_stop.configure(state="normal")
        
        # 重置任务状态
        with self.queue_lock:
            for filepath in self.file_queue:
                if filepath in self.task_widgets:
                    self.task_data[filepath]['status'] = STATUS_WAIT
                    self.queue_ui_update(lambda f=filepath: self.task_widgets[f].set_status("等待处理", COLOR_TEXT_GRAY, STATUS_WAIT))
        
        # 启动工作线程
        threading.Thread(target=self.preload_worker, daemon=True, name="Preloader").start()
        threading.Thread(target=self.engine, daemon=True, name="Engine").start()
        
        self.set_status_bar("4080引擎已启动 - 充分利用14900K+64GB性能")

    def stop(self):
        """安全停止"""
        if not self.running:
            return
            
        self.set_status_bar("🛑 正在安全停止任务 (等待当前帧完成)...")
        self.stop_flag.set()
        
        # 更新UI
        self.queue_ui_update(lambda: [
            self.btn_run.configure(state="normal", text="启动4080引擎"),
            self.btn_stop.configure(state="disabled")
        ])
        
        # 重置任务状态
        with self.queue_lock:
            for filepath in self.file_queue:
                if filepath in self.task_widgets and self.task_data[filepath]['status'] in [STATUS_RUN, STATUS_READ]:
                    self.queue_ui_update(lambda f=filepath: self.task_widgets[f].set_status("🛑 已停止", COLOR_PAUSED, STATUS_WAIT))
        
        self.running = False

    def reset_ui_state(self):
        """重置UI状态"""
        self.btn_run.configure(state="normal", text="🚀 启动4080引擎")
        self.btn_stop.configure(state="disabled")
        self.running = False
        self.set_status_bar("✅ 所有任务完成 (14900K+4080)")

    # === 工具函数 ===
    def open_cache(self):
        """打开缓存目录"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            os.startfile(self.temp_dir)
        else:
            self.set_status_bar("缓存目录未初始化")

    def add_file(self):
        """添加文件"""
        f_list = filedialog.askopenfilenames(
            title="选择视频文件",
            filetypes=[
                ("视频文件", "*.mp4 *.mkv *.mov *.avi *.mpg *.mpeg *.flv *.webm"),
                ("所有文件", "*.*")
            ]
        )
        if f_list:
            self.add_list(f_list)

    def clear_all(self):
        """清空队列"""
        if self.running:
            messagebox.showwarning("警告", "请先停止运行中的任务!")
            return
            
        confirm = messagebox.askyesno("确认", "清空所有任务? (不会删除源文件)")
        if not confirm:
            return
            
        # 清理UI
        for widget in self.scroll.winfo_children():
            widget.destroy()
        
        # 重置数据
        self.file_queue.clear()
        self.task_widgets.clear()
        self.task_data.clear()
        
        # 释放内存
        with self.cache_lock:
            self.memory_cache.clear()
            self.cache_size = 0
        
        self.set_status_bar("✅ 队列已清空")

    def clean_junk(self):
        """清理垃圾文件"""
        cleaned = 0
        for f in list(self.temp_files):
            try:
                if os.path.exists(f):
                    os.remove(f)
                    cleaned += 1
            except Exception as e:
                print(f"Clean failed for {f}: {str(e)}")
        
        # 清理缓存目录
        if self.temp_dir and os.path.exists(self.temp_dir):
            for f in os.listdir(self.temp_dir):
                if f.startswith("TMP_") or f.endswith(".tmp"):
                    try:
                        fp = os.path.join(self.temp_dir, f)
                        if time.time() - os.path.getmtime(fp) > 3600:  # 1小时旧文件
                            os.remove(fp)
                            cleaned += 1
                    except:
                        pass
        
        if cleaned > 0:
            self.set_status_bar(f"🧹 清理了 {cleaned} 个临时文件")

    def set_status_bar(self, text):
        """设置状态栏"""
        if self.winfo_exists():
            self.queue_ui_update(lambda: self.lbl_global_status.configure(text=f"状态: {text}"))

if __name__ == "__main__":
    # 14900K专属: 设置高DPI支持
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
    
    app = UltraEncoderApp()
    app.mainloop()

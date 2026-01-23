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
from concurrent.futures import ThreadPoolExecutor

# === 全局配置与硬件适配 ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# 针对 64GB 内存环境的配置
MAX_RAM_LOAD_GB = 12.0  # 单个文件最大允许载入内存的大小 (GB)，Python处理超大对象效率低，建议不要设太大
SAFE_RAM_RESERVE = 8.0  # 保留给系统的最小内存 (GB)

COLOR_BG_MAIN = "#121212"
COLOR_PANEL_LEFT = "#1a1a1a"
COLOR_PANEL_RIGHT = "#0f0f0f"
COLOR_CARD = "#2d2d2d"
COLOR_ACCENT = "#3B8ED0"
COLOR_ACCENT_HOVER = "#36719f"
COLOR_CHART_LINE = "#00E676"
COLOR_SUCCESS = "#2ECC71"
COLOR_MOVING = "#F1C40F"
COLOR_READING = "#9B59B6"
COLOR_RAM     = "#3498DB"
COLOR_SSD_CACHE = "#E67E22"
COLOR_DIRECT  = "#1ABC9C"
COLOR_PAUSED = "#7f8c8d"
COLOR_ERROR = "#FF4757"

# 状态码
STATUS_WAIT = 0
STATUS_CACHING = 1
STATUS_READY = 2
STATUS_RUN = 3
STATUS_DONE = 5
STATUS_ERR = -1

# 优先级常量
PRIORITY_NORMAL = 0x00000020
PRIORITY_ABOVE = 0x00008000
PRIORITY_HIGH = 0x00000080

# 拖拽支持检测
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

# Windows 内存 API
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), 
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), 
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), 
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), 
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

def get_free_ram_gb():
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullAvailPhys / (1024**3)
    except: return 8.0 

def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except: return False

def get_force_ssd_dir():
    # 优先寻找非系统盘的最大剩余空间
    drives = ["D", "E", "F", "G", "C"]
    best = None
    max_free = 0
    for d in drives:
        root = f"{d}:\\"
        if os.path.exists(root):
            try:
                free = shutil.disk_usage(root).free
                if free > max_free and free > 50*1024**3:
                    max_free = free
                    best = root
            except: pass
    if not best: best = "C:\\" 
    path = os.path.join(best, "_Ultra_Smart_Cache_")
    os.makedirs(path, exist_ok=True)
    return path

# === 磁盘类型检测 (带缓存) ===
drive_type_cache = {}
def is_drive_ssd(path):
    drive_letter = os.path.splitdrive(path)[0]
    if not drive_letter: return False
    drive_letter = drive_letter.upper()
    if drive_letter in drive_type_cache: return drive_type_cache[drive_letter]
    try:
        # 优化：PowerShell 调用比较慢，仅在未缓存时调用
        cmd = f'Get-Partition -DriveLetter {drive_letter[0]} | Get-Disk | Select-Object -ExpandProperty MediaType'
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        result = subprocess.check_output(["powershell", "-Command", cmd], 
                                       startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW).decode().strip()
        is_ssd = "SSD" in result.upper()
        drive_type_cache[drive_letter] = is_ssd
        return is_ssd
    except: 
        drive_type_cache[drive_letter] = False # 默认 fallback
        return False

# === UI 组件 ===
class InfinityScope(ctk.CTkCanvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=COLOR_PANEL_RIGHT, highlightthickness=0, **kwargs)
        self.points = [] 
        self.max_val = 10.0
        self.bind("<Configure>", self.draw)
    def add_point(self, val):
        self.points.append(val)
        if len(self.points) > 100: self.points.pop(0) 
        self.draw()
    def clear(self):
        self.points = []
        self.max_val = 10.0
        self.delete("all")
    def draw(self, event=None):
        self.delete("all")
        if not self.points: return
        w = self.winfo_width(); h = self.winfo_height()
        if w < 10 or h < 10: return
        n = len(self.points)
        data_max = max(self.points) if self.points else 10
        target_max = max(data_max, 10) * 1.1 
        self.max_val += (target_max - self.max_val) * 0.1 
        scale_y = (h - 20) / self.max_val
        self.create_line(0, h/2, w, h/2, fill="#2a2a2a", dash=(4,4))
        if n < 2: return
        step_x = w / (n - 1)
        coords = []
        for i, val in enumerate(self.points):
            coords.extend([i * step_x, h - (val * scale_y) - 10])
        if len(coords) >= 4:
            self.create_line(coords, fill=COLOR_CHART_LINE, width=2, smooth=True)

class MonitorChannel(ctk.CTkFrame):
    def __init__(self, master, ch_id, **kwargs):
        super().__init__(master, fg_color="#181818", corner_radius=10, border_width=1, border_color="#333", **kwargs)
        head = ctk.CTkFrame(self, fg_color="transparent", height=25)
        head.pack(fill="x", padx=15, pady=(10,0))
        self.lbl_title = ctk.CTkLabel(head, text=f"Core {ch_id} · IDLE", font=("微软雅黑", 12, "bold"), text_color="#555")
        self.lbl_title.pack(side="left")
        self.lbl_info = ctk.CTkLabel(head, text="WAITING", font=("Arial", 11), text_color="#444")
        self.lbl_info.pack(side="right")
        self.scope = InfinityScope(self)
        self.scope.pack(fill="both", expand=True, padx=2, pady=5)
        btm = ctk.CTkFrame(self, fg_color="transparent")
        btm.pack(fill="x", padx=15, pady=(0,10))
        self.lbl_fps = ctk.CTkLabel(btm, text="0", font=("Impact", 20), text_color="#333")
        self.lbl_fps.pack(side="left")
        ctk.CTkLabel(btm, text="FPS", font=("Arial", 10, "bold"), text_color="#444").pack(side="left", padx=(5,0), pady=(8,0))
        self.lbl_eta = ctk.CTkLabel(btm, text="--:--", font=("Consolas", 12), text_color="#666")
        self.lbl_eta.pack(side="right", padx=(10, 0))
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 14, "bold"), text_color="#333")
        self.lbl_prog.pack(side="right")

    def activate(self, filename, tag):
        if not self.winfo_exists(): return
        self.lbl_title.configure(text=f"RUN: {filename[:15]}...", text_color=COLOR_ACCENT)
        self.lbl_info.configure(text=tag, text_color="#AAA")
        self.lbl_fps.configure(text_color="#FFF")
        self.lbl_prog.configure(text_color=COLOR_ACCENT)
        self.lbl_eta.configure(text_color=COLOR_SUCCESS)
        self.scope.clear()

    def update_data(self, fps, prog, eta):
        if not self.winfo_exists(): return
        self.scope.add_point(fps)
        self.lbl_fps.configure(text=f"{fps}")
        self.lbl_prog.configure(text=f"{int(prog*100)}%")
        self.lbl_eta.configure(text=f"ETA: {eta}")

    def reset(self):
        if not self.winfo_exists(): return
        self.lbl_title.configure(text="CHANNEL · IDLE", text_color="#555")
        self.lbl_info.configure(text="WAITING", text_color="#444")
        self.lbl_fps.configure(text="0", text_color="#333")
        self.lbl_prog.configure(text="0%", text_color="#333")
        self.lbl_eta.configure(text="--:--", text_color="#333")
        self.scope.clear()

class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=10, border_width=0, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        self.status_code = STATUS_WAIT 
        self.ram_data = None 
        self.ssd_cache_path = None
        self.source_mode = "PENDING"
        self.filepath = filepath
        
        ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 20), text_color="#555").grid(row=0, column=0, rowspan=2, padx=15)
        ctk.CTkLabel(self, text=os.path.basename(filepath), font=("微软雅黑", 12, "bold"), text_color="#EEE", anchor="w").grid(row=0, column=1, sticky="w", padx=5, pady=(8,0))
        self.lbl_status = ctk.CTkLabel(self, text="等待处理", font=("Arial", 10), text_color="#888", anchor="w")
        self.lbl_status.grid(row=1, column=1, sticky="w", padx=5, pady=(0,8))
        self.progress = ctk.CTkProgressBar(self, height=4, corner_radius=0, progress_color=COLOR_ACCENT, fg_color="#444")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew")

    def set_status(self, text, color="#888", code=None):
        try:
            if self.winfo_exists():
                self.lbl_status.configure(text=text, text_color=color)
                if code is not None: self.status_code = code
        except: pass
    
    def set_progress(self, val, color=COLOR_ACCENT):
        try:
            if self.winfo_exists():
                self.progress.set(val)
                self.progress.configure(progress_color=color)
        except: pass
        
    def clean_memory(self):
        # 显式清理内存
        self.ram_data = None

# === 主程序 ===
class UltraEncoderApp(DnDWindow):
    def __init__(self):
        super().__init__()
        self.title("Ultra Encoder v45 [RTX 4080 + 14900K Optimized]")
        self.geometry("1300x900")
        self.configure(fg_color=COLOR_BG_MAIN)
        self.minsize(1200, 850) 
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.file_queue = [] 
        self.task_widgets = {}
        self.active_procs = []
        self.running = False
        self.stop_flag = False
        
        self.queue_lock = threading.Lock() 
        self.slot_lock = threading.Lock()
        self.read_lock = threading.Lock()
        
        self.monitor_slots = []
        self.available_indices = [] 
        self.current_workers = 2
        
        # 14900K 拥有24核心，适当增加线程池
        self.executor = ThreadPoolExecutor(max_workers=24) 
        self.submitted_tasks = set() 
        self.temp_dir = ""
        self.temp_files = set()
        
        self.setup_ui()
        self.after(200, self.sys_check)
        
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    def drop_file(self, event):
        files = self.tk.splitlist(event.data)
        self.add_list(files)

    def add_list(self, files):
        with self.queue_lock:
            for f in files:
                if f not in self.file_queue and f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.ts', '.flv')):
                    self.file_queue.append(f)
                    card = TaskCard(self.scroll, len(self.file_queue), f)
                    card.pack(fill="x", pady=4) 
                    self.task_widgets[f] = card

    def apply_system_priority(self, level):
        mapping = {"常规": PRIORITY_NORMAL, "优先": PRIORITY_ABOVE, "极速": PRIORITY_HIGH}
        p_val = mapping.get(level, PRIORITY_ABOVE)
        try:
            pid = os.getpid()
            handle = ctypes.windll.kernel32.OpenProcess(0x0100 | 0x0200, False, pid)
            ctypes.windll.kernel32.SetPriorityClass(handle, p_val)
            self.set_status_bar(f"Process Priority: {level}")
        except: pass

    def on_closing(self):
        if self.running:
            if not messagebox.askokcancel("Exit", "Tasks running. Abort?"): return
        self.stop_flag = True
        self.running = False
        self.executor.shutdown(wait=False)
        self.kill_all_procs()
        self.clean_junk()
        self.destroy()
        os._exit(0)
        
    def kill_all_procs(self):
        for p in self.active_procs:
            try: 
                p.terminate()
                p.kill()
            except: pass
        # 再次兜底，防止僵尸进程
        try:
            subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe"], creationflags=subprocess.CREATE_NO_WINDOW)
        except: pass

    def sys_check(self):
        if not check_ffmpeg():
            messagebox.showerror("Critical Error", "FFmpeg not found in PATH!")
            return
        threading.Thread(target=self.scan_disk, daemon=True).start()
        threading.Thread(target=self.smart_preload_worker, daemon=True).start()
        self.update_monitor_layout()

    def scan_disk(self):
        path = get_force_ssd_dir()
        self.temp_dir = path
        self.after(0, lambda: self.btn_cache.configure(text=f"Cache Pool: {path}"))

    def set_status_bar(self, text):
        self.lbl_global_status.configure(text=f"Status: {text}")

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=0, minsize=320) 
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0, width=320)
        left.grid(row=0, column=0, sticky="nsew")
        left.pack_propagate(False)
        
        l_head = ctk.CTkFrame(left, fg_color="transparent")
        l_head.pack(fill="x", padx=20, pady=(25, 10))
        ctk.CTkLabel(l_head, text="ULTRA ENCODER", font=("Impact", 26), text_color="#FFF").pack(anchor="w")
        ctk.CTkLabel(l_head, text="v45 // 14900K+4080 Edition", font=("Arial", 10), text_color=COLOR_ACCENT).pack(anchor="w")
        
        self.btn_cache = ctk.CTkButton(left, text="Checking Drive...", fg_color="#252525", hover_color="#333", 
                                     text_color="#AAA", font=("Consolas", 10), height=28, corner_radius=14, command=self.open_cache)
        self.btn_cache.pack(fill="x", padx=20, pady=(5, 5))
        self.btn_ram = ctk.CTkButton(left, text="RAM Monitor...", fg_color="#252525", hover_color="#333", 
                                     text_color="#AAA", font=("Consolas", 10), height=28, corner_radius=14, state="disabled")
        self.btn_ram.pack(fill="x", padx=20, pady=(5, 5))
        
        tools = ctk.CTkFrame(left, fg_color="transparent")
        tools.pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(tools, text="+ Import", width=120, height=36, corner_radius=18, 
                     fg_color="#333", hover_color="#444", command=self.add_file).pack(side="left", padx=5)
        self.btn_clear = ctk.CTkButton(tools, text="Clear", width=60, height=36, corner_radius=18, 
                     fg_color="transparent", border_width=1, border_color="#444", hover_color="#331111", text_color="#CCC", command=self.clear_all)
        self.btn_clear.pack(side="left", padx=5)

        l_btm = ctk.CTkFrame(left, fg_color="#222", corner_radius=20)
        l_btm.pack(side="bottom", fill="x", padx=15, pady=20, ipadx=5, ipady=10)
        
        rowP = ctk.CTkFrame(l_btm, fg_color="transparent")
        rowP.pack(fill="x", pady=(10, 5), padx=10)
        ctk.CTkLabel(rowP, text="Process Priority", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        self.priority_var = ctk.StringVar(value="优先")
        self.seg_priority = ctk.CTkSegmentedButton(rowP, values=["常规", "优先", "极速"], 
                                                  variable=self.priority_var, command=lambda v: self.apply_system_priority(v),
                                                  selected_color=COLOR_ACCENT, corner_radius=10)
        self.seg_priority.pack(fill="x", pady=(5, 0))

        row3 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row3.pack(fill="x", pady=(10, 5), padx=10)
        ctk.CTkLabel(row3, text="Concurrency (4080 Dual Enc)", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        w_box = ctk.CTkFrame(row3, fg_color="transparent")
        w_box.pack(fill="x")
        self.worker_var = ctk.StringVar(value="2")
        # 增加并发选项到 8，适配 4080 的性能
        self.seg_worker = ctk.CTkSegmentedButton(w_box, values=["1", "2", "4", "8"], variable=self.worker_var, 
                                               corner_radius=10, command=self.update_monitor_layout)
        self.seg_worker.pack(side="left", fill="x", expand=True)
        self.gpu_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(w_box, text="GPU", width=60, variable=self.gpu_var, progress_color=COLOR_ACCENT).pack(side="right", padx=(10,0))
        
        row2 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row2.pack(fill="x", pady=10, padx=10)
        ctk.CTkLabel(row2, text="Quality (CRF/CQ)", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        c_box = ctk.CTkFrame(row2, fg_color="transparent")
        c_box.pack(fill="x")
        self.crf_var = ctk.IntVar(value=20) # 默认为20，适合4080的高质量输出
        ctk.CTkSlider(c_box, from_=0, to=51, variable=self.crf_var, progress_color=COLOR_ACCENT).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(c_box, textvariable=self.crf_var, width=25, font=("Arial", 12, "bold"), text_color=COLOR_ACCENT).pack(side="right")
        
        row1 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row1.pack(fill="x", pady=(5, 5), padx=10)
        ctk.CTkLabel(row1, text="Codec", font=("微软雅黑", 12, "bold"), text_color="#DDD").pack(anchor="w")
        self.codec_var = ctk.StringVar(value="H.265")
        self.seg_codec = ctk.CTkSegmentedButton(row1, values=["H.264", "H.265"], variable=self.codec_var, selected_color=COLOR_ACCENT, corner_radius=10)
        self.seg_codec.pack(fill="x", pady=(5, 0))

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=20, pady=(0, 20))
        self.btn_run = ctk.CTkButton(btn_row, text="START ENGINE", height=45, corner_radius=22, 
                                   font=("微软雅黑", 15, "bold"), fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, 
                                   text_color="#000", command=self.run)
        self.btn_run.pack(side="left", fill="x", expand=True, padx=(0, 10)) 
        self.btn_stop = ctk.CTkButton(btn_row, text="HALT", height=45, corner_radius=22, width=80,
                                    fg_color="transparent", border_width=2, border_color=COLOR_ERROR, 
                                    text_color=COLOR_ERROR, hover_color="#221111", 
                                    state="disabled", command=self.stop)
        self.btn_stop.pack(side="right")

        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=10, pady=10)

        right = ctk.CTkFrame(self, fg_color=COLOR_PANEL_RIGHT, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        r_head = ctk.CTkFrame(right, fg_color="transparent")
        r_head.pack(fill="x", padx=30, pady=(25, 10))
        ctk.CTkLabel(r_head, text="LIVE MONITOR", font=("Impact", 20), text_color="#333").pack(side="left")
        self.lbl_global_status = ctk.CTkLabel(r_head, text="System: Ready", font=("微软雅黑", 11), text_color="#555")
        self.lbl_global_status.pack(side="right")
        self.monitor_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.monitor_frame.pack(fill="both", expand=True, padx=25, pady=(0, 25))

    def update_monitor_layout(self, val=None):
        if self.running:
            self.seg_worker.set(str(self.current_workers))
            return
        try: n = int(self.worker_var.get())
        except: n = 2
        self.current_workers = n
        for ch in self.monitor_slots: ch.destroy()
        self.monitor_slots.clear()
        with self.slot_lock:
            self.available_indices = [i for i in range(n)] 
        for i in range(n):
            ch = MonitorChannel(self.monitor_frame, i+1)
            ch.pack(fill="both", expand=True, pady=5)
            self.monitor_slots.append(ch)

    def process_caching(self, src_path, widget):
        self.after(0, lambda: [widget.set_status("🔍 Analyzing...", COLOR_READING, STATUS_CACHING)])
        
        file_size_gb = os.path.getsize(src_path) / (1024**3)
        
        # 1. 优先 SSD 直读检测
        is_ssd = is_drive_ssd(src_path)
        if is_ssd:
            self.after(0, lambda: [widget.set_status("Direct Read (NVMe)", COLOR_DIRECT, STATUS_READY)])
            widget.source_mode = "DIRECT"
            return True

        # 2. RAM 缓存逻辑优化 (增加上限保护)
        free_ram = get_free_ram_gb()
        available_for_cache = free_ram - SAFE_RAM_RESERVE

        # 只有文件小于 MAX_RAM_LOAD_GB 且内存足够时才使用 RAM 缓存
        # 即使你有64GB内存，Python处理20GB以上bytes对象效率极低，不如直接读SSD
        if available_for_cache > file_size_gb and file_size_gb < MAX_RAM_LOAD_GB:
            self.after(0, lambda: [widget.set_status("📥 Loading to RAM...", COLOR_RAM, STATUS_CACHING), widget.set_progress(0, COLOR_RAM)])
            try:
                # 使用分块读取，防止界面假死，尽管是在线程中
                with open(src_path, 'rb') as f:
                    widget.ram_data = f.read() # 这里对于10GB以下文件还是安全的
                self.after(0, lambda: [widget.set_status("RAM Ready", COLOR_RAM, STATUS_READY), widget.set_progress(1, COLOR_RAM)])
                widget.source_mode = "RAM"
                return True
            except Exception as e: 
                print(f"RAM Load Failed: {e}")
                widget.clean_memory()
                # 失败则回退

        # 3. SSD 缓存逻辑
        self.after(0, lambda: [widget.set_status("📥 Caching to Pool...", COLOR_SSD_CACHE, STATUS_CACHING), widget.set_progress(0, COLOR_SSD_CACHE)])
        try:
            fname = os.path.basename(src_path)
            cache_path = os.path.join(self.temp_dir, f"CACHE_{int(time.time())}_{fname}")
            total = os.path.getsize(src_path)
            copied = 0
            with open(src_path, 'rb') as fsrc:
                with open(cache_path, 'wb') as fdst:
                    while True:
                        if self.stop_flag: 
                            fdst.close(); os.remove(cache_path); return False
                        chunk = fsrc.read(32*1024*1024) # 32MB chunks for faster copy on 14900K
                        if not chunk: break
                        fdst.write(chunk)
                        copied += len(chunk)
                        if total > 0:
                            self.after(0, lambda p=copied/total: widget.set_progress(p, COLOR_SSD_CACHE))
            self.temp_files.add(cache_path)
            widget.ssd_cache_path = cache_path
            widget.source_mode = "SSD_CACHE"
            self.after(0, lambda: [widget.set_status("Cache Ready", COLOR_SSD_CACHE, STATUS_READY), widget.set_progress(1, COLOR_SSD_CACHE)])
            return True
        except:
            self.after(0, lambda: widget.set_status("Cache Failed", COLOR_ERROR, STATUS_ERR))
            return False

    def smart_preload_worker(self):
        while True:
            free = get_free_ram_gb()
            self.after(0, lambda f=free: self.btn_ram.configure(text=f"Free RAM: {f:.1f} GB"))
            
            if self.running and not self.stop_flag:
                if not self.read_lock.acquire(blocking=False):
                    time.sleep(0.5); continue
                
                target_file, target_widget = None, None
                with self.queue_lock: 
                    for f in self.file_queue:
                        w = self.task_widgets.get(f)
                        if w and w.status_code == STATUS_WAIT and w.source_mode == "PENDING":
                            target_file, target_widget = f, w
                            break 
                
                if target_file and target_widget:
                    self.process_caching(target_file, target_widget)
                
                self.read_lock.release()
                time.sleep(0.5) 
            else:
                time.sleep(1)

    def engine(self):
        while not self.stop_flag:
            tasks_to_run = []
            active_count = len(self.submitted_tasks)
            slots_free = self.current_workers - active_count
            
            if slots_free > 0:
                with self.queue_lock:
                    for f in self.file_queue:
                        if slots_free <= 0: break
                        if f in self.submitted_tasks: continue 
                        card = self.task_widgets[f]
                        if card.status_code in [STATUS_WAIT, STATUS_CACHING, STATUS_READY]:
                            tasks_to_run.append(f)
                            self.submitted_tasks.add(f)
                            slots_free -= 1
            
            # 检查是否全部完成
            if not tasks_to_run and active_count == 0 and self.file_queue:
                all_done = True
                with self.queue_lock:
                    for f in self.file_queue:
                        if self.task_widgets[f].status_code not in [STATUS_DONE, STATUS_ERR]:
                            all_done = False; break
                if all_done: break
            
            if not tasks_to_run: time.sleep(0.2); continue
            
            for f in tasks_to_run:
                self.executor.submit(self.process, f)
            time.sleep(0.1) 

        if not self.stop_flag:
            self.after(0, lambda: messagebox.showinfo("Done", "All tasks completed!"))
        self.running = False
        self.after(0, self.reset_ui_state)

    def process(self, input_file):
        if self.stop_flag: return
        my_slot_idx = None
        # 等待可用槽位
        while my_slot_idx is None and not self.stop_flag:
            with self.slot_lock:
                if self.available_indices: my_slot_idx = self.available_indices.pop(0)
            if my_slot_idx is None: time.sleep(0.1)
        if self.stop_flag: return

        card = self.task_widgets[input_file]
        
        # 等待缓存完成
        while card.status_code == STATUS_CACHING and not self.stop_flag: 
            time.sleep(0.5)

        # 如果尚未缓存，尝试最后一次缓存（或直读）
        if card.source_mode == "PENDING":
            self.read_lock.acquire()
            try:
                if card.source_mode == "PENDING" and not self.stop_flag:
                   self.process_caching(input_file, card)
            finally:
                self.read_lock.release()
        
        if self.stop_flag: return

        try:
            ch_ui = self.monitor_slots[my_slot_idx]
            mode_label = {"DIRECT": "SSD Direct", "RAM": "RAM Disk", "SSD_CACHE": "Smart Cache"}.get(card.source_mode, "Unknown")
            self.after(0, lambda: [card.set_status(f"▶️ Encoding ({mode_label})", COLOR_ACCENT, STATUS_RUN), card.set_progress(0, COLOR_ACCENT)])
            
            fname = os.path.basename(input_file)
            name, ext = os.path.splitext(fname)
            codec_sel = self.codec_var.get()
            tag = "HEVC" if "H.265" in codec_sel else "AVC"
            gpu_flag = "NVENC" if self.gpu_var.get() else "CPU"
            self.after(0, lambda: ch_ui.activate(fname, f"{tag} | {gpu_flag}"))
            
            suffix = "_H265" if "H.265" in codec_sel else "_H264"
            final_out = os.path.join(os.path.dirname(input_file), f"{name}{suffix}{ext}")
            
            # === FFmpeg 命令构建 ===
            v_codec = "hevc_nvenc" if "H.265" in codec_sel else "h264_nvenc"
            if not self.gpu_var.get(): v_codec = "libx265" if "H.265" in codec_sel else "libx264"
            
            input_arg = input_file
            if card.source_mode == "RAM": input_arg = "pipe:0"
            elif card.source_mode == "SSD_CACHE": input_arg = card.ssd_cache_path
            
            cmd = ["ffmpeg", "-y", "-i", input_arg, "-c:v", v_codec]
            if self.gpu_var.get():
                # RTX 4080 优化参数
                cmd.extend(["-pix_fmt", "yuv420p", "-rc", "vbr", "-cq", str(self.crf_var.get()), 
                           "-preset", "p6", # p6/p7 为高质量预设
                           "-spatial-aq", "1", # 开启空间自适应量化
                           "-multipass", "qres" # 若支持，启用多重编码
                           ])
            else:
                cmd.extend(["-crf", str(self.crf_var.get()), "-preset", "medium"])
            cmd.extend(["-c:a", "copy", final_out])
            
            dur_file = input_file if card.source_mode != "SSD_CACHE" else card.ssd_cache_path
            duration = self.get_dur(dur_file)
            
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if card.source_mode == "RAM" else None, 
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                   startupinfo=si)
            self.active_procs.append(proc)
            
            # RAM 模式下的数据泵 (独立线程)
            def feed_stdin():
                try:
                    if card.ram_data:
                        proc.stdin.write(card.ram_data)
                        proc.stdin.close()
                except Exception as e: 
                    print(f"Pipe Error: {e}")
            
            if card.source_mode == "RAM":
                threading.Thread(target=feed_stdin, daemon=True).start()
            
            start_t = time.time()
            last_upd = 0
            
            # 实时输出解析
            for line in proc.stdout:
                if self.stop_flag: break
                try: line_str = line.decode('utf-8', errors='ignore')
                except: continue
                
                if "time=" in line_str and duration > 0:
                    tm = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line_str)
                    fm = re.search(r"fps=\s*(\d+)", line_str)
                    if tm:
                        h, m, s = map(float, tm.groups())
                        prog = (h*3600 + m*60 + s) / duration
                        if time.time() - last_upd > 0.1: # 限制 UI 刷新率
                            elap = time.time() - start_t
                            eta = f"{int((elap/prog-elap)//60):02d}:{int((elap/prog-elap)%60):02d}" if prog > 0.01 else "--:--"
                            # 使用闭包参数避免 lambda 延迟绑定问题
                            self.after(0, lambda p=prog: card.set_progress(p, COLOR_ACCENT))
                            self.after(0, lambda f=int(fm.group(1)) if fm else 0, p=prog, e=eta: ch_ui.update_data(f, p, e))
                            last_upd = time.time()
            
            proc.wait()
            if proc in self.active_procs: self.active_procs.remove(proc)
            
            # === 成功判定 ===
            success = (not self.stop_flag and proc.returncode == 0)
            if success:
                if not os.path.exists(final_out) or os.path.getsize(final_out) < 500*1024: # 至少500KB
                    success = False
            
            # 立即释放内存
            card.clean_memory()
            if card.ssd_cache_path:
                try: 
                    os.remove(card.ssd_cache_path)
                    self.temp_files.remove(card.ssd_cache_path)
                except: pass
            
            self.after(0, ch_ui.reset)
            with self.slot_lock: self.available_indices.append(my_slot_idx); self.available_indices.sort()
            
            if success:
                 orig_sz = os.path.getsize(input_file)
                 new_sz = os.path.getsize(final_out)
                 sv = 100 - (new_sz/orig_sz*100) if orig_sz > 0 else 0
                 self.after(0, lambda: [card.set_status(f"Done | Ratio: {sv:.1f}%", COLOR_SUCCESS, STATUS_DONE), card.set_progress(1, COLOR_SUCCESS)])
            else:
                 self.after(0, lambda: card.set_status("Failed", COLOR_ERROR, STATUS_ERR))

        finally:
            with self.queue_lock:
                if input_file in self.submitted_tasks: self.submitted_tasks.remove(input_file)
            # 再次确保内存释放
            card.clean_memory()

    def run(self):
        if not self.file_queue: return
        self.running = True
        self.stop_flag = False
        self.btn_run.configure(state="disabled", text="RUNNING...")
        self.btn_stop.configure(state="normal")
        self.update_monitor_layout()
        threading.Thread(target=self.engine, daemon=True).start()

    def stop(self):
        self.stop_flag = True
        self.kill_all_procs()
        self.active_procs = []
        with self.queue_lock:
            for f, card in self.task_widgets.items():
                card.clean_memory()
                if card.status_code in [STATUS_RUN, STATUS_CACHING, STATUS_READY]:
                    card.set_status("STOPPED", COLOR_TEXT_GRAY, STATUS_WAIT)
                    card.set_progress(0)
        self.submitted_tasks.clear()
        self.running = False
        self.reset_ui_state()

    def reset_ui_state(self):
        self.btn_run.configure(state="normal", text="START ENGINE")
        self.btn_stop.configure(state="disabled")

    def open_cache(self):
        if self.temp_dir: os.startfile(self.temp_dir)
    def add_file(self):
        f_list = filedialog.askopenfilenames()
        self.add_list(f_list)

    def clear_all(self):
        if self.running:
            if not messagebox.askyesno("Warning", "Stop queue and clear?"):
                return
            self.stop()
        self.after(100, self._do_clear)

    def _do_clear(self):
        for w in list(self.task_widgets.values()): 
            w.clean_memory()
            w.destroy()
        self.task_widgets.clear()
        self.file_queue.clear()
        self.submitted_tasks.clear()

    def get_dur(self, f):
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", f]
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return float(subprocess.check_output(cmd, startupinfo=si).strip())
        except: return 0

    def clean_junk(self):
        for f in list(self.temp_files):
            try: os.remove(f)
            except: pass
        self.temp_files.clear()

if __name__ == "__main__":
    app = UltraEncoderApp()
    app.mainloop()

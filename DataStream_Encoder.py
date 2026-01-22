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
from collections import deque

# === 全局配置 ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# 专业配色 (Command Center Theme)
COLOR_BG_LEFT = "#252526"      # VSCode 风格深灰
COLOR_BG_RIGHT = "#1e1e1e"     # 更深的监控背景
COLOR_CARD_LEFT = "#333333"    # 左侧卡片
COLOR_PANEL_RIGHT = "#2d2d2d"  # 右侧监控面板
COLOR_ACCENT = "#3B8ED0"
COLOR_CHART_LINE = "#00E676"   # 荧光绿折线 (Cyberpunk)
COLOR_TEXT_GRAY = "#888888"
COLOR_SUCCESS = "#2ECC71"
COLOR_ERROR = "#E74C3C"

# 尝试导入拖拽库
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

# === 硬件与工具 ===
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

def get_free_ram_gb():
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullAvailPhys / (1024**3)
    except: return 16.0

def get_smart_ssd_temp_dir():
    print("扫描 SSD 中...")
    drives = [f"{d}" for d in "DEFGHIJKLMNOPQRSTUVWXYZ"]
    best_drive = None
    max_free = 0
    fallback_drive = None 
    fallback_free = 0
    
    for drive in drives:
        root = f"{drive}:\\"
        if os.path.exists(root):
            try:
                free = shutil.disk_usage(root).free
                if free > fallback_free:
                    fallback_drive = root
                    fallback_free = free
                
                cmd = f"powershell -Command \"(Get-Partition -DriveLetter {drive} | Get-Disk).MediaType\""
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=si).stdout.strip()
                
                if "SSD" in result:
                    if free > max_free:
                        max_free = free
                        best_drive = root
            except: pass
    
    final_root = best_drive if best_drive else (fallback_drive if fallback_drive else "C:\\")
    if not best_drive and os.path.exists("C:\\"): final_root = "C:\\"

    temp_path = os.path.join(final_root, "_Ultra_Temp_Cache_")
    os.makedirs(temp_path, exist_ok=True)
    return temp_path

def format_size(size_bytes):
    if size_bytes == 0: return "0B"
    i = int(os.math.floor(os.math.log(size_bytes, 1024)))
    p = os.math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, ("B", "KB", "MB", "GB", "TB")[i])

# === 组件：右侧的大型监控图表 ===
class MonitorChart(ctk.CTkCanvas):
    def __init__(self, master, height=120, **kwargs):
        super().__init__(master, height=height, bg="#111", highlightthickness=0, **kwargs)
        self.height = height
        self.data_points = deque(maxlen=100) # 更多点数，更细腻
        self.max_val = 1
        
    def add_point(self, value):
        self.data_points.append(value)
        self.draw()
        
    def draw(self):
        self.delete("all")
        if not self.data_points: return
        
        w = self.winfo_width()
        h = self.height
        
        curr = max(self.data_points)
        if curr > self.max_val: self.max_val = curr
        else: self.max_val = max(1, self.max_val * 0.99) # 平滑衰减
        
        points = []
        n = len(self.data_points)
        x_step = w / (n - 1) if n > 1 else w
        
        # 绘制网格线
        self.create_line(0, h/2, w, h/2, fill="#222", width=1, dash=(2, 4))
        self.create_line(0, h/4, w, h/4, fill="#222", width=1, dash=(2, 4))
        self.create_line(0, h*0.75, w, h*0.75, fill="#222", width=1, dash=(2, 4))

        # 绘制波形
        for i, val in enumerate(self.data_points):
            x = i * x_step
            y = h - (val / self.max_val * (h - 10)) - 5
            points.extend([x, y])
            
        if len(points) >= 4:
            self.create_line(points, fill=COLOR_CHART_LINE, width=2, smooth=True)

# === 组件：右侧监控面板 (Monitor Panel) ===
class MonitorPanel(ctk.CTkFrame):
    def __init__(self, master, filename, tag, **kwargs):
        super().__init__(master, fg_color=COLOR_PANEL_RIGHT, corner_radius=6, border_width=1, border_color="#444", **kwargs)
        self.filename = filename
        
        # 头部：文件名 + 编码器
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(top, text=f"🔴 LIVE: {filename}", font=("Arial", 12, "bold"), text_color="#EEE").pack(side="left")
        ctk.CTkLabel(top, text=f"[{tag}]", font=("Consolas", 10), text_color="#888").pack(side="right")
        
        # 图表区域
        self.chart = MonitorChart(self, height=120)
        self.chart.pack(fill="x", padx=1, pady=5)
        
        # 数据区域
        data = ctk.CTkFrame(self, fg_color="transparent")
        data.pack(fill="x", padx=10, pady=5)
        
        self.lbl_fps = ctk.CTkLabel(data, text="FPS: 0", font=("Consolas", 14, "bold"), text_color=COLOR_ACCENT)
        self.lbl_fps.pack(side="left", padx=5)
        
        self.lbl_prog = ctk.CTkLabel(data, text="0%", font=("Arial", 14, "bold"), text_color="white")
        self.lbl_prog.pack(side="right", padx=5)

    def update_data(self, fps, percent):
        self.chart.add_point(fps)
        self.lbl_fps.configure(text=f"FPS: {fps}")
        self.lbl_prog.configure(text=f"{int(percent*100)}%")

# === 组件：左侧任务卡片 (Compact List Item) ===
class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD_LEFT, corner_radius=4, **kwargs)
        self.filepath = filepath
        
        # 布局：序号 | 文件名 | 状态
        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(fill="x", padx=8, pady=(8, 2))
        
        ctk.CTkLabel(r1, text=f"{index}", font=("Arial", 12, "bold"), text_color="#666", width=20).pack(side="left")
        ctk.CTkLabel(r1, text=os.path.basename(filepath), font=("Roboto Medium", 12), text_color="white").pack(side="left", padx=5)
        self.lbl_status = ctk.CTkLabel(r1, text="等待中", font=("Arial", 11), text_color=COLOR_TEXT_GRAY)
        self.lbl_status.pack(side="right")
        
        # 底部细进度条
        self.progress = ctk.CTkProgressBar(self, height=3, corner_radius=2, progress_color=COLOR_ACCENT, fg_color="#444", border_width=0)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=8, pady=(2, 6))

    def set_status(self, text, color=COLOR_TEXT_GRAY):
        self.lbl_status.configure(text=text, text_color=color)

    def set_progress(self, val):
        self.progress.set(val)

# === 主程序 ===
class UltraEncoderApp(DnDWindow):
    def __init__(self):
        super().__init__()
        
        self.title("Ultra Encoder v8 - Command Center")
        self.geometry("1280x800")
        
        self.file_queue = [] 
        self.task_widgets_left = {}  
        self.active_monitors = {}    
        self.active_procs = []
        self.active_temp_files = set() # 追踪临时文件以便清理
        self.is_running = False
        self.stop_requested = False
        self.cpu_threads = os.cpu_count() or 16
        
        # 默认 H.264
        self.codec_var = ctk.StringVar(value="AVC (H.264)")
        
        threading.Thread(target=self.init_disk_scan, daemon=True).start()
        self.setup_ui()
        threading.Thread(target=self.preload_monitor, daemon=True).start()
        
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    def init_disk_scan(self):
        path = get_smart_ssd_temp_dir()
        self.temp_dir = path
        self.after(0, lambda: self.lbl_cache.configure(text=f"SSD Cache: {self.temp_dir}"))

    def setup_ui(self):
        # 左右分栏 Grid
        self.grid_columnconfigure(0, weight=3) # 左侧 30%
        self.grid_columnconfigure(1, weight=7) # 右侧 70%
        self.grid_rowconfigure(0, weight=1)

        # === 左侧：任务列队 ===
        self.left_panel = ctk.CTkFrame(self, fg_color=COLOR_BG_LEFT, corner_radius=0)
        self.left_panel.grid(row=0, column=0, sticky="nsew")
        
        # 头部
        l_head = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        l_head.pack(fill="x", padx=15, pady=20)
        ctk.CTkLabel(l_head, text="TASK QUEUE", font=("Arial Black", 16), text_color="#FFF").pack(anchor="w")
        self.lbl_cache = ctk.CTkLabel(l_head, text="Scanning...", font=("Arial", 10), text_color="#888")
        self.lbl_cache.pack(anchor="w")

        # 按钮
        btn_box = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        btn_box.pack(fill="x", padx=15, pady=(0, 10))
        ctk.CTkButton(btn_box, text="+ 添加", width=60, command=self.add_files, fg_color="#444").pack(side="left", padx=(0, 5))
        ctk.CTkButton(btn_box, text="清空", width=50, command=self.clear_all, fg_color="#444", hover_color=COLOR_ERROR).pack(side="left")
        ctk.CTkButton(btn_box, text="⚙️ 缓存", width=50, command=self.change_temp_dir, fg_color="#333").pack(side="right")

        # 列表
        self.scroll_left = ctk.CTkScrollableFrame(self.left_panel, fg_color="transparent")
        self.scroll_left.pack(fill="both", expand=True, padx=5)

        # 底部控制区
        l_btm = ctk.CTkFrame(self.left_panel, fg_color="#181818", corner_radius=0)
        l_btm.pack(fill="x", side="bottom")
        
        # 参数
        param_box = ctk.CTkFrame(l_btm, fg_color="transparent")
        param_box.pack(fill="x", padx=15, pady=10)
        
        self.crf_var = ctk.IntVar(value=23)
        ctk.CTkLabel(param_box, text="CRF:", width=30).pack(side="left")
        ctk.CTkSlider(param_box, from_=0, to=51, variable=self.crf_var, width=80).pack(side="left")
        ctk.CTkLabel(param_box, textvariable=self.crf_var, width=20, font=("Arial", 12, "bold")).pack(side="left")
        
        self.use_gpu = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(param_box, text="GPU", variable=self.use_gpu, command=self.on_mode_change, width=50).pack(side="right")

        # 大按钮
        act_box = ctk.CTkFrame(l_btm, fg_color="transparent")
        act_box.pack(fill="x", padx=15, pady=(0, 20))
        self.stop_btn = ctk.CTkButton(act_box, text="STOP", command=self.stop, state="disabled", fg_color=COLOR_ERROR, width=60)
        self.stop_btn.pack(side="left")
        self.run_btn = ctk.CTkButton(act_box, text="START ENGINE", command=self.run, font=("Arial", 14, "bold"), fg_color=COLOR_ACCENT)
        self.run_btn.pack(side="right", fill="x", expand=True, padx=(10, 0))

        # === 右侧：实时监控 ===
        self.right_panel = ctk.CTkFrame(self, fg_color=COLOR_BG_RIGHT, corner_radius=0)
        self.right_panel.grid(row=0, column=1, sticky="nsew")
        
        r_head = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        r_head.pack(fill="x", padx=20, pady=20)
        ctk.CTkLabel(r_head, text="LIVE MONITOR", font=("Arial Black", 16), text_color=COLOR_ACCENT).pack(side="left")
        self.strategy_lbl = ctk.CTkLabel(r_head, text="Mode: GPU", text_color="#555")
        self.strategy_lbl.pack(side="right")
        
        ctk.CTkFrame(r_head, height=2, fg_color="#333").pack(fill="x", side="bottom", pady=(5,0))

        self.scroll_right = ctk.CTkScrollableFrame(self.right_panel, fg_color="transparent")
        self.scroll_right.pack(fill="both", expand=True, padx=20, pady=10)
        
        self.placeholder = ctk.CTkLabel(self.scroll_right, text="等待任务启动...\n\n(右侧区域仅显示正在运行的任务详情)", 
                                      font=("Arial", 14), text_color="#444")
        self.placeholder.pack(pady=150)

        # 隐藏参数
        self.preload_var = ctk.BooleanVar(value=True)
        self.preset_var = ctk.StringVar(value="p6 (Better)")
        self.recalc_concurrency()

    # === 逻辑方法 ===
    def change_temp_dir(self):
        if self.is_running: return
        d = filedialog.askdirectory()
        if d:
            self.temp_dir = os.path.join(d, "_Ultra_Temp_Cache_")
            os.makedirs(self.temp_dir, exist_ok=True)
            self.lbl_cache.configure(text=f"Custom: {self.temp_dir}")

    def on_mode_change(self):
        self.recalc_concurrency()

    def recalc_concurrency(self):
        if self.use_gpu.get():
            self.workers = 2
            self.strategy_lbl.configure(text="MODE: RTX 4080 (Dual NVENC)")
            self.preset_var.set("p6 (Better)")
        else:
            self.workers = min(max(1, (self.cpu_threads - 4) // 7), 5)
            self.strategy_lbl.configure(text=f"MODE: CPU ({self.workers} Workers)")
            self.preset_var.set("medium")

    def add_files(self): self.add_list(filedialog.askopenfilenames())
    def drop_file(self, event): self.add_list(self.tk.splitlist(event.data))

    def add_list(self, files):
        for f in files:
            if f not in self.file_queue and f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi')):
                self.file_queue.append(f)
                idx = len(self.file_queue)
                card = TaskCard(self.scroll_left, idx, f)
                card.pack(fill="x", pady=4)
                self.task_widgets_left[f] = card

    def clear_all(self):
        if self.is_running: return
        for w in self.task_widgets_left.values(): w.destroy()
        self.task_widgets_left = {}
        self.file_queue = []

    # === 预读逻辑 ===
    def preload_monitor(self):
        while True:
            if self.is_running and self.preload_var.get() and not self.stop_requested:
                if get_free_ram_gb() < 8.0:
                    time.sleep(2)
                    continue
                target = None
                for f in self.file_queue:
                    w = self.task_widgets_left.get(f)
                    if w and w.lbl_status.cget("text") == "等待中":
                        target = f
                        break
                if target:
                    w = self.task_widgets_left[target]
                    self.after(0, lambda: w.set_status("⚡ 预读", COLOR_ACCENT))
                    try:
                        sz = os.path.getsize(target)
                        if sz > 50*1024*1024:
                            with open(target, 'rb') as f:
                                while chunk := f.read(32*1024*1024):
                                    if self.stop_requested: return
                        self.after(0, lambda: w.set_status("🚀 就绪", COLOR_SUCCESS))
                    except: pass
            else: time.sleep(1)

    # === 执行引擎 ===
    def run(self):
        if not self.file_queue: return
        self.is_running = True
        self.stop_requested = False
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.placeholder.pack_forget() 
        self.recalc_concurrency()
        threading.Thread(target=self.worker_pool, daemon=True).start()

    def stop(self):
        self.stop_requested = True
        self.status_lbl_text = "停止中..."
        
        # 1. 杀进程
        for p in self.active_procs:
            try: p.terminate(); p.kill()
            except: pass
        self.active_procs = []
        
        # 2. 清理缓存 (新增逻辑)
        threading.Thread(target=self.clean_cache_on_stop).start()
        
        self.is_running = False
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
    
    def clean_cache_on_stop(self):
        """后台线程：清理残留的临时文件"""
        time.sleep(0.5) # 等待文件句柄释放
        count = 0
        for f in list(self.active_temp_files):
            try:
                if os.path.exists(f):
                    os.remove(f)
                    count += 1
            except: pass
        self.active_temp_files.clear()
        if count > 0:
            print(f"已清理 {count} 个缓存文件")

    def worker_pool(self):
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = [executor.submit(self.process_video, f) for f in self.file_queue]
            for fut in futures:
                if self.stop_requested: break
                try: fut.result() 
                except: pass
        if not self.stop_requested:
            self.after(0, lambda: messagebox.showinfo("完成", "所有任务结束"))
            self.is_running = False
            self.after(0, lambda: [self.run_btn.configure(state="normal"), self.stop_btn.configure(state="disabled")])

    def process_video(self, input_file):
        if self.stop_requested: return
        
        left_card = self.task_widgets_left[input_file]
        
        # 创建右侧监控面板
        fname = os.path.basename(input_file)
        monitor_panel = None
        
        def create_monitor():
            nonlocal monitor_panel
            monitor_panel = MonitorPanel(self.scroll_right, fname, "NVENC" if self.use_gpu.get() else "CPU")
            monitor_panel.pack(fill="x", pady=10)
            self.active_monitors[input_file] = monitor_panel
            
        self.after(0, create_monitor)
        
        name, ext = os.path.splitext(fname)
        tag = "H264"
        temp_out = os.path.join(self.temp_dir, f"TEMP_{name}_{tag}{ext}")
        final_out = os.path.join(os.path.dirname(input_file), f"{name}_{tag}_V8{ext}")
        
        # 记录临时文件以便清理
        self.active_temp_files.add(temp_out)
        
        self.after(0, lambda: left_card.set_status("▶️ 运行中", "#FFF"))
        
        cmd = ["ffmpeg", "-y", "-i", input_file]
        crf = self.crf_var.get()
        preset = self.preset_var.get().split(" ")[0]
        
        if self.use_gpu.get():
            cmd.extend(["-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", "-rc", "vbr", "-cq", str(crf), "-preset", preset, "-spatial-aq", "1"])
        else:
            cmd.extend(["-c:v", "libx264", "-crf", str(crf), "-preset", preset])
        cmd.extend(["-c:a", "copy", temp_output])

        duration = self.get_duration(input_file)
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                universal_newlines=True, encoding='utf-8', errors='ignore', startupinfo=si)
        self.active_procs.append(proc)
        
        last_update = 0
        for line in proc.stdout:
            if self.stop_requested: break
            if "time=" in line and duration > 0:
                tm = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                fm = re.search(r"fps=\s*(\d+)", line)
                if tm:
                    h, m, s = map(float, tm.groups())
                    per = (h*3600 + m*60 + s) / duration
                    fps = int(fm.group(1)) if fm else 0
                    
                    now = time.time()
                    if now - last_update > 0.2:
                        self.after(0, lambda p=per: left_card.set_progress(p))
                        if monitor_panel:
                            self.after(0, lambda f=fps, p=per: monitor_panel.update_data(f, p))
                        last_update = now

        proc.wait()
        if proc in self.active_procs: self.active_procs.remove(proc)
        
        def cleanup_monitor():
            if input_file in self.active_monitors:
                w = self.active_monitors.pop(input_file)
                w.destroy() 
        
        self.after(0, cleanup_monitor)
        
        if not self.stop_requested and proc.returncode == 0:
            try:
                if os.path.exists(temp_out): shutil.move(temp_out, final_out)
                if temp_out in self.active_temp_files: self.active_temp_files.remove(temp_out)
                
                orig = os.path.getsize(input_file)
                comp = os.path.getsize(final_out)
                saved = 100 - (comp/orig*100)
                self.after(0, lambda: [
                    left_card.set_status(f"✅ -{saved:.1f}%", COLOR_SUCCESS),
                    left_card.set_progress(1)
                ])
            except: 
                self.after(0, lambda: left_card.set_status("⚠️ 移动错误", COLOR_ERROR))
        else:
            if os.path.exists(temp_out): os.remove(temp_out)
            if temp_out in self.active_temp_files: self.active_temp_files.remove(temp_out)
            self.after(0, lambda: left_card.set_status("❌ 中止", COLOR_ERROR))

    def get_duration(self, f):
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", f]
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return float(subprocess.check_output(cmd, startupinfo=si).strip())
        except: return 0

if __name__ == "__main__":
    app = UltraEncoderApp()
    app.mainloop()

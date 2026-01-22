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
import math

# === 全局视觉配置 ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# Cyberpunk 2077 风格配色
COLOR_BG_MAIN = "#0f0f0f"      # 极黑背景
COLOR_PANEL_LEFT = "#181818"   # 左侧面板
COLOR_PANEL_RIGHT = "#121212"  # 右侧面板
COLOR_ACCENT = "#00E5FF"       # 赛博蓝 (高亮)
COLOR_CHART_LINE = "#00FF9D"   # 荧光毒液绿 (折线)
COLOR_TEXT_WHITE = "#EEEEEE"
COLOR_TEXT_GRAY = "#666666"
COLOR_SUCCESS = "#2ECC71"
COLOR_ERROR = "#FF2A6D"        # 故障红

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

# === 硬件底层工具 ===
class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

def get_free_ram_gb():
    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullAvailPhys / (1024**3)
    except: return 16.0

def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except: return False

def get_force_ssd_dir():
    """
    暴力寻找缓存目录策略：
    1. 优先检查 D: 和 E: (通常是数据盘)，只要有空间就用。
    2. 其次才扫描 F-Z。
    3. 坚决抵制 C 盘。
    """
    print("正在扫描最佳缓存位置...")
    
    # 优先列表 (根据你提供的截图，D和E是NVMe SSD)
    priority_drives = ["D", "E"]
    candidates = []

    # 1. 先看 D 和 E
    for d in priority_drives:
        root = f"{d}:\\"
        if os.path.exists(root):
            try:
                free = shutil.disk_usage(root).free
                if free > 10 * 1024 * 1024 * 1024: # 大于10G
                    candidates.append((root, free, 10)) # 权重10
            except: pass

    # 2. 如果 D/E 都不行，再找其他盘 (F-Z)
    if not candidates:
        for d in "FGHIJKLMNOPQRSTUVWXYZ":
            root = f"{d}:\\"
            if os.path.exists(root):
                try:
                    free = shutil.disk_usage(root).free
                    if free > 20 * 1024 * 1024 * 1024:
                        candidates.append((root, free, 1)) # 权重1
                except: pass

    # 3. 排序：先按权重，再按剩余空间
    candidates.sort(key=lambda x: (x[2], x[1]), reverse=True)

    if candidates:
        best_drive = candidates[0][0]
        print(f"选中缓存盘: {best_drive}")
    else:
        # 实在没办法才用C盘
        best_drive = "C:\\"
        print("警告: 未发现合适的非C盘，被迫使用系统盘")

    temp_path = os.path.join(best_drive, "_Ultra_Temp_Cache_")
    if not os.path.exists(temp_path):
        os.makedirs(temp_path, exist_ok=True)
    return temp_path

# === 核心组件：高帧率平滑示波器 ===
class SmoothScope(ctk.CTkCanvas):
    def __init__(self, master, height=140, **kwargs):
        super().__init__(master, height=height, bg="#000", highlightthickness=0, **kwargs)
        self.height = height
        self.points = deque([0]*100, maxlen=100) # 初始填满0
        self.target_val = 0
        self.current_val = 0
        self.anim_running = False
        
    def push_data(self, val):
        self.target_val = val
        
    def start_animation(self):
        if not self.anim_running:
            self.anim_running = True
            self.animate()
            
    def stop_animation(self):
        self.anim_running = False
        
    def animate(self):
        if not self.anim_running: return
        
        # 1. 数据平滑插值 (Lerp)
        # 让 current_val 慢慢接近 target_val，形成丝滑感
        self.current_val += (self.target_val - self.current_val) * 0.2
        
        # 2. 滚动数组
        self.points.append(self.current_val)
        
        # 3. 绘制
        self.draw()
        
        # 4. 60 FPS 循环
        self.after(16, self.animate)
        
    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.height
        
        # 动态缩放 Y 轴
        max_v = max(max(self.points), 10) # 最小量程10
        scale = (h - 20) / max_v
        
        # 绘制网格 (Cyberpunk Grid)
        self.create_line(0, h/2, w, h/2, fill="#1a1a1a", width=1)
        self.create_line(0, h*0.25, w, h*0.25, fill="#1a1a1a", width=1)
        self.create_line(0, h*0.75, w, h*0.75, fill="#1a1a1a", width=1)
        for i in range(1, 5):
            x = w * (i/5)
            self.create_line(x, 0, x, h, fill="#1a1a1a", width=1)

        # 生成坐标点
        coords = []
        step = w / (len(self.points) - 1)
        
        # 绘制填充区域 (Area Chart)
        poly_coords = [0, h]
        for i, v in enumerate(self.points):
            x = i * step
            y = h - (v * scale) - 5 # 留底边
            coords.extend([x, y])
            poly_coords.extend([x, y])
        poly_coords.extend([w, h])
        
        # 模拟荧光效果：画一条粗的半透明线（用深绿），再画一条细的高亮线
        # self.create_polygon(poly_coords, fill="#003311", outline="") # Tkinter不支持Alpha，用深色模拟
        self.create_line(coords, fill="#005522", width=4, smooth=True) # 光晕
        self.create_line(coords, fill=COLOR_CHART_LINE, width=1.5, smooth=True) # 核心线

# === 监控通道 ===
class MonitorChannel(ctk.CTkFrame):
    def __init__(self, master, ch_id, **kwargs):
        super().__init__(master, fg_color=COLOR_PANEL_RIGHT, corner_radius=8, border_width=1, border_color="#222", **kwargs)
        
        # 头部信息
        head = ctk.CTkFrame(self, fg_color="transparent", height=25)
        head.pack(fill="x", padx=12, pady=8)
        
        self.lbl_title = ctk.CTkLabel(head, text=f"CHANNEL {ch_id} // STANDBY", font=("Consolas", 12, "bold"), text_color="#444")
        self.lbl_title.pack(side="left")
        
        self.lbl_tag = ctk.CTkLabel(head, text="--", font=("Arial", 10), text_color="#333")
        self.lbl_tag.pack(side="right")
        
        # 示波器
        self.scope = SmoothScope(self, height=130)
        self.scope.pack(fill="both", expand=True, padx=2, pady=2)
        
        # 底部数据
        btm = ctk.CTkFrame(self, fg_color="transparent")
        btm.pack(fill="x", padx=12, pady=8)
        
        self.lbl_fps = ctk.CTkLabel(btm, text="000", font=("Impact", 24), text_color="#333")
        self.lbl_fps.pack(side="left")
        ctk.CTkLabel(btm, text="FPS", font=("Arial", 10), text_color="#444").pack(side="left", padx=(5,0), pady=(10,0))
        
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 16, "bold"), text_color="#333")
        self.lbl_prog.pack(side="right")

    def active(self, name, tag):
        self.lbl_title.configure(text=f"ACTIVE // {name[:20]}...", text_color=COLOR_ACCENT)
        self.lbl_tag.configure(text=f"[{tag}]", text_color="#FFF")
        self.lbl_fps.configure(text_color=COLOR_CHART_LINE)
        self.lbl_prog.configure(text_color="#FFF")
        self.scope.start_animation()

    def update(self, fps, prog):
        self.scope.push_data(fps)
        self.lbl_fps.configure(text=f"{fps:03d}")
        self.lbl_prog.configure(text=f"{int(prog*100)}%")

    def reset(self):
        self.lbl_title.configure(text="CHANNEL // STANDBY", text_color="#444")
        self.lbl_tag.configure(text="--", text_color="#333")
        self.lbl_fps.configure(text="000", text_color="#333")
        self.lbl_prog.configure(text="0%", text_color="#333")
        self.scope.push_data(0)
        self.scope.stop_animation()

# === 任务卡片 ===
class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color="#222", corner_radius=6, **kwargs)
        
        self.grid_columnconfigure(1, weight=1)
        
        # 序号
        ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 18), text_color="#444").grid(row=0, column=0, rowspan=2, padx=10)
        
        # 文件名
        ctk.CTkLabel(self, text=os.path.basename(filepath), font=("Arial", 11, "bold"), text_color="#DDD", anchor="w").grid(row=0, column=1, sticky="w", padx=5, pady=(5,0))
        
        # 状态
        self.lbl_status = ctk.CTkLabel(self, text="WAITING", font=("Arial", 9), text_color="#666", anchor="w")
        self.lbl_status.grid(row=1, column=1, sticky="w", padx=5, pady=(0,5))
        
        # 进度条
        self.progress = ctk.CTkProgressBar(self, height=2, corner_radius=0, progress_color=COLOR_ACCENT, fg_color="#333")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew")

    def set_status(self, text, col="#666"):
        self.lbl_status.configure(text=text, text_color=col)
    def set_progress(self, val):
        self.progress.set(val)

# === 主程序 ===
class UltraEncoderApp(DnDWindow):
    def __init__(self):
        super().__init__()
        self.title("Ultra Encoder v10 - Final Edition")
        self.geometry("1280x850")
        self.configure(fg_color=COLOR_BG_MAIN)
        
        # 状态
        self.file_queue = [] 
        self.task_widgets = {}
        self.active_procs = []
        self.temp_files = set()
        self.running = False
        self.stop_flag = False
        
        # 通道管理
        self.slot_lock = threading.Lock()
        self.slots = [0, 1] # 双通道
        
        self.temp_dir = "" # 稍后初始化
        
        self.setup_ui()
        
        # 启动自检
        self.after(200, self.sys_check)
        
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    def sys_check(self):
        # 1. 检查FFmpeg
        if not check_ffmpeg():
            messagebox.showerror("Fatal Error", "FFmpeg 未找到！\n请安装 FFmpeg 并配置环境变量。")
            self.btn_run.configure(state="disabled", text="FFMPEG MISSING")
            return
        
        # 2. 扫描硬盘 (后台)
        threading.Thread(target=self.scan_disk, daemon=True).start()
        
        # 3. 启动预读 (后台)
        threading.Thread(target=self.preload_worker, daemon=True).start()

    def scan_disk(self):
        path = get_force_ssd_dir()
        self.temp_dir = path
        self.after(0, lambda: self.btn_cache.configure(text=f"CACHE: {path}"))

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=7)
        self.grid_rowconfigure(0, weight=1)

        # === 左边栏 (控制台) ===
        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        
        # 标题
        ctk.CTkLabel(left, text="ULTRA ENCODER", font=("Impact", 24), text_color="#FFF").pack(anchor="w", padx=20, pady=(25, 5))
        ctk.CTkLabel(left, text="v10.0 // STABLE", font=("Arial", 10), text_color=COLOR_ACCENT).pack(anchor="w", padx=22)
        
        # 缓存显示
        self.btn_cache = ctk.CTkButton(left, text="SCANNING DRIVES...", fg_color="#222", hover_color="#333", 
                                     font=("Consolas", 10), height=24, anchor="w", command=self.open_cache)
        self.btn_cache.pack(fill="x", padx=20, pady=(15, 10))
        
        # 按钮组
        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(btns, text="+ IMPORT", width=80, fg_color="#333", command=self.add_file).pack(side="left", padx=2)
        ctk.CTkButton(btns, text="CLEAR", width=60, fg_color="#333", hover_color=COLOR_ERROR, command=self.clear_all).pack(side="left", padx=2)
        
        # 列表
        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=5, pady=10)
        
        # 底部参数
        l_btm = ctk.CTkFrame(left, fg_color="#111", corner_radius=0)
        l_btm.pack(fill="x", side="bottom")
        
        # CRF
        p_box = ctk.CTkFrame(l_btm, fg_color="transparent")
        p_box.pack(fill="x", padx=20, pady=15)
        self.crf_var = ctk.IntVar(value=23)
        ctk.CTkLabel(p_box, text="CRF").pack(side="left")
        ctk.CTkSlider(p_box, from_=0, to=51, variable=self.crf_var, width=120, progress_color=COLOR_ACCENT).pack(side="left", padx=10)
        ctk.CTkLabel(p_box, textvariable=self.crf_var, font=("Arial", 12, "bold"), text_color=COLOR_ACCENT).pack(side="left")
        
        # GPU Switch
        self.gpu_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(p_box, text="RTX 4080", variable=self.gpu_var, progress_color=COLOR_ACCENT, button_color="#FFF").pack(side="right")
        
        # 启动按钮
        act_box = ctk.CTkFrame(l_btm, fg_color="transparent")
        act_box.pack(fill="x", padx=20, pady=(0, 25))
        self.btn_stop = ctk.CTkButton(act_box, text="ABORT", fg_color="#222", width=60, hover_color=COLOR_ERROR, state="disabled", command=self.stop)
        self.btn_stop.pack(side="left")
        self.btn_run = ctk.CTkButton(act_box, text="INITIALIZE SYSTEM", font=("Arial", 13, "bold"), fg_color=COLOR_ACCENT, text_color="#000", command=self.run)
        self.btn_run.pack(side="right", fill="x", expand=True, padx=(10,0))

        # === 右边栏 (监控室) ===
        right = ctk.CTkFrame(self, fg_color=COLOR_PANEL_RIGHT, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        
        ctk.CTkLabel(right, text="SYSTEM MONITOR", font=("Arial Black", 16), text_color="#333").pack(anchor="w", padx=30, pady=(25, 10))
        
        # 通道
        self.ch_uis = []
        for i in range(2):
            ch = MonitorChannel(right, i+1)
            ch.pack(fill="both", expand=True, padx=30, pady=10)
            self.ch_uis.append(ch)
            
        # 底部留白
        ctk.CTkFrame(right, fg_color="transparent", height=20).pack()

    # === 逻辑 ===
    def open_cache(self):
        if self.temp_dir and os.path.exists(self.temp_dir):
            os.startfile(self.temp_dir)

    def add_file(self): self.add_list(filedialog.askopenfilenames())
    def drop_file(self, event): self.add_list(self.tk.splitlist(event.data))
    
    def add_list(self, files):
        for f in files:
            if f not in self.file_queue and f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi')):
                self.file_queue.append(f)
                card = TaskCard(self.scroll, len(self.file_queue), f)
                card.pack(fill="x", pady=2)
                self.task_widgets[f] = card

    def clear_all(self):
        if self.running: return
        for w in self.task_widgets.values(): w.destroy()
        self.task_widgets.clear()
        self.file_queue.clear()

    # === 预读 ===
    def preload_worker(self):
        while True:
            if self.running and not self.stop_flag:
                if get_free_ram_gb() < 8.0: 
                    time.sleep(2); continue
                    
                target = None
                for f in self.file_queue:
                    w = self.task_widgets.get(f)
                    if w and w.lbl_status.cget("text") == "WAITING":
                        target = f; break
                
                if target:
                    w = self.task_widgets[target]
                    self.after(0, lambda: w.set_status("CACHING...", COLOR_ACCENT))
                    try:
                        sz = os.path.getsize(target)
                        if sz > 50*1024*1024:
                            with open(target, 'rb') as f:
                                while chunk := f.read(32*1024*1024):
                                    if self.stop_flag: return
                        self.after(0, lambda: w.set_status("READY", COLOR_SUCCESS))
                    except: pass
            else: time.sleep(1)

    # === 运行 ===
    def run(self):
        if not self.file_queue: return
        self.running = True
        self.stop_flag = False
        self.btn_run.configure(state="disabled", text="RUNNING")
        self.btn_stop.configure(state="normal", fg_color=COLOR_ERROR)
        
        # 重置通道
        self.slots = [0, 1]
        for ch in self.ch_uis: ch.reset()
        
        threading.Thread(target=self.engine, daemon=True).start()

    def stop(self):
        self.stop_flag = True
        for p in self.active_procs:
            try: p.terminate(); p.kill()
            except: pass
        
        # 清理垃圾
        threading.Thread(target=self.clean_junk).start()
        
        self.running = False
        self.btn_run.configure(state="normal", text="INITIALIZE SYSTEM")
        self.btn_stop.configure(state="disabled", fg_color="#222")

    def clean_junk(self):
        time.sleep(0.5)
        for f in list(self.temp_files):
            try: os.remove(f)
            except: pass
        self.temp_files.clear()

    def engine(self):
        workers = 2
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(self.process, f) for f in self.file_queue]
                for fut in futures:
                    if self.stop_flag: break
                    try: fut.result()
                    except Exception as e: print(e)
        except: pass
        
        if not self.stop_flag:
            self.after(0, lambda: messagebox.showinfo("DONE", "All tasks finished."))
            self.running = False
            self.after(0, lambda: [
                self.btn_run.configure(state="normal", text="INITIALIZE SYSTEM"),
                self.btn_stop.configure(state="disabled", fg_color="#222")
            ])

    def process(self, input_file):
        if self.stop_flag: return
        
        # 获取显示通道
        my_slot = None
        with self.slot_lock:
            if self.slots: my_slot = self.slots.pop(0)
            
        if my_slot is None: return # 理论上不会发生

        ch_ui = self.ch_uis[my_slot]
        card = self.task_widgets[input_file]
        
        # 路径准备
        fname = os.path.basename(input_file)
        name, ext = os.path.splitext(fname)
        
        # !!! 之前报错的罪魁祸首在此 !!!
        temp_out = os.path.join(self.temp_dir, f"TMP_{name}{ext}")
        final_out = os.path.join(os.path.dirname(input_file), f"{name}_V10{ext}")
        
        self.temp_files.add(temp_out)
        
        # UI 启动
        self.after(0, lambda: [card.set_status("ENCODING", "#FFF"), 
                               ch_ui.active(fname, "GPU" if self.gpu_var.get() else "CPU")])
        
        # 命令
        cmd = ["ffmpeg", "-y", "-i", input_file]
        if self.gpu_var.get():
            cmd.extend(["-c:v", "h264_nvenc", "-pix_fmt", "yuv420p", "-rc", "vbr", "-cq", str(self.crf_var.get()), 
                        "-preset", "p6", "-spatial-aq", "1"])
        else:
            cmd.extend(["-c:v", "libx264", "-crf", str(self.crf_var.get()), "-preset", "medium"])
        
        cmd.extend(["-c:a", "copy", temp_out]) # 这里修复了变量名

        # 执行
        try:
            duration = self.get_dur(input_file)
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                    universal_newlines=True, encoding='utf-8', errors='ignore', startupinfo=si)
            self.active_procs.append(proc)
            
            last_t = 0
            for line in proc.stdout:
                if self.stop_flag: break
                if "time=" in line and duration > 0:
                    tm = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
                    fm = re.search(r"fps=\s*(\d+)", line)
                    if tm:
                        h, m, s = map(float, tm.groups())
                        prog = (h*3600 + m*60 + s) / duration
                        fps = int(fm.group(1)) if fm else 0
                        
                        now = time.time()
                        if now - last_t > 0.05: # 提高UI刷新率到20Hz
                            self.after(0, lambda p=prog: card.set_progress(p))
                            self.after(0, lambda f=fps, p=prog: ch_ui.update(f, p))
                            last_t = now
            
            proc.wait()
            if proc in self.active_procs: self.active_procs.remove(proc)

            if not self.stop_flag and proc.returncode == 0:
                if os.path.exists(temp_out): shutil.move(temp_out, final_out)
                if temp_out in self.temp_files: self.temp_files.remove(temp_out)
                
                orig = os.path.getsize(input_file)
                new = os.path.getsize(final_out)
                sv = 100 - (new/orig*100)
                self.after(0, lambda: [card.set_status(f"DONE -{sv:.1f}%", COLOR_SUCCESS), card.set_progress(1)])
            else:
                self.after(0, lambda: card.set_status("FAILED", COLOR_ERROR))

        except Exception as e:
            print(e)
            self.after(0, lambda: card.set_status("ERROR", COLOR_ERROR))
        
        # 释放通道
        self.after(0, ch_ui.reset)
        with self.slot_lock:
            self.slots.append(my_slot)
            self.slots.sort()

    def get_dur(self, f):
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", f]
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return float(subprocess.check_output(cmd, startupinfo=si).strip())
        except: return 0

if __name__ == "__main__":
    app = UltraEncoderApp()
    app.mainloop()

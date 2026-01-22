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

# === 全局视觉配置 ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# 旗舰版配色 (Deep Space)
COLOR_BG_MAIN = "#121212"
COLOR_PANEL_LEFT = "#1a1a1a"
COLOR_PANEL_RIGHT = "#0f0f0f"
COLOR_CARD = "#2d2d2d"         # 明显的卡片色
COLOR_ACCENT = "#3B8ED0"
COLOR_ACCENT_HOVER = "#36719f"
COLOR_CHART_LINE = "#00E676"   # 荧光绿
COLOR_TEXT_WHITE = "#FFFFFF"
COLOR_TEXT_GRAY = "#999999"
COLOR_SUCCESS = "#2ECC71"
COLOR_ERROR = "#FF4757"

# 拖拽支持
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

# === 增强组件：悬浮提示 (Tooltip) ===
class CTkToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tooltip_window or not self.text: return
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(tw, text=self.text, justify='left',
                       background="#333333", foreground="#ffffff",
                       relief='solid', borderwidth=1,
                       font=("微软雅黑", 9))
        label.pack(ipadx=5, ipady=3)

    def hide_tip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

# === 硬件底层 ===
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
    drives = ["D", "E"]
    best = None
    for d in drives:
        root = f"{d}:\\"
        if os.path.exists(root):
            try:
                if shutil.disk_usage(root).free > 20*1024**3:
                    best = root
                    break
            except: pass
    if not best: best = "C:\\" 
    path = os.path.join(best, "_Ultra_Temp_Cache_")
    os.makedirs(path, exist_ok=True)
    return path

# === 组件：丝滑示波器 ===
class InfinityScope(ctk.CTkCanvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=COLOR_PANEL_RIGHT, highlightthickness=0, **kwargs)
        self.points = [] 
        self.max_val = 10
        self.bind("<Configure>", self.draw) # 窗口大小改变时重绘
        
    def add_point(self, val):
        self.points.append(val)
        self.draw()
        
    def clear(self):
        self.points = []
        self.max_val = 10
        self.delete("all")
        
    def draw(self, event=None):
        self.delete("all")
        if not self.points: return
        
        w = self.winfo_width()
        h = self.winfo_height()
        n = len(self.points)
        
        current_max = max(self.points)
        if current_max > self.max_val: self.max_val = current_max
        else: self.max_val = max(10, self.max_val * 0.99)
        
        scale_y = (h - 20) / self.max_val
        
        # 动态网格
        self.create_line(0, h/2, w, h/2, fill="#2a2a2a", dash=(4,4))
        self.create_line(0, h*0.25, w, h*0.25, fill="#2a2a2a", dash=(2,8))
        self.create_line(0, h*0.75, w, h*0.75, fill="#2a2a2a", dash=(2,8))

        if n < 2: return
        
        step_x = w / (n - 1)
        coords = []
        
        for i, val in enumerate(self.points):
            x = i * step_x
            y = h - (val * scale_y) - 10
            coords.extend([x, y])
            
        if len(coords) >= 4:
            self.create_line(coords, fill=COLOR_CHART_LINE, width=2, smooth=True)
            # 闭合区域做渐变填充模拟
            poly = [0, h] + coords + [w, h]
            # self.create_polygon(poly, fill="#113322", outline="") # Tkinter暂不支持alpha，暂略

# === 监控通道 (液态布局) ===
class MonitorChannel(ctk.CTkFrame):
    def __init__(self, master, ch_id, **kwargs):
        super().__init__(master, fg_color="#181818", corner_radius=10, border_width=1, border_color="#333", **kwargs)
        
        # 头部
        head = ctk.CTkFrame(self, fg_color="transparent", height=25)
        head.pack(fill="x", padx=15, pady=(10,0))
        self.lbl_title = ctk.CTkLabel(head, text=f"通道 {ch_id} · 空闲", font=("微软雅黑", 12, "bold"), text_color="#555")
        self.lbl_title.pack(side="left")
        self.lbl_info = ctk.CTkLabel(head, text="等待任务分配...", font=("Arial", 11), text_color="#444")
        self.lbl_info.pack(side="right")
        
        # 示波器 (expand=True 是关键)
        self.scope = InfinityScope(self)
        self.scope.pack(fill="both", expand=True, padx=2, pady=5)
        
        # 底部数据
        btm = ctk.CTkFrame(self, fg_color="transparent")
        btm.pack(fill="x", padx=15, pady=(0,10))
        self.lbl_fps = ctk.CTkLabel(btm, text="0", font=("Impact", 20), text_color="#333")
        self.lbl_fps.pack(side="left")
        ctk.CTkLabel(btm, text="FPS", font=("Arial", 10, "bold"), text_color="#444").pack(side="left", padx=(5,0), pady=(8,0))
        self.lbl_prog = ctk.CTkLabel(btm, text="0%", font=("Arial", 14, "bold"), text_color="#333")
        self.lbl_prog.pack(side="right")

    def activate(self, filename, tag):
        self.lbl_title.configure(text=f"正在运行: {filename[:25]}...", text_color=COLOR_ACCENT)
        self.lbl_info.configure(text=tag, text_color="#AAA")
        self.lbl_fps.configure(text_color="#FFF")
        self.lbl_prog.configure(text_color=COLOR_ACCENT)
        self.scope.clear()

    def update_data(self, fps, prog):
        self.scope.add_point(fps)
        self.lbl_fps.configure(text=f"{fps}")
        self.lbl_prog.configure(text=f"{int(prog*100)}%")

    def reset(self):
        self.lbl_title.configure(text="通道 · 空闲", text_color="#555")
        self.lbl_info.configure(text="等待任务分配...", text_color="#444")
        self.lbl_fps.configure(text="0", text_color="#333")
        self.lbl_prog.configure(text="0%", text_color="#333")
        self.scope.clear()

# === 任务卡片 (大气风格) ===
class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        # 使用更亮的背景色，做出卡片感
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=10, border_width=0, **kwargs)
        self.grid_columnconfigure(1, weight=1)
        
        # 序号 (大字体)
        ctk.CTkLabel(self, text=f"{index:02d}", font=("Impact", 20), text_color="#555").grid(row=0, column=0, rowspan=2, padx=15)
        
        # 文件名
        ctk.CTkLabel(self, text=os.path.basename(filepath), font=("微软雅黑", 12, "bold"), text_color="#EEE", anchor="w").grid(row=0, column=1, sticky="w", padx=5, pady=(8,0))
        
        # 状态
        self.lbl_status = ctk.CTkLabel(self, text="等待处理", font=("Arial", 10), text_color="#888", anchor="w")
        self.lbl_status.grid(row=1, column=1, sticky="w", padx=5, pady=(0,8))
        
        # 进度条 (细条，贴底)
        self.progress = ctk.CTkProgressBar(self, height=4, corner_radius=0, progress_color=COLOR_ACCENT, fg_color="#444")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew")

    def set_status(self, text, color="#888"):
        self.lbl_status.configure(text=text, text_color=color)
    def set_progress(self, val):
        self.progress.set(val)

# === 主程序 ===
class UltraEncoderApp(DnDWindow):
    def __init__(self):
        super().__init__()
        self.title("Ultra Encoder v14 - Liquid Layout")
        self.geometry("1300x850")
        self.configure(fg_color=COLOR_BG_MAIN)
        
        self.file_queue = [] 
        self.task_widgets = {}
        self.active_procs = []
        self.temp_files = set()
        self.running = False
        self.stop_flag = False
        self.slot_lock = threading.Lock()
        
        self.monitor_slots = []
        self.available_indices = []
        self.current_workers = 2
        self.temp_dir = ""
        
        self.setup_ui()
        self.after(200, self.sys_check)
        
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    def sys_check(self):
        self.set_status_bar("正在自检环境...")
        if not check_ffmpeg():
            messagebox.showerror("Fatal Error", "找不到 FFmpeg！\n请确保已安装。")
            return
        threading.Thread(target=self.scan_disk, daemon=True).start()
        threading.Thread(target=self.preload_worker, daemon=True).start()

    def scan_disk(self):
        self.set_status_bar("扫描高性能缓存中...")
        path = get_force_ssd_dir()
        self.temp_dir = path
        self.after(0, lambda: self.btn_cache.configure(text=f"SSD Cache: {path}"))
        self.set_status_bar("系统就绪")

    def set_status_bar(self, text):
        self.lbl_global_status.configure(text=f"STATUS: {text}")

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=3) # 左侧
        self.grid_columnconfigure(1, weight=7) # 右侧
        self.grid_rowconfigure(0, weight=1)

        # === 左侧面板 (毛玻璃深色) ===
        left = ctk.CTkFrame(self, fg_color=COLOR_PANEL_LEFT, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew")
        
        # 1. 顶部标题与缓存
        l_head = ctk.CTkFrame(left, fg_color="transparent")
        l_head.pack(fill="x", padx=20, pady=(25, 10))
        ctk.CTkLabel(l_head, text="ULTRA ENCODER", font=("Impact", 26), text_color="#FFF").pack(anchor="w")
        ctk.CTkLabel(l_head, text="v14.0 // PROFESSIONAL", font=("Arial", 10, "bold"), text_color=COLOR_ACCENT).pack(anchor="w")
        
        self.btn_cache = ctk.CTkButton(left, text="Checking...", fg_color="#252525", hover_color="#333", 
                                     text_color="#AAA", font=("Consolas", 10), height=28, corner_radius=14, command=self.open_cache)
        self.btn_cache.pack(fill="x", padx=20, pady=(10, 10))
        
        # 2. 列表操作
        tools = ctk.CTkFrame(left, fg_color="transparent")
        tools.pack(fill="x", padx=15, pady=5)
        # 大圆角按钮
        ctk.CTkButton(tools, text="+ 导入视频", width=120, height=36, corner_radius=18, 
                     fg_color="#333", hover_color="#444", command=self.add_file).pack(side="left", padx=5)
        ctk.CTkButton(tools, text="清空", width=60, height=36, corner_radius=18, 
                     fg_color="transparent", border_width=1, border_color="#444", hover_color="#331111", text_color="#CCC", command=self.clear_all).pack(side="left", padx=5)

        # 3. 任务列表
        self.scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        # 4. 底部参数区
        l_btm = ctk.CTkFrame(left, fg_color="#222", corner_radius=20)
        l_btm.pack(fill="x", padx=15, pady=20, ipadx=5, ipady=5)
        
        # 参数: 编码格式
        row1 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row1.pack(fill="x", pady=10, padx=10)
        
        lbl_fmt = ctk.CTkLabel(row1, text="编码格式 ❓", font=("微软雅黑", 11, "bold"), text_color="#888", cursor="hand2")
        lbl_fmt.pack(anchor="w")
        CTkToolTip(lbl_fmt, "H.264 (AVC): 兼容性最好，适合所有设备。\nH.265 (HEVC): 压缩率高，同画质体积减半，推荐。")
        
        self.codec_var = ctk.StringVar(value="H.265")
        self.seg_codec = ctk.CTkSegmentedButton(row1, values=["H.264", "H.265"], variable=self.codec_var, 
                                              selected_color=COLOR_ACCENT, corner_radius=10)
        self.seg_codec.pack(fill="x", pady=5)
        
        # 参数: 画质 (CRF)
        row2 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row2.pack(fill="x", pady=5, padx=10)
        
        lbl_crf = ctk.CTkLabel(row2, text="画质 (CRF) ❓", font=("微软雅黑", 11, "bold"), text_color="#888", cursor="hand2")
        lbl_crf.pack(anchor="w")
        CTkToolTip(lbl_crf, "CRF 数值越小画质越高。\n18: 极高画质\n23: 标准 (推荐)\n28: 较低画质")
        
        crf_box = ctk.CTkFrame(row2, fg_color="transparent")
        crf_box.pack(fill="x")
        self.crf_var = ctk.IntVar(value=23)
        ctk.CTkSlider(crf_box, from_=0, to=51, variable=self.crf_var, progress_color=COLOR_ACCENT).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(crf_box, textvariable=self.crf_var, width=25, font=("Arial", 12, "bold"), text_color=COLOR_ACCENT).pack(side="right")
        
        # 参数: 硬件与并发
        row3 = ctk.CTkFrame(l_btm, fg_color="transparent")
        row3.pack(fill="x", pady=10, padx=10)
        
        # 并发
        w_box = ctk.CTkFrame(row3, fg_color="transparent")
        w_box.pack(side="left")
        lbl_work = ctk.CTkLabel(w_box, text="并发任务 ❓", font=("微软雅黑", 11), text_color="#888", cursor="hand2")
        lbl_work.pack(anchor="w")
        CTkToolTip(lbl_work, "决定同时处理几个视频。\n建议: 2-3 个能发挥最佳性能。\n修改后右侧图表会自动更新。")
        
        self.worker_var = ctk.StringVar(value="2")
        self.seg_worker = ctk.CTkSegmentedButton(w_box, values=["1", "2", "3", "4"], variable=self.worker_var, 
                                               width=100, corner_radius=10, command=self.update_monitor_layout)
        self.seg_worker.pack(pady=2)
        
        # GPU开关
        self.gpu_var = ctk.BooleanVar(value=True)
        g_sw = ctk.CTkSwitch(row3, text="RTX 4080", variable=self.gpu_var, font=("Arial", 11, "bold"), progress_color=COLOR_ACCENT)
        g_sw.pack(side="right", pady=10)
        CTkToolTip(g_sw, "开启后使用 NVENC 硬件编码，速度极快。\n关闭则使用 CPU 编码。")

        # 启动区
        self.btn_run = ctk.CTkButton(left, text="启动引擎", height=45, corner_radius=22, 
                                   font=("微软雅黑", 15, "bold"), fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, 
                                   text_color="#000", command=self.run)
        self.btn_run.pack(fill="x", padx=20, pady=(0, 5))
        
        self.btn_stop = ctk.CTkButton(left, text="停止", height=30, corner_radius=15, 
                                    fg_color="transparent", text_color=COLOR_ERROR, hover_color="#221111", 
                                    state="disabled", command=self.stop)
        self.btn_stop.pack(fill="x", padx=20, pady=(0, 20))

        # === 右侧面板 (液态监控) ===
        right = ctk.CTkFrame(self, fg_color=COLOR_PANEL_RIGHT, corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        
        # 顶部状态
        r_head = ctk.CTkFrame(right, fg_color="transparent")
        r_head.pack(fill="x", padx=30, pady=(25, 10))
        ctk.CTkLabel(r_head, text="LIVE MONITOR", font=("Impact", 20), text_color="#333").pack(side="left")
        self.lbl_global_status = ctk.CTkLabel(r_head, text="SYSTEM READY", font=("Arial", 11), text_color="#555")
        self.lbl_global_status.pack(side="right")
        
        # 监控容器 (不使用 ScrollFrame，使用普通 Frame 配合 pack fill 来实现液态布局)
        self.monitor_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.monitor_frame.pack(fill="both", expand=True, padx=25, pady=(0, 25))
        
        self.update_monitor_layout()

    # === 核心逻辑 ===
    def update_monitor_layout(self, val=None):
        if self.running:
            messagebox.showwarning("提示", "运行中无法修改布局，请先停止。")
            self.seg_worker.set(str(self.current_workers))
            return

        try: n = int(self.worker_var.get())
        except: n = 2
        self.current_workers = n
        
        # 清空
        for ch in self.monitor_slots: ch.destroy()
        self.monitor_slots.clear()
        
        # 液态填充：pack(expand=True) 是关键
        for i in range(n):
            ch = MonitorChannel(self.monitor_frame, i+1)
            ch.pack(fill="both", expand=True, pady=5)
            self.monitor_slots.append(ch)

    def open_cache(self):
        if self.temp_dir and os.path.exists(self.temp_dir): os.startfile(self.temp_dir)
    def add_file(self): self.add_list(filedialog.askopenfilenames())
    def drop_file(self, event): self.add_list(self.tk.splitlist(event.data))
    
    def add_list(self, files):
        for f in files:
            if f not in self.file_queue and f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi')):
                self.file_queue.append(f)
                card = TaskCard(self.scroll, len(self.file_queue), f)
                card.pack(fill="x", pady=4) # 增加间距
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
                    if w and w.lbl_status.cget("text") == "等待处理":
                        target = f; break
                if target:
                    w = self.task_widgets[target]
                    self.after(0, lambda: w.set_status("正在预读...", COLOR_ACCENT))
                    try:
                        sz = os.path.getsize(target)
                        if sz > 50*1024*1024:
                            with open(target, 'rb') as f:
                                while chunk := f.read(32*1024*1024):
                                    if self.stop_flag: return
                        self.after(0, lambda: w.set_status("就绪 (RAM)", COLOR_SUCCESS))
                    except: pass
            else: time.sleep(1)

    # === 执行 ===
    def run(self):
        if not self.file_queue: return
        self.running = True
        self.stop_flag = False
        
        self.btn_run.configure(state="disabled", text="运行中...")
        self.btn_stop.configure(state="normal")
        self.seg_worker.configure(state="disabled")
        self.seg_codec.configure(state="disabled")
        
        self.available_indices = list(range(self.current_workers))
        for ch in self.monitor_slots: ch.reset()
        
        threading.Thread(target=self.engine, daemon=True).start()

    def stop(self):
        self.stop_flag = True
        self.set_status_bar("正在强制停止...")
        for p in self.active_procs:
            try: p.terminate(); p.kill()
            except: pass
        threading.Thread(target=self.clean_junk).start()
        self.running = False
        self.reset_ui_state()

    def reset_ui_state(self):
        self.btn_run.configure(state="normal", text="启动引擎")
        self.btn_stop.configure(state="disabled")
        self.seg_worker.configure(state="normal")
        self.seg_codec.configure(state="normal")
        self.set_status_bar("就绪")

    def clean_junk(self):
        time.sleep(0.5)
        for f in list(self.temp_files):
            try: os.remove(f)
            except: pass
        self.temp_files.clear()

    def engine(self):
        try:
            with ThreadPoolExecutor(max_workers=self.current_workers) as pool:
                futures = [pool.submit(self.process, f) for f in self.file_queue]
                for fut in futures:
                    if self.stop_flag: break
                    try: fut.result()
                    except Exception as e: print(e)
        except: pass
        
        if not self.stop_flag:
            self.after(0, lambda: messagebox.showinfo("完成", "队列任务已全部结束。"))
            self.running = False
            self.after(0, self.reset_ui_state)

    def scroll_to_card(self, card):
        try: card.configure(fg_color="#383838") # 高亮
        except: pass

    def process(self, input_file):
        if self.stop_flag: return
        
        my_slot_idx = None
        while my_slot_idx is None and not self.stop_flag:
            with self.slot_lock:
                if self.available_indices:
                    my_slot_idx = self.available_indices.pop(0)
            if my_slot_idx is None: time.sleep(0.1)

        if self.stop_flag: return

        ch_ui = self.monitor_slots[my_slot_idx]
        card = self.task_widgets[input_file]
        
        self.after(0, lambda: self.scroll_to_card(card))
        self.set_status_bar(f"正在处理: {os.path.basename(input_file)}")

        fname = os.path.basename(input_file)
        name, ext = os.path.splitext(fname)
        
        codec_sel = self.codec_var.get()
        is_h265 = "H.265" in codec_sel
        tag = "HEVC" if is_h265 else "AVC"
        
        temp_out = os.path.join(self.temp_dir, f"TMP_{name}_{tag}{ext}")
        final_out = os.path.join(os.path.dirname(input_file), f"{name}_{tag}_V14{ext}")
        self.temp_files.add(temp_out)
        
        self.after(0, lambda: card.set_status("压制中...", COLOR_ACCENT))
        self.after(0, lambda: ch_ui.activate(fname, f"{tag} | {'GPU' if self.gpu_var.get() else 'CPU'}"))
        
        cmd = ["ffmpeg", "-y", "-i", input_file]
        crf = str(self.crf_var.get())
        
        if self.gpu_var.get():
            enc = "hevc_nvenc" if is_h265 else "h264_nvenc"
            cmd.extend(["-c:v", enc, "-pix_fmt", "yuv420p", "-rc", "vbr", "-cq", crf, "-preset", "p6", "-spatial-aq", "1"])
        else:
            enc = "libx265" if is_h265 else "libx264"
            cmd.extend(["-c:v", enc, "-crf", crf, "-preset", "medium"])
        
        cmd.extend(["-c:a", "copy", temp_out])

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
                        if now - last_t > 0.1: 
                            self.after(0, lambda p=prog: card.set_progress(p))
                            self.after(0, lambda f=fps, p=prog: ch_ui.update_data(f, p))
                            last_t = now
            
            proc.wait()
            if proc in self.active_procs: self.active_procs.remove(proc)

            if not self.stop_flag and proc.returncode == 0:
                if os.path.exists(temp_out): shutil.move(temp_out, final_out)
                if temp_out in self.temp_files: self.temp_files.remove(temp_out)
                
                orig = os.path.getsize(input_file)
                new = os.path.getsize(final_out)
                sv = 100 - (new/orig*100)
                self.after(0, lambda: [card.set_status(f"完成 -{sv:.1f}%", COLOR_SUCCESS), card.set_progress(1)])
            else:
                self.after(0, lambda: card.set_status("失败", COLOR_ERROR))

        except Exception as e:
            print(e)
            self.after(0, lambda: card.set_status("错误", COLOR_ERROR))
        
        self.after(0, ch_ui.reset)
        with self.slot_lock:
            self.available_indices.append(my_slot_idx)
            self.available_indices.sort()
            
        self.set_status_bar("就绪")

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

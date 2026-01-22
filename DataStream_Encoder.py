import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import threading
import re
import os
import time
from concurrent.futures import ThreadPoolExecutor

# === 现代化 UI 配置 ===
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# 颜色常量 (Cyberpunk/Modern Palette)
COLOR_BG = "#1a1a1a"
COLOR_CARD = "#2b2b2b"
COLOR_ACCENT = "#3B8ED0"
COLOR_SUCCESS = "#2ECC71"
COLOR_ERROR = "#E74C3C"
COLOR_TEXT_GRAY = "#AAAAAA"
FONT_MAIN = ("Roboto Medium", 12)
FONT_MONO = ("Consolas", 11)

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

# === 辅助函数：格式化文件大小 ===
def format_size(size_bytes):
    if size_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(os.math.floor(os.math.log(size_bytes, 1024)))
    p = os.math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])

# === 自定义组件：任务卡片 (Task Card) ===
class TaskCard(ctk.CTkFrame):
    def __init__(self, master, index, filepath, **kwargs):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=10, border_width=1, border_color="#333", **kwargs)
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        
        # 布局网格
        self.grid_columnconfigure(1, weight=1) # 中间撑开
        
        # 1. 序号与图标
        self.lbl_idx = ctk.CTkLabel(self, text=f"{index}", font=("Arial", 14, "bold"), text_color="#555", width=30)
        self.lbl_idx.grid(row=0, column=0, rowspan=2, padx=10, pady=5)
        
        # 2. 文件名
        self.lbl_name = ctk.CTkLabel(self, text=self.filename, font=FONT_MAIN, anchor="w", text_color="white")
        self.lbl_name.grid(row=0, column=1, sticky="w", padx=5, pady=(8, 0))
        
        # 3. 状态/进度文本
        self.lbl_status = ctk.CTkLabel(self, text="等待中...", font=("Arial", 11), text_color=COLOR_TEXT_GRAY, anchor="w")
        self.lbl_status.grid(row=1, column=1, sticky="w", padx=5, pady=(0, 8))
        
        # 4. 数据统计 (压制完成后显示)
        self.lbl_stats = ctk.CTkLabel(self, text="", font=FONT_MONO, text_color=COLOR_ACCENT, anchor="e")
        self.lbl_stats.grid(row=0, column=2, padx=15, pady=5, sticky="e")
        
        # 5. 进度条 (卡片底部)
        self.progress = ctk.CTkProgressBar(self, height=4, corner_radius=0, progress_color=COLOR_ACCENT)
        self.progress.set(0)
        self.progress.grid(row=2, column=0, columnspan=3, sticky="ew")

    def set_status(self, text, color=COLOR_TEXT_GRAY):
        self.lbl_status.configure(text=text, text_color=color)

    def set_progress(self, val, color=None):
        self.progress.set(val)
        if color: self.progress.configure(progress_color=color)

    def show_stats(self, original, compressed):
        if original > 0:
            ratio = (compressed / original) * 100
            saved = 100 - ratio
            text = f"{format_size(original)} ➔ {format_size(compressed)} (省 {saved:.1f}%)"
            self.lbl_stats.configure(text=text)
            
            # 颜色逻辑：压缩率越高越绿
            if saved > 50: self.lbl_stats.configure(text_color=COLOR_SUCCESS)
            elif saved > 0: self.lbl_stats.configure(text_color="#F1C40F")
            else: self.lbl_stats.configure(text_color=COLOR_ERROR) # 变大了

# === 主程序 ===
class ModernEncoderApp(DnDWindow):
    def __init__(self):
        super().__init__()
        
        self.title("Ultra Encoder Pro - i9 & 4080 终极版")
        self.geometry("1000x800")
        
        # 状态变量
        self.file_queue = [] 
        self.task_widgets = {} # 存储 TaskCard 对象 {filepath: widget}
        self.active_procs = []
        self.is_running = False
        self.stop_requested = False
        self.cpu_threads = os.cpu_count() or 16
        
        self.setup_ui()
        
        # 后台线程
        threading.Thread(target=self.preload_monitor, daemon=True).start()
        
        # 初始化设置
        self.recalc_concurrency()
        
        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.drop_file)

    def setup_ui(self):
        # === 顶部：控制面板 (Dashboard) ===
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=20, pady=20)
        
        # 标题与 Logo
        ctk.CTkLabel(top_frame, text="⚡ ULTRA ENCODER", font=("Arial Black", 20), text_color=COLOR_ACCENT).pack(side="left")
        
        # 硬件开关组
        switch_frame = ctk.CTkFrame(top_frame, fg_color="#222", corner_radius=20)
        switch_frame.pack(side="right")
        
        self.use_gpu = ctk.BooleanVar(value=True)
        self.gpu_switch = ctk.CTkSwitch(switch_frame, text="RTX 4080 加速", variable=self.use_gpu, command=self.on_mode_change, font=("Arial", 12, "bold"))
        self.gpu_switch.pack(side="left", padx=15, pady=8)
        
        self.preload_var = ctk.BooleanVar(value=True)
        self.preload_switch = ctk.CTkSwitch(switch_frame, text="64G 内存预读", variable=self.preload_var)
        self.preload_switch.pack(side="left", padx=15, pady=8)

        # === 中部：设置栏 ===
        settings_frame = ctk.CTkFrame(self, fg_color=COLOR_CARD)
        settings_frame.pack(fill="x", padx=20, pady=(0, 15))
        
        # 策略显示
        self.strategy_lbl = ctk.CTkLabel(settings_frame, text="初始化中...", text_color="#888", font=("Arial", 11))
        self.strategy_lbl.pack(side="top", anchor="w", padx=15, pady=(10, 0))

        # 参数控制行
        param_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        param_row.pack(fill="x", padx=10, pady=10)
        
        # CRF 滑块
        ctk.CTkLabel(param_row, text="CRF 画质:").pack(side="left", padx=5)
        self.crf_var = ctk.IntVar(value=23)
        self.crf_slider = ctk.CTkSlider(param_row, from_=0, to=51, variable=self.crf_var, number_of_steps=51, width=200)
        self.crf_slider.pack(side="left", padx=5)
        self.crf_label = ctk.CTkLabel(param_row, text="23", font=("Arial", 12, "bold"), width=30)
        self.crf_label.pack(side="left", padx=5)
        self.crf_var.trace("w", lambda *args: self.crf_label.configure(text=f"{self.crf_var.get()}"))
        
        # 下拉菜单
        self.codec_var = ctk.StringVar(value="HEVC (H.265)")
        ctk.CTkComboBox(param_row, values=["HEVC (H.265)", "AVC (H.264)"], variable=self.codec_var, width=140).pack(side="right", padx=5)
        
        self.preset_var = ctk.StringVar(value="p6 (Better)")
        self.preset_combo = ctk.CTkComboBox(param_row, values=["p7 (Best)", "p6 (Better)", "p4 (Medium)"], variable=self.preset_var, width=140)
        self.preset_combo.pack(side="right", padx=5)

        # === 核心：任务列表 (滚动区域) ===
        list_container = ctk.CTkFrame(self, fg_color="transparent")
        list_container.pack(fill="both", expand=True, padx=20, pady=5)
        
        # 列表头
        header = ctk.CTkFrame(list_container, fg_color="transparent", height=30)
        header.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(header, text="任务队列", font=("Arial", 14, "bold")).pack(side="left")
        
        # 操作按钮
        ctk.CTkButton(header, text="📂 打开源目录", command=self.open_source_dir, width=100, fg_color="#444", hover_color="#555").pack(side="right", padx=5)
        ctk.CTkButton(header, text="清空", command=self.clear_queue, width=60, fg_color=COLOR_ERROR, hover_color="#C0392B").pack(side="right", padx=5)
        ctk.CTkButton(header, text="+ 添加文件", command=self.add_files, width=100).pack(side="right", padx=5)

        # 滚动区域
        self.scroll_frame = ctk.CTkScrollableFrame(list_container, fg_color="transparent", label_text="")
        self.scroll_frame.pack(fill="both", expand=True)

        # === 底部：总控栏 ===
        bottom_bar = ctk.CTkFrame(self, fg_color="#111", height=70, corner_radius=0)
        bottom_bar.pack(fill="x", side="bottom")

        # 总体进度条
        self.total_progress = ctk.CTkProgressBar(bottom_bar, height=5, progress_color=COLOR_ACCENT)
        self.total_progress.set(0)
        self.total_progress.pack(fill="x", side="top")
        
        # 底部按钮与状态
        ctrl_area = ctk.CTkFrame(bottom_bar, fg_color="transparent")
        ctrl_area.pack(fill="x", padx=20, pady=15)
        
        self.status_main = ctk.CTkLabel(ctrl_area, text="准备就绪", font=("Arial", 13))
        self.status_main.pack(side="left")
        
        self.stop_btn = ctk.CTkButton(ctrl_area, text="⏹ 停止", command=self.stop_batch, state="disabled", fg_color=COLOR_ERROR, width=100)
        self.stop_btn.pack(side="right", padx=10)
        
        self.start_btn = ctk.CTkButton(ctrl_area, text="🚀 开始压制", command=self.start_batch, font=("Arial", 14, "bold"), width=150, height=35)
        self.start_btn.pack(side="right")

    # === 功能逻辑 ===
    
    def on_mode_change(self):
        self.recalc_concurrency()
        if self.use_gpu.get():
            self.preset_combo.configure(values=["p7 (Best)", "p6 (Better)", "p4 (Medium)"])
            self.preset_var.set("p6 (Better)")
        else:
            self.preset_combo.configure(values=["veryslow", "slower", "medium", "fast", "ultrafast"])
            self.preset_var.set("medium")

    def recalc_concurrency(self):
        if self.use_gpu.get():
            self.workers = 2
            desc = "⚡ GPU 模式: 锁定 2 并发 (RTX 4080 双芯片优化)"
        else:
            calc = max(1, (self.cpu_threads - 4) // 7)
            self.workers = min(calc, 5)
            desc = f"🐢 CPU 模式: 智能分配 {self.workers} 并发 (保留系统资源)"
        self.strategy_lbl.configure(text=desc)

    def open_source_dir(self):
        """打开第一个文件所在的文件夹"""
        path_to_open = ""
        if self.file_queue:
            path_to_open = os.path.dirname(self.file_queue[0])
        else:
            path_to_open = os.path.expanduser("~") # 默认打开用户目录
            
        try:
            os.startfile(path_to_open)
        except Exception as e:
            messagebox.showerror("错误", f"无法打开目录: {e}")

    # === 文件与任务管理 ===
    
    def add_files(self):
        files = filedialog.askopenfilenames()
        self.add_files_to_list(files)

    def drop_file(self, event):
        files = self.tk.splitlist(event.data)
        self.add_files_to_list(files)

    def add_files_to_list(self, files):
        for f in files:
            if f not in self.file_queue and f.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.flv')):
                self.file_queue.append(f)
                # 创建 UI 卡片
                idx = len(self.file_queue)
                card = TaskCard(self.scroll_frame, idx, f)
                card.pack(fill="x", pady=5, padx=5)
                self.task_widgets[f] = card
                
    def clear_queue(self):
        if self.is_running: return
        for widget in self.task_widgets.values():
            widget.destroy()
        self.task_widgets = {}
        self.file_queue = []
        self.total_progress.set(0)
        self.status_main.configure(text="队列已清空")

    # === 预读逻辑 ===
    def preload_monitor(self):
        while True:
            if self.is_running and self.preload_var.get() and not self.stop_requested:
                target = None
                # 寻找第一个等待中的任务
                for f in self.file_queue:
                    # 如果卡片存在且状态是"等待中"
                    widget = self.task_widgets.get(f)
                    if widget and widget.lbl_status.cget("text") == "等待中...":
                        target = f
                        break
                
                if target:
                    self.run_preload(target)
                else:
                    time.sleep(1)
            else:
                time.sleep(1)

    def run_preload(self, filepath):
        try:
            widget = self.task_widgets[filepath]
            self.after(0, lambda: widget.set_status("⚡ 内存预读中...", COLOR_ACCENT))
            
            f_size = os.path.getsize(filepath)
            if f_size > 50 * 1024 * 1024:
                with open(filepath, 'rb') as f:
                    while chunk := f.read(32 * 1024 * 1024):
                        if self.stop_requested: return
            
            self.after(0, lambda: widget.set_status("🚀 就绪 (已缓存)", COLOR_SUCCESS))
        except:
            pass # 预读失败不影响主流程

    # === 压制引擎 ===

    def start_batch(self):
        if not self.file_queue: return
        self.is_running = True
        self.stop_requested = False
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.gpu_switch.configure(state="disabled")
        self.recalc_concurrency()
        
        threading.Thread(target=self.run_process_pool, daemon=True).start()

    def stop_batch(self):
        self.stop_requested = True
        self.is_running = False
        self.status_main.configure(text="正在强制停止...")
        
        for proc in self.active_procs:
            if proc.poll() is None:
                try:
                    proc.terminate()
                    time.sleep(0.1)
                    proc.kill()
                except: pass
        self.active_procs = []
        
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.gpu_switch.configure(state="normal")
        messagebox.showinfo("提示", "任务已停止")

    def run_process_pool(self):
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = [executor.submit(self.process_video, f) for f in self.file_queue]
            for future in futures:
                if self.stop_requested: break
                try: future.result()
                except: pass
        
        if not self.stop_requested:
            self.after(0, self.finish_all)

    def process_video(self, input_file):
        if self.stop_requested: return
        
        widget = self.task_widgets[input_file]
        name, ext = os.path.splitext(input_file)
        tag = "NVENC" if self.use_gpu.get() else "CPU"
        output_file = f"{name}_{tag}_V5{ext}"
        
        # 获取源文件大小
        try:
            original_size = os.path.getsize(input_file)
        except:
            original_size = 0
            
        # UI 更新: 开始
        self.after(0, lambda: widget.set_status("▶️ 正在压制...", "#3498DB"))
        self.after(0, lambda: widget.set_progress(0, "#3498DB"))

        # 构建命令
        cmd = ["ffmpeg", "-y", "-i", input_file]
        crf = self.crf_var.get()
        preset = self.preset_var.get().split(" ")[0]
        
        if self.use_gpu.get():
            if "H.265" in self.codec_var.get(): cmd.extend(["-c:v", "hevc_nvenc"])
            else: cmd.extend(["-c:v", "h264_nvenc"])
            cmd.extend(["-pix_fmt", "yuv420p", "-rc", "vbr", "-cq", str(crf), "-preset", preset, "-spatial-aq", "1"])
        else:
            if "H.265" in self.codec_var.get(): cmd.extend(["-c:v", "libx265"])
            else: cmd.extend(["-c:v", "libx264"])
            cmd.extend(["-crf", str(crf), "-preset", preset])
            
        cmd.extend(["-c:a", "copy", output_file])

        # 获取时长用于进度计算
        duration = self.get_duration(input_file)

        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                   universal_newlines=True, encoding='utf-8', errors='ignore', startupinfo=startupinfo)
        
        self.active_procs.append(process)
        
        for line in process.stdout:
            if self.stop_requested: break
            
            time_match = re.search(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)", line)
            if time_match and duration > 0:
                h, m, s = map(float, time_match.groups())
                curr_sec = h*3600 + m*60 + s
                percent = curr_sec / duration
                
                fps_match = re.search(r"fps=\s*(\d+)", line)
                fps = fps_match.group(1) if fps_match else "?"
                
                # 实时更新 UI (使用 after 避免线程冲突)
                status_text = f"▶️ 压制中... {int(percent*100)}% (FPS: {fps})"
                self.after(0, lambda w=widget, t=status_text, p=percent: [w.set_status(t, "#3498DB"), w.set_progress(p)])

        process.wait()
        if process in self.active_procs: self.active_procs.remove(process)
        
        if not self.stop_requested and process.returncode == 0:
            # 获取压制后大小
            try:
                compressed_size = os.path.getsize(output_file)
            except:
                compressed_size = 0
            
            # UI 更新: 完成与数据
            self.after(0, lambda: widget.set_status("✅ 完成", COLOR_SUCCESS))
            self.after(0, lambda: widget.set_progress(1, COLOR_SUCCESS))
            self.after(0, lambda: widget.show_stats(original_size, compressed_size))
            
            # 更新总进度
            done_count = sum(1 for w in self.task_widgets.values() if "完成" in w.lbl_status.cget("text"))
            total_count = len(self.file_queue)
            self.after(0, lambda: self.total_progress.set(done_count / total_count))
            self.after(0, lambda: self.status_main.configure(text=f"已完成 {done_count}/{total_count}"))

    def get_duration(self, input_file):
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", input_file]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            return float(subprocess.check_output(cmd, startupinfo=startupinfo).strip())
        except: return 0

    def finish_all(self):
        self.is_running = False
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.gpu_switch.configure(state="normal")
        messagebox.showinfo("全部完成", "所有视频处理完毕！")

if __name__ == "__main__":
    app = ModernEncoderApp()
    app.mainloop()

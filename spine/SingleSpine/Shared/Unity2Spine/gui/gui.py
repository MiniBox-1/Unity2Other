# -*- coding: utf-8 -*-
"""
Unity2Spine 图形界面
====================
两条路线：
    A. 静态 prefab 路线（当前）：NormalLocal 2DModel（Sprite+SkinnedMesh+Animator）
     —— 默认按源图像素导出、可选全局预乘(PMA)、自动静态检查/几何自检/单脸校验，
        并集成校准工具、查看器 .config.json，以及 Spine 3.8 二进制
        .skel 导出（"同时输出 .skel"/"补写 .skel"，见
        docs/_archive_20260917/静态prefab路线.md 9.3）。
  B. NGUI 路线：BdOne 这类 NGUI 动态立绘 prefab -> Spine 3.8。

目录（2026-09-19 整理后的布局，这里用正斜杠避免转义）：
  Unity2Spine/gui/gui.py         本文件（GUI）
  Unity2Spine/src/unity2spine/   转换库（按功能分：unity/ ngui/ convert/ spine/ validate/）
  Unity2Spine/src/unity2spine_compat/ + Unity2Spine/ngui2spine/  老 import 名的兼容层
  Unity2Spine/tools/             命令行工具（校验/渲染/批量/内存探针）
  Unity2Spine/_scratch/          对账与探针脚本（几何/显隐/顺序/骨骼/.skel 审计）
  Unity2Spine/info/              Unity 侧动态导出根（Data 真值 + _refshot_*/_draworder_*）
  Unity2Spine/_probe50_rt4/      当前全量产物（50 角色，含 .skel）
  Unity2Spine/_待删除_20260919/  本轮挪出的中间件（只挪不删；含已搁置的 bones/）
  文档先读 Unity2Spine/docs/交接与核查.md（手段 / 铁律 / 闭环）

运行：python gui/gui.py（或双击 gui/run_gui.bat）
依赖：Python 3 + Pillow + tkinter（Anaconda 自带）
"""

import glob
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))          # ...\Unity2Spine\gui
ROOT = os.path.dirname(HERE)                                # ...\Unity2Spine
SRC = os.path.join(ROOT, "src")
for _p in (SRC, ROOT):                                      # 新库 + 兼容层
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 库化之后：`ngui2spine` 是兼容层，真正的实现按功能分在 `unity2spine/` 子包里
from unity2spine.ngui.convert_chr import convert_character
from unity2spine.validate.validate_spine import validate_tree
from unity2spine.validate.merge_existing_spine import merge_existing_spine
from unity2spine.convert.convert_2dmodel import convert as convert_2d

TOOLS = os.path.join(ROOT, "tools")
DEFAULT_2D_ASSETS = r"D:\VB\Search\NormalLocal\lastOrign\Assets"
# Unity 侧**动态导出**的统一根（2026-09-18 起，见 Assets\Script\ExportRoots.cs）
DEFAULT_UNITY_INFO = r"D:\VB\Unity2Spine\info"
DEFAULT_2D_OUT = r"D:\VB\Unity2Spine\samples\2DModel"
DEFAULT_RENDER_PY = r"D:\VB\Viewer\Render\.venv\Scripts\python.exe"
DEFAULT_RENDER_SCRIPT = r"D:\VB\Viewer\Render\render_offline.py"
PREFERRED_2D = ("audrey_normal.prefab", "blacklilith_normal.prefab",
                "aeda_normal.prefab")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Unity 内置动画 -> Spine 3.8 转换器")
        self.geometry("920x760")
        self.minsize(800, 620)
        self._queue = queue.Queue()

        self.project_var = tk.StringVar(value=r"D:\VB\Search\BdOne\Assets")
        self.prefab_var = tk.StringVar()
        self.out_dir_var = tk.StringVar(value=r"D:\VB\Unity2Spine\output")
        self.interval_var = tk.DoubleVar(value=0.05)
        self.max_atlas_var = tk.IntVar(value=4096)
        self.validate_var = tk.BooleanVar(value=True)
        self.merge_mode_var = tk.StringVar(value="direct")
        self.merge_skel_var = tk.BooleanVar(value=False)
        self.t2d_truth_var = tk.StringVar(
            value=os.path.join(DEFAULT_UNITY_INFO, "Data", "SceneT0"))
        self.t2d_dt_var = tk.DoubleVar(value=0.1)
        self.render_exe_var = tk.StringVar(
            value=r"D:\VB\Viewer\Render\build\render_offline.dist\render_offline.exe")
        self.preview_dir_var = tk.StringVar(value=r"D:\VB\Unity2Spine\preview")
        self.preview_size_var = tk.StringVar(value="512x512")

        # ---- 静态 prefab 路线（A：NormalLocal 2DModel，当前路线）----
        self.s_assets_var = tk.StringVar(value=DEFAULT_2D_ASSETS)
        self.s_scene_var = tk.StringVar(
            value=os.path.join(DEFAULT_2D_ASSETS, "Scenes", "save.unity"))
        self.s_out_var = tk.StringVar(value=DEFAULT_2D_OUT)
        self.s_prefab_var = tk.StringVar()
        self.s_clip_var = tk.StringVar(value="")          # 空 = 全部 clip
        self.s_dt_var = tk.DoubleVar(value=0.05)
        self.s_units_var = tk.StringVar(value="px")       # px=源图像素(1:1)
        self.s_secondary_var = tk.BooleanVar(value=True)  # 全转所有 Animator
        self.s_animated_only_var = tk.BooleanVar(value=True)  # 只导 Animator 子树
        self.s_calib_var = tk.BooleanVar(value=True)      # 导出后几何自检
        self.s_facecheck_var = tk.BooleanVar(value=True)   # 导出后单脸 vision 校验
        self.s_skel_var = tk.BooleanVar(value=False)      # 同时输出 .skel 二进制
        self.s_render_py_var = tk.StringVar(value=DEFAULT_RENDER_PY)
        self.s_render_script_var = tk.StringVar(value=DEFAULT_RENDER_SCRIPT)
        self.s_unity_data_var = tk.StringVar(
            value=os.path.join(DEFAULT_UNITY_INFO, "Data"))

        # ---- 交付 / 维护（2026-09-17 新增）----
        self.d_prefab_dir_var = tk.StringVar(
            value=os.path.join(DEFAULT_2D_ASSETS, "prefabs", "Change50"))
        self.d_out_var = tk.StringVar(value=r"D:\VB\Unity2Spine\_probe50_rt4")
        self.d_anim_var = tk.StringVar(value="lobby")
        self.d_times_var = tk.StringVar(value="0.05,0.3,0.6,0.9")
        self.guard_var = tk.BooleanVar(value=True)          # 重活前套内存护栏
        self.guard_mb_var = tk.IntVar(value=6000)

        self._build_ui()
        self._refresh_prefabs()
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        pad = {"padx": 6, "pady": 3}

        # 参数区放进可滚动画布：窗口再小也能点到所有按钮
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(win, width=e.width))

        def _wheel(event):
            step = -1 if getattr(event, "delta", 0) > 0 else 1
            canvas.yview_scroll(step * 3, "units")
            return "break"

        canvas.bind_all("<MouseWheel>", _wheel)

        frame = ttk.LabelFrame(
            inner, text="B. NGUI 动态路线（BdOne：NGUI prefab -> Spine 3.8）")
        frame.pack(fill="x", padx=8, pady=6)
        frame.columnconfigure(1, weight=1)

        # 工程与角色
        row = 0
        ttk.Label(frame, text="Unity Assets 目录:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.project_var).grid(
            row=row, column=1, sticky="ew", **pad)
        ttk.Button(frame, text="浏览…", command=self._browse_project).grid(
            row=row, column=2, **pad)

        row += 1
        ttk.Label(frame, text="角色 prefab:").grid(row=row, column=0, sticky="w", **pad)
        self.prefab_box = ttk.Combobox(frame, textvariable=self.prefab_var, state="readonly")
        self.prefab_box.grid(row=row, column=1, sticky="ew", **pad)
        self.prefab_box.bind("<<ComboboxSelected>>", lambda e: None)
        ttk.Button(frame, text="刷新", command=self._refresh_prefabs).grid(
            row=row, column=2, **pad)
        ttk.Button(frame, text="手动选择…", command=self._browse_prefab).grid(
            row=row, column=3, **pad)

        row += 1
        ttk.Label(frame, text="输出目录:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.out_dir_var).grid(
            row=row, column=1, sticky="ew", **pad)
        ttk.Button(frame, text="浏览…", command=self._browse_out).grid(
            row=row, column=2, **pad)
        ttk.Button(frame, text="打开输出", command=self._open_out).grid(
            row=row, column=3, **pad)

        row += 1
        ttk.Label(frame, text="采样间隔(s):").grid(row=row, column=0, sticky="w", **pad)
        ttk.Spinbox(frame, from_=0.01, to=0.5, increment=0.01,
                    textvariable=self.interval_var, width=8).grid(
            row=row, column=1, sticky="w", **pad)
        ttk.Label(frame, text="图集最大边长:").grid(row=row, column=2, sticky="w", **pad)
        ttk.Spinbox(frame, from_=1024, to=8192, increment=1024,
                    textvariable=self.max_atlas_var, width=8).grid(
            row=row, column=3, sticky="w", **pad)

        row += 1
        ttk.Checkbutton(frame, text="转换后自动结构校验",
                        variable=self.validate_var).grid(
            row=row, column=1, sticky="w", **pad)

        btns = ttk.Frame(inner)
        btns.pack(fill="x", padx=8, pady=4)
        ttk.Button(btns, text="转换当前角色",
                   command=lambda: self._start(self._task_convert, False)).pack(
            side="left", padx=4)
        ttk.Button(btns, text="批量转换全部角色",
                   command=lambda: self._start(self._task_convert, True)).pack(
            side="left", padx=4)
        ttk.Button(btns, text="校验输出",
                   command=lambda: self._start(self._task_validate, False)).pack(
            side="left", padx=4)

        # 多 Spine（已有 skel/json）合成
        merge_box = ttk.LabelFrame(inner, text="多 Spine 合成（prefab 里多个 SkeletonAnimation -> 1 个 Spine）")
        merge_box.pack(fill="x", padx=8, pady=4)
        ttk.Label(merge_box, text="合并方式:").pack(side="left", padx=6, pady=4)
        ttk.Combobox(merge_box, textvariable=self.merge_mode_var, state="readonly",
                     values=("direct", "json"), width=10).pack(side="left", padx=4)
        ttk.Label(merge_box, text="direct=直接读 .skel 二进制合并; "
                                  "json=先经转换器转 json 再合并").pack(side="left", padx=4)
        ttk.Checkbutton(merge_box, text="同时输出 .skel",
                        variable=self.merge_skel_var).pack(side="right", padx=6)
        ttk.Button(merge_box, text="合并当前角色",
                   command=lambda: self._start(self._task_merge, False)).pack(
            side="right", padx=4, pady=4)

        # ---- A. 静态 prefab 路线（当前路线）----
        box_s = ttk.LabelFrame(
            inner, text="A. 静态 prefab 路线（NormalLocal 2DModel，当前路线）")
        box_s.pack(fill="x", padx=8, pady=4, before=frame)
        box_s.columnconfigure(1, weight=1)
        row = 0
        ttk.Label(box_s, text="Assets 目录:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(box_s, textvariable=self.s_assets_var).grid(
            row=row, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(box_s, text="浏览…", command=self._s_browse_assets).grid(
            row=row, column=3, **pad)
        row += 1
        ttk.Label(box_s, text="角色 prefab:").grid(row=row, column=0, sticky="w", **pad)
        self.s_prefab_box = ttk.Combobox(box_s, textvariable=self.s_prefab_var,
                                         state="readonly")
        self.s_prefab_box.grid(row=row, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(box_s, text="刷新", command=self._s_refresh_prefabs).grid(
            row=row, column=3, **pad)
        row += 1
        ttk.Label(box_s, text="场景(save.unity):").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(box_s, textvariable=self.s_scene_var).grid(
            row=row, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(box_s, text="浏览…", command=self._s_browse_scene).grid(
            row=row, column=3, **pad)
        row += 1
        ttk.Label(box_s, text="输出根目录:").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(box_s, textvariable=self.s_out_var).grid(
            row=row, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(box_s, text="浏览…", command=self._s_browse_out).grid(
            row=row, column=3, **pad)
        row += 1
        opt = ttk.Frame(box_s)
        opt.grid(row=row, column=0, columnspan=4, sticky="w", **pad)
        ttk.Label(opt, text="clip(空=全部):").pack(side="left")
        ttk.Entry(opt, textvariable=self.s_clip_var, width=10).pack(side="left", padx=2)
        ttk.Label(opt, text="dt:").pack(side="left", padx=(8, 0))
        ttk.Entry(opt, textvariable=self.s_dt_var, width=6).pack(side="left", padx=2)
        ttk.Label(opt, text="单位:").pack(side="left", padx=(8, 0))
        ttk.Combobox(opt, textvariable=self.s_units_var, state="readonly",
                     values=("px", "world"), width=7).pack(side="left", padx=2)
        ttk.Checkbutton(opt, text="全部 Animator",
                        variable=self.s_secondary_var).pack(side="left", padx=6)
        ttk.Checkbutton(opt, text="只导 Animator 子树",
                        variable=self.s_animated_only_var).pack(side="left", padx=6)
        ttk.Checkbutton(opt, text="几何自检",
                        variable=self.s_calib_var).pack(side="left", padx=6)
        ttk.Checkbutton(opt, text="单脸 vision 校验",
                        variable=self.s_facecheck_var).pack(side="left", padx=6)
        ttk.Checkbutton(opt, text="同时输出 .skel",
                        variable=self.s_skel_var).pack(side="left", padx=6)
        row += 1
        act = ttk.Frame(box_s)
        act.grid(row=row, column=0, columnspan=4, sticky="ew", **pad)
        for text, cb in (
                ("导出当前角色", lambda: self._start(self._task_s_export, False, False)),
                ("导出三个主力角色", lambda: self._start(self._task_s_export, True, False)),
                ("导出+PMA", lambda: self._start(self._task_s_export, False, True)),
                ("三主力+PMA", lambda: self._start(self._task_s_export, True, True)),
        ):
            ttk.Button(act, text=text, command=cb).pack(side="left", padx=3)
        ttk.Button(act, text="打开输出",
                   command=self._s_open_out).pack(side="right", padx=3)
        row += 1
        cal = ttk.Frame(box_s)
        cal.grid(row=row, column=0, columnspan=4, sticky="ew", **pad)
        ttk.Label(cal, text="校准/检查:").pack(side="left")
        for text, cb in (
                ("几何(逐顶点)", lambda: self._start(self._task_s_calib, "geo")),
                ("单脸", lambda: self._start(self._task_s_calib, "face")),
                ("参考帧几何对账", lambda: self._start(self._task_s_geomref)),
                (".skel 加载审计", lambda: self._start(self._task_s_audit)),
                ("静态检查", lambda: self._start(self._task_s_check, False)),
                ("静态检查(3主力)", lambda: self._start(self._task_s_check, True)),
                ("刷新 .config.json", lambda: self._start(self._task_s_config, False)),
                ("补写 .skel", lambda: self._start(self._task_s_skel, False)),
                ("离线渲染(1:1)", lambda: self._start(self._task_s_preview, False)),
        ):
            ttk.Button(cal, text=text, command=cb).pack(side="left", padx=3)
        row += 1
        uni = ttk.Frame(box_s)
        uni.grid(row=row, column=0, columnspan=4, sticky="ew", **pad)
        ttk.Label(uni, text="Unity 校准数据:").pack(side="left")
        ttk.Entry(uni, textvariable=self.s_unity_data_var).pack(
            side="left", fill="x", expand=True, padx=4)
        ttk.Button(uni, text="打开", command=self._s_open_unity_data).pack(
            side="left", padx=2)
        ttk.Button(uni, text="显示导出命令",
                   command=self._s_show_unity_cmd).pack(side="left", padx=2)

        # 离线渲染预览
        preview = ttk.LabelFrame(inner, text="离线渲染预览（可选）")
        preview.pack(fill="x", padx=8, pady=4)
        preview.columnconfigure(1, weight=1)
        ttk.Label(preview, text="Render exe:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(preview, textvariable=self.render_exe_var).grid(
            row=0, column=1, sticky="ew", **pad)
        ttk.Button(preview, text="浏览…", command=self._browse_exe).grid(
            row=0, column=2, **pad)
        ttk.Label(preview, text="预览输出:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(preview, textvariable=self.preview_dir_var).grid(
            row=1, column=1, sticky="ew", **pad)
        ttk.Label(preview, text="尺寸:").grid(row=1, column=2, sticky="w", **pad)
        ttk.Entry(preview, textvariable=self.preview_size_var, width=10).grid(
            row=1, column=3, sticky="w", **pad)
        ttk.Label(preview, text="Render py:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(preview, textvariable=self.s_render_py_var).grid(
            row=2, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(preview, text="Render 脚本:").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(preview, textvariable=self.s_render_script_var).grid(
            row=3, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(preview, text="（上面两项供 A 路线“离线渲染(1:1)”使用）").grid(
            row=3, column=3, sticky="w", **pad)
        ttk.Button(preview, text="渲染当前角色",
                   command=lambda: self._start(self._task_preview, False)).grid(
            row=4, column=3, sticky="e", **pad)

        # 交付 / 维护（2026-09-17 新增：批量 50、补 skel、显隐校验、内存护栏）
        deliv = ttk.LabelFrame(
            inner, text="交付 / 维护（批量 · .skel · 显隐校验 · 内存护栏）")
        deliv.pack(fill="x", padx=8, pady=4)
        deliv.columnconfigure(1, weight=1)
        ttk.Label(deliv, text="批量 prefab 目录:").grid(
            row=0, column=0, sticky="w", **pad)
        ttk.Entry(deliv, textvariable=self.d_prefab_dir_var).grid(
            row=0, column=1, columnspan=3, sticky="ew", **pad)
        ttk.Label(deliv, text="产物根:").grid(
            row=1, column=0, sticky="w", **pad)
        ttk.Entry(deliv, textvariable=self.d_out_var).grid(
            row=1, column=1, columnspan=3, sticky="ew", **pad)
        opt = ttk.Frame(deliv)
        opt.grid(row=2, column=0, columnspan=4, sticky="ew", **pad)
        ttk.Label(opt, text="多帧渲染 动画:").pack(side="left")
        ttk.Entry(opt, textvariable=self.d_anim_var, width=12).pack(
            side="left", padx=2)
        ttk.Label(opt, text="时刻(比例):").pack(side="left")
        ttk.Entry(opt, textvariable=self.d_times_var, width=20).pack(
            side="left", padx=2)
        ttk.Checkbutton(opt, text="重活套内存护栏", variable=self.guard_var).pack(
            side="left", padx=8)
        ttk.Label(opt, text="上限 MB:").pack(side="left")
        ttk.Entry(opt, textvariable=self.guard_mb_var, width=7).pack(
            side="left", padx=2)
        act = ttk.Frame(deliv)
        act.grid(row=3, column=0, columnspan=4, sticky="ew", **pad)
        for text, cb in (
                ("批量转换(该目录)", lambda: self._start(self._task_d_batch)),
                ("补写全部 .skel", lambda: self._start(self._task_d_skel)),
                ("显隐校验(全部)", lambda: self._start(self._task_d_vis)),
                ("静态检查(全部)", lambda: self._start(self._task_d_static)),
                ("多帧渲染(自动配图)", lambda: self._start(self._task_d_frames)),
        ):
            ttk.Button(act, text=text, command=cb).pack(side="left", padx=3)
        act2 = ttk.Frame(deliv)
        act2.grid(row=4, column=0, columnspan=4, sticky="ew", **pad)
        ttk.Button(act2, text="打开 docs",
                   command=lambda: os.startfile(os.path.join(ROOT, "docs"))
                   ).pack(side="left", padx=3)
        ttk.Button(act2, text="打开 _scratch（对账脚本）",
                   command=lambda: os.startfile(os.path.join(ROOT, "_scratch"))
                   ).pack(side="left", padx=3)
        ttk.Button(act2, text="打开待删中间件",
                   command=lambda: os.startfile(
                       os.path.join(ROOT, "_待删除_20260919"))
                   if os.path.isdir(os.path.join(ROOT, "_待删除_20260919"))
                   else self._log("没有 _待删除_20260919 目录")
                   ).pack(side="left", padx=3)
        ttk.Button(act2, text="打开产物根",
                   command=self._d_open_out).pack(side="left", padx=3)
        ttk.Label(act2, text="提示：批量转换/补 skel 用 --jobs 2，别和 Unity 批处理同时跑"
                  ).pack(side="left", padx=6)

        log_frame = ttk.LabelFrame(self, text="日志")
        log_frame.pack(side="bottom", fill="both", padx=8, pady=(2, 6))
        self.log = tk.Text(log_frame, height=12, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)
        self.log.bind("<MouseWheel>", lambda e: "break")

    # ------------------------------------------------------------------ 浏览
    def _browse_project(self):
        p = filedialog.askdirectory(title="选择 Unity 工程的 Assets 目录",
                                    initialdir=self.project_var.get())
        if p:
            self.project_var.set(p)
            self._refresh_prefabs()

    def _refresh_prefabs(self):
        assets = self.project_var.get().strip()
        candidates = []
        for pattern in ("prefab/chr/*.prefab", "prefab/*.prefab",
                        "prefabs/lo/*/*.prefab"):
            candidates += glob.glob(os.path.join(assets, pattern))
        items = sorted(candidates, key=lambda s: os.path.basename(s))
        self._prefab_paths = items
        names = [os.path.basename(p) for p in items]
        self.prefab_box["values"] = names
        if names:
            self.prefab_box.current(0)

    def _browse_prefab(self):
        p = filedialog.askopenfilename(
            title="选择角色 prefab",
            initialdir=os.path.join(self.project_var.get(), "prefab"),
            filetypes=[("Unity Prefab", "*.prefab")])
        if p:
            self._prefab_paths = [p]
            self.prefab_var.set(os.path.basename(p))

    def _browse_out(self):
        p = filedialog.askdirectory(title="选择输出目录", initialdir=self.out_dir_var.get())
        if p:
            self.out_dir_var.set(p)

    def _browse_exe(self):
        p = filedialog.askopenfilename(
            title="选择 render_offline.exe",
            filetypes=[("可执行程序", "*.exe")],
            initialdir=os.path.dirname(self.render_exe_var.get()))
        if p:
            self.render_exe_var.set(p)

    def _browse_truth(self):
        p = filedialog.askdirectory(
            title="选择 Unity 真值目录（含 <角色>_normal.json）",
            initialdir=self.t2d_truth_var.get())
        if p:
            self.t2d_truth_var.set(p)

    def _open_out(self):
        d = self.out_dir_var.get().strip()
        if d and os.path.isdir(d):
            os.startfile(d)  # Windows only

    # -------------------------------------------------- A 路线的浏览/工具
    def _s_browse_assets(self):
        p = filedialog.askdirectory(title="选择 Unity 工程的 Assets 目录",
                                    initialdir=self.s_assets_var.get())
        if p:
            self.s_assets_var.set(p)
            self.s_scene_var.set(os.path.join(p, "Scenes", "save.unity"))
            self.s_unity_data_var.set(os.path.join(DEFAULT_UNITY_INFO, "Data"))
            self._s_refresh_prefabs()

    def _s_refresh_prefabs(self):
        assets = self.s_assets_var.get().strip()
        items = []
        for pattern in (r"prefabs\lo\*\*.prefab", r"prefabs\*\*.prefab",
                        r"prefab\*\*.prefab"):
            items += glob.glob(os.path.join(assets, pattern))
        # 常用三个角色排在最前，方便直接选
        preferred = PREFERRED_2D

        def key(p):
            b = os.path.basename(p)
            return (preferred.index(b) if b in preferred else 99, b)

        items = sorted(set(items), key=key)
        self._s_prefabs = items
        self.s_prefab_box["values"] = [os.path.basename(p) for p in items]
        if items:
            self.s_prefab_box.current(0)
        self.s_prefab_box.bind("<<ComboboxSelected>>", lambda e: None)

    def _s_browse_scene(self):
        p = filedialog.askopenfilename(
            title="选择场景 save.unity",
            initialdir=os.path.dirname(self.s_scene_var.get()),
            filetypes=[("Unity Scene", "*.unity")])
        if p:
            self.s_scene_var.set(p)

    def _s_browse_out(self):
        p = filedialog.askdirectory(title="选择输出根目录",
                                    initialdir=self.s_out_var.get())
        if p:
            self.s_out_var.set(p)

    def _s_open_out(self):
        d = self.s_out_var.get().strip()
        if d and os.path.isdir(d):
            os.startfile(d)

    def _s_open_unity_data(self):
        d = self.s_unity_data_var.get().strip()
        if d and os.path.isdir(d):
            os.startfile(d)

    def _s_show_unity_cmd(self):
        assets = self.s_assets_var.get().strip()
        proj = os.path.dirname(assets)
        self._log("—— Unity 侧校准数据导出（在 Unity 编辑器里跑，或命令行）——")
        self._log("菜单：Tools/2DModel/校准数据/全部导出")
        self._log('"D:\\Unity\\Editor\\2022.3.3f1c1\\Editor\\Unity.exe" '
                  '-batchmode -projectPath "%s" -quit '
                  '-executeMethod TwoDModelCalibExport.ExportAll '
                  '-logFile %s\\_logs\\calib.log'
                  % (proj, DEFAULT_UNITY_INFO))
        self._log("（导参考图时不要加 -nographics；输出在 info\\Data\\）")

    def _s_selected_prefab(self):
        if not hasattr(self, "_s_prefabs") or not self._s_prefabs:
            return None
        name = self.s_prefab_var.get()
        for p in self._s_prefabs:
            if os.path.basename(p) == name:
                return p
        return None

    def _s_chars(self, batch):
        if batch:
            # 批量只导三个主力角色：这个 Assets 下有 1900+ 个 prefab，
            # 全量导出会跑飞
            allp = list(getattr(self, "_s_prefabs", []))
            picked = [p for p in allp
                      if os.path.basename(p) in PREFERRED_2D]
            return picked or allp[:3]
        p = self._s_selected_prefab()
        return [p] if p else []

    # 跑子进程并把输出实时写进日志
    def _run_stream(self, cmd, cwd=None):
        self._log("$ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
        try:
            proc = subprocess.Popen(
                cmd, cwd=cwd or HERE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1)
        except Exception as ex:
            self._log("启动失败：%r" % ex)
            return 1
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                self._log("  " + line)
        return proc.wait()

    def _s_spine_dir(self, prefab, pma=False):
        char = os.path.splitext(os.path.basename(prefab))[0]
        # 与既有产物目录保持一致：aeda_normal -> aeda
        if char.endswith("_normal"):
            char = char[:-len("_normal")]
        name = "static_spine_pma" if pma else "static_spine"
        return os.path.join(self.s_out_var.get().strip(), char, name)

    # ------------------------------------------------------------------ 任务
    def _selected_prefab(self):
        if not hasattr(self, "_prefab_paths") or not self._prefab_paths:
            return None
        name = self.prefab_var.get()
        for p in self._prefab_paths:
            if os.path.basename(p) == name:
                return p
        return None

    def _start(self, fn, *args):
        """在后台线程里跑任务（可带任意参数）。"""
        self._log("开始任务…")
        t = threading.Thread(target=fn, args=args, daemon=True)
        t.start()

    def _task_convert(self, batch):
        assets = self.project_var.get().strip()
        out_root = self.out_dir_var.get().strip()
        if not os.path.isdir(out_root):
            os.makedirs(out_root, exist_ok=True)

        prefab = self._selected_prefab()
        if batch:
            chars = glob.glob(os.path.join(assets, "prefab", "chr", "*.prefab"))
        elif prefab:
            chars = [prefab]
        else:
            chars = []

        if not chars:
            self._log("错误：没有可用 prefab")
            return

        for i, p in enumerate(sorted(chars), 1):
            name = os.path.splitext(os.path.basename(p))[0]
            out = os.path.join(out_root, name)
            self._log("[%d/%d] %s -> %s" % (i, len(chars), name, out))
            try:
                convert_character(p, assets, out,
                                  sample_dt=float(self.interval_var.get()),
                                  max_atlas=int(self.max_atlas_var.get()))
                self._log("完成：%s" % name)
            except Exception as ex:
                self._log("失败：%s：%r" % (name, ex))

        if self.validate_var.get():
            self._task_validate(False)
        else:
            self._log("全部任务结束")

    def _task_merge(self, batch):
        assets = self.project_var.get().strip()
        out_root = self.out_dir_var.get().strip()
        prefab = self._selected_prefab()
        if not prefab:
            self._log("错误：没有可用 prefab")
            return
        os.makedirs(out_root, exist_ok=True)
        char = os.path.splitext(os.path.basename(prefab))[0]
        out = os.path.join(out_root, char + "_合并")
        mode = self.merge_mode_var.get()
        self._log("多Spine合并 %s（%s） -> %s" % (char, mode, out))
        try:
            files = merge_existing_spine(
                prefab, assets, out, mode=mode,
                want_skel=bool(self.merge_skel_var.get()))
            for f in files:
                self._log("  输出 %s" % f)
            self._log("合并完成：%s" % char)
        except Exception as ex:
            self._log("合并失败：%s：%r" % (char, ex))

    def _task_2d(self, batch):
        assets = self.project_var.get().strip()
        prefab = self._selected_prefab()
        if not prefab:
            self._log("错误：没有可用 prefab")
            return
        char = os.path.splitext(os.path.basename(prefab))[0]
        out_root = self.out_dir_var.get().strip() or r"D:\VB\Unity2Spine\samples\2DModel"
        out = os.path.join(out_root, char)
        os.makedirs(out, exist_ok=True)
        truth_dir = self.t2d_truth_var.get().strip()
        truth = os.path.join(truth_dir, char + ".json")
        if not os.path.isfile(truth):
            truth = None
        self._log("2DModel转换 %s -> %s（truth=%s）" % (char, out, truth or "无"))
        try:
            files = convert_2d(prefab, assets, out,
                               dt=float(self.t2d_dt_var.get()), truth_path=truth)
            for f in files:
                self._log("  输出 %s" % f)
            self._log("2DModel转换完成：%s" % char)
        except Exception as ex:
            self._log("2DModel转换失败：%s：%r" % (char, ex))

    def _task_validate(self, batch):
        root = self.out_dir_var.get().strip()
        if not root or not os.path.isdir(root):
            self._log("校验失败：输出目录不存在")
            return
        ok, failures = validate_tree(root)
        self._log("校验：通过 %d 个资源" % ok)
        for f in failures[:20]:
            self._log("  校验失败：%s" % f)
        if len(failures) > 20:
            self._log("  …共 %d 项失败" % len(failures))
        self._log("校验结束")

    def _task_preview(self, batch):
        exe = self.render_exe_var.get().strip()
        if not os.path.isfile(exe):
            self._log("错误：找不到 render_offline.exe")
            return
        out_root = self.out_dir_var.get().strip()
        preview_root = self.preview_dir_var.get().strip()
        os.makedirs(preview_root, exist_ok=True)

        dirs = []
        if os.path.isdir(out_root):
            for char in sorted(os.listdir(out_root)):
                cd = os.path.join(out_root, char)
                if not os.path.isdir(cd):
                    continue
                for costume in sorted(os.listdir(cd)):
                    sub = os.path.join(cd, costume)
                    if os.path.isdir(sub) and glob.glob(os.path.join(sub, "*.json")):
                        dirs.append(sub)

        for i, d in enumerate(dirs, 1):
            self._log("渲染 [%d/%d] %s" % (i, len(dirs), d))
            cmd = [exe, d, "--output", preview_root,
                   "--only", "spine", "--mode", "single",
                   "--size", self.preview_size_var.get(), "--overwrite"]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=120, encoding="utf-8", errors="replace")
                if r.returncode != 0:
                    self._log("  Render 返回非 0：" + (r.stderr or r.stdout)[-300:])
            except Exception as ex:
                self._log("  Render 异常：%r" % ex)
        self._log("预览渲染结束 -> " + preview_root)

    # ------------------------------------------------- A 路线的任务（子进程）
    # --------------------------------------- 交付 / 维护任务（2026-09-17 新增）
    def _guard_cmd(self, cmd):
        """重活前套 `tools\\mem_probe.ps1`：连子进程一起量峰值，超限直接杀。

        （铁律：不量内存不许并行；批量转换/补 skel 是内存大户。）
        """
        if not self.guard_var.get():
            return cmd
        probe = os.path.join(TOOLS, "mem_probe.ps1")
        if not os.path.isfile(probe):
            return cmd
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", probe, "-Exe", cmd[0],
                "-ArgList", "|".join(cmd[1:]),
                "-LimitMB", str(self.guard_mb_var.get())]

    def _d_open_out(self):
        p = self.d_out_var.get().strip() or ROOT
        if not os.path.isdir(p):
            self._log("目录不存在：" + p)
            return
        try:
            os.startfile(p)
        except Exception as ex:
            self._log("打开失败：%r" % ex)

    def _d_chars(self):
        out = self.d_out_var.get().strip()
        if not os.path.isdir(out):
            return []
        return sorted(d for d in os.listdir(out)
                      if os.path.isdir(os.path.join(out, d)))

    def _task_d_batch(self):
        pd = self.d_prefab_dir_var.get().strip()
        out = self.d_out_var.get().strip()
        if not os.path.isdir(pd):
            self._log("错误：批量 prefab 目录不存在：" + pd)
            return
        cmd = [sys.executable, os.path.join(TOOLS, "convert_all_2dmodel.py"),
               "--prefab-dir", pd, "--out", out, "--jobs", "2",
               "--assets", self.s_assets_var.get().strip()]
        scene = self.s_scene_var.get().strip()
        if os.path.isfile(scene):
            cmd += ["--scene", scene]
        rc = self._run_stream(self._guard_cmd(cmd))
        self._log("批量转换结束（退出码 %d）→ %s" % (rc, out))

    def _task_d_skel(self):
        out = self.d_out_var.get().strip()
        cmd = [sys.executable, os.path.join(TOOLS, "write_all_skel.py"),
               out, "--force"]
        rc = self._run_stream(self._guard_cmd(cmd))
        self._log("补写 .skel 结束（退出码 %d）" % rc)

    def _task_d_vis(self):
        out = self.d_out_var.get().strip()
        chars = self._d_chars()
        if not chars:
            self._log("错误：产物根下没有角色目录：" + out)
            return
        cmd = [sys.executable, os.path.join(TOOLS, "check_clip_visibility.py"),
               "--spine-root", out] + chars
        rc = self._run_stream(cmd)
        self._log("显隐校验结束（退出码 %d，%d 个角色）" % (rc, len(chars)))

    def _task_d_static(self):
        out = self.d_out_var.get().strip()
        chars = self._d_chars()
        if not chars:
            self._log("错误：产物根下没有角色目录：" + out)
            return
        assets = self.s_assets_var.get().strip()
        scene = self.s_scene_var.get().strip()
        bad = []
        for i, ch in enumerate(chars, 1):
            d = os.path.join(out, ch)
            info_path = os.path.join(d, "_static_info.json")
            if not os.path.isfile(info_path):
                continue
            info = json.load(open(info_path, encoding="utf-8-sig"))
            cmd = [sys.executable, os.path.join(TOOLS, "static_check.py"),
                   info.get("prefab") or "", "--assets", assets,
                   "--spine-dir", d]
            if os.path.isfile(scene):
                cmd += ["--scene", scene]
            self._log("[%d/%d] 静态检查 %s" % (i, len(chars), ch))
            rc = self._run_stream(cmd)
            if rc:
                bad.append(ch)
        self._log("静态检查结束：%d 个角色，%d 个有问题 %s"
                  % (len(chars), len(bad), "、".join(bad)))

    def _task_d_frames(self):
        """多帧渲染（`tools/rt_frames.py`）：角色取 A 路线选中的那个，产物在产物根下。"""
        prefab = self._s_selected_prefab()
        char = os.path.splitext(os.path.basename(prefab))[0] if prefab else ""
        out = self.d_out_var.get().strip()
        sdir = os.path.join(out, char) if char else ""
        if not sdir or not os.path.isdir(sdir):
            self._log("错误：先在 A 路线里选一个角色（且产物根下有同名目录）")
            return
        dst = os.path.join(ROOT, "_scratch", "_gui_frames", char)
        cmd = [os.path.join(r"D:\VB\Viewer\Render\.venv\Scripts", "python.exe"),
               os.path.join(TOOLS, "rt_frames.py"), sdir,
               self.d_anim_var.get().strip() or "lobby",
               "--out", dst, "--times", self.d_times_var.get().strip(),
               "--size", "900"]
        rc = self._run_stream(cmd)
        self._log("多帧渲染结束（退出码 %d）→ %s" % (rc, dst))

    def _task_s_export(self, batch, pma):
        prefabs = self._s_chars(batch)
        if not prefabs:
            self._log("错误：没有可用 prefab（先点“刷新”）")
            return
        self._log("将导出 %d 个角色：%s%s"
                  % (len(prefabs), "、".join(os.path.basename(p)
                                             for p in prefabs),
                     "（PMA）" if pma else ""))
        assets = self.s_assets_var.get().strip()
        scene = self.s_scene_var.get().strip()
        clip = self.s_clip_var.get().strip()
        for i, prefab in enumerate(prefabs, 1):
            char = os.path.splitext(os.path.basename(prefab))[0]
            out = self._s_spine_dir(prefab, pma)
            os.makedirs(out, exist_ok=True)
            self._log("[%d/%d] %s -> %s%s"
                      % (i, len(prefabs), char, out, "（PMA）" if pma else ""))
            cmd = [sys.executable, "-m", "ngui2spine.static_prefab_spine",
                   prefab, out, "--assets", assets, "--dt", str(self.s_dt_var.get()),
                   "--units", self.s_units_var.get()]
            if os.path.isfile(scene):
                cmd += ["--scene", scene]
            if clip:
                cmd += ["--clip", clip]
            if pma:
                cmd += ["--pma"]
            if not self.s_secondary_var.get():
                cmd += ["--no-secondary-anim"]
            if not self.s_animated_only_var.get():
                cmd += ["--no-animated-only"]
            if self.s_calib_var.get():
                cmd += ["--calib"]
            if self.s_skel_var.get():
                cmd += ["--skel"]
            if not self.s_facecheck_var.get():
                cmd += ["--no-face-check"]
            rc = self._run_stream(cmd)
            self._log("完成：%s（退出码 %d）" % (char, rc))
        self._log("全部导出结束 -> " + self.s_out_var.get().strip())

    def _task_s_calib(self, kind):
        prefab = self._s_selected_prefab()
        if not prefab:
            self._log("错误：没有可用 prefab")
            return
        char = os.path.splitext(os.path.basename(prefab))[0]
        spine_dir = self._s_spine_dir(prefab, False)
        if not os.path.isdir(spine_dir):
            pma_dir = self._s_spine_dir(prefab, True)
            if os.path.isdir(pma_dir):
                spine_dir = pma_dir
        if not os.path.isdir(spine_dir):
            self._log("找不到产物目录：" + spine_dir)
            return
        assets = self.s_assets_var.get().strip()
        scene = self.s_scene_var.get().strip()
        unity_data = self.s_unity_data_var.get().strip() or \
            os.path.join(DEFAULT_UNITY_INFO, "Data")
        frames = os.path.join(unity_data, "Frames", char)
        pose = os.path.join(unity_data, "PoseFrames", char + ".json")
        if kind == "geo":
            cmd = [sys.executable, os.path.join(TOOLS, "calib_geo.py"),
                   "--prefab", prefab, "--assets", assets,
                   "--only-spine-dir", "--spine-dir", spine_dir,
                   "--times", "0,1.5,3,6,9,12,16"]
            if os.path.isfile(scene):
                cmd += ["--scene", scene]
            if os.path.isfile(pose):
                cmd += ["--pose", pose]
        elif kind == "face":
            # 单脸截出 + vision.js 方向/镜像校验（产物写在 _face_check/）
            cmd = [sys.executable, os.path.join(TOOLS, "face_check.py"),
                   spine_dir]
        else:
            return
        rc = self._run_stream(cmd)
        self._log("校准(%s) 结束，退出码 %d" % (kind, rc))

    def _task_s_geomref(self):
        """参考帧几何对账：产物 vs `info\\_refshot_<角色>\\*.json` 的世界顶点。

        对每个参考帧调用 `_scratch\\geom_vs_refshot.py <产物> <真值json> <动画> <秒>`
        （真值文件名里就带 `<角色>__<状态>__t<毫秒>.json`，直接解析出参数）。
        """
        prefab = self._s_selected_prefab()
        if not prefab:
            self._log("错误：没有可用 prefab")
            return
        char = os.path.splitext(os.path.basename(prefab))[0]
        spine_dir = self._s_spine_dir(prefab, False)
        if not os.path.isdir(spine_dir):
            pma_dir = self._s_spine_dir(prefab, True)
            if os.path.isdir(pma_dir):
                spine_dir = pma_dir
        if not os.path.isdir(spine_dir):
            self._log("找不到产物目录：" + spine_dir)
            return
        ref_dir = os.path.join(DEFAULT_UNITY_INFO, "_refshot_" + char)
        if not os.path.isdir(ref_dir):
            self._log("没有参考帧目录：" + ref_dir +
                      "（先在 Unity 里跑 菜单 Tools/2DModel/运行时采样/参考帧…）")
            return
        tool = os.path.join(ROOT, "_scratch", "geom_vs_refshot.py")
        files = sorted(glob.glob(os.path.join(ref_dir, char + "__*.json")))
        if not files:
            self._log("参考帧目录里没有 JSON：" + ref_dir)
            return
        for i, jf in enumerate(files, 1):
            base = os.path.basename(jf)[:-5]
            parts = base.split("__")
            if len(parts) < 3 or not parts[-1].startswith("t"):
                continue
            anim = parts[-2]
            try:
                t = int(parts[-1][1:]) / 1000.0
            except ValueError:
                continue
            self._log("[%d/%d] 几何对账 %s t=%.3f" % (i, len(files), anim, t))
            self._run_stream([sys.executable, tool, spine_dir, jf, anim,
                              "%g" % t])
        self._log("参考帧几何对账结束（只报超差的那几件）")

    def _task_s_audit(self):
        """.skel 加载审计：`_scratch\\q3_audit_load.py <产物根> --bin --max N`。

        spine-cpp 不回收内存，必须分片（默认 12 个/片）；重活用内存护栏包一层。
        """
        root = self.d_out_var.get().strip() or \
            os.path.join(ROOT, "_probe50_rt4")
        cmd = [sys.executable, os.path.join(ROOT, "_scratch",
                                            "q3_audit_load.py"),
               root, "--bin", "--max", "12"]
        self._log("用法提醒：脚本逐个加载产物，内存线性增长；要跑全量请分片。")
        rc = self._run_stream(self._guard_cmd(cmd))
        self._log(".skel 加载审计结束，退出码 %d（+ 内存护栏）" % rc)

    def _task_s_check(self, batch):
        prefabs = self._s_chars(batch)
        if not prefabs:
            self._log("错误：没有可用 prefab")
            return
        scene = self.s_scene_var.get().strip()
        for i, prefab in enumerate(prefabs, 1):
            char = os.path.splitext(os.path.basename(prefab))[0]
            spine_dir = self._s_spine_dir(prefab, False)
            if not os.path.isdir(spine_dir):
                pma_dir = self._s_spine_dir(prefab, True)
                if os.path.isdir(pma_dir):
                    spine_dir = pma_dir
            rep = os.path.join(spine_dir, "_calib", "static_check.json")
            os.makedirs(os.path.dirname(rep), exist_ok=True)
            cmd = [sys.executable, os.path.join(TOOLS, "static_check.py"),
                   prefab, "--assets", self.s_assets_var.get().strip(),
                   "--spine-dir", spine_dir, "--json", rep]
            if os.path.isfile(scene):
                cmd += ["--scene", scene]
            self._log("[%d/%d] 静态检查 %s" % (i, len(prefabs), char))
            rc = self._run_stream(cmd)
            self._log("静态检查结束（%s），退出码 %d，报告：%s"
                      % (char, rc, rep))

    def _task_s_config(self, batch):
        cmd = [sys.executable, os.path.join(TOOLS, "refresh_viewer_config.py"),
               self.s_out_var.get().strip()]
        rc = self._run_stream(cmd)
        self._log("刷新 .config.json 结束，退出码 %d" % rc)

    def _task_s_skel(self, batch):
        """给已有产物补写 .skel：把 <产物目录>/*_static[_pma].json 转成同名的
        Spine 3.8 二进制骨架（原生写出器，不再依赖第三方转换器）。"""
        prefabs = self._s_chars(batch)
        if not prefabs:
            self._log("错误：没有可用 prefab")
            return
        done = 0
        for i, prefab in enumerate(prefabs, 1):
            for pma in (False, True):
                spine_dir = self._s_spine_dir(prefab, pma)
                if not os.path.isdir(spine_dir):
                    continue
                names = [fn for fn in sorted(os.listdir(spine_dir))
                         if fn.endswith("_static.json")
                         or fn.endswith("_static_pma.json")]
                for fn in names:
                    rel = os.path.join(os.path.basename(spine_dir), fn)
                    self._log("[%d/%d] 补写 .skel <- %s"
                              % (i, len(prefabs), rel))
                    rc = self._run_stream(
                        [sys.executable, "-m",
                         "ngui2spine.spine38_binary_writer",
                         os.path.join(spine_dir, fn), "--verify"])
                    if rc == 0:
                        done += 1
        if not done:
            self._log("没有找到可转换的 <角色>_static[_pma].json"
                      "（先导出一份 A 路线产物）")
        else:
            self._log("补写 .skel 完成：%d 个" % done)

    def _task_s_preview(self, batch):
        prefab = self._s_selected_prefab()
        if not prefab:
            self._log("错误：没有可用 prefab")
            return
        char = os.path.splitext(os.path.basename(prefab))[0]
        spine_dir = self._s_spine_dir(prefab, False)
        if not os.path.isdir(spine_dir):
            pma_dir = self._s_spine_dir(prefab, True)
            if os.path.isdir(pma_dir):
                spine_dir = pma_dir
        if not os.path.isdir(spine_dir):
            self._log("找不到产物目录：" + spine_dir)
            return
        # 按源图尺寸 1:1 渲染（读 _static_info.json 的 sourceSizes）
        size = "2048x2048"
        try:
            import json as _json
            info = _json.load(open(os.path.join(spine_dir, "_static_info.json"),
                                   encoding="utf-8"))
            src = (info.get("sourceSizes") or [[2048, 2048]])[0]
            size = "%dx%d" % (src[0], src[1])
        except Exception:
            pass
        out_dir = os.path.join(self.preview_dir_var.get().strip() or HERE, char)
        os.makedirs(out_dir, exist_ok=True)
        py = self.s_render_py_var.get().strip()
        script = self.s_render_script_var.get().strip()
        if os.path.isfile(py) and os.path.isfile(script):
            cmd = [py, script, spine_dir, "--only", "spine", "--size", size,
                   "--background", "255,255,255,255", "--output", out_dir,
                   "--pma", "auto", "--overwrite"]
        else:
            exe = self.render_exe_var.get().strip()
            if not os.path.isfile(exe):
                self._log("错误：找不到离线渲染器（Render exe 或 python 脚本）")
                return
            cmd = [exe, spine_dir, "--only", "spine", "--size", size,
                   "--background", "255,255,255,255", "--output", out_dir,
                   "--pma", "auto", "--overwrite"]
        rc = self._run_stream(cmd)
        self._log("离线渲染结束（%s，%s），退出码 %d -> %s"
                  % (char, size, rc, out_dir))

    # ------------------------------------------------------------------ 日志
    def _log(self, msg):
        self._queue.put(msg)

    def _poll_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", msg + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


if __name__ == "__main__":
    App().mainloop()

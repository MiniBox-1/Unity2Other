# -*- coding: utf-8 -*-
"""lo_uncen2Spine GUI（PySide6）。

只跟 `unity2spine.api` 的协议打交道：
  * 启动 `discover()` 找出所有特化（ext_bdone / ext_lo …）→ 线路下拉；
  * 选中线路后按它的 `defaults` 与 `options_schema` 生成表单；
  * 输入可以是**单个 prefab**，也可以是**目录**（目录=批量，逐个跑）；
  * "每角色口径"里按 `KEY=VAL` 逐行写环境变量（例如相位 U2S_LAYER_PHASE=0.499）；
  * 点"开始转换" → 后台线程里 `profile.run(ConvertRequest(...))` → 日志实时回显。

运行：`python -m unity2spine.gui.main`（或双击项目根的 run_gui.bat）
"""
from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from unity2spine.api import ConvertRequest, discover

PREFAB_GLOBS = (".uAnim.prefab", ".prefab")


def list_prefabs(path: str):
    """输入是目录 → 列出里面的 prefab（批量）；是文件 → 就它一个。"""
    if os.path.isdir(path):
        out = [os.path.join(path, f) for f in sorted(os.listdir(path))
               if f.endswith(PREFAB_GLOBS)]
        return out
    return [path] if path else []


def parse_env(text: str):
    """`KEY=VAL` 逐行 → dict（空行/`#` 注释行忽略）。"""
    env = {}
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip()
    return env


class Worker(QThread):
    """后台跑（批量就是在一个线程里顺序跑完，别占住界面）。"""

    line = Signal(str)
    tick = Signal(int, int, str)
    done = Signal(bool, str)

    def __init__(self, profile, inputs, out_dir, assets_dir, options, env):
        super().__init__()
        self.profile = profile
        self.inputs = inputs
        self.out_dir = out_dir
        self.assets_dir = assets_dir
        self.options = options
        self.env = env

    def run(self) -> None:                                        # noqa: D102
        ok_all = True
        total = len(self.inputs)
        for i, inp in enumerate(self.inputs, 1):
            name = os.path.basename(inp)
            self.tick.emit(i, total, name)
            req = ConvertRequest(input_path=inp, output_dir=self.out_dir,
                                 assets_dir=self.assets_dir,
                                 options=self.options, env=self.env,
                                 log=self.line.emit)
            try:
                res = self.profile.run(req)
                ok = bool(res.ok)
                detail = res.detail or ""
            except Exception:                                     # noqa: BLE001
                self.line.emit(traceback.format_exc())
                ok, detail = False, "异常"
            ok_all = ok_all and ok
            self.line.emit("[gui] [%d/%d] %s %s %s"
                           % (i, total, "完成" if ok else "失败", name, detail))
        self.done.emit(ok_all, "共 %d 个" % total)


class MainWindow(QMainWindow):
    def __init__(self, profiles):
        super().__init__()
        self.setWindowTitle("lo_uncen2Spine —— Unity → Spine 3.8")
        self.profiles = profiles
        self.widgets = {}
        self.worker = None
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)

        top = QFormLayout()
        self.cb = QComboBox()
        for p in profiles:
            self.cb.addItem(p.label, p.name)
        self.cb.currentIndexChanged.connect(self._on_profile)
        top.addRow("线路（扩展库）", self.cb)
        outer.addLayout(top)

        grid = QGridLayout()
        self.inp = QLineEdit()
        self.out = QLineEdit()
        self.assets = QLineEdit()
        rows = (("输入 prefab / 目录（目录=批量）", self.inp, self._pick_file,
                 self._pick_in_dir),
                ("输出目录", self.out, self._pick_out_dir, None),
                ("Unity Assets", self.assets, self._pick_assets_dir, None))
        for i, (lab, ed, fn, fn2) in enumerate(rows):
            grid.addWidget(QLabel(lab), i, 0)
            grid.addWidget(ed, i, 1)
            b = QPushButton("…")
            b.setFixedWidth(32)
            b.clicked.connect(fn)
            grid.addWidget(b, i, 2)
            if fn2 is not None:
                b2 = QPushButton("目录")
                b2.setFixedWidth(48)
                b2.clicked.connect(fn2)
                grid.addWidget(b2, i, 3)
        outer.addLayout(grid)

        self.opt_box = QWidget()
        self.opt_layout = QFormLayout(self.opt_box)
        outer.addWidget(self.opt_box)

        env_form = QFormLayout()
        self.env_edit = QPlainTextEdit()
        self.env_edit.setPlaceholderText(
            "每角色口径（KEY=VAL，一行一条；与 config\\per_char_env.txt 同义）\n"
            "例：U2S_LAYER_PHASE=0.499\n"
            "    U2S_FORCE_INACTIVE=*:parts_BP_028")
        self.env_edit.setFixedHeight(64)
        env_form.addRow("环境变量", self.env_edit)
        outer.addLayout(env_form)

        bar = QHBoxLayout()
        self.btn = QPushButton("开始转换")
        self.btn.clicked.connect(self._run)
        bar.addWidget(self.btn)
        b_open = QPushButton("打开输出目录")
        b_open.clicked.connect(self._open_out)
        bar.addWidget(b_open)
        self.progress = QLabel("就绪")
        bar.addWidget(self.progress)
        bar.addStretch(1)
        outer.addLayout(bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        outer.addWidget(self.log, 1)
        self.statusBar().showMessage("就绪")
        self._on_profile(0)

    # ---------------------------------------------------------------- 表单
    def cur(self):
        return next(p for p in self.profiles if p.name == self.cb.currentData())

    def _on_profile(self, _i):
        p = self.cur()
        self.inp.setText("")
        self.out.setText(p.defaults.get("output_dir", ""))
        self.assets.setText(p.defaults.get("assets_dir", ""))
        while self.opt_layout.count():
            it = self.opt_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self.widgets = {}
        for spec in p.options_schema:
            key, typ = spec.get("key"), spec.get("type", "str")
            if typ == "bool":
                w = QCheckBox()
                w.setChecked(bool(spec.get("default", False)))
            else:
                w = QLineEdit(str(spec.get("default", "") or ""))
            self.widgets[key] = w
            self.opt_layout.addRow(spec.get("label", key), w)
        self.statusBar().showMessage(p.description or p.label)

    def _pick_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "选 prefab", self.assets.text(),
                                           "Prefab (*.prefab)")
        if f:
            self.inp.setText(f)

    def _pick_in_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选批量目录（含 prefab）",
                                             self.inp.text() or os.getcwd())
        if d:
            self.inp.setText(d)

    def _pick_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选输出目录",
                                             self.out.text() or os.getcwd())
        if d:
            self.out.setText(d)

    def _pick_assets_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选 Unity Assets 根",
                                             self.assets.text() or os.getcwd())
        if d:
            self.assets.setText(d)

    # ---------------------------------------------------------------- 执行
    def _log(self, s):
        self.log.appendPlainText(str(s))

    def _open_out(self):
        d = self.out.text().strip()
        if d and os.path.isdir(d):
            os.startfile(d)                                       # noqa: S606
        else:
            self._log("[gui] 输出目录还不存在：%s" % d)

    def _options(self):
        opts = {}
        for k, w in self.widgets.items():
            opts[k] = w.isChecked() if isinstance(w, QCheckBox) else w.text()
        return opts

    def _run(self):
        inputs = list_prefabs(self.inp.text().strip())
        out_dir = self.out.text().strip()
        if not inputs:
            self._log("[gui] 输入目录里没找到 prefab（*.uAnim.prefab / *.prefab）")
            return
        if not out_dir:
            self._log("[gui] 先填输出目录")
            return
        os.makedirs(out_dir, exist_ok=True)
        self.btn.setEnabled(False)
        self.progress.setText("0/%d" % len(inputs))
        self.statusBar().showMessage("转换中…")
        self.worker = Worker(self.cur(), inputs, out_dir,
                             self.assets.text().strip(), self._options(),
                             parse_env(self.env_edit.toPlainText()))
        self.worker.line.connect(self._log)
        self.worker.tick.connect(self._on_tick)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _on_tick(self, i, total, name):
        self.progress.setText("%d/%d  %s" % (i, total, name))

    def _on_done(self, ok, detail):
        self.btn.setEnabled(True)
        self.statusBar().showMessage(("完成 " if ok else "有失败 ") + detail)
        self._log("[gui] %s %s" % ("全部完成" if ok else "有失败", detail))


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))          # ...\lo_uncen2Spine
    if root not in sys.path:
        sys.path.insert(0, root)
    profiles = discover()
    app = QApplication(sys.argv)
    win = MainWindow(profiles)
    win.resize(980, 720)
    win.show()
    print("[gui] 发现 %d 条线路：%s"
          % (len(profiles), ", ".join(p.name for p in profiles)))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

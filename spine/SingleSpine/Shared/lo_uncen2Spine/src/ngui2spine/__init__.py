# -*- coding: utf-8 -*-
"""老包名的兼容别名：`ngui2spine.xxx` → `unity2spine_compat.xxx` → 真库 `unity2spine.xxx`。

历史脚本（含 `-m ngui2spine.xxx` 的命令行）用的是这个名字。

**为什么要显式注册 `sys.modules`**：开发态 `__path__` 指到 `unity2spine_compat/`
就够了；但**打包（Nuitka）后拿不到那个目录**，靠路径找不到子模块
（表现为 `ModuleNotFoundError: No module named 'ngui2spine'`）。所以这里直接
按名字把每个转发模块 import 进来注册好——`sys.modules` 优先于路径查找，
开发态/打包态都成立。
"""
import importlib
import os
import sys

#: 与 `unity2spine_compat/` 里的转发模块一一对应（新增转发模块时补这里）
_SHIMS = (
    "anim_to_spine", "convert_2dmodel", "convert_chr", "extract_unity_spine",
    "frame_baked", "merge_char", "merge_existing_spine", "ngui_anim",
    "ngui_model", "pack_images", "single_frame_spine", "spine38_binary",
    "spine38_binary_writer", "spine_out", "sprite_outline",
    "static_prefab_spine", "unity_2dmodel", "unity_anim2d", "unity_mesh",
    "unity_parse", "validate_spine",
)

_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.isdir(os.path.join(_HERE, "..", "unity2spine")):
    _SRC = os.path.abspath(os.path.join(_HERE, ".."))
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)                 # 开发态：让 unity2spine 可导入
    # 开发态保留路径兜底（打包态这个目录不存在，但下面的注册已经够用）
    __path__ = [os.path.join(_SRC, "unity2spine_compat")]

for _name in _SHIMS:
    _key = __name__ + "." + _name
    if _key in sys.modules:
        continue
    try:
        sys.modules[_key] = importlib.import_module("unity2spine_compat." + _name)
    except Exception:                                        # noqa: BLE001
        pass                                                 # 缺哪个就哪个不可用

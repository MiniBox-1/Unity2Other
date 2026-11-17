# -*- coding: utf-8 -*-
r"""老绝对路径 → 当前位置的**统一解析器**（给历史工具/脚本用）。

背景：`src/tools\` 里有一批历史工具，CLI 默认值写死了老布局（`D:\VB\Unity2Spine\...`、
`D:\VB\Search\NormalLocal\...`、`D:\VB\Viewer\Render\...`）。为了让整个项目
**不依赖文件夹以外的任何文件**，这些默认值一律经本模块解析：

  * 先在 `lo_uncen2Spine.json`（或 `U2S_CONFIG` 指定的那份）里找同名键；
  * 再用环境变量覆盖（见下表）；
  * 最后才回落到"老路径"（只作为兜底，且允许用户改）。

用法：
    from unity2spine.env import resolve
    DEFAULT_ASSETS = resolve(r"D:\VB\Search\NormalLocal\lastOrign\Assets")
"""
from __future__ import annotations

import os

from .paths import app_root, cfg

#: 老前缀 → (配置键, 环境变量名)
MAP = {
    r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old": ("lo.project_root",
                                                              "U2S_LO_PROJECT"),
    r"D:\VB\Search\New\归档-proj-Mobile-old": ("lo.root", "U2S_LO_ROOT"),
    # 老主仓下的两处**数据**（真值帧、CS 烘焙中间件）在另一台机器上会分开放，
    # 所以单列出来：环境变量优先（U2S_INFO_DIR / U2S_CSBAKE_DIR），
    # 其次是配置（lo.info_dir / lo.csbake_dir）。Unity 侧同名环境变量对齐。
    r"D:\VB\Unity2Spine\info": ("lo.info_dir", "U2S_INFO_DIR"),
    r"D:\VB\Unity2Spine\_scratch\_csbake": ("lo.csbake_dir", "U2S_CSBAKE_DIR"),
    # 老主仓其它部分 = 历史工具里 `D:\VB\Unity2Spine\...`（_probe / _scratch …）
    # 这些是**数据**，不随代码搬。留空则落回本项目根。
    r"D:\VB\Unity2Spine": ("unity2spine.legacy_home", "U2S_OLD_HOME"),
    r"D:\VB\Search\NormalLocal\lastOrign\Assets": ("lo.legacy_2d_assets",
                                                   "U2S_2D_ASSETS"),
    r"D:\VB\Search\BdOne": ("bdone.project_root", "U2S_BDONE_PROJECT"),
    r"D:\VB\Search\del": ("lo.del_dir", "U2S_DEL_DIR"),
    r"D:\VB\Search\SpineOut": ("bdone.spine_out", "U2S_SPINE_OUT"),
    r"D:\VB\Viewer\Render": ("external.viewer_root", "U2S_VIEWER_ROOT"),
    r"D:\Reverse": ("external.reverse_root", "U2S_REVERSE_ROOT"),
    r"D:\VB": ("external.vb_root", "U2S_VB_ROOT"),
}


def resolve(path: str) -> str:
    """把老绝对路径（或它下面的子路径）解析成当前应使用的位置。"""
    p = path.replace("/", "\\")
    for old, (key, env) in MAP.items():
        if p == old or p.startswith(old + "\\"):
            tail = p[len(old):].lstrip("\\")
            base = os.environ.get(env) or cfg(key)
            if not base and key == "unity2spine.legacy_home":
                base = app_root()
            if not base:
                return path
            return os.path.join(base, tail) if tail else base
    return path

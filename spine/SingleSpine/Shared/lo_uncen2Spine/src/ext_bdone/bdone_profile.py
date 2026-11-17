# -*- coding: utf-8 -*-
"""BdOne（NGUI 动态立绘）→ Spine 3.8 的**特化**。

公有部分（资源解析、Spine 3.8 写出、校验）都在总项目 `unity2spine`；
这里只放 BdOne 这条线路特有的东西：默认路径、参数、最终调用哪个公有入口。
（对应老 tkinter GUI 的"路线 B"。）
"""
from __future__ import annotations

import os

from unity2spine.api import ConvertRequest, ConvertResult, Profile, register
from unity2spine.paths import cfg

DEFAULT_ASSETS = cfg("bdone.assets_dir")
DEFAULT_OUT = cfg("bdone.out_dir")


def run(req: ConvertRequest) -> ConvertResult:
    """按 NGUI 路线跑一次转换。"""
    from unity2spine.ngui.convert_chr import convert_character
    prefab = req.input_path
    assets = req.assets_dir or DEFAULT_ASSETS
    # 公有入口的真实签名：convert_character(prefab_path, project_root, out_dir,
    #                                      sample_dt=0.05, max_atlas=4096)
    # 注意第二参是**Unity 工程根**（Assets 的父目录），不是 Assets 本身。
    project_root = os.path.dirname(os.path.abspath(assets.rstrip("\\/")))
    out_dir = os.path.join(req.output_dir,
                           os.path.splitext(os.path.basename(prefab))[0])
    os.makedirs(out_dir, exist_ok=True)
    req.say("[bdone] 输入 %s" % req.input_path)
    req.say("[bdone] 工程根 %s → 输出 %s" % (project_root, out_dir))
    opts = dict(req.options or {})
    convert_character(prefab, project_root, out_dir,
                      sample_dt=float(opts.get("sample_dt", 0.05) or 0.05),
                      max_atlas=int(opts.get("max_atlas", 4096) or 4096))
    return ConvertResult(ok=os.path.isdir(out_dir), outputs=[out_dir],
                         detail="BdOne(NGUI) 路线完成")


PROFILE = register(Profile(
    name="bdone",
    label="BdOne（NGUI 动态立绘）",
    description="NGUI 立绘 prefab → Spine 3.8；走 unity2spine.ngui.convert_chr",
    input_kind="prefab",
    defaults={"assets_dir": DEFAULT_ASSETS, "output_dir": DEFAULT_OUT},
    options_schema=[
        {"key": "sample_dt", "type": "str", "default": "0.05",
         "label": "采样步长 sample_dt（秒）"},
        {"key": "max_atlas", "type": "str", "default": "4096",
         "label": "图集最大边 max_atlas"},
    ],
    run=run,
))

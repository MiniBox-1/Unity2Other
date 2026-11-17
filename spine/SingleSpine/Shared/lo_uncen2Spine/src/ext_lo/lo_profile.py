# -*- coding: utf-8 -*-
r"""lo（NormalLocal 2DModel 静态 prefab）→ Spine 3.8 的**特化**。

这条线路特有口径（公有代码都在总项目 `unity2spine`）：

* **标准导出** ＝ 只出 `.skel` + 同名 `<目录名>.config.json`（`--json` 仅研究用）；
* **每角色口径表** `config/per_char_env.txt`（相位 / 预跑 / 死曲线部件…），
  批量脚本 `src/tools\batch_cs_convert.py` 会读它并打印 `每角色口径 …`；
* 产物落 `<out>\<角色>\`；旧产物先搬 `D:\VB\Search\del\` 保留可回退。
"""
from __future__ import annotations

import os
import subprocess
import sys

from unity2spine.api import ConvertRequest, ConvertResult, Profile, register
from unity2spine.paths import cfg, is_frozen

# 位置一律走配置（代码不依赖外部文件）；见 lo_uncen2Spine.json
DEFAULT_ASSETS = cfg("lo.assets_dir")
DEFAULT_OUT = cfg("lo.out_dir")
DEFAULT_PROJECT = cfg("lo.project_root")

#: 代码根 = 本文件所在包的上一层（`<项目根>\src`）。子进程要靠它 import 到
#: `unity2spine`（代码都收在 `src\` 下，光靠 cwd 找不到）。
_CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(req: ConvertRequest) -> ConvertResult:
    """按 lo 路线跑一次（单角色；批量交给 src\\tools\\batch_cs_convert.py）。"""
    prefab = req.input_path
    name = os.path.basename(prefab).replace(".uAnim.prefab", "") \
        .replace(".prefab", "")
    out_dir = os.path.join(req.output_dir, name)
    os.makedirs(out_dir, exist_ok=True)
    args = [prefab, out_dir, "--assets", req.assets_dir or DEFAULT_ASSETS,
            "--skel", "--no-face-check"]
    if (req.options or {}).get("cs", True):
        args.append("--cs")
    if (req.options or {}).get("json"):
        args.append("--json")
    env = dict(os.environ)
    # 子进程按 UTF-8 输出（本机控制台是 GBK），我们这边也按 UTF-8 解码——
    # 与 src/tools\batch_cs_convert.py 的口径一致。
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = _CODE_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env.update({k: str(v) for k, v in (req.env or {}).items()})

    if is_frozen():
        # 打包（Nuitka）后 sys.executable 就是本 exe，不能当解释器起子进程；
        # 直接**同进程**调用公有入口（位置解析/自检在进程内照旧生效）。
        req.say("[lo] (frozen) -m unity2spine.convert.static_prefab_spine "
                + " ".join(args))
        from unity2spine.convert import static_prefab_spine as sps
        old = dict(os.environ)
        os.environ.update(env)
        try:
            rc = sps.run_cli(args)
        finally:
            os.environ.clear()
            os.environ.update(old)
        ok = rc == 0 and os.path.isdir(out_dir)
        return ConvertResult(ok=ok, outputs=[out_dir] if ok else [],
                             detail="rc=%d(frozen)" % rc)

    cmd = [sys.executable, "-m", "unity2spine.convert.static_prefab_spine"] + args
    req.say("[lo] " + " ".join(cmd[1:]))
    p = subprocess.run(cmd, capture_output=True, text=True, env=env,
                       encoding="utf-8", errors="replace")
    for line in (p.stdout or "").splitlines():
        req.say("  " + line)
    ok = p.returncode == 0 and os.path.isdir(out_dir)
    return ConvertResult(ok=ok, outputs=[out_dir] if ok else [],
                         detail="rc=%d" % p.returncode)


PROFILE = register(Profile(
    name="lo",
    label="lo（NormalLocal 2DModel 静态 prefab）",
    description="静态 prefab → Spine 3.8（标准只出 .skel）；支持 CS 烘焙与每角色口径",
    input_kind="prefab",
    defaults={"assets_dir": DEFAULT_ASSETS, "output_dir": DEFAULT_OUT},
    options_schema=[
        {"key": "cs", "type": "bool", "default": True,
         "label": "带 CS 烘焙（DynamicBone / GlobalControl）"},
        {"key": "json", "type": "bool", "default": False,
         "label": "同时出 debug JSON（研究用）"},
    ],
    run=run,
))

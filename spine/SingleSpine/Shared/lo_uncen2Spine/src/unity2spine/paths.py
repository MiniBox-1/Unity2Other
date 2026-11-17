# -*- coding: utf-8 -*-
"""路径配置：**代码本身不依赖任何外部文件**，外部的"用户数据 / 别人的工具"位置
集中在一份 json 里读；代码里不出现会执行的写死盘符路径。

位置查找顺序：

1. 环境变量 `U2S_CONFIG` 指向的那份 json；
2. **项目根**（`app_root()`）下的 `config/lo_uncen2Spine.json`
   （旧布局 `<根>/lo_uncen2Spine.json` 仍兼容）；
3. 内置兜底（缺键就返回默认值，刚 clone 也能跑起来）。

项目根怎么认：从本文件往上找带 `.u2s_root` 标记的那一层；打包后就是 exe 所在目录。

用法：
    from unity2spine.paths import app_root, cfg, cache_dir
    cfg("lo.assets_dir")          # 支持 "a.b.c" 点号取值；相对路径按项目根展开
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

_CACHE: Dict[str, Any] = {}

#: 项目根标记文件（跟着项目走；打包时随 exe 放一份）
MARKER = ".u2s_root"


def is_frozen() -> bool:
    """是不是在**打包产物**里跑（Nuitka / PyInstaller / cx_Freeze 都覆盖）。

    坑（2026-10-13 踩到）：**Nuitka standalone 不设 `sys.frozen`**，只在每个被编译
    的模块里注入全局 `__compiled__`；PyInstaller 才是设 `sys.frozen`。
    另外打包后 `sys.executable` 是"本程序自己"，**不能当解释器**起子进程，
    所以这里也把"可执行文件名不像 python"算作打包态。
    """
    if getattr(sys, "frozen", False):
        return True
    if "__compiled__" in globals():
        return True
    try:
        import __main__
        if getattr(__main__, "__compiled__", None):
            return True
    except Exception:                                            # noqa: BLE001
        pass
    exe = os.path.basename(sys.executable or "").lower()
    return bool(exe) and not exe.startswith(("python", "pythonw"))


def _search_root(start: str) -> str:
    """从 `start` 往上找带 `.u2s_root` 标记的目录。"""
    d = os.path.abspath(start)
    for _ in range(10):
        if os.path.isfile(os.path.join(d, MARKER)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return ""


def app_root() -> str:
    """项目根：开发态＝标记文件那一层；打包态＝exe 所在目录。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    found = _search_root(os.path.dirname(os.path.abspath(__file__)))
    if found:
        return found
    # 兜底：src/unity2spine/paths.py -> 上三级
    return os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))


def project_root() -> str:
    """同 `app_root()`（保留老名字，历史工具在用）。"""
    return app_root()


def config_path() -> str:
    """配置文件路径：`U2S_CONFIG` > `config/lo_uncen2Spine.json` > 根下的老位置。"""
    env = os.environ.get("U2S_CONFIG")
    if env:
        return env
    root = app_root()
    new = os.path.join(root, "config", "lo_uncen2Spine.json")
    old = os.path.join(root, "lo_uncen2Spine.json")
    if os.path.isfile(new) or not os.path.isfile(old):
        return new
    return old


def load() -> Dict[str, Any]:
    p = config_path()
    if _CACHE.get("_path") != p:
        try:
            with open(p, encoding="utf-8-sig") as fh:
                _CACHE.clear()
                _CACHE.update(json.load(fh))
            _CACHE["_path"] = p
        except Exception:                                        # noqa: BLE001
            _CACHE.clear()
            _CACHE["_path"] = p
    return _CACHE


def cfg(key: str, default: str = "") -> str:
    """取配置并展开相对路径（相对项目根）。"""
    cur: Any = load()
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    if not isinstance(cur, str):
        return default
    if cur and not os.path.isabs(cur):
        cur = os.path.join(app_root(), cur)
    return cur or default


def cache_dir(sub: str = "") -> str:
    """可写的缓存目录（guid 索引、临时产物）——默认 `<项目根>/.cache/`。

    位置只由配置 `unity2spine.cache_dir`（或环境变量 `U2S_CACHE`）决定；
    代码不往包目录里写东西（打包成单目录后包目录可能只读）。
    """
    d = os.environ.get("U2S_CACHE") or cfg("unity2spine.cache_dir")
    if not d:
        d = os.path.join(app_root(), ".cache")
    if sub:
        d = os.path.join(d, sub)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d

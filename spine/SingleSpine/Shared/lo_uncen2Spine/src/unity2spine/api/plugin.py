# -*- coding: utf-8 -*-
"""扩展库（特化）协议。

* 总项目（`unity2spine`）只提供**公有转化代码** + 这个协议；
* 每个特化库（`ext_bdone` / `ext_lo`）各是独立包，实现一个或多个 `Profile`，
  通过 `register()` 或 setuptools entry point（组名 `u2spine.profiles`）挂上来；
* GUI 只跟协议打交道：列 profile → 收集参数 → `profile.run(request)`。
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

ENTRY_GROUP = "u2spine.profiles"
FALLBACK_MODULES = ("ext_bdone", "ext_lo")


@dataclass
class ConvertRequest:
    """一次转换请求：GUI 填、profile 读（路径一律绝对路径）。"""
    input_path: str
    output_dir: str
    assets_dir: str = ""
    options: Dict[str, object] = field(default_factory=dict)
    env: Dict[str, str] = field(default_factory=dict)
    log: Optional[Callable[[str], None]] = None

    def say(self, msg: str) -> None:
        if self.log:
            self.log(msg)


@dataclass
class ConvertResult:
    ok: bool
    outputs: List[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class Profile:
    """一条"线路/特化"的元信息与执行入口。"""
    name: str
    label: str
    description: str = ""
    input_kind: str = "prefab"
    defaults: Dict[str, str] = field(default_factory=dict)
    options_schema: List[dict] = field(default_factory=list)
    run: Optional[Callable[[ConvertRequest], ConvertResult]] = None


_REGISTRY: Dict[str, Profile] = {}


def register(profile: Profile) -> Profile:
    _REGISTRY[profile.name] = profile
    return profile


def all_profiles() -> List[Profile]:
    return list(_REGISTRY.values())


def discover() -> List[Profile]:
    """发现所有特化：优先 entry points，其次按名字兜底 import。"""
    try:
        from importlib.metadata import entry_points
        eps = entry_points()
        group = (eps.select(group=ENTRY_GROUP) if hasattr(eps, "select")
                 else eps.get(ENTRY_GROUP, []))
        for ep in group:
            try:
                ep.load()
            except Exception as ex:                              # noqa: BLE001
                print("[api] 载入扩展 %s 失败：%s" % (ep.name, ex))
    except Exception:                                            # noqa: BLE001
        pass
    for mod in FALLBACK_MODULES:
        try:
            importlib.import_module(mod)
        except Exception:                                        # noqa: BLE001
            pass
    return all_profiles()

# -*- coding: utf-8 -*-
"""Remove the unused GlobalControl helpers (kept only as documented finding)."""
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "src" / "unity2live2d" / "convert" / "prefab_filter.py"
s = p.read_text(encoding="utf-8")
start = s.find("CONTROL_GROUPS = {")
end = s.find("def control_transforms(")
block_start = s.find("# Puppet2D_GlobalControl 的序列化开关")
if block_start > 0 and end > block_start:
    head = s[:block_start]
    tail = s[end:]
    note = ("# 备注：Puppet2D_GlobalControl 用「精灵名含 Control/ffd + 序列化开关」隐藏控制件\n"
            "# （见 docs\\04 E48）。我们的部件只有贴图 GUID、没有精灵名，而现有的\n"
            "# 「控制组 + 命名」规则已能覆盖同类物体（RoyalArsenal 0.967），故不启用。\n"
            "CONTROL_GROUPS = {\"Global_CTRL\", \"CTRL_IK\", \"Controllers\"}\n\n\n")
    p.write_text(head + note + tail, encoding="utf-8")
    print("cleaned")
else:
    print("nothing to clean")

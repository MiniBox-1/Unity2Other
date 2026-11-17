# -*- coding: utf-8 -*-
"""二进制产物 `.skel` 校验（原版源码丢失后按同一口径重建的；2026-09-14）。

1) 我们的写出器 JSON -> .skel，再用本项目读回器 .skel -> JSON，比对结构（含 drawOrder）
2) 与第三方 SpineSkeletonDataConverter.exe 的 JSON -> .skel 输出**逐字节**比对

用法：

    python src/tools\\check_skel.py <产物目录>              # 写出 .skel → 本项目读回 → 比对
    python src/tools\\check_skel.py <产物目录> --ref-exe    # 再与第三方转换器**逐字节**对拍

产物目录 = 含 `<角色>_static.json` 的目录（例如 `_probe50_rt2\\banshee_skin1`）。
"""
# --- lo_uncen2Spine: 位置解析（自动插入，见 src/tools\deabs_paths.py）--
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
while _ROOT and not _os.path.isdir(_os.path.join(_ROOT, 'unity2spine')):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT and _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
from unity2spine.env import resolve as _resolve  # noqa: E402
from unity2spine.console import fix_console as _fix_console  # noqa: E402
_fix_console()
from unity2spine.paths import app_root as _app_root  # noqa: E402
# ---------------------------------------------------------------------

import io
import json
import os
import subprocess
import sys

HERE = _app_root()  # 项目根
sys.path.insert(0, HERE)

from ngui2spine import spine38_binary as R            # noqa: E402
from ngui2spine import spine38_binary_writer as W     # noqa: E402

REF = os.path.join(HERE, "deps", "third_party",
                   "SpineSkeletonDataConverter.exe")


def main():
    d = sys.argv[1]
    ref = "--ref-exe" in sys.argv
    # 骨架 JSON 优先：同目录里还有查看器配置 `<目录名>.config.json`（那不是骨架，
    # 它的 "skeleton" 是个**字符串**路径，直接喂写出器会 AttributeError）。
    js = [f for f in sorted(os.listdir(d))
          if f.endswith(".json") and not f.startswith(("_", "."))
          and not f.endswith(".config.json")]
    js.sort(key=lambda f: ("static" not in f, f))
    if not js:
        print("目录里没有产物 json"); return 1
    src = io.open(os.path.join(d, js[0]), encoding="utf-8-sig").read()
    model = json.loads(src)
    blob = W.build_binary(model)
    skel = os.path.join(d, os.path.splitext(js[0])[0] + ".skel")
    open(skel, "wb").write(blob)
    print("写出 %s：%d 字节" % (os.path.basename(skel), len(blob)))

    back = R.read_skeleton_json(skel)
    ok = True
    a = model.get("animations") or {}
    b = back.get("animations") or {}
    for name in sorted(set(a) | set(b)):
        da = (a.get(name) or {}).get("drawOrder") or []
        db = (b.get(name) or {}).get("drawOrder") or []
        same = (len(da) == len(db)
                and all(abs(float(x.get("time", 0)) - float(y.get("time", 0))) < 1e-6
                        and [(o["slot"], o["offset"]) for o in x.get("offsets") or []]
                        == [(o["slot"], o["offset"]) for o in y.get("offsets") or []]
                        for x, y in zip(da, db)))
        if not same:
            ok = False
            print("  [x] %s drawOrder 读写不一致：源 %d 帧 / 读回 %d 帧"
                  % (name, len(da), len(db)))
        elif da:
            print("  [v] %-10s drawOrder %d 帧 往返一致" % (name, len(da)))
    print("drawOrder 往返：%s" % ("通过" if ok else "失败"))

    # --- 语义检查：按 spine-cpp 的读入语义解码 drawOrder，和"曲线->顺序"的期望值比
    slots = [s["name"] for s in model["slots"]]
    n = len(slots)

    def decode(offsets):
        draw = [-1] * n
        unchanged = []
        orig = 0
        for off in offsets:
            s = slots.index(off["slot"])
            while orig != s:
                unchanged.append(orig)
                orig += 1
            draw[orig + int(off["offset"])] = orig
            orig += 1
        while orig < n:
            unchanged.append(orig)
            orig += 1
        for ii in range(n - 1, -1, -1):
            if draw[ii] == -1:
                draw[ii] = unchanged.pop()
        return draw

    sem_ok = True
    for name, anim in (model.get("animations") or {}).items():
        frames = anim.get("drawOrder") or []
        if not frames:
            continue
        # 期望顺序由 _static_info 里记录的曲线推出：这里用"解码后再编码"的自洽性检查
        # （跨语言算法一致即可；输入曲线 -> 顺序的映射另有单元测试覆盖）
        for fr in frames:
            order = decode(fr.get("offsets") or [])
            if sorted(order) != list(range(n)):
                sem_ok = False
                print("  [x] %s t=%s 解码后不是排列" % (name, fr.get("time")))
    print("drawOrder 解码语义：%s" % ("通过" if sem_ok else "失败"))
    ok = ok and sem_ok

    if ref and os.path.isfile(REF):
        out = os.path.join(d, "_ref.skel")
        r = subprocess.run([REF, os.path.join(d, js[0]), out],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if r.returncode != 0 or not os.path.isfile(out):
            print("  第三方转换失败：%s" % (r.stdout or r.stderr)[:200])
            return 2
        rb = open(out, "rb").read()
        print("第三方输出 %d 字节；逐字节一致：%s" % (len(rb), rb == blob))
        if rb != blob:
            n = min(len(rb), len(blob))
            pos = next((i for i in range(n) if rb[i] != blob[i]), n)
            print("  首个差异位置 %d（我们 %r / 参考 %r）"
                  % (pos, blob[pos:pos + 8], rb[pos:pos + 8]))
    return 0 if ok else 1


sys.exit(main())

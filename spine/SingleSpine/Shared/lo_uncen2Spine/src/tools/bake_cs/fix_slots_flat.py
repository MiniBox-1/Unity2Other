# -*- coding: utf-8 -*-
r"""把产物 JSON 里被误写成 `animations.x.slots.default.<槽位>` 的结构**拉平**成
`animations.x.slots.<槽位>`（spine-cpp 3.8 要的就是扁平的，见 SkeletonJson.cpp）。

只动 JSON，`.skel` 不受影响（二进制里 slot 时间轴带的是槽位下标）。

用法:
    python fix_slots_flat.py <产物目录> [<产物目录> ...]
"""

import io
import json
import os
import sys


def main():
    n_file = n_anim = 0
    for d in sys.argv[1:]:
        if not os.path.isdir(d):
            print("[skip] 不是目录：%s" % d)
            continue
        for fn in os.listdir(d):
            if not fn.endswith("_static.json"):
                continue
            p = os.path.join(d, fn)
            with io.open(p, encoding="utf-8-sig") as fh:
                S = json.load(fh)
            fixed = 0
            for an, A in (S.get("animations") or {}).items():
                sl = A.get("slots")
                if not isinstance(sl, dict) or len(sl) != 1:
                    continue
                inner = sl.get("default")
                if not isinstance(inner, dict):
                    continue
                # inner 的值应该是 {槽位名: {attachment/color...}}
                if not all(isinstance(v, dict) for v in inner.values()):
                    continue
                A["slots"] = inner
                fixed += 1
            if fixed:
                with io.open(p, "w", encoding="utf-8") as fh:
                    json.dump(S, fh, ensure_ascii=False, separators=(",", ":"))
                n_file += 1
                n_anim += fixed
                print("  修好 %s：%d 条动画拉平" % (p, fixed))
            else:
                print("  无需修改 %s" % p)
    print("共 %d 个文件、%d 条动画 slots 拉平" % (n_file, n_anim))
    return 0


if __name__ == "__main__":
    sys.exit(main())

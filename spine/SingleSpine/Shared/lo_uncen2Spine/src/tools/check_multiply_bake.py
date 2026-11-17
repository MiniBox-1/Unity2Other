# -*- coding: utf-8 -*-
r"""检查产物里"乘法件"（Unity `Particles/Multiply` 影子）的处理口径。

默认口径（2026-10-10 用户指令）：**转换时直接对图集处理** ——
把乘法烘进图集（区域写成 `黑 + α=1−m`），槽位输出 `blend=normal`，
产物**不依赖运行时的 multiply 混合**。实验口径（`--multiply-blend`）
才输出 `blend=multiply`（贴图直通 + 区域 α 置 1）。

**判定依据是转换器自己写进 `_static_info.json` 的账本**（`multiply.parts`）：
每条记录带 `page`（落在哪张页）、`rects`（在源图/页像素里的**闭区间**矩形）、
`uvMap`（裁剪页的 UV 重映射）、`factor`。所以这里不靠"槽位名 ↔ 部件名"去猜，
也不受 JSON 里 UV 被四舍五入的影响（早先按 UV 反推矩形会差 1px，是工具的
off-by-one，不是产物问题）。

检查四件事：
  1. 产物 slot 里还有没有 `blend=multiply`（默认口径应为 0；实验口径应等于乘法件数）；
  2. 每条记录的矩形里是否真的烘对了：默认口径 **rgb 全 0、α = 1−m**；
     实验口径 **α = 255**；
  3. 裁剪页（`_mul`）整页只应有"黑 + α"（含 2px 透明留边）；
  4. 可选 `--base <旧产物目录>`：逐页比对，确认**改动只发生在这些矩形里**。

用法:
    python src/tools\check_multiply_bake.py <产物目录> [--base <旧产物目录>]
"""

import argparse
import io
import json
import os
import sys

import numpy as np
from PIL import Image


def load_json(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def atlas_regions(atlas_path):
    """解析 .atlas -> {region: (页文件名, 页宽, 页高)} 与页文件列表。"""
    reg = {}
    pages = []
    cur = None
    pending = None
    for ln in io.open(atlas_path, encoding="utf-8").read().splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.lower().endswith(".png"):
            cur = s
            pages.append(s)
            continue
        if cur and ":" not in s:
            pending = s
            reg[s] = [cur, 0, 0]
            continue
        if cur and s.startswith("size:") and pending:
            wh = s.split(":", 1)[1].strip().split(",")
            reg[pending][1] = int(wh[0])
            reg[pending][2] = int(wh[1])
    return reg, pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("product")
    ap.add_argument("--base", default=None,
                    help="旧产物目录：逐页确认只有乘法件的矩形被动过")
    a = ap.parse_args()

    pd = a.product
    jn = [f for f in os.listdir(pd) if f.endswith("_static.json")]
    an = [f for f in os.listdir(pd) if f.endswith(".atlas")]
    S = load_json(os.path.join(pd, jn[0])) if jn else None
    reg, pages = atlas_regions(os.path.join(pd, an[0]))
    info = load_json(os.path.join(pd, "_static_info.json"))
    mul = info.get("multiply") or {}
    add = info.get("additive") or {}
    baked = str(mul.get("mode", "")).startswith("baked")

    print("产物: %s" % pd)
    print("模式: %s   乘法件 %d 个" % (mul.get("mode"), mul.get("count", 0)))
    print("加色件: %d 个（图集里按 alpha 预乘，账本 %d 条）"
          % (add.get("count", 0), len(add.get("items") or [])))
    bad = 0

    if S is not None:
        other = [(s["name"], s.get("blend")) for s in S["slots"]
                 if s.get("blend") not in (None, "normal")]
        print("非普通混合的槽位: %d 个%s"
              % (len(other), "  " + str(other[:8]) if other else ""))
        if baked:
            badmul = [n for n, b in other if b == "multiply"]
            if badmul:
                print("[fail] 默认口径下仍有 blend=multiply：%s" % badmul[:8])
                bad += 1
        else:
            n_mul = sum(1 for _n, b in other if b == "multiply")
            if mul.get("count") and n_mul != mul["count"]:
                print("[fail] 实验口径：blend=multiply 槽位 %d 个，乘法件记了 %d 个"
                      % (n_mul, mul["count"]))
                bad += 1
    else:
        print("（没有 *_static.json，跳过槽位混合检查；矩形检查不受影响）")

    # ---- 逐条记录查矩形（闭区间）----
    print("\n逐件检查（矩形是闭区间，与转换器同源）:")
    rects_by_page = {}
    for m in (mul.get("parts") or []):
        pg = m.get("page")
        if pg not in reg:
            print("  [warn] %s 的页 %r 不在 atlas 里" % (m["part"], pg))
            continue
        fn = reg[pg][0]
        im = Image.open(os.path.join(pd, fn)).convert("RGBA")
        arr = np.array(im, dtype=np.uint8)          # 低内存：uint8（2048² = 16MB）
        H, W = arr.shape[:2]
        boxes = []
        if m.get("cropped"):
            # 裁剪页：整页都是烘过的区域（外圈 2px 透明留边）
            um = m.get("uvMap") or []
            boxes = [(2, 2, W - 3, H - 3)]
            if um:
                print("  %-46s 裁剪页 %-14s 页 %dx%d（源图 %.0fx%.0f，uvMap=%s）"
                      % (m["part"], fn, W, H, um[4], um[5],
                         ",".join("%.0f" % v for v in um)))
        else:
            boxes = [tuple(int(v) for v in r) for r in (m.get("rects") or [])]
            print("  %-46s 页 %-14s 页 %dx%d" % (m["part"], fn, W, H))
        for (x0, y0, x1, y1) in boxes:
            x0 = max(0, x0); y0 = max(0, y0)
            x1 = min(W - 1, x1); y1 = min(H - 1, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            sub = arr[y0:y1 + 1, x0:x1 + 1]
            rgbmax = int(sub[..., :3].max())
            al = sub[..., 3]
            al_min, al_max = int(al.min()), int(al.max())
            al_mean = float(al.mean())
            if baked:
                print("     矩形 (%d,%d)-(%d,%d)  rgb_max=%d（应 0）"
                      "  α min/max/均值 %d/%d/%.1f  ⇒ 乘法因子 m ∈ [%.3f, %.3f]"
                      % (x0, y0, x1, y1, rgbmax, al_min, al_max, al_mean,
                         1 - al_max / 255.0, 1 - al_min / 255.0))
                if rgbmax != 0:
                    print("        [fail] 矩形里仍有非黑像素 —— 烘暗没覆盖到")
                    bad += 1
                if al_max == 0:
                    # 贴图因子 = 1（纯白）时 Unity 里也是 dst×1 = 什么都不改，
                    # 烘出来就是全透明 —— 这是"忠实"，不是 bug（例：Babariana 的
                    # parts_004_shadow acc_skinned_21）。所以只提示，不算失败。
                    print("        [warn] α 全 0：该件在图集里完全透明"
                          "（贴图因子 = 1 ⇒ Unity 里本来就什么都不改）；"
                          "若它本该可见才需要查")
            else:
                print("     矩形 (%d,%d)-(%d,%d)  rgb_max=%d（贴图直通）"
                      "  α min/max=%d/%d（应 255/255）"
                      % (x0, y0, x1, y1, rgbmax, al_min, al_max))
                if al_min != 255:
                    print("        [fail] 实验口径下 α 不是全 255 —— multiply 会泛白")
                    bad += 1
            if not m.get("cropped"):
                rects_by_page.setdefault(fn, []).append((x0, y0, x1, y1))

    # ---- 与旧产物逐页比对 ----
    if a.base:
        # 允许清单 = 乘法件的就地矩形 ∪ 加色件"按 alpha 预乘"的就地矩形
        #（加色件那条路径本来就会改图集，账本在 _static_info.json 的 `additive` 段）
        for it in ((info.get("additive") or {}).get("items") or []):
            if it.get("cropped"):
                continue
            fn = reg.get(it.get("page") or "", [None])[0]
            if fn:
                rects_by_page.setdefault(fn, []).extend(
                    tuple(int(v) for v in r) for r in (it.get("rects") or []))
        print("\n与旧产物逐页比对（%s）:" % a.base)
        olds = [g for g in os.listdir(a.base) if g.endswith(".png")]
        for f in pages:
            # 低内存：uint8 读图；旧页一张一张比、比完立刻释放（不缓存整目录）
            new = np.array(Image.open(os.path.join(pd, f)).convert("RGBA"),
                           dtype=np.uint8)
            best, best_diff = None, None
            for g in olds:
                o = np.array(Image.open(os.path.join(a.base, g))
                             .convert("RGBA"), dtype=np.uint8)
                if o.shape != new.shape:
                    del o
                    continue
                d = int((o != new).any(axis=2).sum())
                if best_diff is None or d < best_diff:
                    best, best_diff = g, d
                del o
            if best is None:
                print("  %-34s 新页（旧产物里没有同尺寸页）⇒ 只查自身烘焙" % f)
                del new
                continue
            o = np.array(Image.open(os.path.join(a.base, best)).convert("RGBA"),
                         dtype=np.uint8)
            mask = (o != new).any(axis=2)
            allow = np.zeros(mask.shape, dtype=bool)
            for (x0, y0, x1, y1) in rects_by_page.get(f, []):
                allow[y0:y1 + 1, x0:x1 + 1] = True
            # 还要容忍"加色件的预乘/反预乘"引起的差异：加色件该预乘的像素位置会
            # 随部件集合变化（`mesh_style()` 修好后加色件变多），旧产物与新产物在
            # **布局**上可能不同 —— 但每个像素的变化只应该是"把 rgb 乘/除上 alpha"。
            rest = mask & ~allow
            ys, xs = np.where(rest)
            n_rel = n_zero = 0
            if ys.size:
                # 只对"矩形外且确实变了"的像素做关系判定（通常几百个，内存可忽略）
                # ⚠️ 必须用 int32：`rgb*alpha` 能到 65025，int16 会溢出（踩过）
                nb = new[ys, xs].astype(np.int32)          # (N,4)
                ob = o[ys, xs].astype(np.int32)
                tol = 2
                same_a = nb[:, 3] == ob[:, 3]
                na = np.maximum(nb[:, 3], 1)
                oa = np.maximum(ob[:, 3], 1)
                # 四种都算"合法差异"：谁被预乘过都解释得通
                #（预乘会把 rgb 按 α 压小，α=0/小的时候信息不可逆，所以两边都试）
                pm_o = (ob[:, :3] * ob[:, 3:4]) // 255          # 预乘(old) == new ?
                pm_n = (nb[:, :3] * nb[:, 3:4]) // 255          # 预乘(new) == old ?
                up_o = np.minimum(255, (ob[:, :3] * 255) // oa[:, None])
                up_n = np.minimum(255, (nb[:, :3] * 255) // na[:, None])
                rel = ((np.abs(nb[:, :3] - pm_o).max(axis=1) <= tol) |
                       (np.abs(ob[:, :3] - pm_n).max(axis=1) <= tol) |
                       (np.abs(nb[:, :3] - up_o).max(axis=1) <= tol) |
                       (np.abs(ob[:, :3] - up_n).max(axis=1) <= tol)) & same_a
                # α 在两边都是 0：像素根本不画（普通混合不画、加色件读的是**裁剪页**
                # 里那份已预乘的副本），rgb 差多少都看不出来
                zero = (nb[:, 3] == 0) & (ob[:, 3] == 0)
                n_rel, n_zero = int(rel.sum()), int((zero & ~rel).sum())
            leak = int(rest.sum()) - n_rel - n_zero
            print("  %-34s ≈旧 %-30s 改动 %d 像素；矩形外 %d"
                  "（其中 %d 个 预乘/反预乘、%d 个 两边都全透明，都可解释）"
                  % (f, best, int(mask.sum()), int(rest.sum()), n_rel, n_zero))
            if leak:
                print("      [fail] 矩形外也被改了 —— 就地烘焙改到了别的部件")
                bad += 1
            del new, o, mask, allow, rest

    print("\n%s" % ("PASS：乘法件的图集口径正确（与转换器账本逐条吻合）" if not bad
                    else "FAIL：%d 处问题" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

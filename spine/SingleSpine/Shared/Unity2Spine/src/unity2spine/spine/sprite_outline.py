# -*- coding: utf-8 -*-
r"""按 Unity 的 SpriteUtility.GenerateSpriteOutline 生成 sprite 的多边形网格。

为什么要：Unity 的 SpriteRenderer 默认用 **Tight** 网格（贴着 alpha 的多边形），
只有 FullRect 才是一整块四边形。我们原来永远发四边形，于是"精灵矩形里混进来的
别人图素 / 孤立小岛"会一起被画出来 -- 用户报的 alice_skin1_dl_idle
"右上角小黑点" 就是 parts_Horn_L 矩形角上那块 109 像素的孤立小岛
（见 docs/已知问题.md 1.6）。

逆向依据（2022.3.3f1c1 的 UnityPlayer.dll + PDB，资料在 _reverse/）：

    SpriteUtility.GenerateSpriteOutline(tex, ppu, rect, pivot, extrude, meshType, ...)
      -> SpriteMeshGenerator::MakeShape(pixels, w, h, alphaCutoff, dilate, ..., budget, ...)
           mask::initialize : 位掩码 = (alpha > alphaCutoff)，再按 dilate 膨胀
           contour          : 方向链码（45/43）走轮廓
           path::select     : 选主路径
           path::simplify   : 容差是**归一化到 [0,1]** 的（fminf(1.0, a2)）
           MakeShape 的迭代  : while (w*h*0.25 > 顶点预算 && 方向码==45) 重提轮廓
                              （顶点预算驱动的迭代放松，所以 Unity 的网格面积
                                会明显大于 alpha 面积，小岛被切在外面）

本模块复刻到：掩码 ->（可选膨胀）-> 取轮廓 -> 丢掉过小的孤立岛 ->
归一化容差的折线简化 -> 顶点预算内迭代放松 -> 耳切三角化。
任何一步出问题都返回 None，调用方回落四边形（保证不把产物做坏）。
"""
import os

try:
    import numpy as np
    from PIL import Image
except Exception:                                    # pragma: no cover
    np = None
    Image = None

try:
    from skimage import measure as _measure
except Exception:                                    # pragma: no cover
    _measure = None


MAX_VERTS = 96


def _mask_of(path, rect, alpha_cutoff):
    im = Image.open(path).convert("RGBA")
    W, H = im.size
    x, y, w, h = [int(round(v)) for v in rect]
    ytop = H - (y + h)
    reg = np.asarray(im)[ytop:ytop + h, x:x + w, 3]
    return (reg > alpha_cutoff), (W, H)


def _dilate(mask, r):
    out = mask
    for _ in range(int(r)):
        m = out
        out = m.copy()
        out[1:, :] |= m[:-1, :]
        out[:-1, :] |= m[1:, :]
        out[:, 1:] |= m[:, :-1]
        out[:, :-1] |= m[:, 1:]
    return out


def _rdp(pts, eps):
    if len(pts) < 3 or eps <= 0:
        return pts
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        ab = b - a
        L = float(np.hypot(ab[0], ab[1]))
        seg = pts[i + 1:j] - a
        if L < 1e-12:
            d = np.hypot(seg[:, 0], seg[:, 1])
        else:
            d = np.abs(seg[:, 0] * ab[1] - seg[:, 1] * ab[0]) / L
        k = int(np.argmax(d))
        if d[k] > eps:
            m = i + 1 + k
            keep[m] = True
            stack += [(i, m), (m, j)]
    return pts[keep]


def _poly_area(p):
    x = p[:, 0]
    y = p[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _ear_clip(poly):
    n = len(poly)
    if n < 3:
        return []
    idx = list(range(n))

    def cr(a, b, c):
        return ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))

    if sum(cr(poly[i], poly[(i + 1) % n], poly[(i + 2) % n])
           for i in range(n)) < 0:
        idx.reverse()
    tris, guard = [], 0
    while len(idx) > 3 and guard < 20000:
        guard += 1
        for i in range(len(idx)):
            i0, i1, i2 = idx[i - 1], idx[i], idx[(i + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if cr(a, b, c) <= 0:
                continue
            bad = False
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                p = poly[j]
                if (cr(a, b, p) >= 0 and cr(b, c, p) >= 0
                        and cr(c, a, p) >= 0):
                    bad = True
                    break
            if bad:
                continue
            tris.append((i0, i1, i2))
            idx.pop(i)
            break
        else:
            break
    if len(idx) == 3:
        tris.append((idx[0], idx[1], idx[2]))
    return tris


def build(tex_path, rect, pivot, ppu, extrude=1, alpha_cutoff=0,
          tol=0.02, min_island_px=4, max_verts=MAX_VERTS,
          flip_x=False, flip_y=False, cache=None):
    """生成 sprite 多边形网格；失败返回 None（调用方回落四边形）。

    坐标是 sprite 局部空间（pivot 在原点、世界单位），与 Unity 的
    Sprite.vertices 同一套；uv 用本链路约定（v 以贴图顶行为 0）。
    """
    if np is None or Image is None or _measure is None or not tex_path:
        return None
    try:
        key = (os.path.abspath(tex_path), tuple(rect), alpha_cutoff)
        if cache is not None and key in cache:
            mask, size = cache[key]
        else:
            mask, size = _mask_of(tex_path, rect, alpha_cutoff)
            if cache is not None:
                cache[key] = (mask, size)
        if not mask.any():
            return None
        m = _dilate(mask, extrude)
        cont = _measure.find_contours(m.astype(np.float32), 0.5)
        if not cont:
            return None
        x0, y0, w, h = [float(v) for v in rect]
        px = w * float(pivot[0])
        py = h * float(pivot[1])
        k = float(ppu) or 100.0
        W, H = size

        def to_local(rc):
            col = rc[:, 1]
            row = rc[:, 0]
            return np.stack([(col + 0.5 - px) / k,
                             ((h - row - 0.5) - py) / k], axis=1)

        def to_uv(rc):
            col = rc[:, 1]
            row = rc[:, 0]
            return np.stack([(x0 + col + 0.5) / W,
                             1.0 - (y0 + (h - row - 0.5)) / H], axis=1)

        # 丢掉过小的孤立岛。Unity 是"顶点预算驱动的迭代放松"把小岛切在外面，
        # 实测 alice 的 horn：主块 27045 px、那个小黑点只有 109 px（0.4%），
        # 所以用**相对阈值**（默认 1% of 最大岛）+ 绝对下限更贴近它的行为。
        raw = []
        for c in cont:
            p = to_local(c)
            if len(p) < 4:
                continue
            raw.append((_poly_area(p) * k * k, c))
        if not raw:
            return None
        raw.sort(key=lambda z: -z[0])
        # 下限要**小**：有的 sprite 整个矩形只有十几个实体像素
        # （bloodypanther 的 hair 零件是 8×12 px、实体 28 px），
        # 用 64 会把它的所有轮廓都当小岛丢掉 -> 只能回落四边形。
        # 真正管用的是那条相对规则（1% of 最大岛），它把 horn 那块
        # 109 px 的小岛相对 27045 px 的主块判掉。
        keep_min = max(float(min_island_px), 0.01 * raw[0][0])
        cand = [z for z in raw if z[0] >= keep_min]
        if not cand:
            return None

        scale = max(w, h) / k
        positions, uvs, tris = [], [], []
        for _a, c in cand:
            pts = to_local(c)
            uv = to_uv(c)
            if not np.allclose(pts[0], pts[-1]):
                pts = np.vstack([pts, pts[0]])
                uv = np.vstack([uv, uv[0]])
            eps = max(1e-6, tol * scale)
            sm = _rdp(pts, eps)
            guard = 0
            while len(sm) > max_verts and guard < 8:
                eps *= 1.7
                sm = _rdp(pts, eps)
                guard += 1
            if len(sm) < 3:
                continue                    # 这块太小、简化后退化 ⇒ 丢掉
            if not np.allclose(sm[0], sm[-1]):
                sm = np.vstack([sm, sm[0]])
            ring = sm[:-1]
            idx = [int(np.argmin(np.hypot(pts[:, 0] - v[0], pts[:, 1] - v[1])))
                   for v in ring]
            base = len(positions)
            positions += [(-float(p[0]) if flip_x else float(p[0]),
                           -float(p[1]) if flip_y else float(p[1]))
                          for p in ring]
            uvs += [tuple(q) for q in (uv[idx] if len(idx)
                                       else uv[:len(ring)])]
            for t in _ear_clip(ring):
                a, b, c = t
                if flip_x != flip_y:
                    a, b, c = a, c, b
                tris += [base + a, base + b, base + c]
        if len(positions) < 3 or len(tris) < 3:
            return None
        return {"positions": positions, "uvs": uvs, "triangles": tris,
                "bindposes": [], "weights": [], "boneIndexRaw": []}
    except Exception:
        return None

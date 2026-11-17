# -*- coding: utf-8 -*-
"""把多个 NGUI 图集页里“真正用到的裁切块”重新打包成一/少数 Spine 图集页。"""

from PIL import Image


def _next_pow2(v):
    p = 1
    while p < v:
        p <<= 1
    return p


def _shelf_fit(items, width, height):
    """简单 shelf(先按高降序)放置。成功返回 [(name, (x,y))]；失败返回 None。"""
    order = sorted(items, key=lambda it: (-it[1].height, -it[1].width))
    placements = {}
    shelves = []  # (y, row_height, x_next)
    for it in order:
        name, img = it[0], it[1]
        w, h = img.size
        placed = None
        for i, (y, rh, x) in enumerate(shelves):
            if rh >= h and x + w <= width:
                shelves[i] = (y, rh, x + w)
                placed = (x, y)
                break
        if placed is None:
            y = shelves[-1][0] + shelves[-1][1] if shelves else 0
            if y + h > height:
                return None
            shelves.append((y, h, w))
            placed = (0, y)
        placements[name] = placed
    return placements


def pack_items(items, max_dim=4096):
    """items: [(name, PIL.Image, meta)]。
    返回 [{file, image, regions:[(name, new_meta)]}]。
    会优先尝试把所有图片放进一张（宽高取 2 的幂、面积最小的方案）。
    """
    if not items:                       # 全部 region 都被排除时不要炸
        return []
    total = sum(i[1].width * i[1].height for i in items)
    widest = max(i[1].width for i in items)
    min_w = _next_pow2(max(widest, int(total ** 0.5)))
    best = None  # (area, w, h, placements)
    w = max(256, min_w)
    while w <= max_dim:
        h_limit = max_dim
        ph = _shelf_fit(items, w, h_limit)
        if ph is not None:
            used_h = max((ph[it[0]][1] + it[1].height for it in items), default=0)
            used_h = _next_pow2(used_h)
            if used_h > max_dim:
                used_h = max_dim
            if best is None or w * used_h < best[0]:
                best = (w * used_h, w, used_h, ph)
        w <<= 1

    pages = []
    if best is not None:
        area, pw, ph, placements = best
        pages.append(_make_page(items, pw, ph, placements))
        return pages

    # 极端情况下单页放不下：贪心切页
    remain = list(items)
    idx = 0
    while remain:
        used = []
        rest = []
        w = min(max_dim, max(256, _next_pow2(int(sum(i[1].width * i[1].height
                                                   for i in remain)) ** 0.5)))
        ph = None
        for cand in (w, max_dim):
            ph = _shelf_fit(remain, cand, max_dim)
            if ph:
                w = cand
                break
        if ph is None:
            # 放不下单个 sprite 时的最后兜底：逐张单独成页
            name, img, meta = remain.pop(0)
            pages.append(_make_page([(name, img, meta)], _next_pow2(img.width),
                                    _next_pow2(img.height), {name: (0, 0)}))
            continue
        for name, img, meta in remain:
            if name in ph:
                used.append((name, img, meta))
            else:
                rest.append((name, img, meta))
        pages.append(_make_page(used, w, max_dim, ph))
        remain = rest
        idx += 1
        if idx > 64:
            break
    return pages


def _make_page(items, pw, ph, placements):
    img = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    regions = []
    for name, crop, meta in items:
        x, y = placements[name]
        img.paste(crop, (x, y))
        new_meta = dict(meta)
        new_meta["x"] = x
        new_meta["y"] = y
        regions.append((name, new_meta))
    regions.sort(key=lambda r: (r[1]["y"], r[1]["x"]))
    return {"image": img, "size": img.size, "regions": regions}

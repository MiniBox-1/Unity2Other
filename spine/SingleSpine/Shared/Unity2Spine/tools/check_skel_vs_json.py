# -*- coding: utf-8 -*-
r"""验证 **`.skel` 与 `.json` 是不是同一份数据**（删 JSON 之前必须先过这一关）。

做法：用查看器那套 spine-cpp 绑定（`D:\VB\Viewer\Render\v4\renderer_src\Spine\Spine380.pyd`）
把两个文件**各加载一遍**，然后
  ① 比动画名（集合+顺序）、皮肤名；
  ② setup 姿态的顶点/索引缓冲（VBO/IBO 长度 + 逐元素差）；
  ③ 每条动画取若干归一化时刻 `SetAnimationTime → Update → Apply → UpdateWorldTransform`，
     比顶点缓冲（逐元素 max|Δ|、逐顶点 max 欧氏距离）。

⚠️ 一次只跑**一个**角色目录（大 JSON 解析很吃内存），用法：

```powershell
$py="D:\VB\Viewer\Render\v4\.venv\Scripts\python.exe"
& $py tools\check_skel_vs_json.py --dir <产物目录>
```
"""
import argparse
import json
import os
import sys

SPINE_DIR = r"D:\VB\Viewer\Render\v4\renderer_src\Spine"
if SPINE_DIR not in sys.path:
    sys.path.append(SPINE_DIR)


def find(d, suffix):
    for f in sorted(os.listdir(d)):
        if f.endswith(suffix):
            return os.path.join(d, f)
    return None


def vbo_of(skel_mod, d):
    s = d.getSkeleton()
    s.SetToSetupPose()
    s.UpdateWorldTransform()
    return s, d.getAnimationState()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--times", default="0,0.25,0.5,0.75,0.99")
    ap.add_argument("--max-anims", type=int, default=0, help="只查前 N 条动画（0=全部）")
    a = ap.parse_args()
    D = a.dir
    js = find(D, "_static.json")
    sk = find(D, "_static.skel")
    at = find(D, ".atlas")
    print("目录: %s" % os.path.basename(D.rstrip("\\/")))
    print("  json: %s (%.1f MB)" % (js and os.path.basename(js),
                                    (os.path.getsize(js) / 1048576.0) if js else 0))
    print("  skel: %s (%.1f MB)" % (sk and os.path.basename(sk),
                                    (os.path.getsize(sk) / 1048576.0) if sk else 0))
    if not (js and sk and at):
        raise SystemExit("缺 json/skel/atlas")
    import Spine380
    import gc

    print("  加载 json…", flush=True)
    dj = Spine380.SpineData(js, [at], False, 0.0)
    sj, stj = vbo_of(Spine380, dj)
    print("  加载 skel…", flush=True)
    dk = Spine380.SpineData(sk, [at], True, 0.0)
    sk_, stk = vbo_of(Spine380, dk)

    nj, nk = list(sj.GetAnimationNames()), list(sk_.GetAnimationNames())
    print("  动画: json %d 个 / skel %d 个  名字一致=%s"
          % (len(nj), len(nk), nj == nk))
    if nj != nk:
        print("     只在 json: %s" % sorted(set(nj) - set(nk)))
        print("     只在 skel: %s" % sorted(set(nk) - set(nj)))
    gj, gk = list(sj.GetSkinNames()), list(sk_.GetSkinNames())
    print("  皮肤: %s / %s  一致=%s" % (gj, gk, gj == gk))

    def cmp_vbo(tag, bj, bk):
        # 顶点缓冲要走 **buffer 协议**（和查看器 `SpineRender.py:810` 一样）：
        #   np.array(gb, copy=False, dtype='f4')  /  gb.getIbo()
        import numpy as np
        vj = np.array(bj, copy=False, dtype="f4")
        vk = np.array(bk, copy=False, dtype="f4")
        if len(vj) != len(vk):
            print("      %s: **长度不同** json=%d skel=%d" % (tag, len(vj), len(vk)))
            return None
        mx = float(np.abs(vj - vk).max()) if len(vj) else 0.0
        ij = np.array(bj.getIbo(), copy=False, dtype="i4")
        ik = np.array(bk.getIbo(), copy=False, dtype="i4")
        iok = (len(ij) == len(ik)) and (len(ij) == 0 or bool((ij == ik).all()))
        print("      %s: VBO %d float max|Δ|=%.3e   IBO %d/%d %s   blendRanges %s/%s"
              % (tag, len(vj), mx, len(ij), len(ik), "一致" if iok else "**不同**",
                 getattr(bj, "blendRanges", None), getattr(bk, "blendRanges", None)))
        return mx

    cmp_vbo("setup 姿态", sj.getGLBuffer(), sk_.getGLBuffer())
    times = [float(x) for x in a.times.split(",")]
    anims = nj if not a.max_anims else nj[:a.max_anims]
    worst = 0.0
    for nm in anims:
        stj = dj.getAnimationState()
        stj.SetAnimation(0, nm, False)
        stk2 = dk.getAnimationState()
        stk2.SetAnimation(0, nm, False)
        mx = 0.0
        for tn in times:
            stj.SetAnimationTime(0, tn)
            stj.Update(0.0)
            stj.Apply(sj)
            sj.UpdateWorldTransform()
            stk2.SetAnimationTime(0, tn)
            stk2.Update(0.0)
            stk2.Apply(sk_)
            sk_.UpdateWorldTransform()
            m = cmp_vbo("  %-28s t=%.2f" % (nm, tn), sj.getGLBuffer(), sk_.getGLBuffer())
            if m is not None and m > mx:
                mx = m
        worst = max(worst, mx)
        # 复位 ready 状态，避免下一条动画受影响
        stj.ClearTracks()
        stk2.ClearTracks()
        del stj, stk2
        gc.collect()
    print("  汇总：顶点缓冲最大差 = %.3e（px，0 表示逐位一致）" % worst)
    return 0


if __name__ == "__main__":
    sys.exit(main())

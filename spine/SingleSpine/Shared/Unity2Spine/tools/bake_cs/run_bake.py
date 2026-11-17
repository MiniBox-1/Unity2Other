# -*- coding: utf-8 -*-
r"""驱动 Unity 侧 CS 烘焙（每次只采一个 state，避免 MCP 调用超时/内存爆）。

流程：
  1 从产物里取「候选部件路径」+「每条动画的关键帧时刻」写成文件
  2 逐个 state 写 plan.txt -> 调 mcp_exec.py 跑 runner_bake2.cs
  3 把 per-state 结果拼成 bake.json（流式拼接，不整包解析）

用法:
    python run_bake.py --product <产物目录> --prefab <uAnim.prefab> [--outdir <目录>]
        [--states lobby,breast] [--probe 1] [--abevery 2] [--no-run]

--no-run 只生成 parts.txt / keys，不调 Unity（自检用）。
"""

import argparse
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRATCH = r"D:\VB\Unity2Spine\_scratch\_csbake"
PLAN = os.path.join(SCRATCH, "plan.txt")
RUNNER = os.path.join(SCRATCH, "runner_bake2.cs")


def load_json(p):
    with io.open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def find_json(d):
    for fn in os.listdir(d):
        if fn.endswith("_static.json"):
            return os.path.join(d, fn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", required=True)
    ap.add_argument("--prefab", required=True)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--states", default="")
    ap.add_argument("--probe", default="1")
    ap.add_argument("--abevery", type=int, default=2)
    ap.add_argument("--abstate", default=None)
    ap.add_argument("--fps", default="60")
    ap.add_argument("--overlay", action="append", default=[],
                    help="非 Base Layer 状态要叠的其它层默认状态 clip，"
                         "写法 <state>=<clip>[,<clip>]；不叠的话那条 state 的 A "
                         "姿态会漏掉基底层（curtain 上实测 delta 恒为 0）")
    ap.add_argument("--no-run", action="store_true")
    a = ap.parse_args()

    overlay = {}
    for spec in a.overlay:
        if "=" not in spec:
            raise SystemExit("--overlay 要写成 <state>=<clip>[,<clip>]：%r" % spec)
        st, cl = spec.split("=", 1)
        overlay[st.strip()] = [x.strip() for x in cl.split(",") if x.strip()]

    info = load_json(os.path.join(a.product, "_static_info.json"))
    sk = load_json(find_json(a.product))
    base = os.path.basename(a.prefab)
    if base.endswith(".prefab"):
        base = base[: -len(".prefab")]
    outdir = a.outdir or os.path.join(SCRATCH, base)
    os.makedirs(outdir, exist_ok=True)
    keysdir = os.path.join(outdir, "keys")
    os.makedirs(keysdir, exist_ok=True)

    parts = []
    for m in info.get("partsMeta") or []:
        p = (m.get("path") or "").replace("\\", "/")
        seg = p.split("/")
        rel = "/".join(seg[1:]) if len(seg) > 1 else p
        if rel:
            parts.append(rel)
    parts_path = os.path.join(outdir, "parts.txt")
    with io.open(parts_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(set(parts))) + "\n")
    print("候选部件 %d 个 -> %s" % (len(set(parts)), parts_path))

    states = [s.strip() for s in a.states.split(",") if s.strip()] \
        if a.states else list(sk.get("animations", {}).keys())
    for st in states:
        anim = sk["animations"].get(st)
        if not anim:
            print("  [warn] 产物里没有动画 %s" % st)
            continue
        ts = set()
        for nm, smap in (anim.get("deform") or {}).get("default", {}).items():
            for att, frames in smap.items():
                for fr in frames:
                    ts.add(round(float(fr["time"]), 6))
        ts = sorted(ts)
        with io.open(os.path.join(keysdir, st + ".txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join("%.6f" % t for t in ts) + "\n")
        print("  key %-26s %4d 个时刻（0 ~ %.3f）"
              % (st, len(ts), ts[-1] if ts else 0))

    abstate = a.abstate if a.abstate is not None else (info.get("setupClip") or "-")
    if abstate not in states:
        abstate = states[0] if states else "-"
    print("absA 只记 state = %s（每 %d 个关键帧一次）" % (abstate, a.abevery))
    if overlay:
        print("叠层: %s" % "，".join("%s←%s" % (k, "+".join(v))
                                     for k, v in sorted(overlay.items())))

    if a.no_run:
        return 0

    # --- 先单独跑一次"探测"（用全新实例），把"真的会被 CS 改动的渲染器"列出来。
    #     探测本身会把 DynamicBone 的粒子状态搅乱（实测能让 B-A 差 1e-3 世界单位），
    #     所以正式采集必须在**没探测过**的实例上跑。
    picked_path = os.path.join(outdir, "picked.txt")
    with io.open(PLAN, "w", encoding="utf-8") as fh:
        fh.write("prefab=%s\nout=%s\nclip=%s\nfps=%s\nparts=%s\nkeys=%s\n"
                 "abstate=-\nabevery=1\nprobe=%s\nbake=0\n"
                 % (a.prefab, picked_path, states[0], a.fps, parts_path, keysdir,
                    a.probe))
        # 探测也要带叠层：非 Base Layer 的状态，不叠的话探测会漏掉"只有基底层
        # 才驱动得动"的部件（curtain 上实测漏掉 parts_Tail_B）。
        if overlay.get(states[0]):
            fh.write("layers=%s\n" % ",".join(overlay[states[0]]))
    print("  -> 探测受影响的渲染器 ...", flush=True)
    r = subprocess.run([sys.executable, os.path.join(HERE, "mcp_exec.py"), RUNNER],
                       cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("     %s" % (r.stdout or "").strip()[-400:])
    have_picked = os.path.exists(picked_path)
    if have_picked:
        with io.open(picked_path, encoding="utf-8") as fh:
            n_picked = len([x for x in fh.read().splitlines()
                            if x.strip() and not x.startswith("#")])
        print("     探测命中 %d 个渲染器 -> %s" % (n_picked, picked_path))

    done = []
    for st in states:
        outp = os.path.join(outdir, st + ".json")
        with io.open(PLAN, "w", encoding="utf-8") as fh:
            fh.write("# auto-generated by run_bake.py\n")
            fh.write("prefab=%s\n" % a.prefab)
            fh.write("out=%s\n" % outp)
            fh.write("clip=%s\n" % st)
            fh.write("fps=%s\n" % a.fps)
            fh.write("parts=%s\n" % parts_path)
            fh.write("keys=%s\n" % keysdir)
            fh.write("abstate=%s\n" % abstate)
            fh.write("abevery=%d\n" % a.abevery)
            fh.write("probe=0\n")
            if have_picked:
                fh.write("picked=%s\n" % picked_path)
            if overlay.get(st):
                fh.write("layers=%s\n" % ",".join(overlay[st]))
        print("  -> 采 %s ..." % st, flush=True)
        r = subprocess.run([sys.executable, os.path.join(HERE, "mcp_exec.py"), RUNNER],
                           cwd=HERE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        print("     %s" % (r.stdout or "").strip()[-700:])
        if not os.path.exists(outp):
            print("     [fail] 没有产出 %s" % outp)
            continue
        done.append((st, outp, os.path.getsize(outp)))

    if not done:
        raise SystemExit("没有任何 state 采集成功")

    bake_path = os.path.join(outdir, "bake.json")
    pieces = []
    with io.open(bake_path, "w", encoding="utf-8") as fh:
        fh.write("{\n \"product\": %s,\n \"fps\": %s,\n \"clips\": [\n"
                 % (json.dumps(a.product), float(a.fps)))
        for i, (st, p, _sz) in enumerate(done):
            d = load_json(p)
            if i > 0:
                fh.write(",\n")
            fh.write(json.dumps({
                "state": d["state"], "clip": d["clip"], "length": d["length"],
                "nFrames": d["nFrames"], "times": d["keyTimes"],
                "absEvery": d.get("absEvery", 1),
                "absState": d.get("absState", ""),
                "renderers": d["renderers"], "data": d["data"]},
                ensure_ascii=False, separators=(",", ":")))
            pieces.append("%s %.1fMB" % (st, _sz / 1048576.0))
        fh.write("\n ]\n}\n")
    print("拼装 -> %s (%.1f MB)  [%s]"
          % (bake_path, os.path.getsize(bake_path) / 1048576.0, ", ".join(pieces)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

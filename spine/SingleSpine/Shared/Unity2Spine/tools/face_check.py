# -*- coding: utf-8 -*-
"""单脸截出 + vision.js 校验。

每次转换后自动执行：
1. 从 Spine JSON 中只取脸/面罩附件（parts_head / face / BL_parts_head 等，
   排除 glow），生成只含脸的临时骨架；
2. 调用 Render 离线渲染器输出单脸 PNG；
3. 调用 node D:\\VB\\vision.js 对该 PNG 做方向/花纹校验，并保存结果。

用法：
  python tools/face_check.py <spine目录> [--out <目录>] [--size 768x768]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

RENDER_PY = r"D:\VB\Viewer\Render\.venv\Scripts\python.exe"
RENDER_PY_SCRIPT = r"D:\VB\Viewer\Render\render_offline.py"
VISION_JS = r"D:\VB\vision.js"


def _is_face(name):
    low = name.lower()
    if "glow" in low or "star" in low or "fx" in low:
        return False
    return ("head" in low) or ("face" in low)


def face_check(spine_dir, out_dir=None, size=None):
    spine_dir = os.path.abspath(spine_dir)
    out_dir = os.path.abspath(out_dir or os.path.join(spine_dir, "_face_check"))
    os.makedirs(out_dir, exist_ok=True)

    # 默认按素材原尺寸渲染（避免下采样）：优先取 _static_info.json 里记录的
    # 源贴图尺寸，其次取图集页大小。
    if size is None:
        size = "2048x2048"
        try:
            import json as _json
            info_p = os.path.join(spine_dir, "_static_info.json")
            if os.path.isfile(info_p):
                _info = _json.load(open(info_p, encoding="utf-8-sig"))
                srcs = _info.get("sourceSizes") or []
                if srcs:
                    w, h = srcs[0]
                    size = "%dx%d" % (w, h)
        except Exception:
            pass

    # 目录里可能有 .config.json / _static_info.json，按内容挑真正的骨架 json
    data = None
    src = None
    for f in sorted(os.listdir(spine_dir)):
        if not f.endswith(".json") or f.startswith((".", "_")):
            continue
        cand = json.load(open(os.path.join(spine_dir, f),
                              encoding="utf-8-sig"))
        if isinstance(cand, dict) and ("skins" in cand or "bones" in cand):
            data, src = cand, os.path.join(spine_dir, f)
            break
    if data is None:
        raise SystemExit(
            "目录里没有 spine json: %s\n"
            "（2026-10-10 起**标准导出只出 .skel**；要跑 face_check 请用 "
            "`--json` 重新导出一次，或对它指向带 .json 的目录）" % spine_dir)

    atts = data["skins"][0]["attachments"]
    face_names = [n for n in atts if _is_face(n)]
    if not face_names:
        raise SystemExit("没有脸/面罩附件可截取")

    data["slots"] = [s for s in data["slots"] if s["name"] in face_names]
    data["skins"] = [{"name": "default",
                      "attachments": {n: atts[n] for n in face_names}}]
    data["animations"] = {"idle": {}}

    face_dir = os.path.join(out_dir, "spine")
    os.makedirs(face_dir, exist_ok=True)
    for f in os.listdir(spine_dir):
        if f.endswith((".atlas", ".png")):
            shutil.copy2(os.path.join(spine_dir, f), os.path.join(face_dir, f))
    json.dump(data, open(os.path.join(face_dir, "face.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=1)

    render_out = os.path.join(out_dir, "render")
    subprocess.run([RENDER_PY, RENDER_PY_SCRIPT, face_dir, "--only", "spine",
                    "--size", size, "--background", "255,255,255,255",
                    "--output", render_out, "--in-process"], check=True)
    pngs = []
    for root, _dirs, files in os.walk(render_out):
        pngs += [os.path.join(root, f) for f in files if f.endswith(".png")]
    if not pngs:
        raise SystemExit("单脸渲染没有输出 PNG")

    prompt = ("这是只含脸部/面罩的图：尖角(下巴/窄端)在上还是下？"
              "花纹/发光图案在哪一端？是否有明显上下颠倒或左右镜像？")
    env = dict(os.environ)
    res = subprocess.run(["node", VISION_JS, pngs[0], prompt],
                         capture_output=True, text=True, encoding="utf-8",
                         env=env)
    try:
        print(res.stdout)
    except UnicodeEncodeError:
        print(res.stdout.encode("utf-8", "replace").decode("utf-8"))
    open(os.path.join(out_dir, "face_vision.txt"), "w",
         encoding="utf-8").write(res.stdout or "")
    return pngs[0]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spine_dir")
    ap.add_argument("--out")
    ap.add_argument("--size", default=None,
                    help="渲染画布尺寸，默认取源贴图原尺寸（1:1）")
    a = ap.parse_args()
    print(face_check(a.spine_dir, a.out, a.size))

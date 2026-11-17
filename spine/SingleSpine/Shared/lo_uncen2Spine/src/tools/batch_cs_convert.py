# -*- coding: utf-8 -*-
r"""批量把 `Assets\Prefabs\*.uAnim.prefab` 用 **纯离线** 的 `--cs` 转成 Spine 产物。

用法:
    python src/tools\batch_cs_convert.py                 # 全量（157 个）
    python src/tools\batch_cs_convert.py --limit 3       # 只跑前 3 个（冒烟测速）
    python src/tools\batch_cs_convert.py --only Alice,Alexandra   # 名字子串匹配
    python src/tools\batch_cs_convert.py --skip-done     # 已有 *_static.skel 的跳过
    python src/tools\batch_cs_convert.py --no-static-check        # 省掉逐角色自检

设计要点:
  * **每个角色一个子进程**（崩/挂只影响那一个，批量不会中断）；
  * 每个角色一行开始/结束日志 + 尾部输出，实时 flush，便于盯进度；
  * 结束写 `_scratch\batch_cs_<时间戳>.log` 与 `..._summary.txt`（ok/失败清单 + 耗时）。
"""
# --- lo_uncen2Spine: 位置解析（自动插入，见 src/tools\deabs_paths.py）------
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

import argparse
import io
import os
import shutil
import subprocess
import sys
import time

REPO = _app_root()
ASSETS = _resolve(r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old\Assets")
OUT = _resolve(r"D:\VB\Search\New\归档-proj-Mobile-old\_spine_conv_cs_port")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=ASSETS)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default=None, help="逗号分隔的名字子串")
    ap.add_argument("--exact-file", default=None, metavar="TXT",
                    help="只转清单里的角色（每行一个名字，精确匹配；"
                         "可用 `src/tools\\shader_usage_inventory.py --out-txt` 生成）")
    ap.add_argument("--skip-done", action="store_true")
    ap.add_argument("--no-static-check", action="store_true")
    ap.add_argument("--timeout", type=float, default=2400.0, help="单角色秒数上限")
    a = ap.parse_args()

    pfdir = os.path.join(a.assets, "Prefabs")
    names = sorted(fn for fn in os.listdir(pfdir) if fn.endswith(".uAnim.prefab"))
    if a.only:
        keys = [s.strip() for s in a.only.split(",") if s.strip()]
        names = [n for n in names if any(k in n for k in keys)]
    if a.exact_file and os.path.isfile(a.exact_file):
        want = set()
        for line in io.open(a.exact_file, encoding="utf-8-sig"):
            line = line.split("#", 1)[0].strip()
            if line:
                want.add(line)
        names = [n for n in names
                 if n.replace(".uAnim.prefab", "") in want]
    if a.skip_done:
        # 产物文件名保留 `.uAnim`（`<prefab基名>_static.skel`），目录名去掉 `.uAnim`：
        #   Assets\Prefabs\2DModel_3P_Alice_NS1.uAnim.prefab
        #   -> _spine_conv_cs_port\2DModel_3P_Alice_NS1\2DModel_3P_Alice_NS1.uAnim_static.skel
        def _done(fn):
            base = fn[:-len(".prefab")]                      # 含 .uAnim
            d = fn.replace(".uAnim.prefab", "")              # 去 .uAnim
            return os.path.isfile(os.path.join(a.out, d, base + "_static.skel"))
        names = [n for n in names if not _done(n)]
    if a.limit:
        names = names[:a.limit]

    ts = time.strftime("%Y%m%d_%H%M%S")
    logp = os.path.join(REPO, ".cache", "logs", "batch_cs_%s.log" % ts)
    os.makedirs(os.path.dirname(logp), exist_ok=True)
    log = io.open(logp, "w", encoding="utf-8")

    def w(msg):
        print(msg)
        log.write(msg + "\n")
        log.flush()

    w("批量开始 %s  角色数=%d" % (ts, len(names)))
    w("assets=%s" % a.assets)
    w("out=%s" % a.out)
    ok, bad = [], []
    t0 = time.time()
    for i, fn in enumerate(names, 1):
        name = fn.replace(".uAnim.prefab", "")
        pre = os.path.join(pfdir, fn)
        dst = os.path.join(a.out, name)
        # ★ 2026-10-13（用户要求"删除所有旧的，全部重新转换"）：每个角色转换前先清空它的
        #   产物目录，避免旧文件（例如以前 Debug 用的 .json）残留在新口径的产物里。
        if os.path.isdir(dst):
            # 用户改为：**旧结果整体搬到** `D:\VB\Search\del\`（可回退），不要就地删。
            _old_root = os.environ.get("U2S_OLD_OUT", _resolve(r"D:\VB\Search\del"))
            _tgt = os.path.join(_old_root, os.path.basename(dst))
            try:
                os.makedirs(_old_root, exist_ok=True)
                if os.path.isdir(_tgt):
                    _tgt += "_" + time.strftime("%Y%m%d_%H%M%S")
                shutil.move(dst, _tgt)
                w("        旧产物已搬到 " + _tgt)
            except Exception as ex:                                  # noqa: BLE001
                w("        [warn] 旧产物搬移失败：%r" % (ex,))
        cmd = [sys.executable, "-m", "unity2spine.convert.static_prefab_spine",
               pre, dst, "--assets", a.assets, "--skel", "--no-face-check", "--cs"]
        if a.no_static_check:
            cmd.append("--no-static-check")
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        # 代码在 <根>\src 下，子进程要能找到 unity2spine（与父进程同一份代码）
        env["PYTHONPATH"] = _ROOT + os.pathsep + env.get("PYTHONPATH", "")
        # ★ 2026-10-13：**每角色口径表**（`config/per_char_env.txt`，每行
        #   `名字子串<TAB>K=V[;K=V]`）。教训：Echidna 的灯光修复是靠
        #   `U2S_LAYER_PHASE=0.499` 这种"每角色环境变量"实现的，全量重转如果不带上，
        #   修好的东西会整体回退（用户 2026-10-13 报的"灯光又出问题"就是它）。
        _cfg = os.path.join(REPO, "config", "per_char_env.txt")
        if os.path.isfile(_cfg):
            for _ln in io.open(_cfg, encoding="utf-8-sig"):
                _ln = _ln.split("#", 1)[0].strip()
                if not _ln or "\t" not in _ln:
                    continue
                _k, _v = _ln.split("\t", 1)
                if _k.strip() and _k.strip() in name:
                    for _kv in _v.split(";"):
                        if "=" in _kv:
                            _a, _b = _kv.split("=", 1)
                            env[_a.strip()] = _b.strip()
                            w("        每角色口径 %s" % _kv.strip())
        t1 = time.time()
        w("[%3d/%3d] START %-44s" % (i, len(names), name))
        try:
            p = subprocess.run(cmd, cwd=REPO, env=env, timeout=a.timeout,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            dt = time.time() - t1
            tail = [ln for ln in (p.stdout or "").splitlines() if ln.strip()][-3:]
            if p.returncode == 0:
                ok.append((name, dt))
                w("[%3d/%3d]   OK   %6.1fs  %s" % (i, len(names), dt, " | ".join(tail)))
            else:
                bad.append((name, dt, "rc=%d" % p.returncode))
                w("[%3d/%3d]  FAIL  %6.1fs  rc=%d" % (i, len(names), dt, p.returncode))
                for ln in (p.stdout or "").splitlines()[-6:]:
                    w("        out| " + ln)
                for ln in (p.stderr or "").splitlines()[-12:]:
                    w("        err| " + ln)
        except subprocess.TimeoutExpired:
            dt = time.time() - t1
            bad.append((name, dt, "timeout"))
            w("[%3d/%3d]  FAIL  %6.1fs  超时 >%.0fs" % (i, len(names), dt, a.timeout))
        except Exception as ex:                                     # noqa: BLE001
            dt = time.time() - t1
            bad.append((name, dt, repr(ex)))
            w("[%3d/%3d]  FAIL  %6.1fs  %r" % (i, len(names), dt, ex))

    tot = time.time() - t0
    w("")
    w("批量结束：成功 %d / 失败 %d，总耗时 %.1f 分钟" % (len(ok), len(bad), tot / 60.0))
    if ok:
        avg = sum(d for _n, d in ok) / len(ok)
        w("平均单角色 %.1fs ⇒ 157 个预计 %.1f 小时" % (avg, avg * 157 / 3600.0))
    for n, d, why in bad:
        w("  FAIL %-44s %6.1fs  %s" % (n, d, why))
    sump = logp.replace(".log", "_summary.txt")
    with io.open(sump, "w", encoding="utf-8") as fh:
        fh.write("log=%s\n" % logp)
        fh.write("成功 %d / 失败 %d  总 %.1f 分钟\n" % (len(ok), len(bad), tot / 60.0))
        fh.write("\n".join("OK   %-44s %6.1fs" % (n, d) for n, d in ok))
        fh.write("\n")
        fh.write("\n".join("FAIL %-44s %6.1fs %s" % (n, d, w2) for n, d, w2 in bad))
        fh.write("\n")
    w("日志: %s" % logp)
    w("汇总: %s" % sump)
    log.close()
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())

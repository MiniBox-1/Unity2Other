# -*- coding: utf-8 -*-
"""Convert every 2DModel *.uAnim.prefab to a multibone Spine product.

Each conversion runs serially.  A per-process memory guard aborts a job before
it can exhaust the machine.  The deform baseline is temporary and is removed
after the multibone product passes structural validation.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

import psutil

BASE = r"D:\VB\MutiBone"
UNITY_LIB = r"D:\VB\Unity2Spine"
PROJECT = r"D:\VB\Search\New\归档-proj-Mobile-old\proj-Mobile-old"
ASSETS = os.path.join(PROJECT, "Assets")
PREFAB_ROOT = os.path.join(ASSETS, "Prefabs")
PYTHON = r"D:\Anconda\python.exe"
CONVERT = os.path.join(BASE, "src", "convert_bones.py")
VALIDATE = os.path.join(BASE, "tools", "validate_multibone.py")


def safe_rmtree(path, root):
    path = os.path.realpath(path)
    root = os.path.realpath(root)
    if os.path.commonpath([path, root]) != root or path == root:
        raise RuntimeError("refusing to remove outside work root: %s" % path)
    if os.path.isdir(path):
        shutil.rmtree(path)


def process_tree_rss(process):
    total = 0
    try:
        total += process.memory_info().rss
        for child in process.children(recursive=True):
            try:
                total += child.memory_info().rss
            except psutil.Error:
                pass
    except psutil.Error:
        pass
    return total


def run_guarded(cmd, cwd, log_path, limit_mb, timeout_s):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    started = time.perf_counter()
    peak = 0
    killed = False
    timed_out = False
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "wb") as log:
        log.write(("CWD=%s\nCMD=%s\n\n" % (cwd, subprocess.list2cmdline(cmd)))
                  .encode("utf-8"))
        log.flush()
        process = subprocess.Popen(
            cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
            env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        wrapped = psutil.Process(process.pid)
        while process.poll() is None:
            peak = max(peak, process_tree_rss(wrapped))
            if peak > limit_mb * 1048576:
                killed = True
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                break
            if time.perf_counter() - started > timeout_s:
                timed_out = True
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                break
            time.sleep(0.25)
        try:
            return_code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            return_code = -9
    return {
        "returnCode": return_code,
        "peakMB": round(peak / 1048576.0, 1),
        "seconds": round(time.perf_counter() - started, 2),
        "killedByMemory": killed,
        "timedOut": timed_out,
        "log": log_path,
    }


def prefab_list():
    found = []
    for root, _, files in os.walk(PREFAB_ROOT):
        for name in files:
            if name.endswith(".uAnim.prefab"):
                found.append(os.path.join(root, name))
    return sorted(found, key=lambda path: os.path.basename(path).lower())


def find_one(directory, suffix):
    for name in sorted(os.listdir(directory)):
        if name.endswith(suffix):
            return os.path.join(directory, name)
    return None


def write_report(out_dir, total, results):
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "total": total,
        "completed": len(results),
        "ok": sum(
            1 for row in results if row["status"] in ("ok", "ok-existing")
        ),
        "failed": sum(
            1 for row in results if row["status"].startswith("failed")
        ),
        "results": results,
    }
    path = os.path.join(out_dir, "conversion_report.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(BASE, "out", "_all_prefabs"))
    parser.add_argument("--work", default=os.path.join(BASE, "out", "_all_prefabs_work"))
    parser.add_argument("--limit-mb", type=int, default=4500)
    parser.add_argument("--timeout-sec", type=int, default=1800)
    parser.add_argument(
        "--deform-dt", type=float, default=0.2,
        help="Temporary deform-baseline sample interval; final multibone keeps "
             "its own animation sampling.",
    )
    parser.add_argument(
        "--deform-clip", default="",
        help="Optional clip filter for the temporary deform baseline.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--only", default="", help="comma-separated prefab stems")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    available_gb = psutil.virtual_memory().available / 1073741824.0
    if available_gb < 3.0:
        raise SystemExit("Free memory below 3 GB: %.1f GB" % available_gb)

    os.makedirs(args.out, exist_ok=True)
    os.makedirs(args.work, exist_ok=True)
    prefabs = prefab_list()
    if args.only:
        wanted = {
            item.strip().casefold() for item in args.only.split(",") if item.strip()
        }
        prefabs = [
            path for path in prefabs
            if os.path.splitext(os.path.basename(path))[0].casefold() in wanted
        ]

    results = []
    for index, prefab in enumerate(prefabs, 1):
        stem = os.path.splitext(os.path.basename(prefab))[0]
        out_dir = os.path.join(args.out, stem)
        deform_dir = os.path.join(args.work, stem, "deform")
        logs_dir = os.path.join(args.out, "_logs")
        print("[%03d/%03d] %s" % (index, len(prefabs), stem), flush=True)

        existing_json = find_one(out_dir, "_static.json") if os.path.isdir(out_dir) else None
        if args.resume and existing_json:
            validation = run_guarded(
                [PYTHON, VALIDATE, out_dir], BASE,
                os.path.join(logs_dir, stem + ".validate.log"),
                args.limit_mb, min(args.timeout_sec, 300),
            )
            if validation["returnCode"] == 0:
                results.append({
                    "prefab": os.path.relpath(prefab, PREFAB_ROOT).replace("\\", "/"),
                    "stem": stem,
                    "status": "ok-existing",
                    "validation": validation,
                })
                write_report(args.out, len(prefabs), results)
                continue
            print("  existing output failed validation; rebuilding", flush=True)
            safe_rmtree(out_dir, args.out)

        if os.path.isdir(out_dir):
            if args.resume:
                print("  incomplete existing output, rebuilding", flush=True)
            else:
                print("  output exists; use --resume to skip complete products", flush=True)
                results.append({
                    "prefab": os.path.relpath(prefab, PREFAB_ROOT).replace("\\", "/"),
                    "stem": stem,
                    "status": "skipped-existing",
                })
                write_report(args.out, len(prefabs), results)
                continue
        if os.path.isdir(deform_dir):
            safe_rmtree(deform_dir, args.work)
        os.makedirs(deform_dir, exist_ok=True)

        deform_cmd = [
            PYTHON, "-m", "ngui2spine.static_prefab_spine",
            prefab, deform_dir, "--assets", ASSETS,
            "--json", "--no-face-check", "--dt", str(args.deform_dt),
        ]
        if args.deform_clip:
            deform_cmd += ["--clip", args.deform_clip]
        deform = run_guarded(
            deform_cmd, UNITY_LIB,
            os.path.join(logs_dir, stem + ".deform.log"),
            args.limit_mb, args.timeout_sec,
        )
        deform_info = os.path.join(deform_dir, "_static_info.json")
        if deform["returnCode"] != 0 or not os.path.isfile(deform_info):
            results.append({
                "prefab": os.path.relpath(prefab, PREFAB_ROOT).replace("\\", "/"),
                "stem": stem,
                "status": "failed-deform",
                "deform": deform,
            })
            write_report(args.out, len(prefabs), results)
            print("  FAILED deform peak=%.1f MB %.1fs" % (
                deform["peakMB"], deform["seconds"]), flush=True)
            continue

        multi_cmd = [
            PYTHON, CONVERT, prefab, out_dir,
            "--assets", ASSETS,
            "--reuse-from", deform_dir,
            "--simplify", "0.05",
            "--deform-residual", "0.005",
        ]
        if stem == "2DModel_BR_BeastHunter_NS1.uAnim":
            multi_cmd += ["--deduped-default", "--secondary-phase", "2.0"]
        multi = run_guarded(
            multi_cmd, BASE,
            os.path.join(logs_dir, stem + ".multi.log"),
            args.limit_mb, args.timeout_sec,
        )
        json_path = find_one(out_dir, "_static.json") if os.path.isdir(out_dir) else None
        if multi["returnCode"] != 0 or not json_path:
            results.append({
                "prefab": os.path.relpath(prefab, PREFAB_ROOT).replace("\\", "/"),
                "stem": stem,
                "status": "failed-multi",
                "deform": deform,
                "multi": multi,
            })
            write_report(args.out, len(prefabs), results)
            print("  FAILED multi peak=%.1f MB %.1fs" % (
                multi["peakMB"], multi["seconds"]), flush=True)
            continue

        validation = run_guarded(
            [PYTHON, VALIDATE, out_dir], BASE,
            os.path.join(logs_dir, stem + ".validate.log"),
            args.limit_mb, min(args.timeout_sec, 300),
        )
        status = "ok" if validation["returnCode"] == 0 else "failed-validate"
        results.append({
            "prefab": os.path.relpath(prefab, PREFAB_ROOT).replace("\\", "/"),
            "stem": stem,
            "status": status,
            "deform": deform,
            "multi": multi,
            "validation": validation,
            "json": json_path,
            "jsonBytes": os.path.getsize(json_path),
            "skelBytes": (
                os.path.getsize(find_one(out_dir, "_static.skel"))
                if find_one(out_dir, "_static.skel") else None
            ),
        })
        print("  %s peak deform/multi=%.1f/%.1f MB" % (
            status.upper(), deform["peakMB"], multi["peakMB"]), flush=True)
        if status == "ok":
            safe_rmtree(os.path.join(args.work, stem), args.work)
        write_report(args.out, len(prefabs), results)

    report_path = write_report(args.out, len(prefabs), results)
    with open(report_path, encoding="utf-8") as handle:
        report = json.load(handle)
    print("ALL_PREFABS_DONE total=%d ok=%d failed=%d report=%s" % (
        report["total"], report["ok"], report["failed"], report_path))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())

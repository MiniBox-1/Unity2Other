# -*- coding: utf-8 -*-
"""Benchmark SpineData JSON vs SKEL load on final multibone products."""

import argparse
import ctypes
import gc
import json
import os
import statistics
import sys
import time

SPINE_DIR = r"D:\VB\Viewer\Render\v4\renderer_src\Spine"
if SPINE_DIR not in sys.path:
    sys.path.insert(0, SPINE_DIR)


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def available_bytes():
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return int(status.ullAvailPhys)


def process_memory():
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    process = kernel32.GetCurrentProcess()
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    if not psapi.GetProcessMemoryInfo(
            process, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)


def one_file(directory, suffix):
    for name in sorted(os.listdir(directory)):
        if name.endswith(suffix):
            return os.path.join(directory, name)
    return None


def load_once(module, skeleton, atlas, binary):
    before_rss, before_peak = process_memory()
    started = time.perf_counter()
    data = module.SpineData(skeleton, [atlas], binary, 0.0)
    state = data.getSkeleton()
    state.SetToSetupPose()
    state.UpdateWorldTransform()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    after_rss, after_peak = process_memory()
    result = {
        "ms": elapsed_ms,
        "rss_delta_mb": (after_rss - before_rss) / 1048576.0,
        "peak_delta_mb": (
            max(after_peak, before_peak) - before_peak
        ) / 1048576.0,
    }
    del state, data
    gc.collect()
    return result


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser()
    parser.add_argument("dirs", nargs="*")
    parser.add_argument("--root", default=os.path.join(root, "out", "_reg_final"))
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()

    available_gb = available_bytes() / 1073741824.0
    if available_gb < 3.0:
        raise SystemExit("Free memory below 3 GB: %.1f GB" % available_gb)

    import Spine380

    dirs = args.dirs or [
        os.path.join(args.root, name)
        for name in sorted(os.listdir(args.root))
        if os.path.isdir(os.path.join(args.root, name))
    ]
    rows = []
    for directory in dirs:
        json_path = one_file(directory, "_static.json")
        skel_path = one_file(directory, "_static.skel")
        atlas_path = one_file(directory, ".atlas")
        if not (json_path and skel_path and atlas_path):
            print("skip incomplete: %s" % directory)
            continue

        # Warm both formats once, then alternate order to reduce cache bias.
        load_once(Spine380, json_path, atlas_path, False)
        load_once(Spine380, skel_path, atlas_path, True)
        samples = {"json": [], "skel": []}
        for index in range(max(1, args.repeat)):
            order = ("json", "skel") if index % 2 == 0 else ("skel", "json")
            for kind in order:
                path = json_path if kind == "json" else skel_path
                samples[kind].append(
                    load_once(Spine380, path, atlas_path, kind == "skel"))

        json_ms = statistics.median(item["ms"] for item in samples["json"])
        skel_ms = statistics.median(item["ms"] for item in samples["skel"])
        json_rss = statistics.median(
            item["rss_delta_mb"] for item in samples["json"])
        skel_rss = statistics.median(
            item["rss_delta_mb"] for item in samples["skel"])
        row = {
            "role": os.path.basename(os.path.normpath(directory)),
            "jsonBytes": os.path.getsize(json_path),
            "skelBytes": os.path.getsize(skel_path),
            "jsonMs": json_ms,
            "skelMs": skel_ms,
            "speedup": json_ms / skel_ms if skel_ms else 0.0,
            "jsonRssDeltaMB": json_rss,
            "skelRssDeltaMB": skel_rss,
        }
        rows.append(row)
        print(
            "%-14s %7.2f ms -> %7.2f ms  %5.2fx  "
            "size %5.2f -> %5.2f MB  rss %+6.1f / %+6.1f MB"
            % (
                row["role"], json_ms, skel_ms, row["speedup"],
                row["jsonBytes"] / 1048576.0, row["skelBytes"] / 1048576.0,
                row["jsonRssDeltaMB"], row["skelRssDeltaMB"],
            ),
            flush=True,
        )

    total_json = sum(row["jsonMs"] for row in rows)
    total_skel = sum(row["skelMs"] for row in rows)
    report = {
        "repeat": args.repeat,
        "roles": len(rows),
        "totalJsonMs": total_json,
        "totalSkelMs": total_skel,
        "totalSpeedup": total_json / total_skel if total_skel else 0.0,
        "rows": rows,
    }
    print(
        "TOTAL roles=%d json=%.2f ms skel=%.2f ms speedup=%.2fx"
        % (len(rows), total_json, total_skel, report["totalSpeedup"])
    )
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        print("report=%s" % args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

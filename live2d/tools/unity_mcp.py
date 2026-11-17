# -*- coding: utf-8 -*-
r"""Minimal MCP stdio client for mcp-for-unity (calls Unity editor tools).

usage:
  python tools\unity_mcp.py tools
  python tools\unity_mcp.py call <tool> '<json-args>'
  python tools\unity_mcp.py exec_code <file.cs>
"""
import json
import os
import subprocess
import sys
import time

UVX = r"D:\Anconda\Scripts\uvx.exe"
PKG = "mcpforunityserver==10.3.0"


class Mcp:
    def __init__(self):
        env = dict(os.environ)
        env["UV_OFFLINE"] = "0"
        self.p = subprocess.Popen(
            [UVX, "--from", PKG, "mcp-for-unity"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True, encoding="utf-8", bufsize=1)
        self._id = 0

    def _send(self, obj):
        self.p.stdin.write(json.dumps(obj) + "\n")
        self.p.stdin.flush()

    def _recv(self, timeout=120):
        t0 = time.time()
        while time.time() - t0 < timeout:
            line = self.p.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except Exception:
                continue
        return None

    def request(self, method, params=None, timeout=180):
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method,
                    "params": params or {}})
        while True:
            msg = self._recv(timeout)
            if msg is None:
                return None
            if msg.get("id") == self._id:
                return msg

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def init(self):
        r = self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "dsh-unity2live2d", "version": "0.1"},
        }, timeout=120)
        self.notify("notifications/initialized")
        return r

    def close(self):
        try:
            self.p.stdin.close()
        except Exception:
            pass
        try:
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    m = Mcp()
    try:
        init = m.init()
        if init is None:
            err = m.p.stderr.read() if m.p.stderr else ""
            print("initialize failed; stderr tail:", err[-2000:])
            return
        print("server:", json.dumps(init.get("result", {}).get("serverInfo", {}),
                                    ensure_ascii=False))
        if cmd == "tools":
            r = m.request("tools/list", {})
            tools = (r or {}).get("result", {}).get("tools", [])
            for t in tools:
                print(f"- {t['name']}: {(t.get('description') or '')[:80]}")
        elif cmd == "call":
            name = sys.argv[2]
            args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
            r = m.request("tools/call", {"name": name, "arguments": args}, timeout=600)
            print(json.dumps(r, ensure_ascii=False)[:4000])
        elif cmd == "exec_code":
            code = open(sys.argv[2], encoding="utf-8").read()
            r = m.request("tools/call", {"name": "execute_code",
                                         "arguments": {"code": code}}, timeout=900)
            print(json.dumps(r, ensure_ascii=False)[:4000])
    finally:
        m.close()


if __name__ == "__main__":
    main()

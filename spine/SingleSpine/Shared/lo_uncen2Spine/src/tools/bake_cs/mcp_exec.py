# -*- coding: utf-8 -*-
r"""把一段 C# 片段文件丢给 Unity MCP 的 execute_code 执行并打印结果。

用法:
    python mcp_exec.py <snippet.cs> [--no-safety] [--raw]

为什么单独做成一个文件: PowerShell 里拼多行 C# 极易被引号规则吃掉,
把片段写成 .cs 文件再整体读进来最稳。
"""

import argparse
import io
import json
import os
import sys
import urllib.request
import uuid

URL = "http://127.0.0.1:8080/mcp"


class Mcp(object):
    def __init__(self, url=URL):
        self.url = url
        self.sid = None

    def _post(self, payload):
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.sid:
            headers["mcp-session-id"] = self.sid
        req = urllib.request.Request(self.url, data=body, headers=headers,
                                     method="POST")
        with urllib.request.urlopen(req, timeout=1800) as resp:
            self.sid = resp.headers.get("mcp-session-id") or self.sid
            raw = resp.read().decode("utf-8", "replace")
        return raw

    @staticmethod
    def _parse(raw):
        out = []
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                out.append(json.loads(line[5:].strip()))
        if out:
            return out[-1]
        return json.loads(raw) if raw.strip() else None

    def connect(self):
        self._post({
            "jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "u2s-bake", "version": "1"}},
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized",
                    "params": {}})

    def call(self, method, params):
        raw = self._post({"jsonrpc": "2.0", "id": str(uuid.uuid4()),
                          "method": method, "params": params})
        msg = self._parse(raw)
        if msg and "error" in msg:
            return {"_error": msg["error"]}
        return msg.get("result") if msg else None


def extract_text(result):
    """tools/call 结果 -> 可读文本。"""
    if not result:
        return ""
    if isinstance(result, dict) and result.get("content"):
        parts = []
        for c in result["content"]:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text") or "")
            else:
                parts.append(json.dumps(c, ensure_ascii=False))
        return "\n".join(parts)
    return json.dumps(result, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snippet")
    ap.add_argument("--no-safety", action="store_true")
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--tool", default="execute_code")
    a = ap.parse_args()

    code = io.open(a.snippet, encoding="utf-8").read()
    args = {"action": "execute", "code": code,
            "safety_checks": not a.no_safety}
    if a.tool != "execute_code":
        args = json.loads(code)

    m = Mcp()
    m.connect()
    res = m.call("tools/call", {"name": a.tool, "arguments": args})
    if a.raw:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(extract_text(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

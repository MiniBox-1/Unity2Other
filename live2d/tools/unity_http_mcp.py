# -*- coding: utf-8 -*-
r"""Tiny MCP client for the Unity-hosted HTTP MCP server (FastMCP streamable HTTP).

usage:
  python tools\unity_http_mcp.py tools
  python tools\unity_http_mcp.py call <tool> "<json-args>"
  python tools\unity_http_mcp.py exec <file.cs>
"""
import json
import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8080/mcp"


class Client:
    def __init__(self, url=URL):
        self.url = url
        self.sid = None
        self.rid = 0

    def _post(self, payload, timeout=600):
        body = json.dumps(payload).encode("utf-8")
        hdr = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
        if self.sid:
            hdr["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(self.url, data=body, headers=hdr, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
            if sid:
                self.sid = sid
            raw = r.read().decode("utf-8", "replace")
        return self._parse_sse(raw)

    @staticmethod
    def _parse_sse(raw):
        out = []
        for block in raw.split("\r\n\r\n"):
            data = None
            for line in block.split("\n"):
                line = line.strip()
                if line.startswith("data:"):
                    data = line[5:].strip()
            if data:
                try:
                    out.append(json.loads(data))
                except Exception:
                    pass
        return out

    def request(self, method, params=None, timeout=600):
        self.rid += 1
        msgs = self._post({"jsonrpc": "2.0", "id": self.rid, "method": method,
                           "params": params or {}}, timeout=timeout)
        for m in msgs:
            if m.get("id") == self.rid:
                return m
        return msgs[-1] if msgs else None

    def notify(self, method, params=None):
        try:
            self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})
        except Exception:
            pass

    def init(self):
        r = self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "dsh-u2l2d", "version": "0.1"},
        }, timeout=60)
        self.notify("notifications/initialized")
        return r


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    c = Client()
    init = c.init()
    if not init or "result" not in init:
        print("initialize failed:", json.dumps(init)[:500])
        return
    info = init["result"].get("serverInfo", {})
    print(f"server: {info.get('name')} {info.get('version')} session={c.sid}")

    if cmd == "tools":
        r = c.request("tools/list", {})
        for t in (r or {}).get("result", {}).get("tools", []):
            print(f"- {t['name']}")
    elif cmd == "call":
        name = sys.argv[2]
        args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        r = c.request("tools/call", {"name": name, "arguments": args}, timeout=1200)
        print(json.dumps(r, ensure_ascii=False)[:4000])
    elif cmd == "exec":
        code = open(sys.argv[2], encoding="utf-8-sig").read()
        r = c.request("tools/call", {"name": "execute_code",
                                     "arguments": {"action": "execute", "code": code}},
                      timeout=1800)
        print(json.dumps(r, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()

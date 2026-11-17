# -*- coding: utf-8 -*-
"""
Unity 文本 YAML（.prefab/.anim/.asset 中的 !u! 文档）专用解析器。

Unity 的序列化 YAML 不是严格 YAML（文档体没有缩进到 tag 下），因此这里
实现一个“按类文档拆分 + 缩进映射/序列”的小型解析器，只覆盖本项目资源所需子集。
"""

import re


def _split_kv(line):
    """把 'key: value' 拆开；没有冒号返回 (None,None)。"""
    if ":" not in line:
        return None, None
    k, v = line.split(":", 1)
    return k.strip(), v.strip()


def parse_flow(text):
    """解析形如 {x: 0, y: -0} 或 {fileID: 5, guid: abc, type: 3} 的 flow map。"""
    text = text.strip()
    if not text:
        return {}
    if text[0] == "{" and text[-1] == "}":
        text = text[1:-1]
    elif text[0] == "[" and text[-1] == "]":
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(x.strip()) for x in inner.split(",")]
    out = {}
    for part in text.split(","):
        k, v = _split_kv(part)
        if k is not None:
            out[k] = parse_scalar(v)
    return out


def parse_scalar(text):
    text = text.strip()
    if text == "":
        return ""
    if text.startswith("{") or text.startswith("["):
        return parse_flow(text)
    if text.startswith('"') and text.endswith('"'):
        return _unescape(text[1:-1])
    if text.startswith("'") and text.endswith("'"):
        return _unescape(text[1:-1])
    low = text.lower()
    if low in ("null", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("infinity", "+infinity"):
        return float("inf")
    if low == "-infinity":
        return float("-inf")
    if re.fullmatch(r"[-+]?\d+", text):
        return int(text)  # fileID 是 64 位整数，不能经 float
    try:
        f = float(text)
    except ValueError:
        return _unescape(text)
    return f


def _unescape(s):
    """解码 Unity YAML 的 \\uXXXX（含代理对）。"""
    if "\\u" not in s:
        return s
    out = []
    i = 0
    ms = list(re.finditer(r"\\u([0-9A-Fa-f]{4})", s))
    for k, m in enumerate(ms):
        out.append(s[i:m.start()])
        code = int(m.group(1), 16)
        if 0xD800 <= code <= 0xDBFF and k + 1 < len(ms) and ms[k + 1].start() == m.end():
            nxt = ms[k + 1]
            lo = int(nxt.group(1), 16)
            out.append(chr(((code - 0xD800) << 10) + (lo - 0xDC00) + 0x10000))
            i = nxt.end()
            continue
        out.append(chr(code))
        i = m.end()
    out.append(s[i:])
    return "".join(out)


class _Line:
    __slots__ = ("indent", "text")

    def __init__(self, indent, text):
        self.indent = indent
        self.text = text


def _make_lines(block_text):
    lines = []
    for raw in block_text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append(_Line(indent, raw.strip()))
    return lines


def _parse_map(lines, i, indent):
    out = {}
    n = len(lines)
    while i < n:
        ln = lines[i]
        if ln.indent != indent or ln.text.startswith("- "):
            break
        key, val = _split_kv(ln.text)
        if key is None:
            i += 1
            continue
        if val != "":
            out[key] = parse_scalar(val)
            i += 1
            continue
        # 空值：嵌套 map 或缩进与父键相同的 list
        j = i + 1
        if j < n and lines[j].text.startswith("- "):
            # Unity 常见写法：list 的 dash 与父键同缩进
            out[key], i = _parse_seq(lines, j, lines[j].indent)
            continue
        if j < n and lines[j].indent > indent:
            out[key], i = _parse_map(lines, j, lines[j].indent)
            continue
        out[key] = None
        i += 1
    return out, i


def _parse_seq_item(lines, i, dash_indent):
    """解析 '-' 后跟 map/标量的一个序列元素。"""
    item = {}
    rest = lines[i].text[2:].strip()
    i += 1
    if rest == "":
        return None, i  # 空元素极少出现
    if rest[0] in "[{":
        return parse_scalar(rest), i  # 纯 flow 对象/数组
    key, val = _split_kv(rest)
    if key is None:
        return parse_scalar(rest), i
    if val != "":
        item[key] = parse_scalar(val)
    eff_indent = dash_indent + 2
    n = len(lines)
    if val == "":
        # 内联 key 的嵌套块（如 '- curve:' 的下一层）
        if i < n and lines[i].indent > eff_indent:
            item[key], i = _parse_map(lines, i, lines[i].indent)
        else:
            item[key] = None
    # 序列元素映射的其余 key 位于 dash_indent+2（Unity 惯例）
    if i < n and lines[i].indent == eff_indent and not lines[i].text.startswith("- "):
        more, i = _parse_map(lines, i, eff_indent)
        item.update(more)
    return item, i


def _parse_seq(lines, i, dash_indent):
    out = []
    n = len(lines)
    while i < n:
        ln = lines[i]
        if ln.indent != dash_indent or not ln.text.startswith("- "):
            break
        item, i = _parse_seq_item(lines, i, dash_indent)
        out.append(item)
    return out, i


def parse_document(block_text):
    """解析一个 '--- !u!XX &fileid' 之后的块。返回 dict。"""
    lines = _make_lines(block_text)
    if not lines:
        return {}
    # 第一行通常是类名（如 GameObject:）；作为普通映射的第一键保留
    data, _ = _parse_map(lines, 0, lines[0].indent)
    # Unity 惯例：块内成员缩进 2 空格的写法直接由 _parse_map 处理
    return data


def split_docs(text):
    """按 '--- !u!类id &fileid' 切分。返回 [(class_id, file_id, block_text)]。"""
    pat = re.compile(r"^--- !u!(\d+) &(\d+)\s*$", re.M)
    pos = [m for m in pat.finditer(text)]
    docs = []
    for k, m in enumerate(pos):
        end = pos[k + 1].start() if k + 1 < len(pos) else len(text)
        block = text[m.end():end]
        docs.append((int(m.group(1)), int(m.group(2)), block))
    return docs


def load_unity_docs(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    return [
        (cls, fid, parse_document(block))
        for cls, fid, block in split_docs(text)
    ]


# ---------------------------------------------------------------- 快捷字段读取
def top(doc, key, default=None):
    if key not in doc:
        return default
    return doc[key]


def comp_fileid(comp_list, script_guid=None, cls=None):
    """从 GameObject.m_Component 的 list 里取出组件 fileID。"""
    out = []
    for c in comp_list or []:
        if isinstance(c, dict) and "component" in c:
            fid = c["component"].get("fileID")
            out.append((fid, c))
    return out


def get(doc, *path, default=None):
    cur = doc
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur

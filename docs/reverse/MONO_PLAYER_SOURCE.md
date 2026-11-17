# 逆向用的 mono 运行时 + 游戏托管程序集（从游戏 build 里拷来的）

来源（原样拷贝，**没有改动**）：

```
D:\Reverse\Build\MonoBleedingEdge\        → 本目录 MonoBleedingEdge\
D:\Reverse\Build\local_Data\Managed\      → 本目录 local_Data\Managed\
```

## 里面是什么

| 路径 | 内容 | 用途 |
| --- | --- | --- |
| `MonoBleedingEdge\EmbedRuntime\mono-2.0-bdwgc.dll`（7.6 MB） | Unity 用的 **Mono 运行时**（Boehm GC 版） | 反编译 UnityPlayer / 追 mono 侧行为时对着看；也是 PDB 符号匹配的基础 |
| `MonoBleedingEdge\EmbedRuntime\MonoPosixHelper.dll`（0.6 MB） | mono 的 POSIX 辅助库 | 同上 |
| `MonoBleedingEdge\etc\` | mono 配置（`mono\` 等） | 同上 |
| `local_Data\Managed\*.dll`（97 个，24 MB） | 游戏自己的**托管程序集**：`mscorlib`、`System.*`、`UnityEngine.*Module`、`Unity.TextMeshPro`、`Unity.VisualScripting.*`… | 用 dnSpy / ILSpy 反编译游戏逻辑（显隐、排序、状态机那套）时**必需** |

## 与本项目 `_reverse\` 的关系

`_reverse\` 里已有（且与 `D:\Reverse\Build\` 下同名文件**逐字节一致**，MD5 核对过）：

| 文件 | 说明 |
| --- | --- |
| `UP2022.dll.i64`（233 MB） | **IDA 数据库**，`tools\ida_q.py` 就是查它（`UP2022.dll` = 改名后的 `UnityPlayer.dll`） |
| `UP2022.dll` / `UnityPlayer.dll`（30 MB） | 被逆向的 Unity 播放器本体 |
| `UP2022.pdb` / `UnityPlayer_Win64_player_mono_x64.pdb`（20 MB 各） | **调试符号**（函数名/行号），IDA 加载后反编译可读性靠它 |
| `res_*.json` / `req_*.json` / `ida*.log` | 之前几轮 IDA 查询的请求与结果（排序比较键、`sortingKey`、显隐口径、网格生成…） |

## 缺什么（没打进包，需要时自己拷）

| 文件 | 大小 | 为什么没带 |
| --- | --- | --- |
| `D:\Reverse\Build\UnityPlayer.dll.i64` | 426 MB | 与 `_reverse\UP2022.dll.i64` 是**同一份 DLL 的两个 IDA 库**（这一份更新/更大）；项目里用的是 `UP2022.dll.i64`，要合并分析时再拷 |
| `D:\Reverse\Build\local_Data\` 的 `*.assets` / `level0` / `globalgamemanagers*` | ~5 MB | 是游戏资源包，不是 mono/pdb |
| `D:\Reverse\Build\{local.exe, UnityCrashHandler64.exe}` | 1.7 MB | 启动器，反编译不需要 |

> 用 IDA 时记得：**别在原始 `.i64` 上直接跑**（IDB 会被改写），先复制一份再让 `idat64`
> 跑 `tools\ida_q.py`；跑完 `Get-Process idat64 | Stop-Process -Force` 收进程。

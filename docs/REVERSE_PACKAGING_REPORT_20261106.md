# Unity 逆向资料打包报告

日期：2026-11-06

## 总结索引

详见：

```text
D:\VB\Convert\Spine\REVERSE_ENGINEERING_INDEX.md
```

该索引按算法整理了 Unity 逆向结论：

- `m_IsActive` / `m_Enabled` 的运行时阈值；
- `m_SortingOrder` 数值写入和逐帧重排；
- PPtr 换图的阶跃语义；
- Hermite 曲线与 ZXY 欧拉顺序；
- BlendShape 阈值空间和“先形变、后蒙皮”；
- 4 骨蒙皮与 Spine 3.8 加权顶点格式；
- Sprite alpha Tight mesh；
- RenderObjectSorter 比较键、renderQueue 分流和 SortingGroup tie-break；
- Animator Additive 参考姿态、四元数混合和短层循环；
- 已登记的不支持通道与多轴加性旋转限制。

## GitHub 主快照增加内容

```text
D:\VB\Unity2Spine_GitHub_20261105\REVERSE_ENGINEERING_INDEX.md
D:\VB\Unity2Spine_GitHub_20261105\ReverseEngineering\
```

包含：

- `Evidence/`：全部 `req_*.json`、`res_*.json` 和 `ida*.log`；
- `Tools/ida_q.py`；
- `Docs/`：完整核心与归档逆向文档；
- `SpineReference/`：Spine 3.8 参考读写代码；
- `UnityEditorScripts/`：运行时采样和渲染顺序采集脚本；
- `MONO_PLAYER_SOURCE.md`；
- `BINARY_MANIFEST.csv`：大型 DLL/PDB/IDA 文件的大小与 SHA256。

主快照当前：

```text
files=880 (不含 PACKAGE_MANIFEST 自身)
size=92.51 MB
largest_file=15.29 MB
manifest_bad=0
```

## 完整逆向附件

目录：

```text
D:\VB\Unity2Spine_ReverseEngineering_Full_20261106
```

压缩包：

```text
D:\VB\Unity2Spine_ReverseEngineering_Full_20261106.7z
D:\VB\Unity2Spine_ReverseEngineering_Full_20261106.7z.sha256
```

完整附件包含：

- `UP2022.dll` / `UnityPlayer.dll`；
- 两个 PDB；
- `UP2022.dll.i64`；
- MonoBleedingEdge；
- `local_Data\Managed` 下 97 个托管程序集；
- 全部 IDA 请求、结果、日志、查询器、参考源码和 Editor 脚本。

验证：

```text
uncompressed=361.94 MB
files=373
largest_file=228.05 MB
method=LZMA:20 BCJ2 ZSTD
7z_test=PASS
package_manifest_bad=0
```

归档大小与 SHA256 以旁边的 `.7z.sha256` 文件为准。

## 发布位置建议

GitHub 主仓使用 `Unity2Spine_GitHub_20261105.7z`。

完整逆向附件含 Unity 播放器、PDB、IDA 数据库和游戏托管程序集，建议放入
GitHub Release assets 或 Git LFS，不放入普通 Git 历史。

# GitHub 打包报告

日期：2026-11-05

## 完整性检查

- `Unity2Spine` 核心源码：Python 编译通过。
- `lo_uncen2Spine`：Python 编译通过。
- 多骨骼 Lo 转换器与工具：Python 编译通过。
- 多骨骼 BD 转换器与验证器：Python 编译通过。
- 静态 `.Lihui` 转换器与验证器：Python 编译通过。
- 全部正式产物目录验证：

```text
ORGANIZATION_OK single=157 skel=157 versions=13 BD=17/34 BDM=17/36 multi=157 curated=14 static=1148/1148 staticProto=2 configs=1550 junctions=26
```

静态示例包内验证：

```text
LIHUI_VALIDATE products=2 bones=13 slots=4 failures=0
```

## 可移植性修正

- 静态立绘转换器和验证器从自身文件位置推导仓库根目录。
- BD region-to-mesh 转换器和验证器改为相对仓库路径。
- 多骨骼 Lo 转换器和共享网格审计改为相对引用 `SingleSpine\Shared\Unity2Spine`。
- 静态转换的外部 Unity Assets/Prefabs 支持 `U2S_LO_ASSETS` 与
  `U2S_LO_PREFABS` 环境变量。

## GitHub 快照

目录：

```text
D:\VB\Unity2Spine_GitHub_20261105
```

- 880 个文件（不含 `PACKAGE_MANIFEST.sha256`）。
- 92.51 MB。
- 最大单文件 15.29 MB，低于 GitHub 100 MB 单文件限制。
- 包含源码、工具、说明、验证器、Spine 3.8 第三方绑定和 5 个小示例。
- 排除 Unity 源工程、Viewer 环境、全量产品、PoseFrames/PlayFrames、
  历史 verification 大包、逆向大型二进制和 scratch。逆向请求/结果、
  IDA 查询器与结论文档现已作为 `ReverseEngineering/` 证据集纳入主快照。

快照入口：

```text
D:\VB\Unity2Spine_GitHub_20261105\README.md
D:\VB\Unity2Spine_GitHub_20261105\PACKAGE_INFO.json
D:\VB\Unity2Spine_GitHub_20261105\PACKAGE_MANIFEST.sha256
```

## ZSTD 压缩包

```text
D:\VB\Unity2Spine_GitHub_20261105.7z
D:\VB\Unity2Spine_GitHub_20261105.7z.sha256
```

- 7-Zip 26.02 ZS。
- 压缩方法：`LZMA:20 BCJ2 ZSTD`。
- `7z t` 完整性测试通过。

最终文件大小与 SHA256 以归档及其旁边的 `.7z.sha256` 文件为准，避免包内报告
与压缩包形成自引用元数据。

## 许可

源目录没有现成 `LICENSE`。公开前必须确认代码与示例角色贴图的再分发权利；
详见快照中的 `LICENSE_STATUS.md`。

# Unity 原始动画导出器（用于与 Spine 结果对比）

## 用途

`UnityAnimationExporter.cs` **只导出原始 Unity 动画**，不读取 Spine。

把它挂到动态立绘 prefab 上，进入 Play Mode（或点组件右键菜单）后：

1. 自动找到 prefab 下每个带默认 `AnimationClip` 的 `Animation` 组件；
2. 对每个 clip 从 `t=0` 开始按 `sampleInterval`（默认 0.05s）
   调用 `AnimationClip.SampleAnimation`；
3. 每帧序列化 clip 根节点下所有 Transform 的：

```text
本地 position / rotationZ(度) / scale / active / UISprite.color(反射) / 世界位置
```

4. 每个 clip 生成一个独立 JSON：

```text
<输出目录>/<prefabName>_<clipName>.json
```

默认输出到 `Application.persistentDataPath`，可在 Inspector 改
`outputDirectory`；文件名默认稳定（不带时间戳），方便后续自动拿回对比。

## 与 Spine 结果对应关系

原始 prefab（例如 `安洁利卡`）里有多个服装子装配，每个服装一个
`Animation` 组件 + clip；脚本按 clip 根 GameObject 作为导出根：

```text
安洁利卡_艾莉希斯_Helper23_1.json   ← Unity 真值
对应 D:\VB\Search\Example\samples\安洁利卡\艾莉希斯\安洁利卡_00_艾莉希斯.json
```

JSON 里每个节点的 `path` 相对 clip 根，例如：

```json
"path": "Sprite - body1/Sprite - arm1_1"
```

Spine 侧对应骨骼名就是 `Sprite - body1`、`Sprite - arm1_1` 等。

## 2DModel（Sprite+Mesh）调试导出

`TwoDModelDebugExporter.cs` 用于 NormalLocal 的 Sprite+Mesh prefab：

1. 复制到工程的 `Assets/Editor` 之外的任意脚本目录（普通 MonoBehaviour，
   建议放 `Assets/Scripts`）；
2. 挂到 prefab 根节点（或挂有 Animator 的 `ch_root`）；
3. Inspector 填 `animState`（如 lobby）与 `normalizedTime`；
4. 进入 Play Mode，等待若干帧后自动导出 JSON 到：
   `D:\VB\Unity2Spine\info\RigDebug\<prefab名>_<时间>.json`（2026-09-18 起统一到 `info`）。

导出内容包括：

- 全部 Transform：本地/世界 position、rotation、scale、worldMatrix；
- 每个 SkinnedMeshRenderer：`bones` 顺序、`bindposes`、boneWeights（Mesh 可读时）、
  `BakeMesh` 得到的当前姿态顶点/uv/三角形、localToWorld；
- 每个 MeshFilter+MeshRenderer 与 SpriteRenderer：网格/精灵矩形、贴图尺寸、
  变换矩阵。

这些 JSON 可与 `Unity2Spine` 的 2DModel 转换中间数据逐点比对，用来校验收敛后
的绑定顺序/坐标。

## 输出 JSON 结构

```json
{
  "format": "unity-legacy-animation-v1",
  "prefabName": "安洁利卡",
  "clipName": "Helper23_1",
  "clipRootPath": "艾莉希斯",
  "duration": 3.5,
  "sampleInterval": 0.05,
  "frames": [
    {
      "time": 0,
      "nodes": [
        {
          "path": "Sprite - body1",
          "name": "Sprite - body1",
          "localX": -59, "localY": -142, "localZ": 0,
          "rotationZ": 0,
          "scaleX": 1, "scaleY": 1, "scaleZ": 1,
          "active": true,
          "hasColor": false,
          "worldX": 0, "worldY": 0
        }
      ]
    }
  ]
}
```

## 推荐设置

```text
sampleInterval = 0.05     （与 Spine 转换侧采样一致）
includeEndFrame = true
includeTimestamp = false  （文件名稳定，方便脚本直接读取）
restoreAfterExport = true （导出完恢复 Transform，不污染场景）
```

## 注意

- 需要进入 Play Mode 才能触发 `Start`（脚本没有 Editor API）。
  也可不进入播放，点组件右键菜单 `导出全部 Unity 动画`，
  但 Unity 在非播放状态对 `AnimationClip.SampleAnimation` 的调用
  仍可能产生场景脏数据；脚本会在每个 clip 导出后恢复原姿态。
- 若原始 prefab 的动画由代码每帧驱动（不写入 AnimationClip），
  本脚本不覆盖；它只采样 clip 本身的内容。
- 拿回本地后，用 `D:\VB\Search\analysis\ngui2spine` 里的参考实现/
  采样脚本读取该 JSON 与 Spine JSON，即可逐帧求位置/旋转误差。

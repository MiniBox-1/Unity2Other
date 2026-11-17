// ExportRoots.cs —— **所有动态导出**的统一根目录（2026-09-18 起）。
//
// 为什么统一：以前东一块西一块 —— 参考帧/渲染顺序/ModelInspect 写在**工程根**
// （`<工程根>\_refshot_*`、`_draworder_*`、`_inspect_*`），PoseFrames/PlayFrames/
// Frames/SceneT0/SceneLayout/StaticMeta 写在 **Assets\Data\** 下。找起来麻烦，
// 而且写在 Assets 里会触发 Unity 导入、写在工程根又和 Library 混在一起。
//
// 现在**全部**写到 `D:\VB\Unity2Spine\info`：
//   info\_refshot_<角色>\...        （PlayRefShot：带相机的参考帧 + *_cam.txt）
//   info\_draworder_<角色>\...      （ExportDrawOrder：渲染顺序 + 同帧渲染图）
//   info\_inspect_<角色>\...        （ModelInspect 批处理产物）
//   info\Data\PoseFrames\<角色>.json              逐帧骨骼 + 顶点真值
//   info\Data\PlayFrames\<角色>@<Animator>@<状态>.json  Play 真值（显隐等）
//   info\Data\Frames\ / SceneT0\ / SceneLayout\ / StaticMeta\ / SelectedInfo\
//   info\RigDebug\                 （TwoDModelDebugExporter 兜底目录）
//   info\_logs\play_sample.log / inspect.log / play_probe.log  统一日志
//
// 想换地方只改下面这一个常量（或者给脚本传各自的 `-probeOut` / 配置项）。
// 注意：**info 在仓库里、不在 Unity 工程里**，所以导出不会触发 Asset 导入。
//
// 这个文件放在 Assets\Script\（**不是** Assets\Editor\），是为了让**运行时**脚本
// （AedaProbeRuntime / TwoDModelDebugExporter / PlayModeProbe）也能直接引用。
using System.IO;

public static class ExportRoots
{
    /// <summary>所有动态导出的根目录。</summary>
    public const string Root = @"D:\VB\Unity2Spine\info";

    /// <summary>`Root` 下的子路径（会自动建目录）。</summary>
    public static string Of(params string[] parts)
    {
        string p = Root;
        if (parts != null)
            foreach (string s in parts)
                if (!string.IsNullOrEmpty(s))
                    p = Path.Combine(p, s);
        Directory.CreateDirectory(p);
        return p;
    }

    /// <summary>`Root\Data\<name>`（PoseFrames / PlayFrames / Frames / SceneT0 …）。</summary>
    public static string Data(string name)
    {
        return Of("Data", name);
    }

    /// <summary>`Root\_logs`（统一日志目录；play_sample.log / inspect.log / play_probe.log）。</summary>
    public static string Logs()
    {
        return Of("_logs");
    }

    /// <summary>`Root\_<prefix>_<name>`（_refshot_/_draworder_/_inspect_ 这类按角色分目录的产物）。</summary>
    public static string Named(string prefix, string name)
    {
        return Of("_" + prefix + "_" + name);
    }
}

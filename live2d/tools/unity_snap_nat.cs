string[] names = new string[] { "2DModel_3P_Alexandra_N" };
string dir = @"D:\VB\Convert\Live2d\Products\_unity_ref_nat\";
System.IO.Directory.CreateDirectory(dir);
int ok = 0;
var report = new System.Text.StringBuilder();
foreach (var name in names) {
    var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
    if (prefab == null) { report.Append(name + ":ERR-PREFAB;"); continue; }
    var go = UnityEngine.Object.Instantiate(prefab);
    go.SetActive(true);
    var rs = go.GetComponentsInChildren<UnityEngine.Renderer>(true);
    if (rs.Length == 0) { UnityEngine.Object.DestroyImmediate(go); report.Append(name + ":ERR-NOREN;"); continue; }
    // 取景只用「可见」渲染器：inactive/禁用的巨型 bounds 会把角色缩成几十像素
    var rsVis = new System.Collections.Generic.List<UnityEngine.Renderer>();
    foreach (var r1 in rs) { if (r1.enabled && r1.gameObject.activeInHierarchy) rsVis.Add(r1); }
    var bb = (rsVis.Count > 0 ? rsVis[0] : rs[0]).bounds;
    foreach (var r1 in (rsVis.Count > 0 ? rsVis : new System.Collections.Generic.List<UnityEngine.Renderer>(rs))) bb.Encapsulate(r1.bounds);
    // 只渲染本角色：把实例挪到独立 layer，相机只拍这个 layer，
    // 否则当前打开的场景里其它物体会一起进画面（DL 展示变体曾被场景内容污染）。
    foreach (var t0 in go.GetComponentsInChildren<UnityEngine.Transform>(true)) t0.gameObject.layer = 31;
    var camGo = new UnityEngine.GameObject("U2L2D_SnapCam");
    var cam = camGo.AddComponent<UnityEngine.Camera>();
    cam.cullingMask = 1 << 31;
    cam.orthographic = true;
    cam.clearFlags = UnityEngine.CameraClearFlags.SolidColor;
    cam.backgroundColor = new UnityEngine.Color(0f, 0f, 0f, 0f);
    cam.orthographicSize = UnityEngine.Mathf.Max(bb.extents.y, 1e-3f) * 1.05f;
    cam.aspect = UnityEngine.Mathf.Max(0.2f, bb.extents.x / UnityEngine.Mathf.Max(1e-3f, bb.extents.y));
    cam.transform.position = new UnityEngine.Vector3(bb.center.x, bb.center.y, bb.center.z - 10f);
    cam.nearClipPlane = 0.01f; cam.farClipPlane = 100f;
    int H = 768;
    int W = UnityEngine.Mathf.Max(64, UnityEngine.Mathf.RoundToInt(H * cam.aspect));
    var rt = new UnityEngine.RenderTexture(W, H, 24, UnityEngine.RenderTextureFormat.ARGB32);
    cam.targetTexture = rt; cam.Render();
    UnityEngine.RenderTexture.active = rt;
    var tex = new UnityEngine.Texture2D(W, H, UnityEngine.TextureFormat.RGBA32, false);
    tex.ReadPixels(new UnityEngine.Rect(0, 0, W, H), 0, 0); tex.Apply();
    UnityEngine.RenderTexture.active = null;
    System.IO.File.WriteAllBytes(dir + name + ".png", tex.EncodeToPNG());
    UnityEngine.Object.DestroyImmediate(camGo);
    UnityEngine.Object.DestroyImmediate(go);
    ok++;
    report.Append(name + ":OK;");
}
return "done=" + ok + " " + report.ToString();

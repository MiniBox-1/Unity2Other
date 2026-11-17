string[] allNames = new string[] { "2DModel_AGS_RheinRitter_NS1" };
string dir = @"D:\VB\Convert\Live2d\Products\_unity_rt\";
System.IO.Directory.CreateDirectory(dir);
int ok = 0;
foreach (var name in allNames) {
    var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
    if (prefab == null) continue;
    var go = UnityEngine.Object.Instantiate(prefab);
    go.SetActive(true);

    // 逐部件真实蒙皮包围盒（同一时刻）
    var parts = new System.Collections.Generic.List<string>();
    var mins = new System.Collections.Generic.List<UnityEngine.Vector3>();
    var maxs = new System.Collections.Generic.List<UnityEngine.Vector3>();
    foreach (var r in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) {
        if (!r.enabled || !r.gameObject.activeInHierarchy) continue;
        var smr = r as UnityEngine.SkinnedMeshRenderer;
        var sr = r as UnityEngine.SpriteRenderer;
        var pts = new System.Collections.Generic.List<UnityEngine.Vector3>();
        if (smr != null && smr.sharedMesh != null) {
            var mesh = smr.sharedMesh;
            var verts = mesh.vertices;
            var bps = mesh.bindposes;
            var bones = smr.bones;
            var bw = mesh.boneWeights;
            bool hasW = bw != null && bw.Length == verts.Length;
            for (int vi = 0; vi < verts.Length; vi++) {
                if (!hasW) { pts.Add(smr.transform.localToWorldMatrix.MultiplyPoint3x4(verts[vi])); continue; }
                var w = bw[vi]; var acc = UnityEngine.Vector3.zero; float sum = 0f;
                for (int k = 0; k < 4; k++) {
                    float wt = k == 0 ? w.weight0 : (k == 1 ? w.weight1 : (k == 2 ? w.weight2 : w.weight3));
                    int bi = k == 0 ? w.boneIndex0 : (k == 1 ? w.boneIndex1 : (k == 2 ? w.boneIndex2 : w.boneIndex3));
                    if (wt <= 0f || bi < 0 || bi >= bones.Length || bi >= bps.Length) continue;
                    acc += (bones[bi].localToWorldMatrix * bps[bi]).MultiplyPoint3x4(verts[vi]) * wt;
                    sum += wt;
                }
                if (sum > 0f) pts.Add(acc / sum);
            }
        } else if (sr != null && sr.sprite != null) {
            var mtx = sr.transform.localToWorldMatrix;
            foreach (var v in sr.sprite.vertices) pts.Add(mtx.MultiplyPoint3x4(new UnityEngine.Vector3(v.x, v.y, 0f)));
        } else continue;
        if (pts.Count == 0) continue;
        var mn = pts[0]; var mx = pts[0];
        foreach (var q in pts) { mn = UnityEngine.Vector3.Min(mn, q); mx = UnityEngine.Vector3.Max(mx, q); }
        parts.Add(r.transform.name.Replace("\\", "/").Replace("\"", "'"));
        mins.Add(mn); maxs.Add(mx);
    }

    // 相机取景：用所有渲染器的 bounds（与截图脚本一致）
    var rs = go.GetComponentsInChildren<UnityEngine.Renderer>(true);
    var bb = rs[0].bounds;
    foreach (var r1 in rs) bb.Encapsulate(r1.bounds);
    var camGo = new UnityEngine.GameObject("U2L2D_SnapCam");
    var cam = camGo.AddComponent<UnityEngine.Camera>();
    cam.orthographic = true;
    cam.clearFlags = UnityEngine.CameraClearFlags.SolidColor;
    cam.backgroundColor = new UnityEngine.Color(0f, 0f, 0f, 0f);
    cam.orthographicSize = UnityEngine.Mathf.Max(bb.extents.y, 1e-3f) * 1.05f;
    cam.aspect = UnityEngine.Mathf.Max(0.2f, bb.extents.x / UnityEngine.Mathf.Max(1e-3f, bb.extents.y));
    cam.transform.position = new UnityEngine.Vector3(bb.center.x, bb.center.y, bb.center.z - 10f);
    cam.nearClipPlane = 0.01f; cam.farClipPlane = 100f;
    int H = 768;
    int W = UnityEngine.Mathf.Max(64, UnityEngine.Mathf.RoundToInt(H * cam.aspect));
    float halfH = cam.orthographicSize;
    float halfW = halfH * cam.aspect;
    float xMin = bb.center.x - halfW, xMax = bb.center.x + halfW;
    float yMin = bb.center.y - halfH, yMax = bb.center.y + halfH;

    var rt = new UnityEngine.RenderTexture(W, H, 24, UnityEngine.RenderTextureFormat.ARGB32);
    cam.targetTexture = rt; cam.Render();
    UnityEngine.RenderTexture.active = rt;
    var tex = new UnityEngine.Texture2D(W, H, UnityEngine.TextureFormat.RGBA32, false);
    tex.ReadPixels(new UnityEngine.Rect(0, 0, W, H), 0, 0); tex.Apply();
    UnityEngine.RenderTexture.active = null;
    System.IO.File.WriteAllBytes(dir + name + ".png", tex.EncodeToPNG());

    var sb = new System.Text.StringBuilder();
    sb.Append("{\"w\":").Append(W).Append(",\"h\":").Append(H)
      .Append(",\"xmin\":").Append(xMin.ToString("F4")).Append(",\"xmax\":").Append(xMax.ToString("F4"))
      .Append(",\"ymin\":").Append(yMin.ToString("F4")).Append(",\"ymax\":").Append(yMax.ToString("F4"))
      .Append(",\"parts\":[");
    for (int i = 0; i < parts.Count; i++) {
        if (i > 0) sb.Append(",");
        sb.Append("{\"n\":\"").Append(parts[i]).Append("\",\"min\":[")
          .Append(mins[i].x.ToString("F4")).Append(",").Append(mins[i].y.ToString("F4"))
          .Append("],\"max\":[").Append(maxs[i].x.ToString("F4")).Append(",").Append(maxs[i].y.ToString("F4")).Append("]}");
    }
    sb.Append("]}");
    System.IO.File.WriteAllText(dir + name + ".json", sb.ToString());

    UnityEngine.Object.DestroyImmediate(camGo);
    UnityEngine.Object.DestroyImmediate(go);
    ok++;
}
return "render+dump=" + ok;

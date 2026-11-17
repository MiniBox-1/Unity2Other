string[] allNames = new string[] { "2DModel_BR_Khan_N" };
string dir = @"D:\VB\Convert\Live2d\Products\_unity_ref\";
int ok = 0;
foreach (var name in allNames) {
    var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
    if (prefab == null) continue;
    var go = UnityEngine.Object.Instantiate(prefab);
    go.SetActive(true);
    foreach (var an in go.GetComponentsInChildren<UnityEngine.Animator>(true)) an.enabled = false;
    var sb = new System.Text.StringBuilder();
    sb.Append("{\"parts\":[");
    bool first = true;
    foreach (var r in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) {
        if (!r.enabled || !r.gameObject.activeInHierarchy) continue;
        var pts = new System.Collections.Generic.List<UnityEngine.Vector3>();
        var smr = r as UnityEngine.SkinnedMeshRenderer;
        var sr = r as UnityEngine.SpriteRenderer;
        if (smr != null) {
            var mesh = smr.sharedMesh;
            var verts = mesh.vertices;
            var bps = mesh.bindposes;
            var bones = smr.bones;
            var bw = mesh.boneWeights;
            for (int vi = 0; vi < verts.Length; vi++) {
                var w = bw[vi];
                UnityEngine.Vector3 acc = UnityEngine.Vector3.zero;
                float sum = 0f;
                for (int k = 0; k < 4; k++) {
                    float wt = k == 0 ? w.weight0 : (k == 1 ? w.weight1 : (k == 2 ? w.weight2 : w.weight3));
                    int bi = k == 0 ? w.boneIndex0 : (k == 1 ? w.boneIndex1 : (k == 2 ? w.boneIndex2 : w.boneIndex3));
                    if (wt <= 0f || bi < 0 || bi >= bones.Length) continue;
                    var m = bones[bi].localToWorldMatrix * bps[bi];
                    acc += m.MultiplyPoint3x4(verts[vi]) * wt;
                    sum += wt;
                }
                if (sum > 0f) pts.Add(acc / sum);
            }
        } else if (sr != null) {
            if (sr.sprite == null) continue;
            var mtx = sr.transform.localToWorldMatrix;
            foreach (var v in sr.sprite.vertices) pts.Add(mtx.MultiplyPoint3x4(new UnityEngine.Vector3(v.x, v.y, 0f)));
        } else {
            var mf = r.GetComponent<UnityEngine.MeshFilter>();
            if (mf == null || mf.sharedMesh == null) continue;
            var mtx = r.transform.localToWorldMatrix;
            foreach (var v in mf.sharedMesh.vertices) pts.Add(mtx.MultiplyPoint3x4(v));
        }
        if (pts.Count == 0) continue;
        var mn = pts[0]; var mx = pts[0];
        foreach (var q in pts) { mn = UnityEngine.Vector3.Min(mn, q); mx = UnityEngine.Vector3.Max(mx, q); }
        if (!first) sb.Append(",");
        first = false;
        string pn = r.transform.name.Replace("\\", "/").Replace("\"", "'");
        sb.Append("{\"name\":\"").Append(pn).Append("\",\"c\":[")
          .Append(((mn.x + mx.x) / 2f).ToString("F4")).Append(",").Append(((mn.y + mx.y) / 2f).ToString("F4"))
          .Append("],\"s\":[").Append((mx.x - mn.x).ToString("F4")).Append(",").Append((mx.y - mn.y).ToString("F4")).Append("]}");
    }
    sb.Append("]}");
    System.IO.File.WriteAllText(dir + name + ".skinbounds.json", sb.ToString());
    UnityEngine.Object.DestroyImmediate(go);
    ok++;
}
return "skin bounds=" + ok;

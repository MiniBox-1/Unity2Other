string[] allNames = new string[] { "2DModel_3P_Alexandra_N" };
string dir = @"D:\VB\Convert\Live2d\Products\_unity_ref\";
System.IO.Directory.CreateDirectory(dir);
int okCount = 0;
foreach (var name in allNames) {
    var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
    if (prefab == null) continue;
    var go = UnityEngine.Object.Instantiate(prefab);
    go.SetActive(true);
    var rs = go.GetComponentsInChildren<UnityEngine.Renderer>(true);

    var bs = new System.Text.StringBuilder();
    bs.Append("{\"parts\":[");
    bool firstB = true;
    foreach (var r in rs) {
        if (!r.enabled || !r.gameObject.activeInHierarchy) continue;
        var smrB = r as UnityEngine.SkinnedMeshRenderer;
        var srB = r as UnityEngine.SpriteRenderer;
        var ptsB = new System.Collections.Generic.List<UnityEngine.Vector3>();
        if (smrB != null) {
            var mesh = smrB.sharedMesh; var verts = mesh.vertices; var bps = mesh.bindposes;
            var bones = smrB.bones; var bw = mesh.boneWeights;
            bool hasW = bw != null && bw.Length == verts.Length;
            for (int vi = 0; vi < verts.Length; vi++) {
                if (!hasW) { ptsB.Add(smrB.transform.localToWorldMatrix.MultiplyPoint3x4(verts[vi])); continue; }
                var w = bw[vi]; var acc = UnityEngine.Vector3.zero; float sum = 0f;
                for (int k = 0; k < 4; k++) {
                    float wt = k == 0 ? w.weight0 : (k == 1 ? w.weight1 : (k == 2 ? w.weight2 : w.weight3));
                    int bi = k == 0 ? w.boneIndex0 : (k == 1 ? w.boneIndex1 : (k == 2 ? w.boneIndex2 : w.boneIndex3));
                    if (wt <= 0f || bi < 0 || bi >= bones.Length || bi >= bps.Length) continue;
                    acc += (bones[bi].localToWorldMatrix * bps[bi]).MultiplyPoint3x4(verts[vi]) * wt;
                    sum += wt;
                }
                if (sum > 0f) ptsB.Add(acc / sum);
            }
        } else if (srB != null) {
            if (srB.sprite == null) continue;
            var mtx = srB.transform.localToWorldMatrix;
            foreach (var v in srB.sprite.vertices) ptsB.Add(mtx.MultiplyPoint3x4(new UnityEngine.Vector3(v.x, v.y, 0f)));
        } else {
            var mf = r.GetComponent<UnityEngine.MeshFilter>();
            if (mf == null || mf.sharedMesh == null) continue;
            var mtx = r.transform.localToWorldMatrix;
            foreach (var v in mf.sharedMesh.vertices) ptsB.Add(mtx.MultiplyPoint3x4(v));
        }
        if (ptsB.Count == 0) continue;
        var mnB = ptsB[0]; var mxB = ptsB[0];
        foreach (var q in ptsB) { mnB = UnityEngine.Vector3.Min(mnB, q); mxB = UnityEngine.Vector3.Max(mxB, q); }
        if (!firstB) bs.Append(",");
        firstB = false;
        string pn = r.transform.name.Replace("\\", "/").Replace("\"", "'");
        bs.Append("{\"name\":\"").Append(pn).Append("\",\"c\":[")
          .Append(((mnB.x + mxB.x) / 2f).ToString("F4")).Append(",").Append(((mnB.y + mxB.y) / 2f).ToString("F4"))
          .Append("],\"s\":[").Append((mxB.x - mnB.x).ToString("F4")).Append(",").Append((mxB.y - mnB.y).ToString("F4")).Append("]}");
    }
    bs.Append("]}");
    System.IO.File.WriteAllText(dir + name + ".skinbounds.json", bs.ToString());

    var sb = new System.Text.StringBuilder();
    sb.Append("{\"parts\":[");
    bool f2 = true;
    foreach (var r in rs) {
        if (!r.enabled || !r.gameObject.activeInHierarchy) continue;
        string pname = r.transform.name.Replace("\\", "/").Replace("\"", "'");
        var vs = new System.Collections.Generic.List<UnityEngine.Vector3>();
        var uvs = new System.Collections.Generic.List<UnityEngine.Vector2>();
        var tris = new System.Collections.Generic.List<int>();
        var smr = r as UnityEngine.SkinnedMeshRenderer;
        var sr = r as UnityEngine.SpriteRenderer;
        if (smr != null) {
            var mesh = smr.sharedMesh; var verts = mesh.vertices; var bps = mesh.bindposes;
            var bones = smr.bones; var bw = mesh.boneWeights;
            bool hasW = bw != null && bw.Length == verts.Length;
            for (int vi = 0; vi < verts.Length; vi++) {
                if (!hasW) { vs.Add(smr.transform.localToWorldMatrix.MultiplyPoint3x4(verts[vi])); continue; }
                var w = bw[vi]; var acc = UnityEngine.Vector3.zero; float sum = 0f;
                for (int k = 0; k < 4; k++) {
                    float wt = k == 0 ? w.weight0 : (k == 1 ? w.weight1 : (k == 2 ? w.weight2 : w.weight3));
                    int bi = k == 0 ? w.boneIndex0 : (k == 1 ? w.boneIndex1 : (k == 2 ? w.boneIndex2 : w.boneIndex3));
                    if (wt <= 0f || bi < 0 || bi >= bones.Length || bi >= bps.Length) continue;
                    acc += (bones[bi].localToWorldMatrix * bps[bi]).MultiplyPoint3x4(verts[vi]) * wt;
                    sum += wt;
                }
                vs.Add(sum > 0f ? acc / sum : smr.transform.localToWorldMatrix.MultiplyPoint3x4(verts[vi]));
            }
            uvs.AddRange(mesh.uv);
            tris.AddRange(mesh.triangles);
        } else if (sr != null) {
            if (sr.sprite == null) continue;
            var mtx = sr.transform.localToWorldMatrix;
            foreach (var v in sr.sprite.vertices) vs.Add(mtx.MultiplyPoint3x4(new UnityEngine.Vector3(v.x, v.y, 0f)));
            uvs.AddRange(sr.sprite.uv);
            foreach (var i in sr.sprite.triangles) tris.Add(i);
        } else {
            var mf = r.GetComponent<UnityEngine.MeshFilter>();
            if (mf == null || mf.sharedMesh == null) continue;
            var mtx = r.transform.localToWorldMatrix;
            foreach (var v in mf.sharedMesh.vertices) vs.Add(mtx.MultiplyPoint3x4(v));
            uvs.AddRange(mf.sharedMesh.uv);
            tris.AddRange(mf.sharedMesh.triangles);
        }
        if (vs.Count == 0 || tris.Count == 0) continue;
        if (!f2) sb.Append(",");
        f2 = false;
        sb.Append("{\"name\":\"").Append(pname).Append("\",\"sort\":").Append(r.sortingOrder).Append(",\"verts\":[");
        for (int i = 0; i < vs.Count; i++) { if (i > 0) sb.Append(","); sb.Append(vs[i].x.ToString("F4")).Append(",").Append(vs[i].y.ToString("F4")); }
        sb.Append("],\"uvs\":[");
        for (int i = 0; i < uvs.Count; i++) { if (i > 0) sb.Append(","); sb.Append(uvs[i].x.ToString("F5")).Append(",").Append(uvs[i].y.ToString("F5")); }
        sb.Append("],\"tris\":[");
        for (int i = 0; i < tris.Count; i++) { if (i > 0) sb.Append(","); sb.Append(tris[i]); }
        sb.Append("]}");
    }
    sb.Append("]}");
    System.IO.File.WriteAllText(dir + name + ".bake.json", sb.ToString());

    UnityEngine.Object.DestroyImmediate(go);
    okCount++;
}
return "dumped=" + okCount;

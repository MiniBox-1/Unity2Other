string name = "2DModel_BR_Khan_N";
var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
var go = UnityEngine.Object.Instantiate(prefab);
go.SetActive(true);
var sb = new System.Text.StringBuilder();
foreach (var r in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) {
    if (!r.enabled) continue;
    string n = r.transform.name;
    if (n != "kh_parts_body" && n != "kh_parts_buster" && n != "kh_parts_hair_3") continue;
    sb.Append(n).Append(" kind=").Append(r.GetType().Name);
    sb.Append(" lossyScale=").Append(r.transform.lossyScale.ToString("F4"));
    var b = r.bounds;
    sb.Append(" boundsC=").Append(b.center.ToString("F3")).Append(" boundsS=").Append(b.size.ToString("F3"));
    if (r is UnityEngine.SkinnedMeshRenderer) {
        var smr = (UnityEngine.SkinnedMeshRenderer)r;
        var m = new UnityEngine.Mesh();
        smr.BakeMesh(m);
        var vs = m.vertices;
        var mn = new UnityEngine.Vector3(1e9f, 1e9f, 0); var mx = new UnityEngine.Vector3(-1e9f, -1e9f, 0);
        foreach (var v in vs) { mn = UnityEngine.Vector3.Min(mn, v); mx = UnityEngine.Vector3.Max(mx, v); }
        sb.Append(" bakeLocalMin=").Append(mn.ToString("F3")).Append(" bakeLocalMax=").Append(mx.ToString("F3"));
        var wm = smr.localToWorldMatrix;
        var wv = wm.MultiplyPoint3x4(mn);
        sb.Append(" worldMin=").Append(wv.ToString("F3"));
    }
    sb.Append("\n");
}
UnityEngine.Object.DestroyImmediate(go);
return sb.ToString();

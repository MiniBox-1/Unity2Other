string name = "2DModel_BR_Khan_N";
var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
var go = UnityEngine.Object.Instantiate(prefab);
go.SetActive(true);
var sb = new System.Text.StringBuilder();
foreach (var r in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) {
    if (!r.enabled) continue;
    var smr = r as UnityEngine.SkinnedMeshRenderer;
    if (smr == null) continue;
    if (r.transform.name != "kh_parts_body") continue;
    var m = new UnityEngine.Mesh();
    smr.BakeMesh(m);
    var vs = m.vertices;
    var b = r.bounds;
    sb.Append("bounds c=").Append(b.center.ToString("F3")).Append(" s=").Append(b.size.ToString("F3")).Append("\n");
    sb.Append("rootBone=").Append(smr.rootBone != null ? smr.rootBone.name : "null");
    if (smr.rootBone != null) sb.Append(" rootLossy=").Append(smr.rootBone.lossyScale.ToString("F4"));
    sb.Append("\n");
    sb.Append("localToWorld lossy=").Append(r.transform.lossyScale.ToString("F4")).Append("\n");
    var wm1 = r.transform.localToWorldMatrix;
    var wm2 = smr.rootBone != null ? smr.rootBone.localToWorldMatrix : wm1;
    UnityEngine.Vector3 mn1 = new UnityEngine.Vector3(1e9f, 1e9f, 1e9f), mx1 = new UnityEngine.Vector3(-1e9f, -1e9f, -1e9f);
    UnityEngine.Vector3 mn2 = mn1, mx2 = mx1;
    foreach (var v in vs) {
        var a1 = wm1.MultiplyPoint3x4(v);
        mn1 = UnityEngine.Vector3.Min(mn1, a1); mx1 = UnityEngine.Vector3.Max(mx1, a1);
        var a2 = wm2.MultiplyPoint3x4(v);
        mn2 = UnityEngine.Vector3.Min(mn2, a2); mx2 = UnityEngine.Vector3.Max(mx2, a2);
    }
    sb.Append("renderer-mtx world min=").Append(mn1.ToString("F3")).Append(" max=").Append(mx1.ToString("F3")).Append("\n");
    sb.Append("rootbone-mtx world min=").Append(mn2.ToString("F3")).Append(" max=").Append(mx2.ToString("F3")).Append("\n");
    sb.Append("bounds min=").Append((b.center - b.size * 0.5f).ToString("F3")).Append(" max=").Append((b.center + b.size * 0.5f).ToString("F3"));
}
UnityEngine.Object.DestroyImmediate(go);
return sb.ToString();

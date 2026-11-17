string name = "2DModel_BR_Khan_N";
string part = "kh_parts_body";
var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
var go = UnityEngine.Object.Instantiate(prefab);
go.SetActive(true);
var sb = new System.Text.StringBuilder();
foreach (var r in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) {
    if (!r.enabled) continue;
    var smr = r as UnityEngine.SkinnedMeshRenderer;
    if (smr == null || r.transform.name != part) continue;
    var mesh = smr.sharedMesh;
    var verts = mesh.vertices;
    var bps = mesh.bindposes;
    var bones = smr.bones;
    var mn = new UnityEngine.Vector3(1e9f, 1e9f, 1e9f);
    var mx = new UnityEngine.Vector3(-1e9f, -1e9f, -1e9f);
    for (int vi = 0; vi < verts.Length; vi++) {
        var bp = bones[vi % bones.Length].localToWorldMatrix * bps[vi % bps.Length];
        var w = bp.MultiplyPoint3x4(verts[vi]);
        mn = UnityEngine.Vector3.Min(mn, w);
        mx = UnityEngine.Vector3.Max(mx, w);
    }
    sb.Append("naive-skin x=(").Append(mn.x.ToString("F3")).Append(",").Append(mx.x.ToString("F3"))
      .Append(") y=(").Append(mn.y.ToString("F3")).Append(",").Append(mx.y.ToString("F3")).Append(")");
    sb.Append(" | mesh verts=").Append(verts.Length).Append(" bones=").Append(bones.Length);
    var b = smr.bounds;
    sb.Append(" | renderer.bounds c=").Append(b.center.ToString("F3")).Append(" s=").Append(b.size.ToString("F3"));
    var lb = smr.localBounds;
    sb.Append(" | localBounds c=").Append(lb.center.ToString("F3")).Append(" s=").Append(lb.size.ToString("F3"));
    sb.Append(" | pos0=").Append(verts[0].ToString("F3"));
    sb.Append(" | bone0=").Append(bones[0].name).Append(" worldPos=").Append(bones[0].position.ToString("F3"));
}
UnityEngine.Object.DestroyImmediate(go);
return sb.ToString();

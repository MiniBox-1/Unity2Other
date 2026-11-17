string name = "2DModel_BR_Khan_N";
string outPath = @"D:\VB\Convert\Live2d\Products\_unity_ref\" + name + ".bake.json";
var prefab = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.GameObject>("Assets/Prefabs/" + name + ".uAnim.prefab");
if (prefab == null) return "ERR prefab";
var go = UnityEngine.Object.Instantiate(prefab);
go.SetActive(true);
foreach (var t in go.GetComponentsInChildren<UnityEngine.Transform>(true)) t.gameObject.SetActive(true);
foreach (var r0 in go.GetComponentsInChildren<UnityEngine.Renderer>(true)) r0.enabled = true;

var sb = new System.Text.StringBuilder();
sb.Append("{\"name\":\"" + name + "\",\"parts\":[");
bool first = true;
int n = 0;
var rs = go.GetComponentsInChildren<UnityEngine.Renderer>(true);
foreach (var r in rs) {
    string pname = r.transform.name.Replace("\\", "/").Replace("\"", "'");
    var vs = new System.Collections.Generic.List<UnityEngine.Vector3>();
    var uvs = new System.Collections.Generic.List<UnityEngine.Vector2>();
    var tris = new System.Collections.Generic.List<int>();
    string tex = "";
    string kind = r.GetType().Name;
    var mtx = r.transform.localToWorldMatrix;
    if (r is UnityEngine.SpriteRenderer) {
        var sr = (UnityEngine.SpriteRenderer)r;
        if (sr.sprite == null) continue;
        tex = sr.sprite.texture != null ? sr.sprite.texture.name : "";
        foreach (var v in sr.sprite.vertices) vs.Add(mtx.MultiplyPoint3x4(new UnityEngine.Vector3(v.x, v.y, 0f)));
        uvs.AddRange(sr.sprite.uv);
        foreach (var i in sr.sprite.triangles) tris.Add(i);
    } else if (r is UnityEngine.SkinnedMeshRenderer) {
        var smr = (UnityEngine.SkinnedMeshRenderer)r;
        var m = new UnityEngine.Mesh();
        smr.BakeMesh(m);
        foreach (var v in m.vertices) vs.Add(mtx.MultiplyPoint3x4(v));
        uvs.AddRange(m.uv);
        tris.AddRange(m.triangles);
        tex = smr.sharedMaterial != null && smr.sharedMaterial.mainTexture != null ? smr.sharedMaterial.mainTexture.name : "";
    } else {
        var mf = r.GetComponent<UnityEngine.MeshFilter>();
        if (mf == null || mf.sharedMesh == null) continue;
        foreach (var v in mf.sharedMesh.vertices) vs.Add(mtx.MultiplyPoint3x4(v));
        uvs.AddRange(mf.sharedMesh.uv);
        tris.AddRange(mf.sharedMesh.triangles);
        var mr = r.GetComponent<UnityEngine.MeshRenderer>();
        tex = mr != null && mr.sharedMaterial != null && mr.sharedMaterial.mainTexture != null ? mr.sharedMaterial.mainTexture.name : "";
    }
    if (vs.Count == 0) continue;
    if (!first) sb.Append(",");
    first = false;
    n++;
    sb.Append("{\"name\":\"" + pname + "\",\"kind\":\"" + kind + "\",\"tex\":\"" + tex + "\",\"sort\":").Append(r.sortingOrder).Append(",\"verts\":[");
    for (int i = 0; i < vs.Count; i++) { if (i > 0) sb.Append(","); sb.Append(vs[i].x.ToString("F4")).Append(",").Append(vs[i].y.ToString("F4")); }
    sb.Append("],\"uvs\":[");
    for (int i = 0; i < uvs.Count; i++) { if (i > 0) sb.Append(","); sb.Append(uvs[i].x.ToString("F5")).Append(",").Append(uvs[i].y.ToString("F5")); }
    sb.Append("],\"tris\":[");
    for (int i = 0; i < tris.Count; i++) { if (i > 0) sb.Append(","); sb.Append(tris[i]); }
    sb.Append("]}");
}
sb.Append("]}");
System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(outPath));
System.IO.File.WriteAllText(outPath, sb.ToString());
UnityEngine.Object.DestroyImmediate(go);
return "OK baked parts=" + n + " -> " + outPath;

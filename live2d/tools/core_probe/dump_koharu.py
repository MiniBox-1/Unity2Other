# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "vendor" / "py-moc3"))
from moc3 import Moc3

P = r"D:\VB\Convert\Live2d\Cubism\Samples\Models\Koharu\Koharu.moc3"
m = Moc3.from_file(P)
print(m.summary())
print("counts:", m.counts)
print("canvas:", m.canvas)

print("\nparams:", m.parameter_ids)
print("parts:", m.part_ids)
print("deformers:", m.deformer_ids[:10], "...")

# first art mesh
xyz = m["keyform_position.xys"]
print("\nart mesh 0:", m["art_mesh.ids"][0],
      "verts", m["art_mesh.vertex_counts"][0],
      "tex", m["art_mesh.texture_indices"][0],
      "flags", m["art_mesh.drawable_flags"][0],
      "parent_part", m["art_mesh.parent_part_indices"][0],
      "parent_def", m["art_mesh.parent_deformer_indices"][0],
      "kf_count", m["art_mesh.keyform_counts"][0],
      "kf_begin", m["art_mesh.keyform_begin_indices"][0],
      "band", m["art_mesh.keyform_binding_band_indices"][0])
vb = m["art_mesh_keyform.keyform_position_begin_indices"][0]
vc = m["art_mesh.vertex_counts"][0]
print("verts:", [(round(xyz[(vb + k) * 2], 3), round(xyz[(vb + k) * 2 + 1], 3)) for k in range(vc)])
print("uv:", [round(v, 2) for v in m["uv.xys"][:12]])
print("indices:", m["position_index.indices"][:12])

print("\nband begin/count:", m["keyform_binding_band.begin_indices"][:5], m["keyform_binding_band.counts"][:5])
print("binding keys_begin/counts:", m["keyform_binding.keys_begin_indices"][:5], m["keyform_binding.keys_counts"][:5])
print("binding param idx:", m["keyform_binding_index.indices"][:8])
print("keys values:", m["keys.values"][:8])

# a rotation deformer sample
print("\nrot deformer 0:", m["rotation_deformer.base_angles"][0],
      "kfcount", m["rotation_deformer.keyform_counts"][0])
print("rot kf angle/origin/scale:",
      m["rotation_deformer_keyform.angles"][:6],
      [round(v, 3) for v in m["rotation_deformer_keyform.origin_xs"][:6]],
      [round(v, 3) for v in m["rotation_deformer_keyform.scales"][:6]])

# min/max of all vertex coordinates
xs = xyz[0::2]
ys = xyz[1::2]
print("\nkeyform pos bbox:", round(min(xs), 3), round(max(xs), 3), round(min(ys), 3), round(max(ys), 3))

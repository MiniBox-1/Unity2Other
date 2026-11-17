"""unity2spine - Unity 2DModel / NGUI static assets to Spine 3.8.

Subpackages by function:
  unity/    Unity side parsing (prefab/scene, Transform, SkinnedMeshRenderer, clips)
  ngui/     legacy NGUI route (atlas packing, PrefabModel, frame animation)
  convert/  2DModel conversion (static prefab to Spine, frame bakes, single frame)
  spine/    Spine 3.8 output (JSON/atlas/.skel) and sprite outline
  validate/ product self-check and merging
"""

__all__ = ["unity", "ngui", "convert", "spine", "validate"]

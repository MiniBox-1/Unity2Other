# Unity Animation to Spine

Offline conversion toolkit for Unity 2DModel, BdOne NGUI and static `.Lihui`
prefabs to Spine 3.8 JSON, atlas, SKEL and viewer configuration files.

This repository contains the conversion source, tools, tests and small sample
outputs. It intentionally excludes the Unity source projects, viewer runtime,
full truth captures and bulk converted products because those assets are large
and may have separate distribution terms.

## Conversion routes

| Route | Input | Output strategy |
| --- | --- | --- |
| SingleSpine Lo | `*.uAnim.prefab` | Root bone plus per-frame vertex deform |
| SingleSpine BD | BdOne NGUI hierarchy | Preserved node hierarchy and region attachments |
| MultiSpine Lo | `*.uAnim.prefab` | True bone tree and weighted mesh attachments |
| MultiSpine BD | BdOne NGUI hierarchy | Per-node rigid weighted mesh attachments |
| StaticSpine Lo | `*.Lihui.prefab` | Bone tree with default-visible component slots |

## Repository layout

```text
SingleSpine/Shared/Unity2Spine/       Shared parser and Spine writer library
SingleSpine/Shared/lo_uncen2Spine/    GUI/CLI and the Lo/BdOne extensions
SingleSpine/LO/Docs/                  Lo handover and algorithm documentation
SingleSpine/BD/Docs/                  BdOne handover documentation
MultiSpine/LO/MutiBone/               True multi-bone converter and validation tools
MultiSpine/BD/Tools/                  BdOne region-to-mesh converter
StaticSpine/LO/Tools/                 Static `.Lihui` converter and validator
Examples/                             Small generated Spine examples
packaging/github/                     Packaging templates and notes
```

The development layout under `D:\VB\Convert\Spine` has the same
relative structure, so scripts and relative imports work unchanged.

## Requirements

- Python 3.10 or newer.
- `Pillow` and `numpy`.
- Optional: `PySide6` for the GUI.
- A Unity project containing the source prefab, Sprite and texture assets.
- Optional: the external headless Spine viewer used by render comparison tools.

```powershell
python -m pip install -e .\SingleSpine\Shared\Unity2Spine
python -m pip install -e .\SingleSpine\Shared\lo_uncen2Spine
```

## External paths

The upstream project currently targets Windows and retains legacy defaults for
the original workstation. Override them before running conversion:

```powershell
$env:U2S_LO_ASSETS = 'D:\Path\To\Mobile-old\Assets'
$env:U2S_LO_PREFABS = Join-Path $env:U2S_LO_ASSETS 'Prefabs'
$env:U2S_BDONE_PROJECT = 'D:\Path\To\BdOne'
$env:U2S_VIEWER_ROOT = 'D:\Path\To\Viewer\Render'
```

## Static `.Lihui` quick start

Convert one prefab:

```powershell
python .\StaticSpine\LO\Tools\convert_lihui_static.py `
  "$env:U2S_LO_PREFABS\2DModel_3P_CSPerrault_N.Lihui.prefab"
```

Convert all static prefabs serially, with one-product checkpoints:

```powershell
python .\StaticSpine\LO\Tools\convert_lihui_static.py `
  --all --resume
```

Validate generated products:

```powershell
python .\StaticSpine\LO\Tools\validate_lihui_static.py `
  .\StaticSpine\LO\Products\Current
```

The static converter emits one slot per default-visible SpriteRenderer. Slots
are enabled by default, preserve GameObject names and `sortingOrder`, and use
the Sprite asset's tight mesh.

## MultiSpine Lo quick start

Export the deform baseline first, then convert the true bone hierarchy:

```powershell
python -m ngui2spine.static_prefab_spine `
  "$env:U2S_LO_PREFABS\2DModel_BR_Banshee_NS1.uAnim.prefab" `
  .\work\banshee_deform --assets $env:U2S_LO_ASSETS --json

python .\MultiSpine\LO\MutiBone\src\convert_bones.py `
  "$env:U2S_LO_PREFABS\2DModel_BR_Banshee_NS1.uAnim.prefab" `
  .\work\banshee_multi --assets $env:U2S_LO_ASSETS `
  --reuse-from .\work\banshee_deform --simplify 0.05 --deform-residual 0.005
```

See the route-specific Markdown files for detailed options, known issues and
validation criteria.

## Memory and execution rules

The upstream converter was developed on a 16 GB Windows machine. Run only one
GL render job at a time. Check free physical memory before a batch and keep at
least 3 GB available. The static batch explicitly clears its outline cache after
each product.

## Included examples

- `Examples/StaticSpine/Ajax_N`: shield, body and shield-arm slots.
- `Examples/StaticSpine/CSPerrault_N`: one full-body slot.
- `Examples/MultiSpine/banshee`: true multi-bone Lo example.
- `Examples/SingleSpine/Alexandra_NS1`: single-bone Lo example.
- `Examples/SingleSpine/BD/Anjielika_01`: BdOne single-bone example.

## License

No open-source license has been declared for this repository. See
`LICENSE_STATUS.md` before publishing or redistributing.

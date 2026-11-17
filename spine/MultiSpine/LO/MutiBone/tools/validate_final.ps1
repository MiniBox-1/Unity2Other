$ErrorActionPreference = 'Stop'

$root = Split-Path $PSScriptRoot -Parent
$python = 'D:\Anconda\python.exe'
$finalRoot = Join-Path $root 'out\_reg_final'

$os = Get-CimInstance Win32_OperatingSystem
$freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
if ($freeGB -lt 3) {
    throw "Free memory below 3 GB: ${freeGB} GB"
}

$dirs = @(Get-ChildItem -LiteralPath $finalRoot -Directory | Sort-Object Name)
if ($dirs.Count -eq 0) {
    throw "Final directory is empty: $finalRoot"
}

Push-Location $root
try {
    $env:PYTHONIOENCODING = 'utf-8'
    & $python -m py_compile `
        'src\convert_bones.py' `
        'src\shared_skin_audit.py' `
        'tools\validate_multibone.py' `
        'tools\compare_runtime_geom.py' `
        'tools\compare_runtime_bones.py' `
        'tools\inspect_part_weights.py' `
        'tools\make_color_variant.py' `
        'tools\scan_runtime_geom_time.py' `
        'tools\diagnose_animators.py' `
        'tools\audit_shared_skins.py' `
        'tools\inspect_runtime_slots.py' `
        'tools\benchmark_load.py' `
        'tools\convert_all_prefabs.py' `
        'tools\make_all_prefabs_manifest.py' `
        'tools\inspect_bone_chain.py'
    if ($LASTEXITCODE -ne 0) { throw 'Python compile failed' }

    & $python 'tools\test_simplify.py'
    if ($LASTEXITCODE -ne 0) { throw 'Simplify tests failed' }

    & $python 'tools\test_shared_skin_audit.py'
    if ($LASTEXITCODE -ne 0) { throw 'Shared-skin audit tests failed' }

    $paths = @($dirs | ForEach-Object FullName)
    & $python 'tools\validate_multibone.py' @paths
    if ($LASTEXITCODE -ne 0) { throw 'Multibone validation failed' }

    $manifest = @()
    foreach ($dir in $dirs) {
        $json = Get-ChildItem -LiteralPath $dir.FullName -Filter '*_static.json' |
            Select-Object -First 1
        $skel = Get-ChildItem -LiteralPath $dir.FullName -Filter '*_static.skel' |
            Select-Object -First 1
        if ($null -eq $json -or $null -eq $skel) {
            throw "Missing JSON or SKEL: $($dir.FullName)"
        }
        $doc = Get-Content -LiteralPath $json.FullName -Raw -Encoding utf8 |
            ConvertFrom-Json
        $manifest += [ordered]@{
            role = $dir.Name
            json = $json.Name
            jsonBytes = $json.Length
            jsonSha256 = (Get-FileHash -LiteralPath $json.FullName -Algorithm SHA256).Hash
            skel = $skel.Name
            skelBytes = $skel.Length
            skelSha256 = (Get-FileHash -LiteralPath $skel.FullName -Algorithm SHA256).Hash
            bones = @($doc.bones).Count
            slots = @($doc.slots).Count
            animations = @($doc.animations.PSObject.Properties).Count
        }
    }

    $report = [ordered]@{
        generatedAt = (Get-Date).ToString('o')
        freeGB = $freeGB
        roleCount = $manifest.Count
        roles = $manifest
    }
    $reportPath = Join-Path $finalRoot 'manifest.json'
    $report | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Output "FINAL_VALIDATION_OK roles=$($manifest.Count) manifest=$reportPath"
}
finally {
    Pop-Location
}

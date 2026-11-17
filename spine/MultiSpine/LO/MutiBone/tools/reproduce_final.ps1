param(
    [string]$OutRoot = '',
    [switch]$UseScene
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = 'D:\Anconda\python.exe'
$converter = Join-Path $root 'src\convert_bones.py'
$finalRoot = Join-Path $root 'out\_reg_final'

if (-not $OutRoot) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $OutRoot = Join-Path $root "out\_repro_$stamp"
}
if (Test-Path -LiteralPath $OutRoot) {
    $existing = @(Get-ChildItem -LiteralPath $OutRoot -Force)
    if ($existing.Count -gt 0) {
        throw "Output directory is not empty: $OutRoot"
    }
} else {
    New-Item -ItemType Directory -Path $OutRoot | Out-Null
}

# Locate the current Unity project without embedding the non-ASCII folder name.
$newRoot = Join-Path (Split-Path $root -Parent) 'Search\New'
$project = Get-ChildItem -LiteralPath $newRoot -Directory |
    ForEach-Object { Join-Path $_.FullName 'proj-Mobile-old' } |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
if (-not $project) {
    throw "Cannot locate proj-Mobile-old below $newRoot"
}
$assets = Join-Path $project 'Assets'
$prefabs = Join-Path $assets 'Prefabs'
$scene = Join-Path $assets 'Sences\save.unity'

$roles = @(
    @{ role = 'alice';       prefab = '2DModel_3P_Alice_NS1.uAnim.prefab';              deform = '_deform_alice_json'; extra = @() },
    @{ role = 'bab';         prefab = '2DModel_PECS_Babariana_NS1.uAnim.prefab';        deform = '_batch\2DModel_PECS_Babariana_NS1\deform'; extra = @() },
    @{ role = 'banshee';     prefab = '2DModel_BR_Banshee_NS1.uAnim.prefab';            deform = '_deform_new2'; extra = @() },
    @{ role = 'beasthunter'; prefab = '2DModel_BR_BeastHunter_NS1.uAnim.prefab';        deform = '_deform_beasthunter_new'; extra = @('--deduped-default', '--secondary-phase', '2.0') },
    @{ role = 'bheur';       prefab = '2DModel_BR_Bheur_NS1.uAnim.prefab';              deform = '_deform_bheur_new'; extra = @() },
    @{ role = 'bl';          prefab = '2DModel_3P_BlackLilith_NS1.uAnim.prefab';        deform = '_deform_bl'; extra = @() },
    @{ role = 'blackwyrm';   prefab = '2DModel_3P_BlackWyrm_NS1.uAnim.prefab';          deform = '_deform_blackwyrm_new'; extra = @() },
    @{ role = 'brownie';     prefab = '2DModel_BR_Brownie_NS1.uAnim.prefab';            deform = '_deform_brownie_new'; extra = @() },
    @{ role = 'c0';          prefab = '2DModel_3P_ConstantiaS2_NS0.uAnim.prefab';       deform = '_batch\2DModel_3P_ConstantiaS2_NS0\deform'; extra = @() },
    @{ role = 'c0ss1';       prefab = '2DModel_3P_ConstantiaS2_SS1.uAnim.prefab';       deform = '_deform_c0_ss1_new'; extra = @() },
    @{ role = 'cerberus3';   prefab = '2DModel_PECS_Cerberus_NS3.uAnim.prefab';         deform = '_deform_cerberus3_new'; extra = @() },
    @{ role = 'circe';       prefab = '2DModel_PECS_Circe_NS1.uAnim.prefab';            deform = '_deform_circe_new'; extra = @() },
    @{ role = 'coco';        prefab = '2DModel_PECS_CoCoWhiteShell_N.uAnim.prefab';     deform = '_batch\2DModel_PECS_CoCoWhiteShell_N\deform'; extra = @() },
    @{ role = 'nightangel';  prefab = '2DModel_BR_NightAngel_NS2.uAnim.prefab';         deform = '_batch\2DModel_BR_NightAngel_NS2\deform'; extra = @() }
)

function Assert-Memory {
    $os = Get-CimInstance Win32_OperatingSystem
    $freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
    if ($freeGB -lt 3) {
        throw "Free memory below 3 GB: $freeGB GB"
    }
}

$results = @()
try {
    foreach ($item in $roles) {
        Assert-Memory
        $prefab = Join-Path $prefabs $item.prefab
        $deform = Join-Path (Join-Path $root 'out') $item.deform
        $out = Join-Path $OutRoot $item.role
        if (-not (Test-Path -LiteralPath $prefab)) {
            throw "Missing prefab: $prefab"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $deform '_static_info.json'))) {
            throw "Missing deform info: $deform"
        }

        $cliArgs = @(
            $converter, $prefab, $out,
            '--assets', $assets,
            '--reuse-from', $deform,
            '--simplify', '0.05',
            '--deform-residual', '0.005'
        )
        if ($UseScene) {
            $cliArgs += @('--scene', $scene)
        }
        $cliArgs += @($item.extra)

        Write-Output "REPRO role=$($item.role)"
        & $python @cliArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Conversion failed for $($item.role)"
        }

        $sourceJson = Get-ChildItem -LiteralPath (Join-Path $finalRoot $item.role) -Filter '*_static.json' |
            Select-Object -First 1
        $sourceSkel = Get-ChildItem -LiteralPath (Join-Path $finalRoot $item.role) -Filter '*_static.skel' |
            Select-Object -First 1
        $madeJson = Get-ChildItem -LiteralPath $out -Filter '*_static.json' |
            Select-Object -First 1
        $madeSkel = Get-ChildItem -LiteralPath $out -Filter '*_static.skel' |
            Select-Object -First 1
        if ($null -eq $sourceJson -or $null -eq $sourceSkel -or
            $null -eq $madeJson -or $null -eq $madeSkel) {
            throw "Missing final/repro JSON or SKEL for $($item.role)"
        }
        $sourceJsonHash = (Get-FileHash -LiteralPath $sourceJson.FullName -Algorithm SHA256).Hash
        $madeJsonHash = (Get-FileHash -LiteralPath $madeJson.FullName -Algorithm SHA256).Hash
        $sourceSkelHash = (Get-FileHash -LiteralPath $sourceSkel.FullName -Algorithm SHA256).Hash
        $madeSkelHash = (Get-FileHash -LiteralPath $madeSkel.FullName -Algorithm SHA256).Hash
        $results += [ordered]@{
            role = $item.role
            jsonEqual = ($sourceJsonHash -eq $madeJsonHash)
            skelEqual = ($sourceSkelHash -eq $madeSkelHash)
            finalJsonSha256 = $sourceJsonHash
            reproJsonSha256 = $madeJsonHash
            finalSkelSha256 = $sourceSkelHash
            reproSkelSha256 = $madeSkelHash
        }
    }
} finally {
    $report = [ordered]@{
        generatedAt = (Get-Date).ToString('o')
        useScene = [bool]$UseScene
        outputRoot = $OutRoot
        results = $results
    }
    $reportPath = Join-Path $OutRoot 'repro_manifest.json'
    $report | ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath $reportPath -Encoding utf8
}

$mismatch = @($results | Where-Object { -not $_.jsonEqual -or -not $_.skelEqual })
if ($mismatch.Count -gt 0) {
    $names = ($mismatch | ForEach-Object { $_.role }) -join ', '
    throw "Reproduction hash mismatch: $names"
}
Write-Output "REPRO_VALIDATION_OK roles=$($results.Count) output=$OutRoot"

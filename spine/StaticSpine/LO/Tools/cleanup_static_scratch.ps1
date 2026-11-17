$ErrorActionPreference = 'Stop'

$products = (Resolve-Path -LiteralPath `
    'D:\VB\Convert\Spine\StaticSpine\LO\Products').Path
$names = @('_uvtest', '_batch_smoke', '_filtertest')
$targets = @()

foreach ($name in $names) {
    $path = Join-Path $products $name
    if (Test-Path -LiteralPath $path) {
        $resolved = (Resolve-Path -LiteralPath $path).Path
        $prefix = $products.TrimEnd('\') + '\'
        if (-not $resolved.StartsWith(
                $prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing cleanup outside Products: $resolved"
        }
        $targets += $resolved
    }
}

foreach ($target in $targets) {
    Remove-Item -LiteralPath $target -Recurse -Force
}

"REMOVED_STATIC_SCRATCH=$($targets.Count)"

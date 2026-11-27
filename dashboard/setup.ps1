param([string]$DataPath = (Join-Path $PSScriptRoot '..\data'))
$ErrorActionPreference = 'Stop'
$resolved = (Resolve-Path -LiteralPath $DataPath).Path
$tables = Join-Path $PSScriptRoot 'DataPulseV4.SemanticModel\definition\tables'
$mapping = [ordered]@{
    FactQuality = 'quality_metrics.csv'
    FactAlerts = 'alerts_log.csv'
    FactPerformance = 'performance_log.csv'
    FactBenchmark = 'benchmarks\comparison.csv'
}
foreach ($name in $mapping.Keys) {
    $source = Join-Path $resolved $mapping[$name]
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing file: $source" }
}
foreach ($name in $mapping.Keys) {
    $file = Join-Path $tables ($name + '.tmdl')
    $source = Join-Path $resolved $mapping[$name]
    $content = [IO.File]::ReadAllText($file)
    $pattern = 'File\.Contents\("(?:[^"]|"")*"\)'
    if ([regex]::Matches($content,$pattern).Count -ne 1) { throw "Expected exactly one literal source in $file" }
    $replacement = 'File.Contents("' + $source.Replace('"','""') + '")'
    $newContent = [regex]::Replace($content,$pattern,[System.Text.RegularExpressions.MatchEvaluator]{param($m) $replacement})
    [IO.File]::WriteAllText($file,$newContent,[Text.UTF8Encoding]::new($false))
    Write-Host "$name -> $source"
}
Write-Host 'Verified all four source files. Open DataPulseV4.pbip and refresh.'

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath 'D:\比赛项目\lingxi-main').Path
$moves = @(
    @{source='C:\Users\twofl\.codex\visualizations\2026\10\13\01a13355-cde6-7b21-adff-2a27813b3af9\lingxi_tf_20261023'; relative='firmware\local_projects\lingxi_tf_20261023'},
    @{source='D:\esp32\lingxi_audio_ram'; relative='firmware\local_projects\lingxi_audio_ram'},
    @{source='D:\esp32\lingxi_lcd'; relative='firmware\local_projects\lingxi_lcd'},
    @{source='D:\esp32\backups'; relative='backups\original_firmware'},
    @{source='D:\BaiduNetdiskDownload\【正点原子】ESP32 AI BOX1'; relative='vendor\ESP32_AI_BOX1'}
)
$report = @()
$reportPath = Join-Path $projectRoot 'docs\FILE_MIGRATION_20261024.json'
if (Test-Path -LiteralPath $reportPath) { $report = @(Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json) }
foreach ($entry in $moves) {
    if ($report | Where-Object { $_.source -eq $entry.source -and $_.sha256_verified }) { continue }
    $source = (Resolve-Path -LiteralPath $entry.source).Path
    if ($source.TrimEnd('\') -ne $entry.source.TrimEnd('\')) { throw 'Unexpected source resolution.' }
    $item = Get-Item -LiteralPath $source -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source is a reparse point.' }
    $destination = [IO.Path]::GetFullPath((Join-Path $projectRoot $entry.relative))
    if (-not $destination.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Destination escaped project.' }
    $before = @(Get-ChildItem -LiteralPath $source -Recurse -Force -File | ForEach-Object {
        if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Nested file reparse point.' }
        [pscustomobject]@{path=$_.FullName.Substring($source.Length+1); bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
    })
    if (Get-ChildItem -LiteralPath $source -Directory -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Nested directory reparse point.' }
    $parent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $copied = $source.StartsWith('D:\esp32\', [StringComparison]::OrdinalIgnoreCase)
    if ($copied) {
        Write-Output ("COPYING protected source " + $entry.relative + ' files=' + $before.Count)
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
        foreach ($record in $before) {
            $target = Join-Path $destination $record.path
            if (Test-Path -LiteralPath $target) {
                if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $record.sha256) { throw "Conflicting destination: $target" }
            } else {
                New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
                Copy-Item -LiteralPath (Join-Path $source $record.path) -Destination $target
            }
        }
    } else {
        if (Test-Path -LiteralPath $destination) { throw "Destination already exists: $destination" }
        Write-Output ("MOVING " + $entry.relative + ' files=' + $before.Count)
        Move-Item -LiteralPath $source -Destination $destination
    }
    $after = @(Get-ChildItem -LiteralPath $destination -Recurse -Force -File)
    if ($after.Count -ne $before.Count) { throw 'File count mismatch.' }
    foreach ($record in $before) {
        $target = Join-Path $destination $record.path
        if ((Get-Item -LiteralPath $target).Length -ne $record.bytes -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $record.sha256) { throw "Integrity mismatch: $target" }
    }
    $report += [pscustomobject]@{source=$source; destination=$destination; files=$before.Count; bytes=($before | Measure-Object bytes -Sum).Sum; sha256_verified=$true; protected_original_retained=$copied; manifest=$before}
    $report | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $reportPath -Encoding UTF8
    Write-Output ("VERIFIED " + $entry.relative)
}
Write-Output 'PROJECT_FILES_CONSOLIDATED'

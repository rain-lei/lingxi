# Update only the existing LingXi factory application on an ESP32-S3 BOX.
# This script never erases the entire flash or writes NVS / partition tables.
# The user must launch it explicitly and provide the device's current COM port.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$Port = '',
    [string]$BinaryPath = '',
    [string]$Sha256 = '',
    [ValidateSet(115200, 230400, 460800, 921600)]
    [int]$Baud = 460800
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Esptool {
    param([Parameter(Mandatory = $true)][string[]]$ToolArguments)
    & $script:PythonExecutable -m esptool @ToolArguments
    if ($LASTEXITCODE -ne 0) {
        throw "esptool failed (exit $LASTEXITCODE). No further write or verification commands were run."
    }
}

try {
    if ([string]::IsNullOrWhiteSpace($Port)) {
        $Port = Read-Host 'Enter the UART COM port shown in Device Manager (for example COM12)'
    }
    $Port = $Port.Trim().ToUpperInvariant()
    if ($Port -cnotmatch '^COM[1-9][0-9]{0,3}$') {
        throw 'Invalid COM port. Use COM followed by 1-4 digits, such as COM12.'
    }

    if ([string]::IsNullOrWhiteSpace($BinaryPath)) {
        $BinaryPath = Join-Path -Path $PSScriptRoot -ChildPath 'lingxi-tf-animation.bin'
    }
    if (-not (Test-Path -LiteralPath $BinaryPath -PathType Leaf)) {
        throw "Application binary not found: $BinaryPath. Extract the firmware package first, or provide -BinaryPath."
    }
    $ResolvedBinary = (Resolve-Path -LiteralPath $BinaryPath).ProviderPath
    $BinaryFile = Get-Item -LiteralPath $ResolvedBinary
    $MaximumApplicationBytes = 0x3F0000
    if ($BinaryFile.Length -lt 1024 -or $BinaryFile.Length -gt $MaximumApplicationBytes) {
        throw "Unexpected application size ($($BinaryFile.Length) bytes). Use the matching LingXi application binary, not a full-flash backup."
    }

    $BinaryStream = [System.IO.File]::OpenRead($ResolvedBinary)
    try {
        $ImageMagic = $BinaryStream.ReadByte()
        $BinaryStream.Position = 32
        $ApplicationDescriptor = New-Object byte[] 4
        $DescriptorLength = $BinaryStream.Read($ApplicationDescriptor, 0, 4)
    } finally { $BinaryStream.Dispose() }
    if ($ImageMagic -ne 0xE9) {
        throw 'The selected file is not an ESP application image (expected magic byte E9).'
    }
    # Decimal uint32 avoids Windows PowerShell treating ABCD5432 as signed int32.
    if ($DescriptorLength -ne 4 -or [System.BitConverter]::ToUInt32($ApplicationDescriptor, 0) -ne [uint32]2882360370) {
        throw 'The file does not contain the expected ESP-IDF application descriptor. Do not select a bootloader or partition-table file.'
    }

    # .NET hashing stays read-only and is not affected by inherited -WhatIf.
    $ChecksumStream = [System.IO.File]::OpenRead($ResolvedBinary)
    $ChecksumAlgorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $ActualSha256 = [System.BitConverter]::ToString($ChecksumAlgorithm.ComputeHash($ChecksumStream)).Replace('-', '')
    } finally {
        $ChecksumAlgorithm.Dispose()
        $ChecksumStream.Dispose()
    }
    $ExpectedHashSource = ''
    if ([string]::IsNullOrWhiteSpace($Sha256)) {
        $ChecksumPath = Join-Path -Path $BinaryFile.DirectoryName -ChildPath 'SHA256SUMS.txt'
        if (Test-Path -LiteralPath $ChecksumPath -PathType Leaf) {
            $MatchingChecksums = @()
            $ChecksumLines = [System.IO.File]::ReadAllLines($ChecksumPath)
            foreach ($ChecksumLine in $ChecksumLines) {
                if ([string]::IsNullOrWhiteSpace($ChecksumLine)) { continue }
                # Accept standard sha256sum output: HASH  filename or HASH *filename.
                if ($ChecksumLine -cnotmatch '^(?<checksum>[0-9A-Fa-f]{64})[ \t]+\*?(?<filename>[^<>:"/\\|?*\r\n]+)$') {
                    throw 'Invalid SHA256SUMS.txt format. Download and extract the complete firmware package again.'
                }
                if ($Matches.filename -ceq $BinaryFile.Name) {
                    $MatchingChecksums += $Matches.checksum
                }
            }
            if ($MatchingChecksums.Count -ne 1) {
                throw 'SHA256SUMS.txt must contain exactly one checksum matching the application filename. The file will not be flashed.'
            }
            $Sha256 = $MatchingChecksums[0]
            $ExpectedHashSource = $ChecksumPath
        }
    } else {
        $ExpectedHashSource = '-Sha256'
    }
    if (-not [string]::IsNullOrWhiteSpace($Sha256)) {
        $Sha256 = $Sha256.Trim().ToUpperInvariant()
        if ($Sha256 -cnotmatch '^[0-9A-F]{64}$') { throw '-Sha256 must contain exactly 64 hexadecimal characters.' }
        if ($ActualSha256 -cne $Sha256) { throw 'SHA-256 mismatch. The file will not be flashed. Download the complete package again.' }
    }

    $IdfPython = 'D:\Espressif\python_env\idf5.4_py3.11_env\Scripts\python.exe'
    if (Test-Path -LiteralPath $IdfPython -PathType Leaf) {
        $script:PythonExecutable = $IdfPython
    } else {
        $PythonCommand = Get-Command -Name python.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $PythonCommand) { throw 'Python was not found. Open the installed ESP-IDF environment, then run this script again.' }
        $script:PythonExecutable = $PythonCommand.Source
    }

    Write-Host "Python: $script:PythonExecutable"
    Write-Host "Application: $ResolvedBinary"
    Write-Host "Size: $($BinaryFile.Length) bytes"
    Write-Host "SHA-256: $ActualSha256"
    if ($ExpectedHashSource) { Write-Host "Checksum verified against: $ExpectedHashSource" }
    Write-Host 'Checking esptool and application image before accessing the serial port...'
    Invoke-Esptool -ToolArguments @('version')
    Invoke-Esptool -ToolArguments @('--chip', 'esp32s3', 'image_info', '--version', '2', $ResolvedBinary)

    if ($PSCmdlet.ShouldProcess("$Port (ESP32-S3, application at 0x10000)", 'Write the LingXi application, then verify the same image')) {
        Write-Host 'Close ESP-IDF Monitor and other programs using this COM port.'
        Write-Host 'Writing only the application at 0x10000. NVS and the existing partition table are preserved.'
        Invoke-Esptool -ToolArguments @('--chip', 'esp32s3', '--port', $Port, '--baud', [string]$Baud,
            '--before', 'default_reset', '--after', 'no_reset',
            'write_flash', '--flash_mode', 'keep', '--flash_freq', 'keep', '--flash_size', 'keep',
            '0x10000', $ResolvedBinary)
        Write-Host 'Verifying the application from flash at 0x10000...'
        Invoke-Esptool -ToolArguments @('--chip', 'esp32s3', '--port', $Port, '--baud', [string]$Baud,
            '--before', 'default_reset', '--after', 'hard_reset',
            'verify_flash', '--flash_mode', 'keep', '--flash_freq', 'keep', '--flash_size', 'keep',
            '0x10000', $ResolvedBinary)
        Write-Host 'Application write and verify_flash completed successfully.' -ForegroundColor Green
        Write-Host 'Next: insert the FAT32 TF card with power off, restart, and open the device page to install animations.'
    }
} catch {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
}

param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$networkClass = [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]
$tetherClass = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
$sessionClass = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringSessionAccessPointConfiguration, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
$bandClass = [Windows.Networking.NetworkOperators.TetheringWiFiBand, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
$authClass = [Windows.Networking.NetworkOperators.TetheringWiFiAuthenticationKind, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
$resultClass = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
$linkProfile = $networkClass::GetInternetConnectionProfile()
if ($null -eq $linkProfile) { throw 'No active Internet profile.' }
$localTether = $tetherClass::CreateFromConnectionProfile($linkProfile)
$currentLinkState = [string]$localTether.TetheringOperationalState
if ($CheckOnly -or $currentLinkState -ne 'Off') {
    $currentLinkSettings = $localTether.GetCurrentAccessPointConfiguration()
    [pscustomobject]@{ status = 'ExistingState'; state = $currentLinkState; ssid = $currentLinkSettings.Ssid; band = [string]$currentLinkSettings.Band } | ConvertTo-Json -Compress
    exit 0
}
$linkSession = [Activator]::CreateInstance($sessionClass)
$linkSession.Ssid = 'LingXi-Link'
$linkSession.Passphrase = 'lingxi2026'
$linkSession.Band = $bandClass::TwoPointFourGigahertz
$linkSession.AuthenticationKind = $authClass::Wpa2
if (-not $linkSession.IsBandSupported($linkSession.Band)) { throw '2.4 GHz hotspot is unavailable.' }
if (-not $linkSession.IsAuthenticationKindSupported($linkSession.AuthenticationKind)) { throw 'WPA2 hotspot is unavailable.' }
$taskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 } | Select-Object -First 1
$startOperation = $localTether.StartTetheringAsync($linkSession)
$startTask = $taskMethod.MakeGenericMethod($resultClass).Invoke($null, @($startOperation))
if (-not $startTask.Wait(20000)) { throw 'Hotspot startup did not complete within 20 seconds.' }
$startResult = $startTask.Result
[pscustomobject]@{ status = [string]$startResult.Status; state = [string]$localTether.TetheringOperationalState; ssid = 'LingXi-Link'; band = '2.4GHz'; temporary_session = $true } | ConvertTo-Json -Compress
if ([string]$startResult.Status -ne 'Success') { throw 'Hotspot startup failed.' }

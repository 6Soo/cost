param(
    [Parameter(Mandatory = $true)]
    [string]$ProfileRoot,
    [int]$Port = 9229,
    [string]$Url = 'https://www.agoda.com/account/bookings.html',
    [switch]$LegacyHeadless,
    [string]$UserAgent = ''
)

$ErrorActionPreference = 'Stop'
$edge = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
if (-not (Test-Path -LiteralPath $edge)) {
    $edge = 'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
}
if (-not (Test-Path -LiteralPath $edge)) {
    throw 'edge_executable_missing'
}

$userData = Join-Path $ProfileRoot 'User Data'
if (-not (Test-Path -LiteralPath $userData)) {
    throw 'headless_profile_missing'
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw 'debug_port_in_use'
}

$headlessFlag = if ($LegacyHeadless) { '--headless' } else { '--headless=new' }
$launchNonce = [guid]::NewGuid().ToString('N')
$arguments = @(
    $headlessFlag,
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--enable-logging=stderr',
    '--v=1',
    '--remote-debugging-address=127.0.0.1',
    "--remote-debugging-port=$Port",
    "`"--user-data-dir=$userData`"",
    '--profile-directory=Default',
    "--agoda-capture-nonce=$launchNonce",
    $Url
)
if (-not [string]::IsNullOrWhiteSpace($UserAgent)) {
    $arguments = @($arguments[0..($arguments.Count - 2)]) + @("`"--user-agent=$UserAgent`"", $Url)
}

$logRoot = Join-Path $ProfileRoot 'probe-logs'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$stdoutPath = Join-Path $logRoot 'stdout.log'
$stderrPath = Join-Path $logRoot 'stderr.log'
$process = Start-Process -FilePath $edge -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
Start-Sleep -Seconds 3

$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)" -ErrorAction SilentlyContinue
$commandLine = if ($null -ne $processInfo) { [string]$processInfo.CommandLine } else { '' }
$commandLineAttested = $commandLine.Contains($headlessFlag) -and
    $commandLine.Contains("--remote-debugging-address=127.0.0.1") -and
    $commandLine.Contains("--remote-debugging-port=$Port") -and
    $commandLine.Contains("--agoda-capture-nonce=$launchNonce") -and
    $commandLine.Contains($userData)
if (-not $commandLineAttested) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw 'headless_process_attestation_failed'
}

$version = $null
$pages = $null
try {
    $version = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 5
} catch {
    $version = $null
}
try {
    $pages = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/json/list" -TimeoutSec 5
} catch {
    $pages = $null
}

$pageObjects = if ($null -ne $pages) { @($pages.Content | ConvertFrom-Json) } else { @() }
$targetCandidates = @($pageObjects | Where-Object { $_.type -eq 'page' })
$target = $targetCandidates | Where-Object { $_.url -match 'agoda\.com' } | Select-Object -First 1
if ($null -eq $target) { $target = $targetCandidates | Where-Object { $_.url -eq 'about:blank' } | Select-Object -First 1 }
if ($null -eq $target) { $target = $targetCandidates | Select-Object -First 1 }
$endpointAttested = $commandLineAttested -and $null -ne $version -and $null -ne $pages -and $null -ne $target
$manifestPath = Join-Path $ProfileRoot 'cdp-manifest.json'
$manifest = [ordered]@{
    schema = 1
    pid = $process.Id
    port = $Port
    profile_root = (Resolve-Path -LiteralPath $ProfileRoot).Path
    user_data_dir = (Resolve-Path -LiteralPath $userData).Path
    edge_executable = $edge
    launch_nonce = $launchNonce
    headless_flag = $headlessFlag
    command_line_attested = $commandLineAttested
    endpoint_attested = $endpointAttested
    target_id = if ($null -ne $target) { $target.id } else { $null }
    target_ids = @($targetCandidates | ForEach-Object { $_.id })
    browser = if ($null -ne $version) { try { ($version.Content | ConvertFrom-Json).Browser } catch { $null } } else { $null }
    created_at_utc = [DateTime]::UtcNow.ToString('o')
}
$temporaryManifest = "$manifestPath.$([guid]::NewGuid().ToString('N')).tmp"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporaryManifest -Encoding UTF8
Move-Item -LiteralPath $temporaryManifest -Destination $manifestPath -Force

[ordered]@{
    pid = $process.Id
    port = $Port
    profile_root = $ProfileRoot
    version_endpoint = ($null -ne $version)
    page_endpoint = ($null -ne $pages)
    page_count = $pageObjects.Count
    manifest = $manifestPath
    endpoint_attested = $endpointAttested
    stderr_bytes = if (Test-Path -LiteralPath $stderrPath) { (Get-Item -LiteralPath $stderrPath).Length } else { 0 }
} | ConvertTo-Json -Compress

$ErrorActionPreference = 'Stop'
$evidenceRoot = 'C:\AX\cost\docs\handoff\2026-10-01'
$candidate = Join-Path $evidenceRoot 'startup-plan-candidate\start_web_ledger_host.ps1'
$arguments = @{
    Mode = 'Plan'
    Checkout = 'C:\AX\cost'
    LauncherPath = 'D:\WebLedgerHost\bin\launch_web_ledger.py'
    DataRoot = 'D:\WebLedgerHost\data'
    ReviewConfig = 'D:\WebLedgerHost\config\real-review.json'
    OAuthFile = 'D:\WebLedgerHost\secrets\google-oauth-pc-client.json'
    SessionSecretFile = 'D:\WebLedgerHost\secrets\session-secret.txt'
    Python = 'D:\WebLedgerHost\venv\Scripts\python.exe'
    CloudflareExe = 'D:\WebLedgerHost\bin\cloudflared.exe'
    CloudflareConfigPath = 'D:\WebLedgerHost\config\candidate.yml'
    TunnelId = '8259194a-39d3-45c2-8b95-c656ce02f3fb'
}
Start-Transcript -Path (Join-Path $evidenceRoot 'startup-administrator-plan.log') -Force
try {
    & $candidate @arguments
} finally {
    Stop-Transcript
}

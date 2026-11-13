# 카드 로그인 시도 가드 해제(사용자가 명시적으로 실행).
# 실패·잠금 경고·추가 인증 대기로 멈춘 사이트를 다시 시도 가능하게 한다.
# 사용법: powershell -NoProfile -ExecutionPolicy Bypass -File tools/card_login/reset_attempt.ps1 -Issuer kb
# 비밀 값을 다루지 않는다(결과 코드·시각만 있는 상태 파일에서 해당 사이트 기록을 지운다).
param(
    [Parameter(Mandatory)][ValidateSet('kb', 'hana', 'ibk')][string]$Issuer,
    [string]$AttemptsPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($AttemptsPath)) {
    $AttemptsPath = 'D:/WebLedgerHost/data/card-login/attempts.json'
}

if (-not (Test-Path -LiteralPath $AttemptsPath)) {
    Write-Host ("해제할 기록이 없습니다: {0} (이미 시도 가능)" -f $Issuer)
    return
}

$store = Get-Content -LiteralPath $AttemptsPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($store.schema -ne 'cost.card-login-attempts.v1') {
    throw 'ATTEMPTS_SCHEMA_MISMATCH'
}

$existed = $false
if ($store.issuers -and ($store.issuers.PSObject.Properties.Name -contains $Issuer)) {
    $store.issuers.PSObject.Properties.Remove($Issuer)
    $existed = $true
}

$json = $store | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText($AttemptsPath, $json, (New-Object Text.UTF8Encoding($false)))

if ($existed) {
    Write-Host ("해제 완료: {0} — 다음 실행에서 로그인을 다시 시도합니다." -f $Issuer)
}
else {
    Write-Host ("해제할 기록이 없습니다: {0} (이미 시도 가능)" -f $Issuer)
}

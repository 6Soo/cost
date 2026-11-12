# 합성 자격 증명 등록·왕복·평문 유출 검사. 비밀이 아닌 불리언 결과만 JSON 으로 출력한다.
# 사용: powershell -NoProfile -ExecutionPolicy Bypass -File tests/card_login/credential_check.ps1 -StoreRoot <temp>
# 합성 값은 실제 비밀이 아닌 테스트 픽스처이며 이 파일 안에만 존재한다.
param([Parameter(Mandatory)][string]$StoreRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '../../tools/card_login/CardLoginSecrets.psm1') -Force

$expId = 'synthetic-id-123'
$expPw = 'synthetic-pw-456'
$expCert = 'synthetic-cert-789'

function ToSecure([string]$s) {
    $ss = New-Object SecureString
    foreach ($ch in $s.ToCharArray()) { $ss.AppendChar($ch) }
    $ss.MakeReadOnly()
    return $ss
}
function FromSecure([SecureString]$ss) {
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($ss)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

$path = Register-CardLoginCredential -Issuer 'kb' -Id (ToSecure $expId) -Password (ToSecure $expPw) -CertPassword (ToSecure $expCert) -StoreRoot $StoreRoot
$read = Read-CardLoginCredential -Issuer 'kb' -StoreRoot $StoreRoot
$idMatch = (FromSecure $read.Id) -ceq $expId
$pwMatch = (FromSecure $read.Password) -ceq $expPw
$certMatch = (FromSecure $read.CertPassword) -ceq $expCert

$raw = Get-Content -LiteralPath $path -Raw -Encoding UTF8
$fileHasPlaintext = ($raw.Contains($expId) -or $raw.Contains($expPw) -or $raw.Contains($expCert))
$schemaOk = $raw.Contains('cost.card-login-credential.v1')
$registered = Test-CardLoginCredentialRegistered -Issuer 'kb' -StoreRoot $StoreRoot
$hanaRegistered = Test-CardLoginCredentialRegistered -Issuer 'hana' -StoreRoot $StoreRoot

[pscustomobject]@{
    registered        = [bool]$registered
    idMatch           = [bool]$idMatch
    pwMatch           = [bool]$pwMatch
    certMatch         = [bool]$certMatch
    fileHasPlaintext  = [bool]$fileHasPlaintext
    schemaOk          = [bool]$schemaOk
    hanaRegistered    = [bool]$hanaRegistered
} | ConvertTo-Json -Compress

# 카드 로그인 자격 증명 저장소 (DPAPI 사용자 범위 암호화).
# 평문은 이 모듈을 거치는 메모리 안에서만 다루며 파일·로그·인자·환경 변수에 남기지 않는다.
# 저장 위치 기본값: D:/WebLedgerHost/secrets/card-login/<issuer>.json
# 테스트는 -StoreRoot 로 임시 폴더를 써서 운영 저장소를 건드리지 않는다.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Security

# named pipe 클라이언트 프로세스 PID 조회(기대 PID 검증용). 비밀 값과 무관한 네이티브 호출.
if (-not ('Win32.CardLoginPipe' -as [type])) {
    Add-Type -Namespace Win32 -Name CardLoginPipe -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern bool GetNamedPipeClientProcessId(IntPtr Pipe, out uint ClientProcessId);
'@
}

$script:DefaultStoreRoot = 'D:/WebLedgerHost/secrets/card-login'
$script:Schema = 'cost.card-login-credential.v1'
$script:Issuers = @('kb', 'hana', 'ibk')

function Get-CardLoginStoreRoot {
    param([string]$StoreRoot)
    if ([string]::IsNullOrWhiteSpace($StoreRoot)) { return $script:DefaultStoreRoot }
    return $StoreRoot
}

function Get-CardLoginCredentialPath {
    param(
        [Parameter(Mandatory)][ValidateSet('kb', 'hana', 'ibk')][string]$Issuer,
        [string]$StoreRoot
    )
    $root = Get-CardLoginStoreRoot -StoreRoot $StoreRoot
    return (Join-Path $root ("$Issuer.json"))
}

function Test-CardLoginCredentialRegistered {
    param(
        [Parameter(Mandatory)][ValidateSet('kb', 'hana', 'ibk')][string]$Issuer,
        [string]$StoreRoot
    )
    return (Test-Path -LiteralPath (Get-CardLoginCredentialPath -Issuer $Issuer -StoreRoot $StoreRoot))
}

function ConvertFrom-CardSecureString {
    param([Parameter(Mandatory)][SecureString]$Secure)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Protect-CardSecret {
    param([Parameter(Mandatory)][AllowEmptyString()][SecureString]$Secure)
    $plain = ConvertFrom-CardSecureString -Secure $Secure
    $bytes = [Text.Encoding]::UTF8.GetBytes($plain)
    try {
        $enc = [Security.Cryptography.ProtectedData]::Protect($bytes, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        return [Convert]::ToBase64String($enc)
    }
    finally { [Array]::Clear($bytes, 0, $bytes.Length) }
}

function Unprotect-CardSecret {
    param([Parameter(Mandatory)][string]$Base64)
    $enc = [Convert]::FromBase64String($Base64)
    $bytes = [Security.Cryptography.ProtectedData]::Unprotect($enc, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
    try { return [Text.Encoding]::UTF8.GetString($bytes) }
    finally { [Array]::Clear($bytes, 0, $bytes.Length) }
}

function Register-CardLoginCredential {
    param(
        [Parameter(Mandatory)][ValidateSet('kb', 'hana', 'ibk')][string]$Issuer,
        [Parameter(Mandatory)][SecureString]$Id,
        [Parameter(Mandatory)][SecureString]$Password,
        [SecureString]$CertPassword,
        [string]$StoreRoot
    )
    if ($Id.Length -eq 0) { throw 'ID_EMPTY' }
    if ($Password.Length -eq 0) { throw 'PASSWORD_EMPTY' }
    $root = Get-CardLoginStoreRoot -StoreRoot $StoreRoot
    if (-not (Test-Path -LiteralPath $root)) {
        New-Item -ItemType Directory -Path $root -Force | Out-Null
    }
    $certBlob = $null
    if ($null -ne $CertPassword -and $CertPassword.Length -gt 0) {
        $certBlob = Protect-CardSecret -Secure $CertPassword
    }
    $record = [ordered]@{
        schema       = $script:Schema
        issuer       = $Issuer
        updatedAt    = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        id           = Protect-CardSecret -Secure $Id
        password     = Protect-CardSecret -Secure $Password
        certPassword = $certBlob
    }
    $path = Get-CardLoginCredentialPath -Issuer $Issuer -StoreRoot $StoreRoot
    $json = $record | ConvertTo-Json -Depth 4
    # 기존 파일 덮어쓰기(교체)는 허용하되 평문은 어디에도 쓰지 않는다.
    [IO.File]::WriteAllText($path, $json, (New-Object Text.UTF8Encoding($false)))
    return $path
}

function Read-CardLoginCredential {
    param(
        [Parameter(Mandatory)][ValidateSet('kb', 'hana', 'ibk')][string]$Issuer,
        [string]$StoreRoot
    )
    $path = Get-CardLoginCredentialPath -Issuer $Issuer -StoreRoot $StoreRoot
    if (-not (Test-Path -LiteralPath $path)) { throw 'CARD_LOGIN_NOT_REGISTERED' }
    $record = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($record.schema -ne $script:Schema) { throw 'CARD_LOGIN_SCHEMA_MISMATCH' }
    $cert = $null
    if ($record.certPassword) {
        $certPlain = Unprotect-CardSecret -Base64 $record.certPassword
        $cert = New-Object SecureString
        foreach ($ch in $certPlain.ToCharArray()) { $cert.AppendChar($ch) }
        $cert.MakeReadOnly()
    }
    $idPlain = Unprotect-CardSecret -Base64 $record.id
    $pwPlain = Unprotect-CardSecret -Base64 $record.password
    $idSs = New-Object SecureString
    foreach ($ch in $idPlain.ToCharArray()) { $idSs.AppendChar($ch) }
    $idSs.MakeReadOnly()
    $pwSs = New-Object SecureString
    foreach ($ch in $pwPlain.ToCharArray()) { $pwSs.AppendChar($ch) }
    $pwSs.MakeReadOnly()
    return [pscustomobject]@{ Id = $idSs; Password = $pwSs; CertPassword = $cert }
}

# 일회성 named pipe 로만 평문을 전달하는 읽기 헬퍼가 쓰는 평문 조회.
# 이 함수의 반환값은 절대 로그·stdout·파일에 쓰지 않는다.
function Read-CardLoginCredentialPlain {
    param(
        [Parameter(Mandatory)][ValidateSet('kb', 'hana', 'ibk')][string]$Issuer,
        [string]$StoreRoot
    )
    $path = Get-CardLoginCredentialPath -Issuer $Issuer -StoreRoot $StoreRoot
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    $record = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($record.schema -ne $script:Schema) { throw 'CARD_LOGIN_SCHEMA_MISMATCH' }
    $cert = $null
    if ($record.certPassword) { $cert = Unprotect-CardSecret -Base64 $record.certPassword }
    return [pscustomobject]@{
        id           = Unprotect-CardSecret -Base64 $record.id
        password     = Unprotect-CardSecret -Base64 $record.password
        certPassword = $cert
    }
}

# 파이프 DACL: 현재 사용자 SID 에만 FullControl 을 허용한다.
# 다른 계정·Everyone·익명에는 허용 규칙이 없으므로 접근이 거부된다(명시적 Deny 는 현재 사용자까지
# 막을 수 있어 쓰지 않는다 — Everyone 구성원인 현재 사용자에게 허용 규칙만 남기는 방식).
function New-CardLoginPipeSecurity {
    $ps = New-Object System.IO.Pipes.PipeSecurity
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $rule = New-Object System.IO.Pipes.PipeAccessRule(
        $sid,
        [System.IO.Pipes.PipeAccessRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $ps.AddAccessRule($rule)
    return $ps
}

# 연결한 클라이언트 프로세스 PID 를 반환한다(기대 PID 와 다르면 값을 보내지 않기 위한 검증).
function Get-CardLoginPipeClientPid {
    param([Parameter(Mandatory)][IntPtr]$PipeHandle)
    [uint32]$clientPid = 0
    $ok = [Win32.CardLoginPipe]::GetNamedPipeClientProcessId($PipeHandle, [ref]$clientPid)
    if (-not $ok) { return -1 }
    return [int]$clientPid
}

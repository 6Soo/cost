# 합성 전용 named pipe 보안 회귀 검사. 비밀이 아닌 불리언 결과만 JSON 으로 출력한다.
# 사용: powershell -NoProfile -ExecutionPolicy Bypass -File tests/card_login/pipe_security_check.ps1 -StoreRoot <temp>
# 검증:
#   (1) 파이프 DACL 이 현재 사용자 SID 에만 허용을 준다(다른 계정·Everyone·익명·합성 타 사용자 SID 거부).
#   (2) 기대 PID 클라이언트는 값을 받는다(실제 파이프 연결).
#   (3) 기대하지 않은 PID 클라이언트는 값을 받지 못한다(fail closed).
# 실제 비밀·운영 저장소 접근 없음: 합성 픽스처를 임시 StoreRoot 에 등록하고 검사 후 제거한다.
param([Parameter(Mandatory)][string]$StoreRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '../../tools/card_login/CardLoginSecrets.psm1') -Force

$expId = 'synthetic-id-123'
$expPw = 'synthetic-pw-456'
$expCert = 'synthetic-cert-789'
$serverScript = Join-Path $PSScriptRoot '../../tools/card_login/read_credentials.ps1'

function ToSecure([string]$s) {
    $ss = New-Object SecureString
    foreach ($ch in $s.ToCharArray()) { $ss.AppendChar($ch) }
    $ss.MakeReadOnly()
    return $ss
}

# 합성 자격 증명 등록(임시 저장소).
Register-CardLoginCredential -Issuer 'kb' -Id (ToSecure $expId) -Password (ToSecure $expPw) -CertPassword (ToSecure $expCert) -StoreRoot $StoreRoot | Out-Null

# (1) DACL 구조 검사 — 허용 규칙의 SID 집합이 현재 사용자뿐인지.
$sec = New-CardLoginPipeSecurity
$currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$rules = $sec.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])
$allowSids = @()
foreach ($r in $rules) {
    if ($r.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow) {
        $allowSids += $r.IdentityReference.Value
    }
}
$aclOnlyCurrentUser = ($allowSids.Count -eq 1) -and ($allowSids[0] -ceq $currentSid)
$aclNoEveryone = ($allowSids -notcontains 'S-1-1-0')
$aclNoAnonymous = ($allowSids -notcontains 'S-1-5-7')
# 합성 타 사용자 SID(실제 계정 아님)에는 허용 규칙이 없어야 한다.
$otherSid = 'S-1-5-21-1111111111-2222222222-3333333333-1001'
$aclOtherUserDenied = ($allowSids -notcontains $otherSid)

# 파이프 서버를 백그라운드 잡으로 띄우고, 이 프로세스가 클라이언트로 연결해 읽는다.
function Start-PipeServer([string]$pipeName, [int]$expectedPid) {
    return Start-Job -ScriptBlock {
        param($script, $issuer, $name, $clientPid, $store)
        & $script -Issuer $issuer -PipeName $name -ClientPid $clientPid -StoreRoot $store
    } -ArgumentList $serverScript, 'kb', $pipeName, $expectedPid, $StoreRoot
}

function Read-PipeText([string]$name) {
    $client = New-Object System.IO.Pipes.NamedPipeClientStream('.', $name, [System.IO.Pipes.PipeDirection]::In)
    $sb = New-Object System.Text.StringBuilder
    try {
        $client.Connect(15000)
        $buf = New-Object byte[] 4096
        while ($true) {
            $n = $client.Read($buf, 0, $buf.Length)
            if ($n -le 0) { break }
            [void]$sb.Append([Text.Encoding]::UTF8.GetString($buf, 0, $n))
        }
    }
    catch {
        # 서버가 값을 보내지 않고 닫은 경우(거부) — 누적된 내용만 반환한다.
    }
    finally { $client.Dispose() }
    return $sb.ToString()
}

function Stop-PipeJob($job) {
    if ($null -eq $job) { return }
    try {
        Wait-Job -Job $job -Timeout 20 | Out-Null
        if ($job.State -eq 'Running') { Stop-Job -Job $job }
        Receive-Job -Job $job -ErrorAction SilentlyContinue | Out-Null
    }
    catch { /* noop */ }
    finally { Remove-Job -Job $job -Force -ErrorAction SilentlyContinue }
}

$acceptedOk = $false
$payloadMatch = $false
$unexpectedRejected = $false
$jobA = $null
$jobB = $null
try {
    # (2) 기대 PID = 이 프로세스 PID → 클라이언트(이 프로세스)가 값을 받는다.
    $pipeA = 'cost-card-sec-a-' + ([Guid]::NewGuid().ToString('N'))
    $jobA = Start-PipeServer $pipeA $PID
    $textA = Read-PipeText $pipeA
    if ($textA) {
        try {
            $obj = $textA | ConvertFrom-Json
            $acceptedOk = ($obj.status -ceq 'ok')
            $payloadMatch = ($obj.id -ceq $expId) -and ($obj.password -ceq $expPw) -and ($obj.certPassword -ceq $expCert)
        }
        catch { $acceptedOk = $false }
    }

    # (3) 기대 PID = 이 프로세스 PID + 1(틀림) → 클라이언트는 값을 받지 못한다.
    $pipeB = 'cost-card-sec-b-' + ([Guid]::NewGuid().ToString('N'))
    $jobB = Start-PipeServer $pipeB ($PID + 1)
    $textB = Read-PipeText $pipeB
    $unexpectedRejected = ($textB.Length -eq 0)
}
finally {
    Stop-PipeJob $jobA
    Stop-PipeJob $jobB
}

[pscustomobject]@{
    aclOnlyCurrentUser       = [bool]$aclOnlyCurrentUser
    aclNoEveryone            = [bool]$aclNoEveryone
    aclNoAnonymous           = [bool]$aclNoAnonymous
    aclOtherUserDenied       = [bool]$aclOtherUserDenied
    expectedPidAccepted      = [bool]$acceptedOk
    payloadMatchesRegistered = [bool]$payloadMatch
    unexpectedClientRejected = [bool]$unexpectedRejected
} | ConvertTo-Json -Compress

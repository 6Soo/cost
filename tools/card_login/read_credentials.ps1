# 자격 증명을 일회성 named pipe 로만 전달하는 읽기 헬퍼.
# 비밀 값은 명령 인자·환경 변수·stdout·stderr·디스크 평문으로 내보내지 않는다.
# 접근 제한: 파이프 DACL 은 현재 사용자 SID 만 허용(다른 계정·Everyone·익명 거부).
# 파이프 이름은 매 실행 무작위(호출자가 생성), 연결 1회 후 즉시 닫는다.
# 서버는 연결한 클라이언트 PID 가 호출자가 넘긴 기대 PID(자식/부모 프로세스)와 같은지 확인하고,
# 다르면 값을 보내지 않고 닫는다(fail closed).
param(
    [Parameter(Mandatory)][ValidateSet('kb', 'hana', 'ibk')][string]$Issuer,
    [Parameter(Mandatory)][string]$PipeName,
    [Parameter(Mandatory)][int]$ClientPid,
    [string]$StoreRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'CardLoginSecrets.psm1') -Force

# 현재 사용자 SID 만 허용하는 DACL 로 파이프를 생성한다(생성 시점에 ACL 적용, 무방비 구간 없음).
$security = New-CardLoginPipeSecurity
$pipe = New-Object System.IO.Pipes.NamedPipeServerStream(
    $PipeName,
    [System.IO.Pipes.PipeDirection]::Out,
    1,
    [System.IO.Pipes.PipeTransmissionMode]::Byte,
    [System.IO.Pipes.PipeOptions]::None,
    0,
    0,
    $security
)
try {
    $pipe.WaitForConnection()

    # 기대하지 않은 클라이언트면 값을 보내지 않는다.
    $actualPid = Get-CardLoginPipeClientPid -PipeHandle $pipe.SafePipeHandle.DangerousGetHandle()
    if ($actualPid -ne $ClientPid) {
        return
    }

    $plain = Read-CardLoginCredentialPlain -Issuer $Issuer -StoreRoot $StoreRoot
    if ($null -eq $plain) {
        $payload = '{"status":"not_registered"}'
    }
    else {
        $obj = [ordered]@{
            status       = 'ok'
            id           = $plain.id
            password     = $plain.password
            certPassword = $plain.certPassword
        }
        $payload = $obj | ConvertTo-Json -Depth 4 -Compress
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes($payload)
    $pipe.Write($bytes, 0, $bytes.Length)
    $pipe.Flush()
    $pipe.WaitForPipeDrain()
}
finally {
    if ($pipe.IsConnected) { $pipe.Disconnect() }
    $pipe.Dispose()
}

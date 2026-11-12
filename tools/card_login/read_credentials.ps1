# 자격 증명을 일회성 named pipe 로만 전달하는 읽기 헬퍼.
# 비밀 값은 명령 인자·환경 변수·stdout·stderr·디스크 평문으로 내보내지 않는다.
# 파이프 이름은 비밀이 아닌 임의 식별자이며 인자로 받는다.
# 호출자(.mjs)가 파이프 클라이언트로 접속해 JSON 한 건을 읽고 끝나면 파이프는 사라진다.
param(
    [Parameter(Mandatory)][ValidateSet('kb', 'hana', 'ibk')][string]$Issuer,
    [Parameter(Mandatory)][string]$PipeName,
    [string]$StoreRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'CardLoginSecrets.psm1') -Force

# 파이프 서버를 먼저 만들어 클라이언트 접속을 기다린다.
# 동기 파이프: WaitForConnection/Write/WaitForPipeDrain 을 동기적으로 사용한다.
# (Asynchronous 파이프에서는 WaitForPipeDrain 이 지원되지 않아 예외가 발생한다.)
$pipe = New-Object System.IO.Pipes.NamedPipeServerStream(
    $PipeName,
    [System.IO.Pipes.PipeDirection]::Out,
    1,
    [System.IO.Pipes.PipeTransmissionMode]::Byte,
    [System.IO.Pipes.PipeOptions]::None
)
try {
    $pipe.WaitForConnection()
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

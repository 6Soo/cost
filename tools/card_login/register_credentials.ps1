# 카드 로그인 자격 증명 등록 (사용자가 직접 1회 실행).
# 사용법:  powershell -NoProfile -ExecutionPolicy Bypass -File tools/card_login/register_credentials.ps1 -Issuer kb
# 입력은 Read-Host -AsSecureString 으로 받으며 화면에 표시되지 않는다.
# 비밀 값은 명령 인자·환경 변수·로그·채팅에 남기지 않는다. DPAPI 사용자 범위로 암호화해 저장한다.
param(
    [Parameter(Mandatory)][ValidateSet('kb', 'hana', 'ibk')][string]$Issuer,
    [string]$StoreRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'CardLoginSecrets.psm1') -Force

$labels = @{ kb = '국민 기업카드'; hana = '하나카드'; ibk = 'IBK 기업은행 카드' }
Write-Host ("[{0}] 자격 증명 등록. 입력값은 화면에 표시되지 않습니다." -f $labels[$Issuer])

$id = Read-Host -AsSecureString '아이디'
$pw = Read-Host -AsSecureString '비밀번호'
$cert = Read-Host -AsSecureString '인증서 비밀번호 (없으면 그냥 Enter)'

$params = @{ Issuer = $Issuer; Id = $id; Password = $pw; CertPassword = $cert }
if ($StoreRoot) { $params.StoreRoot = $StoreRoot }
$path = Register-CardLoginCredential @params

Write-Host ("등록 완료: {0}" -f $Issuer)
Write-Host ("저장 위치(암호화 파일): {0}" -f $path)
Write-Host '비밀번호·인증서 비밀번호는 암호화되어 저장되며 화면·로그에 표시되지 않았습니다.'

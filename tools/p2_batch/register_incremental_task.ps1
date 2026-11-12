[CmdletBinding(SupportsShouldProcess=$true)]
param(
    [Parameter(Mandatory=$true)][string]$Checkout,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$ApiConfig,
    [string]$TaskName = 'WebLedger-P2-Incremental',
    [string]$At = '23:30'
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath $Checkout).Path
$pythonExe = (Resolve-Path -LiteralPath $Python).Path
$configFile = (Resolve-Path -LiteralPath $ApiConfig).Path
if (-not (Test-Path -LiteralPath (Join-Path $repo 'tools/p2_batch/run_incremental.py'))) { throw 'INCREMENTAL_CHECKOUT_REQUIRED' }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw 'TASK_ALREADY_EXISTS' }
# Interactive identity uses the existing Codex subscription and ego login.
# Do not store a password or change any existing Worker task.
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonExe -WorkingDirectory $repo -Argument (
    '-m tools.p2_batch.run_incremental --api-config "' + $configFile + '" --max-merchants 30 --max-calls 1')
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
if ($PSCmdlet.ShouldProcess($TaskName, 'Register daily incremental P2 task')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings
}

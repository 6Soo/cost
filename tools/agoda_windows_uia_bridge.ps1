param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('state', 'click', 'select', 'hotkey', 'type', 'press')]
    [string]$Operation,

    [Parameter(Mandatory = $true)]
    [long]$WindowId,

    [int]$ElementIndex = -1,
    [string]$Text = '',
    [string]$Key = '',
    [string]$ExpectedNameSha256 = '',
    [switch]$ContentOnly
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;

public static class AgodaNativeWindow {
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr processId);

    [DllImport("kernel32.dll")]
    public static extern uint GetCurrentThreadId();

    [DllImport("user32.dll")]
    public static extern bool AttachThreadInput(uint sourceThreadId, uint targetThreadId, bool attach);

    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr SetActiveWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr SetFocus(IntPtr hWnd);
}
'@

function Focus-AgodaWindow([intptr]$WindowHandle) {
    if ($WindowHandle -eq [intptr]::Zero) { return $false }
    $foreground = [AgodaNativeWindow]::GetForegroundWindow()
    $currentThread = [AgodaNativeWindow]::GetCurrentThreadId()
    $foregroundThread = [AgodaNativeWindow]::GetWindowThreadProcessId($foreground, [intptr]::Zero)
    $targetThread = [AgodaNativeWindow]::GetWindowThreadProcessId($WindowHandle, [intptr]::Zero)
    $foregroundAttached = $false
    $targetAttached = $false
    try {
        if ($foregroundThread -ne 0 -and $foregroundThread -ne $currentThread) {
            $foregroundAttached = [AgodaNativeWindow]::AttachThreadInput($currentThread, $foregroundThread, $true)
        }
        if ($targetThread -ne 0 -and $targetThread -ne $currentThread) {
            $targetAttached = [AgodaNativeWindow]::AttachThreadInput($currentThread, $targetThread, $true)
        }
        [AgodaNativeWindow]::ShowWindowAsync($WindowHandle, 9) | Out-Null
        [AgodaNativeWindow]::BringWindowToTop($WindowHandle) | Out-Null
        [AgodaNativeWindow]::SetForegroundWindow($WindowHandle) | Out-Null
        [AgodaNativeWindow]::SetActiveWindow($WindowHandle) | Out-Null
        [AgodaNativeWindow]::SetFocus($WindowHandle) | Out-Null
        Start-Sleep -Milliseconds 80
        return [AgodaNativeWindow]::GetForegroundWindow() -eq $WindowHandle
    }
    finally {
        if ($targetAttached) {
            [AgodaNativeWindow]::AttachThreadInput($currentThread, $targetThread, $false) | Out-Null
        }
        if ($foregroundAttached) {
            [AgodaNativeWindow]::AttachThreadInput($currentThread, $foregroundThread, $false) | Out-Null
        }
    }
}

function Get-UnicodeString([int[]]$CodePoints) {
    return -join ($CodePoints | ForEach-Object { [char]$_ })
}

$RoleButton = Get-UnicodeString @(0xB2E8, 0xCD94)
$RoleTabItem = (Get-UnicodeString @(0xD0ED)) + ' ' + (Get-UnicodeString @(0xD56D, 0xBAA9))
$RoleGroup = Get-UnicodeString @(0xADF8, 0xB8F9)
$RoleText = Get-UnicodeString @(0xD14D, 0xC2A4, 0xD2B8)
$RoleLink = Get-UnicodeString @(0xB9C1, 0xD06C)
$RoleEdit = $RoleText + ' ' + (Get-UnicodeString @(0xD544, 0xB4DC))
$RolePane = Get-UnicodeString @(0xCC3D)
$RoleDocument = Get-UnicodeString @(0xBB38, 0xC11C)
$RoleList = Get-UnicodeString @(0xBAA9, 0xB85D)
$RoleListItem = $RoleList + ' ' + (Get-UnicodeString @(0xD56D, 0xBAA9))
$RoleImage = Get-UnicodeString @(0xC774, 0xBBF8, 0xC9C0)
$RoleDefault = Get-UnicodeString @(0xAE30, 0xBCF8)

function Write-Result([hashtable]$Value) {
    $Value | ConvertTo-Json -Compress -Depth 8
}

function Get-NormalizedName(
    [System.Windows.Automation.AutomationElement]$Element
) {
    return ($Element.Current.Name -replace '[\r\n]+', ' ' -replace '\s+', ' ').Trim()
}

function Get-TextSha256([string]$Value) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($Value)
        return -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') })
    } finally {
        $sha.Dispose()
    }
}

function Test-Actionable(
    [System.Windows.Automation.AutomationElement]$Element,
    [string]$Mode
) {
    if (-not $Element.Current.IsEnabled) {
        return $false
    }
    $pattern = $null
    if ($Element.TryGetCurrentPattern(
        [System.Windows.Automation.SelectionItemPattern]::Pattern,
        [ref]$pattern
    )) {
        return $true
    }
    if ($Mode -eq 'click' -and $Element.TryGetCurrentPattern(
        [System.Windows.Automation.InvokePattern]::Pattern,
        [ref]$pattern
    )) {
        return $true
    }
    return $false
}

function Get-Omnibox([System.Windows.Automation.AutomationElement]$Root) {
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit
    )
    $matches = @(
        $Root.FindAll(
            [System.Windows.Automation.TreeScope]::Descendants,
            $condition
        ) | Where-Object { $_.Current.ClassName -eq 'OmniboxViewViews' }
    )
    if ($matches.Count -ne 1) {
        throw 'browser_omnibox_missing_or_ambiguous'
    }
    return $matches[0]
}

function Get-ContentRoot([System.Windows.Automation.AutomationElement]$Root) {
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
        'RootWebArea'
    )
    $matches = @(
        $Root.FindAll(
            [System.Windows.Automation.TreeScope]::Descendants,
            $condition
        ) | Where-Object { -not $_.Current.IsOffscreen }
    )
    if ($matches.Count -ne 1) {
        throw 'browser_content_root_missing_or_ambiguous'
    }
    return $matches[0]
}

function Get-Role([System.Windows.Automation.AutomationElement]$Element) {
    $kind = $Element.Current.ControlType.ProgrammaticName
    switch ($kind) {
        'ControlType.Button' { return $RoleButton }
        'ControlType.TabItem' { return $RoleTabItem }
        'ControlType.Group' { return $RoleGroup }
        'ControlType.Text' { return $RoleText }
        'ControlType.Hyperlink' { return $RoleLink }
        'ControlType.Edit' { return $RoleEdit }
        'ControlType.Pane' { return $RolePane }
        'ControlType.Document' { return $RoleDocument }
        'ControlType.List' { return $RoleList }
        'ControlType.ListItem' { return $RoleListItem }
        'ControlType.Image' { return $RoleImage }
        default { return $RoleDefault }
    }
}

function Get-TreeData([System.Windows.Automation.AutomationElement]$Root) {
    $walker = [System.Windows.Automation.TreeWalker]::RawViewWalker
    $script:bridgeNodes = [System.Collections.Generic.List[object]]::new()
    $script:bridgeLines = [System.Collections.Generic.List[string]]::new()
    $script:bridgeCounter = 0

    function Visit(
        [System.Windows.Automation.AutomationElement]$Parent,
        [int]$Depth
    ) {
        $child = $walker.GetFirstChild($Parent)
        while ($null -ne $child) {
            $index = $script:bridgeCounter
            $script:bridgeCounter += 1
            $script:bridgeNodes.Add($child)
            $name = Get-NormalizedName $child
            $automationId = ($child.Current.AutomationId -replace '[\r\n]+', ' ').Trim()
            if ($automationId.StartsWith('mmb-booking-card--')) {
                $name = $automationId
            }
            if ($name.Length -gt 0) {
                $indent = '  ' * $Depth
                $role = Get-Role $child
                $script:bridgeLines.Add("$indent$index $role $name")
                if (
                    $child.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
                    $name -match '^\d+$' -and
                    -not $child.Current.IsEnabled
                ) {
                    $script:bridgeLines.Add("$indent$index $RoleDefault $name")
                }
                if ($child.Current.ControlType -eq [System.Windows.Automation.ControlType]::TabItem) {
                    $selection = $null
                    if ($child.TryGetCurrentPattern(
                        [System.Windows.Automation.SelectionItemPattern]::Pattern,
                        [ref]$selection
                    ) -and $selection.Current.IsSelected) {
                        $script:bridgeLines.Add("$indent$index $RoleDefault $name")
                    }
                }
            }
            Visit $child ($Depth + 1)
            $child = $walker.GetNextSibling($child)
        }
    }

    Visit $Root 0
    return @{
        Nodes = $script:bridgeNodes
        TreeText = ($script:bridgeLines -join "`n")
    }
}

$AllowlistedErrors = @(
    'window_not_found',
    'browser_omnibox_missing_or_ambiguous',
    'browser_content_root_missing_or_ambiguous',
    'semantic_action_target_missing_or_ambiguous',
    'element_not_found',
    'element_not_selectable',
    'window_not_focused',
    'browser_omnibox_not_focused',
    'unsupported_hotkey',
    'unsupported_key',
    'focused_value_receiver_missing'
)

try {
    $root = [System.Windows.Automation.AutomationElement]::FromHandle([intptr]$WindowId)
    if ($null -eq $root) {
        throw 'window_not_found'
    }
    $treeRoot = if ($ContentOnly) { Get-ContentRoot $root } else { $root }

    if ($Operation -eq 'state') {
        $tree = Get-TreeData $treeRoot
        Write-Result @{
            ok = $true
            result = @{ snapshot = @{ treeText = $tree.TreeText } }
        }
        exit 0
    }

    if ($Operation -in @('click', 'select')) {
        $tree = Get-TreeData $treeRoot
        if ($ExpectedNameSha256.Length -gt 0) {
            if ($ElementIndex -lt 0 -or $ElementIndex -ge $tree.Nodes.Count) {
                throw 'element_not_found'
            }
            $element = $tree.Nodes[$ElementIndex]
            $nameMatches = (Get-TextSha256 (Get-NormalizedName $element)) -eq $ExpectedNameSha256
            if (-not $nameMatches -or -not (Test-Actionable $element $Operation)) {
                throw 'semantic_action_target_missing_or_ambiguous'
            }
        } else {
            if ($ElementIndex -lt 0 -or $ElementIndex -ge $tree.Nodes.Count) {
                throw 'element_not_found'
            }
            $element = $tree.Nodes[$ElementIndex]
        }
        $pattern = $null
        if ($element.TryGetCurrentPattern(
            [System.Windows.Automation.SelectionItemPattern]::Pattern,
            [ref]$pattern
        )) {
            $pattern.Select()
        } elseif ($Operation -eq 'click' -and $element.TryGetCurrentPattern(
            [System.Windows.Automation.InvokePattern]::Pattern,
            [ref]$pattern
        )) {
            $pattern.Invoke()
        } else {
            throw 'element_not_selectable'
        }
        Write-Result @{ ok = $true; result = @{ action = $Operation } }
        exit 0
    }

    $windowHandle = [intptr]$WindowId
    if (-not (Focus-AgodaWindow $windowHandle)) {
        throw 'window_not_focused'
    }
    if ($Operation -eq 'hotkey') {
        switch ($Key) {
            'CmdOrCtrl+L' {
                $omnibox = Get-Omnibox $root
                $omnibox.SetFocus()
                Start-Sleep -Milliseconds 40
                $focused = [System.Windows.Automation.AutomationElement]::FocusedElement
                if ($null -eq $focused -or $focused.Current.ClassName -ne 'OmniboxViewViews') {
                    throw 'browser_omnibox_not_focused'
                }
            }
            'CmdOrCtrl+R' { [System.Windows.Forms.SendKeys]::SendWait('^r') }
            'Alt+Left' { [System.Windows.Forms.SendKeys]::SendWait('%{LEFT}') }
            default { throw 'unsupported_hotkey' }
        }
    } elseif ($Operation -eq 'press') {
        switch ($Key) {
            'Return' { [System.Windows.Forms.SendKeys]::SendWait('{ENTER}') }
            'Escape' { [System.Windows.Forms.SendKeys]::SendWait('{ESC}') }
            default { throw 'unsupported_key' }
        }
    } elseif ($Operation -eq 'type') {
        $focused = Get-Omnibox $root
        $valuePattern = $null
        if ($focused.TryGetCurrentPattern(
            [System.Windows.Automation.ValuePattern]::Pattern,
            [ref]$valuePattern
        )) {
            $valuePattern.SetValue($Text)
        } else {
            throw 'focused_value_receiver_missing'
        }
    }
    Write-Result @{ ok = $true; result = @{ action = $Operation } }
} catch {
    $code = 'bridge_execution_failed'
    if ($_.Exception -and ($_.Exception.Message -in $AllowlistedErrors)) {
        $code = $_.Exception.Message
    }
    Write-Result @{ ok = $false; error = @{ code = $code } }
    exit 1
}

<#
.SYNOPSIS
    One-time setup so a Windows laptop treats DOE as the default for new folders.

.DESCRIPTION
    Installs three things under %USERPROFILE%\.claude\:

      bin\doe.ps1        the `doe` command (create / init / update)
      doe-guard.ps1      a SessionStart hook that notices a non-DOE folder
      CLAUDE.md          the DOE rule, laptop-scoped

    ...adds a `doe` function to your PowerShell profile, and registers the hook
    in settings.json.

    Everything is additive and re-runnable. Your existing settings.json keys,
    hooks and profile contents are preserved; a timestamped backup is written
    before either file is touched.

.EXAMPLE
    .\Install-DOE.ps1
#>
[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = 'Stop'

$ClaudeDir = Join-Path $env:USERPROFILE '.claude'
$BinDir    = Join-Path $ClaudeDir 'bin'
$CmdDir    = Join-Path $ClaudeDir 'commands'
$Here      = Split-Path -Parent $MyInvocation.MyCommand.Path

function Backup([string]$path) {
    if (Test-Path $path) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        Copy-Item $path "$path.bak-$stamp"
        Write-Host "  backed up $(Split-Path -Leaf $path) -> .bak-$stamp"
    }
}

Write-Host "==> Installing DOE for this laptop" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
New-Item -ItemType Directory -Force -Path $CmdDir | Out-Null

# --- 1. the command, the hook, and the /doe slash command -------------------
Copy-Item (Join-Path $Here 'doe.ps1')       (Join-Path $BinDir 'doe.ps1')          -Force
Copy-Item (Join-Path $Here 'doe-guard.ps1') (Join-Path $ClaudeDir 'doe-guard.ps1') -Force
Copy-Item (Join-Path $Here 'doe-command.md') (Join-Path $CmdDir 'doe.md')          -Force
Write-Host "  installed doe.ps1, doe-guard.ps1, and the /doe slash command"

# --- 2. the `doe` function in the PowerShell profile ------------------------
$marker   = '# --- DOE workspace command (managed by Install-DOE.ps1) ---'
$snippet  = @"
$marker
function doe { & "$BinDir\doe.ps1" @args }
"@
if (-not (Test-Path $PROFILE)) {
    New-Item -ItemType File -Force -Path $PROFILE | Out-Null
}
$profileText = Get-Content $PROFILE -Raw -ErrorAction SilentlyContinue
if ($profileText -and $profileText.Contains($marker)) {
    Write-Host "  profile already has the doe function"
}
else {
    Backup $PROFILE
    Add-Content $PROFILE "`n$snippet`n"
    Write-Host '  added the doe function to your PowerShell profile'
}

# --- 3. the laptop-scoped DOE rule -----------------------------------------
$claudeMd = Join-Path $ClaudeDir 'CLAUDE.md'
$rule = @"
# Laptop rules (Claude Code running locally on this machine)

## Every new workspace uses the DOE framework (HARD RULE)

When standing up a folder for a new job or project, **never bare ``mkdir`` +
``git init``**. Every workspace is created from the DOE template —
**D**irectives / **O**rchestration / **E**xecution:

``````powershell
doe "<Name>"    # create a new workspace here
doe init        # convert the folder you are already in (additive, refuses to merge)
doe update      # pull the latest template
``````

The template lives at ``%USERPROFILE%\.doe-template`` and is a clone of
``trifactorscalingllc/doe-template``. A workspace's *mission* goes in a
directive (``directives/<slug>.md``), NOT in CLAUDE.md — CLAUDE.md/AGENTS.md/
GEMINI.md are the mirrored DOE operating instructions and stay as the template
ships them.

A SessionStart hook notices when a folder is not a DOE workspace and says so.
It never creates anything. Offer ``doe init``; if the user declines, drop a
``.no-doe`` file to silence that folder for good.

**This machine is not the mini.** Webhook receivers are launchd and stay on the
mini. Everything else — directives, execution scripts, headless runs — works
here.
"@
if ((Test-Path $claudeMd) -and -not $Force) {
    $existing = Get-Content $claudeMd -Raw
    if ($existing -notmatch 'DOE framework') {
        Backup $claudeMd
        Add-Content $claudeMd "`n$rule`n"
        Write-Host "  appended the DOE rule to your existing CLAUDE.md"
    }
    else {
        Write-Host "  CLAUDE.md already states the DOE rule"
    }
}
else {
    Backup $claudeMd
    Set-Content $claudeMd $rule -Encoding UTF8
    Write-Host "  wrote CLAUDE.md"
}

# --- 4. register the SessionStart hook -------------------------------------
$settingsPath = Join-Path $ClaudeDir 'settings.json'
$settings = if (Test-Path $settingsPath) {
    Get-Content $settingsPath -Raw | ConvertFrom-Json
} else {
    [pscustomobject]@{}
}

$guardCmd = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$ClaudeDir\doe-guard.ps1`""
$json = $settings | ConvertTo-Json -Depth 20
if ($json -match 'doe-guard') {
    Write-Host "  SessionStart hook already registered"
}
else {
    Backup $settingsPath
    # Rebuild through a hashtable: ConvertFrom-Json gives PSCustomObjects, which
    # are awkward to extend in place across PowerShell versions.
    $h = @{}
    foreach ($p in $settings.PSObject.Properties) { $h[$p.Name] = $p.Value }
    $hooks = @{}
    if ($h.ContainsKey('hooks')) {
        foreach ($p in $h['hooks'].PSObject.Properties) { $hooks[$p.Name] = $p.Value }
    }
    $entry = @{ type = 'command'; command = $guardCmd; timeout = 10; statusMessage = 'Checking workspace shape' }
    $existingStarts = @()
    if ($hooks.ContainsKey('SessionStart')) { $existingStarts = @($hooks['SessionStart']) }
    $hooks['SessionStart'] = $existingStarts + @(@{ hooks = @($entry) })
    $h['hooks'] = $hooks
    ($h | ConvertTo-Json -Depth 20) | Set-Content $settingsPath -Encoding UTF8
    Write-Host "  registered the SessionStart hook"
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Open a NEW terminal, then try:  doe" -ForegroundColor Green
Write-Host "A new Claude Code session in a bare folder will now offer to convert it."

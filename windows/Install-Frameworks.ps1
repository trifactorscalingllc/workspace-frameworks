<#
.SYNOPSIS
    One-time setup so a Windows laptop applies a framework to new folders.

.DESCRIPTION
    Installs three things under %USERPROFILE%\.claude\:

      bin\frame.ps1        the `frame` command (apply / create / update)
      bin\doe.ps1          a shim so the old `doe` name keeps working
      framework-guard.ps1  a SessionStart hook that notices an unframed folder
      commands\*.md        the /doe, /iae and /frameworks slash commands
      CLAUDE.md            the framework rule, laptop-scoped

    ...adds `frame` and `doe` functions to your PowerShell profile, and registers
    the hook in settings.json.

    Everything is additive and re-runnable. Your existing settings.json keys,
    hooks and profile contents are preserved; a timestamped backup is written
    before either file is touched.

.EXAMPLE
    .\Install-Frameworks.ps1
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

Write-Host "==> Installing workspace frameworks for this laptop" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
New-Item -ItemType Directory -Force -Path $CmdDir | Out-Null

# --- 1. the command, the hook, and the /doe slash command -------------------
Copy-Item (Join-Path $Here 'frame.ps1')           (Join-Path $BinDir 'frame.ps1')              -Force
Copy-Item (Join-Path $Here 'framework-guard.ps1') (Join-Path $ClaudeDir 'framework-guard.ps1') -Force
# A shim, not a copy: the old name keeps working and there is only one script to
# maintain. Anything already pointing at bin\doe.ps1 keeps resolving.
Set-Content (Join-Path $BinDir 'doe.ps1') @"
# Alias shim — `doe` is the old name for `frame`. Kept so existing setups and
# muscle memory keep working. Edit frame.ps1, never this file.
& "`$PSScriptRoot\frame.ps1" @args
"@ -Encoding UTF8
$slashCount = 0
foreach ($cmd in (Get-ChildItem (Join-Path $Here '*-command.md') -ErrorAction SilentlyContinue)) {
    $slug = $cmd.Name -replace '-command\.md$', ''
    Copy-Item $cmd.FullName (Join-Path $CmdDir "$slug.md") -Force
    $slashCount++
}
Write-Host "  installed frame.ps1 (+doe shim), framework-guard.ps1, and $slashCount slash command(s)"

# --- 2. the `doe` function in the PowerShell profile ------------------------
$marker   = '# --- workspace framework commands (managed by Install-Frameworks.ps1) ---'
$snippet  = @"
$marker
function frame { & "$BinDir\frame.ps1" @args }
function doe   { & "$BinDir\frame.ps1" @args }   # old name, still works
"@
if (-not (Test-Path $PROFILE)) {
    New-Item -ItemType File -Force -Path $PROFILE | Out-Null
}
$profileText = Get-Content $PROFILE -Raw -ErrorAction SilentlyContinue
if ($profileText -and $profileText.Contains($marker)) {
    Write-Host "  profile already has the frame/doe functions"
}
else {
    Backup $PROFILE
    Add-Content $PROFILE "`n$snippet`n"
    Write-Host '  added the frame and doe functions to your PowerShell profile'
}

# --- 3. the laptop-scoped DOE rule -----------------------------------------
$claudeMd = Join-Path $ClaudeDir 'CLAUDE.md'
$rule = @"
# Laptop rules (Claude Code running locally on this machine)

## Every new workspace gets a framework (HARD RULE)

When standing up a folder for a new job or project, **never bare ``mkdir`` +
``git init``**. Pick a framework and apply it. They are peers — none of them
owns the others:

| Framework | Structures | Use when |
|---|---|---|
| **DOE** | **Work** | Automations, scripts, anything with steps to run |
| **IAE** | **Thinking** | Reading sources and reaching a defensible conclusion |

In Claude, in the folder you are in:

``````
/doe          apply DOE here
/iae          apply IAE here
/frameworks   list them and pick
``````

Or from a terminal: ``frame doe`` / ``frame iae`` / ``frame list``. (``doe`` is an
old alias for ``frame`` and still works.) ``frame "<Name>"`` creates a NEW workspace
folder; ``frame update`` refreshes the registry and the installed files.

The registry lives at ``%USERPROFILE%\.frameworks``, a clone of
``trifactorscalingllc/workspace-frameworks``. Applying a framework is **additive** —
it never overwrites, moves or deletes, and it refuses outright rather than merging
into a directory you already own.

A workspace's *mission* goes in that framework's own layer — a directive
(``directives/<slug>.md``) for DOE — NOT in CLAUDE.md. The CLAUDE.md/AGENTS.md/
GEMINI.md trio is the mirrored operating instructions and stays as shipped. If a
folder already had a CLAUDE.md, a second framework's rules land in ``<NAME>.md``.

A SessionStart hook notices when a folder has no framework and says so. It never
creates anything. Offer the one that fits; if the user declines, drop a
``.no-doe`` file to silence that folder for good.

**This machine is not the mini.** Webhook receivers are launchd and stay there.
Everything else works here.
"@
if ((Test-Path $claudeMd) -and -not $Force) {
    $existing = Get-Content $claudeMd -Raw
    if ($existing -notmatch 'gets a framework') {
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

$guardCmd = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$ClaudeDir\framework-guard.ps1`""
$json = $settings | ConvertTo-Json -Depth 20
if ($json -match 'doe-guard|framework-guard') {
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
Write-Host "Open a NEW terminal, then try:  frame list" -ForegroundColor Green
Write-Host "In Claude, /doe and /iae apply a framework to the folder you are in."
Write-Host "A new session in an unframed folder will offer one on its own."

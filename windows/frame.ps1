<#
.SYNOPSIS
    Apply a workspace framework, or create a new workspace, on Windows.

.DESCRIPTION
    The rule is that project folders come from a framework, never from a bare
    mkdir. On the mini that is `newws`; this is the same thing for a laptop
    running Claude Code locally rather than over Remote-SSH.

    Frameworks are peers — DOE structures work, IAE structures research — and
    none of them owns this command. It keeps a local checkout of the registry at
    %USERPROFILE%\.frameworks and drives the registry's own Python scripts, so
    behaviour matches the mini exactly rather than drifting as a second
    implementation.

    `doe` remains an alias for this command so nothing already installed breaks.

.EXAMPLE
    frame                    # apply the default framework here
    frame iae                # apply the IAE research framework here
    frame list               # every available framework
    frame "Acme Onboarding"  # new workspace in the current directory
    frame update             # refresh the registry and the installed files
    frame syntax off         # the machine-wide Plain English reply style: status|on|off
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Name,
    [Parameter(Position = 1)][string]$Arg,
    [Parameter(Position = 2)][string]$Arg2,
    [string]$Dest = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'

$TemplateRepo = 'https://github.com/trifactorscalingllc/workspace-frameworks.git'
$TemplateDir  = Join-Path $env:USERPROFILE '.frameworks'
# Reuse a clone made under the old name rather than downloading a second copy.
# GitHub redirects the old URL, so the existing checkout still pulls fine.
$LegacyDir = Join-Path $env:USERPROFILE '.doe-template'
if ((Test-Path (Join-Path $LegacyDir '.git')) -and -not (Test-Path $TemplateDir)) {
    Move-Item $LegacyDir $TemplateDir
    git -C $TemplateDir remote set-url origin $TemplateRepo 2>&1 | Out-Null
    Write-Host "  moved .doe-template -> .frameworks (same clone, new name)" -ForegroundColor Yellow
}

function Get-Python {
    # The py launcher is the reliable way to pick a version on Windows; bare
    # `python` is often the Store alias stub that just opens the Microsoft Store.
    # Exe and prefix args are kept as separate fields deliberately: deriving the
    # prefix with a range like $c[1..($c.Length-1)] is wrong for a one-element
    # array, because PowerShell counts 1..0 DOWNWARD and yields @(1,0).
    $candidates = @(
        @{ Exe = 'py';      Pre = @('-3') },
        @{ Exe = 'python';  Pre = @() },
        @{ Exe = 'python3'; Pre = @() }
    )
    # Windows PowerShell 5.1 turns ANY native command's stderr into a throwing
    # NativeCommandError while ErrorActionPreference is Stop, and a version
    # probe legitimately writes there. Local to this function only.
    $ErrorActionPreference = 'Continue'
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        # `--version`, not `-c "..."`: PowerShell strips embedded double quotes
        # when building a native command line, so a -c snippet containing them
        # reaches Python mangled and dies with a SyntaxError.
        # Assignment-from-try is not dependable on Windows PowerShell 5.1, and
        # [regex]::Match beats Select-String's MatchInfo indirection here.
        $raw = $null
        try { $raw = & $c.Exe @($c.Pre + @('--version')) 2>&1 } catch { }
        if (-not $raw) { continue }
        $m = [regex]::Match(($raw | Out-String), '(\d+)\.(\d+)')
        if (-not $m.Success) { continue }
        $major = [int]$m.Groups[1].Value
        $minor = [int]$m.Groups[2].Value
        # The registry's code uses `X | None` unions, so anything below 3.10
        # dies at import with a confusing TypeError rather than a clear message.
        if ($major -eq 3 -and $minor -ge 10) { return $c }
        Write-Host "  found Python $major.$minor, but frameworks need 3.10+" -ForegroundColor Yellow
    }
    throw "No Python 3.10+ found. Install it from https://python.org (tick 'Add python.exe to PATH'), then reopen this terminal."
}

function Invoke-Python {
    param([string[]]$Arguments)
    $py = Get-Python
    $full = $py.Pre + $Arguments
    # init_here.py prints refusals to stderr, and under PS 5.1 with
    # ErrorActionPreference Stop that would throw instead of printing.
    $ErrorActionPreference = 'Continue'
    # Out-Host, not bare invocation: a native command's stdout otherwise joins
    # this function's output stream, so the caller would receive the script's
    # entire console output followed by the exit code, and `exit` would be
    # handed an array instead of an int.
    & $py.Exe @full | Out-Host
    return $LASTEXITCODE
}

function Read-Python {
    <#  Same call, but returns the output instead of displaying it.
        Needed because Invoke-Python swallows stdout into Out-Host, so it cannot
        be used to ask a script a question. #>
    param([string[]]$Arguments)
    $py = Get-Python
    $full = $py.Pre + $Arguments
    $ErrorActionPreference = 'Continue'
    return (& $py.Exe @full 2>$null | Out-String)
}

function Sync-Template {
    # git writes progress to stderr; same PS 5.1 hazard as above.
    $ErrorActionPreference = 'Continue'
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is required. Install Git for Windows: https://git-scm.com/download/win`n(Claude Code's Bash tool also needs it, so this is not optional.)"
    }
    if (Test-Path (Join-Path $TemplateDir '.git')) {
        Write-Host "==> Updating the framework registry" -ForegroundColor Cyan
        git -C $TemplateDir pull --quiet --ff-only 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  could not pull; using the copy already on disk" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "==> Fetching the framework registry (first run)" -ForegroundColor Cyan
        # A private repo with no credential helper configured would otherwise
        # block forever on an invisible prompt.
        $env:GIT_TERMINAL_PROMPT = '0'
        git clone --quiet $TemplateRepo $TemplateDir
        if ($LASTEXITCODE -ne 0) {
            throw "Could not clone $TemplateRepo.`nIt is private, so this needs GitHub auth. Easiest fix: install GitHub CLI (https://cli.github.com) and run ``gh auth login``, then rerun."
        }
        Write-Host "  template at $TemplateDir"
    }
}

# ---------------------------------------------------------------------------

# Bare `doe` applies DOE to the folder you are in. That is the common case —
# you made a folder, opened it, and want it to be a workspace — so it is the
# default rather than a help screen. Safe as a default because init_here.py is
# additive and refuses outright on a folder that has its own directives/ or
# execution/. `doe help` still prints usage.
if (-not $Name) { $Name = 'init' }

switch ($Name.ToLower()) {
    { $_ -in 'help', '-h', '--help', '/?' } {
        Write-Host @"
frame — apply a workspace framework, or create a new workspace

  frame                     apply the default framework (doe) to the folder you are in
  frame doe                 apply DOE — structures work: automations, scripts, steps to run
  frame iae                 apply IAE — structures research: sources, analysis, findings
  frame list                every available framework
  frame "Acme Onboarding"   create a NEW workspace folder here
  frame update              refresh the registry and the installed files
  frame syntax [status|on|off|thinking summary|full]
                            the machine-wide Plain English reply style (not a framework)
  frame help                this message

`doe` is an alias for this command and still works.

Registry: $TemplateDir
"@
        exit 0
    }
    'update' {
        Sync-Template
        # Refresh the installed copies too. doe.ps1 and the hook are COPIED into
        # ~/.claude by Install-Frameworks, so pulling the registry alone would leave
        # this command running last week's code while claiming to be current.
        $claudeDir = Join-Path $env:USERPROFILE '.claude'
        $binDir    = Join-Path $claudeDir 'bin'
        $cmdDir    = Join-Path $claudeDir 'commands'
        foreach ($d in @($binDir, $cmdDir)) {
            if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
        }
        $win = Join-Path $TemplateDir 'windows'

        # Hand off to the registry's own installer when it is there, rather than
        # re-implementing the copy here. It is the single source of truth for
        # what gets installed where, and it survives files being renamed.
        $installer = Join-Path $win 'Install-Frameworks.ps1'
        if (Test-Path $installer) {
            # Not $LASTEXITCODE: that reflects the last NATIVE command, which
            # here is the git pull inside Sync-Template, not the installer. The
            # installer runs with ErrorActionPreference Stop, so a failure
            # throws rather than returning a code.
            & $installer
            exit 0
        }

        # Fallback for a registry older than that installer. Copy by glob and
        # tolerate a missing file: this block is what broke across the
        # doe.ps1 -> frame.ps1 rename, because an old copy of this script went
        # looking for its own former filename in a registry that had moved on.
        # A self-updater must never hard-code the names of the files it updates.
        foreach ($ps1 in (Get-ChildItem (Join-Path $win '*.ps1') -ErrorAction SilentlyContinue)) {
            $dest = if ($ps1.Name -like '*guard*') { $claudeDir } else { $binDir }
            Copy-Item $ps1.FullName (Join-Path $dest $ps1.Name) -Force -ErrorAction SilentlyContinue
        }
        # Glob, not a named list: a new framework ships its own <name>-command.md
        # and must arrive without anyone editing this file.
        foreach ($cmd in (Get-ChildItem (Join-Path $win '*-command.md') -ErrorAction SilentlyContinue)) {
            $slug = $cmd.Name -replace '-command\.md$', ''
            Copy-Item $cmd.FullName (Join-Path $cmdDir "$slug.md") -Force
        }
        Write-Host "Registry and installed files are current." -ForegroundColor Green
        exit 0
    }
    'syntax' {
        # The machine-wide reply style: the Plain English output style plus
        # summarized thinking. Not a framework — it applies in every workspace.
        # Edits %USERPROFILE%\.claude\settings.json only; the next new chat picks
        # it up. The style file itself is installed by `frame update`.
        $settingsPath = Join-Path $env:USERPROFILE '.claude\settings.json'
        # -Encoding UTF8: PS 5.1 reads a BOM-less file as ANSI otherwise. [ordered]: keep key order stable.
        $settings = if (Test-Path $settingsPath) { Get-Content $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json } else { [pscustomobject]@{} }
        $h = [ordered]@{}
        foreach ($p in $settings.PSObject.Properties) { $h[$p.Name] = $p.Value }
        $verb = ($Arg + '').ToLower()
        $what = ($Arg2 + '').ToLower()
        $save = $true
        switch ($verb) {
            ''         { $save = $false }
            'status'   { $save = $false }
            'on'       { $h['outputStyle'] = 'Plain English' }
            'off'      { $h['outputStyle'] = 'default' }
            'thinking' {
                switch ($what) {
                    'summary' { $h['showThinkingSummaries'] = $true }
                    'full'    { $h.Remove('showThinkingSummaries') }
                    default   { Write-Host "usage: frame syntax thinking summary|full"; exit 2 }
                }
            }
            default    { Write-Host "usage: frame syntax [status|on|off|thinking summary|full]"; exit 2 }
        }
        if ($save) {
            if (Test-Path $settingsPath) { Copy-Item $settingsPath "$settingsPath.bak-syntax" -Force }
            ($h | ConvertTo-Json -Depth 20) | Set-Content "$settingsPath.tmp" -Encoding UTF8
            Move-Item "$settingsPath.tmp" $settingsPath -Force
        }
        $style = if ($h.ContainsKey('outputStyle')) { [string]$h['outputStyle'] } else { 'default' }
        $state = if ($style -eq 'Plain English') { 'on' } elseif ($style -eq 'default') { 'off' } else { "other ($style)" }
        $think = if ($h.ContainsKey('showThinkingSummaries') -and $h['showThinkingSummaries']) { 'summary' } else { 'full' }
        $tail  = if ($save) { ' - takes effect on the next new chat' } else { '' }
        Write-Host "Syntax: $state | thinking: $think$tail"
        exit 0
    }
    'list' {
        if ($Arg) { throw "unexpected argument '$Arg' (usage: frame list)" }
        Sync-Template
        exit (Invoke-Python @((Join-Path $TemplateDir 'execution\init_here.py'), '--list'))
    }
    'init' {
        if ($Arg) { throw "unexpected argument '$Arg' (usage: frame, or frame <framework>, or frame ""<Workspace Name>"")" }
        Sync-Template
        Write-Host "==> Applying doe to $((Get-Location).Path)" -ForegroundColor Cyan  # default framework
        exit (Invoke-Python @((Join-Path $TemplateDir 'execution\init_here.py'), '--path', (Get-Location).Path))
    }
    default {
        # Quote a multi-word workspace name. Before Position 1 existed this was a
        # binding error; now it would silently create a workspace named by the first word.
        if ($Arg) { throw "unexpected argument '$Arg'. Quote a multi-word name: frame ""$Name $Arg""" }
        Sync-Template
        $init = Join-Path $TemplateDir 'execution\init_here.py'
        # A bare framework name applies that framework here. Anything else is a
        # workspace name. Ask init_here.py what exists rather than hardcoding the
        # list, so a new framework works without touching this file.
        $known = Read-Python @($init, '--list')
        if ($known -match "(?m)^\s{2}$([regex]::Escape($Name.ToLower()))\s") {
            Write-Host "==> Applying $($Name.ToLower()) to $((Get-Location).Path)" -ForegroundColor Cyan
            exit (Invoke-Python @($init, '--framework', $Name.ToLower(), '--path', (Get-Location).Path))
        }
        exit (Invoke-Python @((Join-Path $TemplateDir 'execution\new_workspace.py'), $Name, '--dest', $Dest, '--open'))
    }
}

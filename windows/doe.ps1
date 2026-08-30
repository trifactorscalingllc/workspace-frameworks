<#
.SYNOPSIS
    Create or convert a DOE workspace on Windows.

.DESCRIPTION
    The DOE rule is that project folders come from the template, never from a
    bare mkdir. On the mini that is `newws`; this is the same thing for a laptop
    running Claude Code locally rather than over Remote-SSH.

    It keeps a local checkout of the template at %USERPROFILE%\.doe-template and
    drives the template's own Python scripts, so behaviour matches the mini
    exactly rather than being a second implementation that drifts.

.EXAMPLE
    doe "Acme Onboarding"    # new workspace in the current directory
    doe init                 # convert the folder you are already in
    doe update               # pull the latest template
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Name,
    [string]$Dest = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'

$TemplateRepo = 'https://github.com/trifactorscalingllc/doe-template.git'
$TemplateDir  = Join-Path $env:USERPROFILE '.doe-template'

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
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        $probe = $c.Pre + @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])')
        $ver = & $c.Exe @probe 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $ver) { continue }
        $parts = "$ver".Trim().Split('.')
        # The template uses `X | None` unions, so anything below 3.10 dies at
        # import with a confusing TypeError rather than a version message.
        if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10) { return $c }
        Write-Host "  found Python $ver, but DOE needs 3.10+" -ForegroundColor Yellow
    }
    throw "No Python 3.10+ found. Install it from https://python.org (tick 'Add python.exe to PATH'), then reopen this terminal."
}

function Invoke-Python {
    param([string[]]$Arguments)
    $py = Get-Python
    $full = $py.Pre + $Arguments
    # Out-Host, not bare invocation: a native command's stdout otherwise joins
    # this function's output stream, so the caller would receive the script's
    # entire console output followed by the exit code, and `exit` would be
    # handed an array instead of an int.
    & $py.Exe @full | Out-Host
    return $LASTEXITCODE
}

function Sync-Template {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is required. Install Git for Windows: https://git-scm.com/download/win`n(Claude Code's Bash tool also needs it, so this is not optional.)"
    }
    if (Test-Path (Join-Path $TemplateDir '.git')) {
        Write-Host "==> Updating the template" -ForegroundColor Cyan
        git -C $TemplateDir pull --quiet --ff-only 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  could not pull; using the copy already on disk" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "==> Fetching the DOE template (first run)" -ForegroundColor Cyan
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

if (-not $Name) {
    Write-Host @"
doe — create or convert a DOE workspace

  doe "Acme Onboarding"   create a new workspace here
  doe init                convert the folder you are already in (additive)
  doe update              pull the latest template

Template: $TemplateDir
"@
    exit 0
}

switch ($Name.ToLower()) {
    'update' {
        Sync-Template
        Write-Host "Template is current." -ForegroundColor Green
        exit 0
    }
    'init' {
        Sync-Template
        Write-Host "==> Converting $((Get-Location).Path)" -ForegroundColor Cyan
        exit (Invoke-Python @((Join-Path $TemplateDir 'execution\init_here.py'), '--path', (Get-Location).Path))
    }
    default {
        Sync-Template
        exit (Invoke-Python @((Join-Path $TemplateDir 'execution\new_workspace.py'), $Name, '--dest', $Dest, '--open'))
    }
}

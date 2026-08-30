<#
    SessionStart hook: say so when this folder is not a DOE workspace.

    The Windows twin of shared/doe-guard.py on the mini. It is PowerShell rather
    than Python on purpose: a hook that fails is worse than a rule that goes
    unenforced, and PowerShell is always present on Windows while Python may not
    be. It also cannot share the mini's settings.json entry, because that one is
    POSIX shell (`2>/dev/null || true`, `python3`), none of which is valid here.

    It NEVER creates or modifies anything — it only prints a sentence, which
    Claude Code injects as session context. Opening a repo to read it stays clean.

    Silence a folder with a `.no-framework` file (`.no-doe` also works, it predates
    the rename). Established codebases are skipped
    automatically: the target is a bare new folder, not every repo you open.
#>

$ErrorActionPreference = 'SilentlyContinue'

try {
    # Claude Code hands the hook a JSON payload on stdin carrying `cwd`.
    $root = $null
    try {
        $raw = [Console]::In.ReadToEnd()
        if ($raw) { $root = ($raw | ConvertFrom-Json).cwd }
    }
    catch { }
    if (-not $root) { $root = (Get-Location).Path }
    if (-not (Test-Path $root)) { exit 0 }

    $dir  = Get-Item -LiteralPath $root
    $name = $dir.Name

    # Never nag in a home directory or at a drive root.
    if ($dir.FullName -eq $env:USERPROFILE -or -not $dir.Parent) { exit 0 }
    # Both names: .no-doe predates the rename and must keep working.
    if ((Test-Path (Join-Path $root '.no-framework')) -or (Test-Path (Join-Path $root '.no-doe'))) { exit 0 }

    # Marker sets, same rule as the mini: every marker in a set must be present,
    # because `directives/` alone is too weak — plenty of repos have one.
    $frameworks = @{
        doe = @('directives', 'execution\config.py')
        iae = @('sources', 'findings', 'check_iae.py')
    }
    foreach ($fw in $frameworks.Keys) {
        $all = $true
        foreach ($m in $frameworks[$fw]) {
            if (-not (Test-Path (Join-Path $root $m))) { $all = $false; break }
        }
        if ($all) { exit 0 }
    }

    $established = @(
        'package.json', 'pyproject.toml', 'Cargo.toml', 'go.mod', 'pom.xml',
        'Gemfile', 'composer.json', 'CMakeLists.txt', 'setup.py', 'requirements.txt'
    )
    foreach ($f in $established) {
        if (Test-Path (Join-Path $root $f)) { exit 0 }
    }

    if (Test-Path (Join-Path $root '.git')) {
        $count = 0
        try { $count = [int](git -C $root rev-list --count HEAD 2>$null) } catch { }
        if ($count -ge 5) { exit 0 }
    }

    Write-Output ("FRAMEWORK: $name has no framework applied. The rule is that project " +
        "folders are built from a template, not by a bare mkdir. Available: doe, iae " +
        "— doe structures work (automations, scripts, anything with steps to run); " +
        "iae structures thinking (reading sources and reaching a defensible " +
        "conclusion). Before starting work here, offer the one that fits and say why; " +
        "ask rather than guess if it is not obvious. Applying one is additive and " +
        "never restructures what is already there. If the user declines, suggest a " +
        ".no-framework file to silence this folder for good.")
}
catch {
    # Fail open, always. Never block a session from starting.
}
exit 0

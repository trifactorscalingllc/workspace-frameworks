<#
    SessionStart hook: say so when this folder is not a DOE workspace.

    The Windows twin of shared/doe-guard.py on the mini. It is PowerShell rather
    than Python on purpose: a hook that fails is worse than a rule that goes
    unenforced, and PowerShell is always present on Windows while Python may not
    be. It also cannot share the mini's settings.json entry, because that one is
    POSIX shell (`2>/dev/null || true`, `python3`), none of which is valid here.

    It NEVER creates or modifies anything — it only prints a sentence, which
    Claude Code injects as session context. Opening a repo to read it stays clean.

    Silence a folder with a `.no-doe` file. Established codebases are skipped
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
    if (Test-Path (Join-Path $root '.no-doe')) { exit 0 }

    # Both markers, same rule as the mini: `directives/` alone is too weak.
    $isDoe = (Test-Path (Join-Path $root 'directives')) -and
             (Test-Path (Join-Path $root 'execution\config.py'))
    if ($isDoe) { exit 0 }

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

    Write-Output ("DOE: $name is not a DOE workspace (no directives/ + execution/). " +
        "The DOE rule says project folders are created from the template, not by a " +
        "bare mkdir. Before starting project work here, offer to convert it with " +
        "``doe init`` — additively, never restructuring what is already there. " +
        "Decline and move on if the user says no, and suggest a .no-doe file to " +
        "silence this folder for good.")
}
catch {
    # Fail open, always. Never block a session from starting.
}
exit 0

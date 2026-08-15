#!/usr/bin/env python3
"""Install the webhook receiver as a launchd **LaunchAgent**.

A LaunchAgent runs in the logged-in (Aqua) session, which is the only way the
run keeps Keychain access and therefore the claude.ai subscription. A system
LaunchDaemon runs outside that session, cannot unlock the login keychain, and
will fail every run — do not convert this to one.

    python execution/install_agent.py --print       # show the plist, change nothing
    python execution/install_agent.py               # probe, then install and start
    python execution/install_agent.py --status
    python execution/install_agent.py --uninstall

Install refuses unless `preflight.py --probe` passes first: shipping a service
that cannot authenticate just moves the failure somewhere harder to see.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from lib.childenv import assert_keyless  # noqa: E402

# Derived from the folder name, so a duplicated workspace gets its own service
# instead of hijacking this one's. See config.workspace_slug().
LABEL = config.LAUNCHD_LABEL
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = Path.home() / "Library" / "Logs" / config.workspace_slug()
DOMAIN = f"gui/{os.getuid()}"
SERVICE = f"{DOMAIN}/{LABEL}"


def venv_python() -> Path:
    """Prefer the repo venv so launchd doesn't inherit whatever python is first."""
    candidate = config.ROOT / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else Path(sys.executable)


def service_path() -> str:
    """PATH for the agent. launchd hands a process a minimal PATH, and `claude`
    usually lives in ~/.local/bin — the single most common reason a LaunchAgent
    works by hand and fails under launchd."""
    parts: list[str] = []
    claude = shutil.which("claude")
    if claude:
        # Deliberately NOT resolved: `claude` is a symlink into a
        # version-stamped directory, and baking that target into the plist
        # would break the agent on the next CLI update. The symlink's own
        # directory is the stable address.
        parts.append(str(Path(claude).parent))
    parts += [
        str(Path.home() / ".local" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return ":".join(seen)


def build_plist(port: int) -> dict:
    # Unbuffered, or launchd's log files stay empty until the process exits —
    # which for a KeepAlive service is never.
    env = {"PATH": service_path(), "PYTHONUNBUFFERED": "1"}
    # The plist is written to disk and read by launchd, so a key here would be
    # both a billing leak and a secret at rest. Neither is acceptable.
    assert_keyless(env, context="LaunchAgent plist EnvironmentVariables")

    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(venv_python()),
            str(config.EXECUTION_DIR / "local_webhook.py"),
            "--port",
            str(port),
        ],
        "WorkingDirectory": str(config.ROOT),
        "EnvironmentVariables": env,
        "RunAtLoad": True,
        "KeepAlive": True,
        # Adaptive: starts backgrounded but is promoted when it does real work,
        # so long directive runs are not I/O throttled.
        "ProcessType": "Adaptive",
        "StandardOutPath": str(LOG_DIR / "out.log"),
        "StandardErrorPath": str(LOG_DIR / "err.log"),
    }


def launchctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=check)


def port_holder(port: int) -> str | None:
    """Who is listening on `port`? A label, a warning string, or None if free.

    Guards the other half of the duplicate-workspace problem: unique labels stop
    launchd collisions, but two receivers still cannot share a socket.
    """
    import socket

    with socket.socket() as sock:
        sock.settimeout(1)
        if sock.connect_ex(("127.0.0.1", port)) != 0:
            return None

    info = health(port, timeout=3)
    if info and info.get("label"):
        return info["label"]
    return "something that is not a directive-runner receiver"


def health(port: int, timeout: int = 5) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def run_preflight() -> bool:
    # flush: the child writes to the same stream unbuffered, so without this
    # the banner lands after the output it introduces.
    print("Running preflight --probe before installing...\n", flush=True)
    proc = subprocess.run(
        [str(venv_python()), str(config.EXECUTION_DIR / "preflight.py"), "--probe"],
        cwd=config.ROOT,
    )
    return proc.returncode == 0


def install(port: int, skip_probe: bool) -> int:
    if not skip_probe and not run_preflight():
        print(
            "\nRefusing to install: preflight failed. Fix it first — a service that "
            "cannot authenticate fails the same way, just less visibly.",
            file=sys.stderr,
        )
        return 1

    # Port check FIRST, before anything is written or booted out. A holder that
    # is us is fine — we are about to replace it. Anything else means we must
    # change nothing: an earlier version of this checked after the bootout and
    # left the workspace with a stopped service and a plist naming a port it
    # could never have.
    holder = port_holder(port)
    if holder is not None and holder != LABEL:
        print(
            f"\n✗ port {port} is already held by {holder}.\n"
            f"  This workspace ({LABEL}) needs its own port. Set WEBHOOK_PORT in\n"
            f"  {config.ENV_FILE} to a free one and re-run, or use --port.\n"
            f"  Nothing was changed.",
            file=sys.stderr,
        )
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    with PLIST_PATH.open("wb") as fh:
        plistlib.dump(build_plist(port), fh)
    print(f"\nwrote {PLIST_PATH}")

    # Bootout first so a re-install picks up plist changes; failure just means
    # it was not loaded. Bootout is ASYNCHRONOUS — bootstrapping while the old
    # job is still unloading fails with a bare "Input/output error", so wait for
    # the service to actually disappear from the domain before continuing.
    launchctl("bootout", SERVICE)
    for _ in range(40):
        if launchctl("print", SERVICE).returncode != 0:
            break
        subprocess.run(["/bin/sleep", "0.25"])
    else:
        print(f"warning: {SERVICE} still loaded after bootout; bootstrap may fail", file=sys.stderr)

    proc = launchctl("bootstrap", DOMAIN, str(PLIST_PATH))
    if proc.returncode != 0:
        print(
            f"launchctl bootstrap failed (rc={proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip() or 'no message'}",
            file=sys.stderr,
        )
        return 1
    launchctl("kickstart", "-k", SERVICE)
    print(f"bootstrapped {SERVICE}")

    for _ in range(30):
        if (info := health(port)) is not None:
            print(f"\n✓ receiver is up on port {port} (model={info.get('model')})")
            print(f"  logs: {LOG_DIR}")
            print("\nIt listens on loopback only. Put a Cloudflare tunnel or a")
            print("Tailscale *funnel* in front of it for public access.")
            return 0
        subprocess.run(["/bin/sleep", "0.5"])

    print(
        f"\n✗ installed, but nothing answered on port {port}. Check {LOG_DIR / 'err.log'}.",
        file=sys.stderr,
    )
    return 1


def uninstall() -> int:
    proc = launchctl("bootout", SERVICE)
    if proc.returncode == 0:
        print(f"booted out {SERVICE}")
    else:
        print(f"not loaded ({proc.stderr.strip() or 'no such service'})")
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        print(f"removed {PLIST_PATH}")
    if LOG_DIR.exists():
        # Kept on purpose — the logs are usually why you are uninstalling.
        print(f"logs left in place at {LOG_DIR} (delete manually if unwanted)")
    return 0


def status(port: int) -> int:
    print(f"plist:   {PLIST_PATH} {'(present)' if PLIST_PATH.exists() else '(absent)'}")
    proc = launchctl("print", SERVICE)
    if proc.returncode != 0:
        print(f"service: not loaded in {DOMAIN}")
    else:
        # launchctl print nests per-endpoint sections that repeat these keys;
        # the first occurrence is the service's own, so keep only that.
        wanted = ("state = ", "pid = ", "last exit code = ", "runs = ")
        seen: set[str] = set()
        for line in proc.stdout.splitlines():
            stripped = line.strip()
            key = next((w for w in wanted if stripped.startswith(w)), None)
            if key and key not in seen:
                seen.add(key)
                print(f"service: {stripped}")
    info = health(port)
    print(f"health:  {info if info else 'no response on port ' + str(port)}")
    if info is None and PLIST_PATH.exists():
        print(
            "\nIf this Mac rebooted and nobody logged in at the GUI console, the login\n"
            "keychain is still locked and runs will fail on auth. Log in at the console."
        )
    return 0 if info else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=config.WEBHOOK_PORT)
    ap.add_argument("--print", dest="show", action="store_true", help="print the plist, change nothing")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--skip-probe", action="store_true", help="install without the live probe")
    args = ap.parse_args()

    if args.show:
        sys.stdout.buffer.write(plistlib.dumps(build_plist(args.port)))
        return 0
    if args.uninstall:
        return uninstall()
    if args.status:
        return status(args.port)
    return install(args.port, args.skip_probe)


if __name__ == "__main__":
    sys.exit(main())

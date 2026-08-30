#!/usr/bin/env python3
"""Take a verifiable, near-free backup of a topic folder before touching it.

This Mac has no Time Machine and no APFS snapshots; the only existing backup is
``fleet-backup.sh``, which covers seven repos. So anything that is about to
restructure a folder takes its own copy first.

The copy uses APFS cloning (``cp -c``), which shares blocks instead of copying
them — measured at 0.43s for 147M. It costs almost nothing until the original
and the clone diverge, which is exactly the safety property wanted here.

    python execution/tools/snapshot_topic.py --path /Users/tfs/slim-bot
    python execution/tools/snapshot_topic.py --verify <snapshot-dir>
    python execution/tools/snapshot_topic.py --list

A snapshot that was never verified is not a backup, so ``--verify`` re-walks the
clone and re-hashes it against the manifest rather than trusting that ``cp``
returned 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402,F401  (import first: scrubs the billing vars)
from lib import topics  # noqa: E402

SNAPSHOT_ROOT = topics.HOME / ".topic-snapshots"
MANIFEST_NAME = "MANIFEST.json"
# Files larger than this are recorded by size+mtime rather than hashed. Hashing
# 28G of video to prove a clone worked is not a good trade.
DEFAULT_HASH_MAX = 8 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path, hash_max: int) -> dict:
    """Walk a tree and record what it contains, without following symlinks."""
    files: dict[str, dict] = {}
    links: dict[str, str] = {}
    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            rel = str(path.relative_to(root))
            if entry.is_symlink():
                try:
                    links[rel] = os.readlink(path)
                except OSError:
                    links[rel] = "<unreadable>"
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(path)
                continue
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            record = {"size": stat.st_size, "mtime": int(stat.st_mtime)}
            if stat.st_size <= hash_max:
                try:
                    record["sha256"] = _sha256(path)
                except OSError:
                    record["sha256"] = None
            files[rel] = record
            total += stat.st_size

    return {
        "file_count": len(files),
        "symlink_count": len(links),
        "total_bytes": total,
        "hash_max_bytes": hash_max,
        "files": files,
        "symlinks": links,
    }


def _free_bytes(path: Path) -> int:
    stat = os.statvfs(path)
    return stat.f_bavail * stat.f_frsize


def snapshot(root: Path, hash_max: int, force: bool) -> dict:
    apparent = topics.dir_size(root)
    free = _free_bytes(SNAPSHOT_ROOT.parent if SNAPSHOT_ROOT.exists() else topics.HOME)
    # Cloned blocks are shared, so this is deliberately conservative: it budgets
    # for the copy fully diverging rather than for what it costs today.
    if not force and free < apparent * 3:
        raise RuntimeError(
            f"refusing: {apparent / 1e9:.1f}GB folder needs ~{apparent * 3 / 1e9:.1f}GB "
            f"headroom, only {free / 1e9:.1f}GB free. Use --force to override."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = SNAPSHOT_ROOT / f"{root.name}-{stamp}"
    if dest.exists():
        raise RuntimeError(f"snapshot already exists: {dest}")
    # 0700: a faithful backup necessarily contains the folder's .env and tokens,
    # so the snapshot root must not be readable by anyone else on the machine.
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_ROOT.chmod(0o700)

    manifest = build_manifest(root, hash_max)
    manifest.update({
        "source": str(root),
        "snapshot": str(dest),
        "created_utc": stamp,
        "git": topics.git_info(root),
        "launchd_labels": [r["label"] for r in topics.launchd_refs(root)],
        "claude_state": topics.claude_state(root),
    })

    # -c clones (copy-on-write), -R recurses, -p preserves metadata. Symlinks are
    # copied as symlinks, so a borrowed node_modules is not slurped in via the link.
    result = subprocess.run(
        ["cp", "-c", "-Rp", str(root), str(dest)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cp failed: {result.stderr.strip()[:400]}")

    (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    return {
        "ok": True, "snapshot": str(dest), "source": str(root),
        "files": manifest["file_count"], "symlinks": manifest["symlink_count"],
        "bytes": manifest["total_bytes"],
        "next": f"verify with: snapshot_topic.py --verify {dest}",
    }


def verify(snapshot_dir: Path) -> dict:
    """Re-hash the clone and compare it to the manifest recorded at capture."""
    manifest_path = snapshot_dir / MANIFEST_NAME
    if not manifest_path.exists():
        raise RuntimeError(f"no {MANIFEST_NAME} in {snapshot_dir}")
    manifest = json.loads(manifest_path.read_text())

    current = build_manifest(snapshot_dir, manifest["hash_max_bytes"])
    current["files"].pop(MANIFEST_NAME, None)  # written after the clone

    expected, actual = manifest["files"], current["files"]
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    corrupt = [
        rel for rel in set(expected) & set(actual)
        if expected[rel].get("sha256") is not None
        and expected[rel]["sha256"] != actual[rel].get("sha256")
    ]
    link_drift = [
        rel for rel, target in manifest["symlinks"].items()
        if current["symlinks"].get(rel) != target
    ]

    ok = not (missing or corrupt or link_drift)
    return {
        "ok": ok,
        "snapshot": str(snapshot_dir),
        "source": manifest["source"],
        "verdict": "intact" if ok else "DAMAGED",
        "checked": len(expected),
        "missing": missing[:20], "missing_count": len(missing),
        "corrupt": corrupt[:20], "corrupt_count": len(corrupt),
        "symlink_drift": link_drift[:20], "symlink_drift_count": len(link_drift),
        "extra_count": len(extra),
    }


def list_snapshots() -> dict:
    entries = []
    if SNAPSHOT_ROOT.is_dir():
        for child in sorted(SNAPSHOT_ROOT.iterdir(), reverse=True):
            manifest_path = child / MANIFEST_NAME
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
            except ValueError:
                continue
            entries.append({
                "snapshot": str(child), "source": manifest.get("source"),
                "created_utc": manifest.get("created_utc"),
                "files": manifest.get("file_count"),
            })
    return {"ok": True, "root": str(SNAPSHOT_ROOT), "snapshots": entries}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path", help="topic folder to snapshot")
    ap.add_argument("--verify", metavar="SNAPSHOT_DIR",
                    help="re-hash an existing snapshot against its manifest")
    ap.add_argument("--list", action="store_true", help="list snapshots taken so far")
    ap.add_argument("--hash-max-bytes", type=int, default=DEFAULT_HASH_MAX,
                    help="files larger than this are recorded but not hashed")
    ap.add_argument("--force", action="store_true",
                    help="proceed despite the free-space guard")
    args = ap.parse_args()

    try:
        if args.list:
            result = list_snapshots()
        elif args.verify:
            result = verify(Path(args.verify).expanduser().resolve())
        elif args.path:
            result = snapshot(topics.resolve_topic(args.path),
                              args.hash_max_bytes, args.force)
        else:
            ap.error("one of --path, --verify or --list is required")
    except Exception as exc:  # noqa: BLE001 - the caller is a model reading stdout
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

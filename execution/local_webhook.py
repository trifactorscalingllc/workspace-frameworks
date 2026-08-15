#!/usr/bin/env python3
"""Webhook receiver — the only receiver.

Runs on this Mac as the logged-in user, so ``claude -p`` can reach the Keychain
and runs bill the claude.ai subscription. Standard library only: no web
framework, and deliberately nothing that would tempt a move to a Linux host,
where there is no Keychain and runs would have to bill the paid API.

    python execution/local_webhook.py --port 8787

In production it runs under launchd as a **LaunchAgent** in the logged-in
session — see `execution/install_agent.py`. It must not be a LaunchDaemon: a
daemon has no access to the login keychain and every run would fail auth.

It binds to 127.0.0.1 by default. To reach it from the outside, put a public
tunnel in front of it (Cloudflare tunnel, or Tailscale **funnel** — funnel is
public, serve is tailnet-only) rather than binding to 0.0.0.0.

Routes (all but /webhooks require ``X-Webhook-Token: $WEBHOOK_TOKEN``):
    GET  /webhooks
    POST /directive?slug={slug}
    POST /test-email
    GET  /health
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import run_directive  # noqa: E402
from lib import notify  # noqa: E402
from lib.childenv import BillingLeak, build_child_env  # noqa: E402

MAX_BODY = 1 << 20  # 1 MiB


def load_webhooks() -> dict:
    if not config.WEBHOOKS_FILE.exists():
        return {}
    return json.loads(config.WEBHOOKS_FILE.read_text()).get("webhooks", {})


class Handler(BaseHTTPRequestHandler):
    server_version = "directive-runner/1.0"

    # --- plumbing ---------------------------------------------------------

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _authorized(self) -> tuple[bool, str]:
        """Fail closed: an unset WEBHOOK_TOKEN means nobody is authorized."""
        expected = config.get("WEBHOOK_TOKEN")
        if not expected:
            return False, "WEBHOOK_TOKEN is not set in .env"
        if self.headers.get("X-Webhook-Token") != expected:
            return False, "bad or missing X-Webhook-Token"
        return True, ""

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    # --- routes -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route == "/health":
            self._send(200, {"ok": True, "model": config.MODEL})
        elif route == "/webhooks":
            hooks = load_webhooks()
            self._send(200, {"webhooks": [
                {"slug": slug, **{k: v for k, v in cfg.items() if not k.startswith("_")}}
                for slug, cfg in hooks.items()
            ]})
        else:
            self._send(404, {"ok": False, "error": f"no route {route}"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        ok, why = self._authorized()
        if not ok:
            self._send(401, {"ok": False, "error": why})
            return

        if route == "/directive":
            self._handle_directive(parse_qs(parsed.query))
        elif route == "/test-email":
            self._handle_test_email()
        else:
            self._send(404, {"ok": False, "error": f"no route {route}"})

    def _handle_directive(self, query: dict) -> None:
        slug = (query.get("slug") or [None])[0]
        if not slug:
            self._send(400, {"ok": False, "error": "missing ?slug="})
            return

        hooks = load_webhooks()
        cfg = hooks.get(slug)
        if not cfg:
            self._send(404, {"ok": False, "error": f"unknown slug {slug!r}", "known": sorted(hooks)})
            return
        if not cfg.get("enabled", True):
            self._send(403, {"ok": False, "error": f"webhook {slug!r} is disabled"})
            return

        payload = self._read_json()
        notify.run_started(slug, source="local")
        try:
            result = run_directive.run(
                cfg.get("directive", slug),
                payload=payload,
                tools=cfg.get("tools", []),
            )
        except (FileNotFoundError, ValueError) as exc:
            # A misconfigured webhooks.json entry, not a run failure.
            result = {"ok": False, "slug": slug, "error": f"bad webhook config: {exc}"}
            notify.run_finished(slug, result)
            self._send(500, result)
            return
        notify.run_finished(slug, result)
        self._send(200 if result["ok"] else 500, result)

    def _handle_test_email(self) -> None:
        body = self._read_json()
        to = body.get("to") or config.get("EMAIL_TO")
        if not to:
            self._send(400, {"ok": False, "error": 'no recipient: pass {"to": ...} or set EMAIL_TO'})
            return

        sys.path.insert(0, str(config.EXECUTION_DIR))
        from tools.send_email import build_message, send  # noqa: PLC0415

        msg = build_message(
            [to],
            body.get("subject", "directive-runner test"),
            body.get("body", "If you are reading this, the webhook email path works."),
            html=False,
            cc=[],
        )
        try:
            resp = send(msg)
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"ok": False, "error": str(exc)})
            return
        self._send(200, {"ok": True, "message_id": resp.get("id"), "to": to})


def startup_selfcheck() -> None:
    """Fail fast on the things that make a launchd-managed run break silently.

    The full audit lives in preflight.py and the installer runs it. This is the
    cheap subset worth repeating on every service start — no model spawn, so
    KeepAlive cannot turn it into a restart loop that burns tokens.
    """
    # Defense in depth. build_child_env *strips* billing vars, so this only
    # fires if the stripping itself is broken — which is exactly the failure
    # worth refusing to serve on, since every child would inherit a key.
    try:
        build_child_env({"ANTHROPIC_MODEL": config.MODEL})
    except BillingLeak as exc:
        sys.exit(f"refusing to serve: {exc}")

    # config scrubbed these at import, so runs are safe either way — but
    # something in the environment is still handing us a key, and under launchd
    # that means the plist or .env. Say so rather than swallowing it.
    if config.SCRUBBED:
        print(
            f"warning: {config.SCRUBBED} was present in this process and has been "
            "scrubbed. Runs are unaffected, but find the source — check .env and "
            "the LaunchAgent plist.",
            file=sys.stderr,
        )

    if not shutil.which("claude"):
        sys.exit(
            "refusing to serve: `claude` is not on PATH.\n"
            "Under launchd the PATH is minimal and does not include ~/.local/bin. "
            "Reinstall with `python execution/install_agent.py`, which writes an "
            "explicit PATH into the plist."
        )

    if not config.get("WEBHOOK_TOKEN"):
        print("warning: WEBHOOK_TOKEN is unset — every POST will 401.", file=sys.stderr)

    if config.billed_api_gate_open():
        print(
            "warning: ALLOW_BILLED_API=1 is set. Runs on this Mac should use the "
            "claude.ai subscription; unset it unless this host has no Keychain.",
            file=sys.stderr,
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=int(config.get("WEBHOOK_PORT", "8787")))
    ap.add_argument("--host", default="127.0.0.1", help="keep this loopback; tunnel for public access")
    args = ap.parse_args()

    startup_selfcheck()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"directive-runner listening on http://{args.host}:{args.port}  (model={config.MODEL})")
    print("routes: GET /health, GET /webhooks, POST /directive?slug=, POST /test-email")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        thread.join()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

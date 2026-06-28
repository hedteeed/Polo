#!/usr/bin/env python3
"""
One-click launcher: starts dashboard + public tunnel, writes a clickable link.

Usage:
  python3 polymarket_research/launch.py

Then open the URL printed (or OPEN_DASHBOARD.md in the repo).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8080
URL_FILE = ROOT / "DASHBOARD_URL.txt"
OPEN_FILE = ROOT / "OPEN_DASHBOARD.md"
TUNNEL_LOG = ROOT / "tunnel.log"
TMUX_CONF = "/exec-daemon/tmux.portal.conf"


def tmux(*args: str) -> subprocess.CompletedProcess:
    cmd = ["tmux", "-f", TMUX_CONF, *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def tmux_has(session: str) -> bool:
    return tmux("has-session", "-t", session).returncode == 0


def tmux_new(session: str, workdir: Path, shell_cmd: str) -> None:
    if tmux_has(session):
        return
    tmux(
        "new-session", "-d", "-s", session,
        "-c", str(workdir),
        "--", "bash", "-lc", shell_cmd,
    )


def health_ok(port: int = PORT) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def url_alive(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/health", timeout=8) as r:
            return r.status == 200
    except Exception:
        return False


def read_tunnel_url_from_log() -> str | None:
    if not TUNNEL_LOG.exists():
        return None
    text = TUNNEL_LOG.read_text(encoding="utf-8", errors="ignore")
    matches = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
    return matches[-1] if matches else None


def write_link_files(url: str) -> None:
    URL_FILE.write_text(url + "\n", encoding="utf-8")
    OPEN_FILE.write_text(
        f"# Open your dashboard\n\n"
        f"**[Click here to open the Polymarket Paper Trading Dashboard]({url})**\n\n"
        f"Direct link: `{url}`\n\n"
        f"Bookmark this page. The tunnel stays up while the cloud agent session runs.\n",
        encoding="utf-8",
    )


def ensure_dashboard() -> None:
    if health_ok():
        print("Dashboard already running on port", PORT)
        return
    tmux_new(
        "polo-dashboard",
        ROOT,
        f"python3 polymarket_research/run_dashboard.py --port {PORT} --host 0.0.0.0 "
        f"2>&1 | tee -a dashboard.log",
    )
    for _ in range(40):
        if health_ok():
            print("Dashboard started on port", PORT)
            return
        time.sleep(0.5)
    raise SystemExit("Dashboard failed to start — check dashboard.log")


def ensure_tunnel() -> str:
    existing = read_tunnel_url_from_log()
    if existing and url_alive(existing):
        print("Tunnel already live:", existing)
        return existing

    if not shutil.which("cloudflared"):
        raise SystemExit("cloudflared not installed")

    if tmux_has("polo-tunnel"):
        tmux("kill-session", "-t", "polo-tunnel")
        time.sleep(1)

    TUNNEL_LOG.write_text("", encoding="utf-8")
    tmux_new(
        "polo-tunnel",
        ROOT,
        f"cloudflared tunnel --url http://127.0.0.1:{PORT} --no-autoupdate 2>&1 | tee -a tunnel.log",
    )

    deadline = time.time() + 90
    while time.time() < deadline:
        url = read_tunnel_url_from_log()
        if url and url_alive(url):
            print("Tunnel live:", url)
            return url
        time.sleep(2)

    raise SystemExit("Tunnel failed to start — check tunnel.log")


def main() -> None:
    print("=" * 60)
    print("  Polymarket Paper Trading — one-click launch")
    print("=" * 60)

    ensure_dashboard()
    url = ensure_tunnel()
    write_link_files(url)

    print()
    print("  OPEN YOUR DASHBOARD (click or copy):")
    print()
    print(f"  >>> {url}")
    print()
    print(f"  Saved to: {OPEN_FILE.name} and {URL_FILE.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()

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
LT_LOG = ROOT / "tunnel-lt.log"
TMUX_CONF = "/exec-daemon/tmux.portal.conf"
CLOUDFLARED_PATHS = ("/usr/local/bin/cloudflared", "/usr/bin/cloudflared")


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


def cloudflared_bin() -> str | None:
    found = shutil.which("cloudflared")
    if found:
        return found
    for path in CLOUDFLARED_PATHS:
        if Path(path).is_file():
            return path
    return None


def ensure_deps() -> None:
    req = ROOT / "polymarket_research" / "requirements.txt"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
        check=False,
    )


def health_ok(port: int = PORT) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def url_alive(url: str) -> bool:
    req = urllib.request.Request(
        f"{url.rstrip('/')}/api/health",
        headers={"Bypass-Tunnel-Reminder": "true"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status == 200
    except Exception:
        return False


def read_cloudflare_url() -> str | None:
    if not TUNNEL_LOG.exists():
        return None
    text = TUNNEL_LOG.read_text(encoding="utf-8", errors="ignore")
    matches = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
    return matches[-1] if matches else None


def read_localtunnel_url() -> str | None:
    if not LT_LOG.exists():
        return None
    text = LT_LOG.read_text(encoding="utf-8", errors="ignore")
    matches = re.findall(r"https://[a-z0-9-]+\.loca\.lt", text)
    return matches[-1] if matches else None


def write_link_files(url: str) -> None:
    URL_FILE.write_text(url + "\n", encoding="utf-8")
    note = ""
    if ".loca.lt" in url:
        note = (
            "\nIf you see a LocalTunnel reminder page, click **Click to Continue** "
            "once — then the dashboard loads.\n"
        )
    OPEN_FILE.write_text(
        f"# Open your dashboard\n\n"
        f"**[Click here to open the Polymarket Paper Trading Dashboard]({url})**\n\n"
        f"Direct link: `{url}`\n"
        f"{note}\n"
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
    for _ in range(60):
        if health_ok():
            print("Dashboard started on port", PORT)
            return
        time.sleep(0.5)
    raise SystemExit("Dashboard failed to start — check dashboard.log")


def start_cloudflare_tunnel() -> str | None:
    cf = cloudflared_bin()
    if not cf:
        return None
    if tmux_has("polo-tunnel"):
        tmux("kill-session", "-t", "polo-tunnel")
        time.sleep(1)
    TUNNEL_LOG.write_text("", encoding="utf-8")
    tmux_new(
        "polo-tunnel",
        ROOT,
        f"{cf} tunnel --url http://127.0.0.1:{PORT} --no-autoupdate 2>&1 | tee -a tunnel.log",
    )
    deadline = time.time() + 90
    while time.time() < deadline:
        url = read_cloudflare_url()
        if url and url_alive(url):
            print("Cloudflare tunnel live:", url)
            return url
        time.sleep(2)
    return None


def start_localtunnel() -> str:
    existing = read_localtunnel_url()
    if existing and url_alive(existing):
        print("LocalTunnel already live:", existing)
        return existing

    if tmux_has("polo-lt"):
        tmux("kill-session", "-t", "polo-lt")
        time.sleep(1)

    LT_LOG.write_text("", encoding="utf-8")
    tmux_new(
        "polo-lt",
        ROOT,
        f"npx --yes localtunnel --port {PORT} 2>&1 | tee -a tunnel-lt.log",
    )

    deadline = time.time() + 60
    while time.time() < deadline:
        url = read_localtunnel_url()
        if url and url_alive(url):
            print("LocalTunnel live:", url)
            return url
        time.sleep(2)

    raise SystemExit("Tunnel failed to start — check tunnel-lt.log")


def ensure_tunnel() -> str:
    for reader in (read_cloudflare_url, read_localtunnel_url):
        url = reader()
        if url and url_alive(url):
            print("Tunnel already live:", url)
            return url

    url = start_cloudflare_tunnel()
    if url:
        return url

    print("Cloudflare tunnel unavailable, using LocalTunnel fallback...")
    return start_localtunnel()


def main() -> None:
    print("=" * 60)
    print("  Polymarket Paper Trading — one-click launch")
    print("=" * 60)

    ensure_deps()
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

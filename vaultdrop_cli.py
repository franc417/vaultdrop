#!/usr/bin/env python3
"""
vaultdrop CLI — seal and claim drops from the terminal

Usage:
  vaultdrop seal file.pdf --server http://localhost:5000
  vaultdrop seal file.pdf --pass mysecret --ttl 6 --burns 1
  vaultdrop claim http://localhost:5000/d/TOKEN#KEY
  vaultdrop claim http://localhost:5000/d/TOKEN --pass mysecret --out ./
  vaultdrop status http://localhost:5000/d/TOKEN
"""

import os
import sys
import json
import base64
import getpass
from pathlib import Path
from urllib.parse import urlparse

import click
import requests

DEFAULT_SERVER = os.environ.get("VAULTDROP_SERVER", "http://localhost:5000")


def fmt_size(n):
    if n < 1024: return f"{n} B"
    if n < 1048576: return f"{n/1024:.1f} KB"
    return f"{n/1048576:.1f} MB"


def fmt_ts(ts):
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def print_banner():
    click.echo(click.style(
        "  ╔══════════════════════════════╗\n"
        "  ║  🔒  vaultdrop  CLI          ║\n"
        "  ╚══════════════════════════════╝",
        fg="green"
    ))


@click.group()
def cli():
    """vaultdrop — one-time encrypted file sharing"""


@cli.command()
@click.argument("filepath", type=click.Path(exists=True, dir_okay=False))
@click.option("--server",    "-s", default=DEFAULT_SERVER, show_default=True, help="vaultdrop server URL")
@click.option("--pass",      "-p", "passphrase", default="", help="Passphrase (blank = auto-generate)")
@click.option("--ttl",       "-t", default=24,   show_default=True, help="Hours until expiry")
@click.option("--burns",     "-b", default=1,    show_default=True, help="Downloads before burn (1-10)")
@click.option("--prompt-pass", is_flag=True,     help="Prompt for passphrase securely")
def seal(filepath, server, passphrase, ttl, burns, prompt_pass):
    """Encrypt and upload a file to a vaultdrop server."""
    print_banner()

    if prompt_pass and not passphrase:
        passphrase = getpass.getpass("  Passphrase: ")

    fp = Path(filepath)
    size = fp.stat().st_size
    click.echo(f"\n  Sealing: {fp.name} ({fmt_size(size)})")
    click.echo(f"  Server:  {server}")
    click.echo(f"  TTL:     {ttl}h   Burns: {burns}")

    with fp.open("rb") as f:
        resp = requests.post(
            f"{server.rstrip('/')}/api/drop",
            files={"file": (fp.name, f)},
            data={
                "passphrase":  passphrase,
                "ttl":         ttl,
                "burn_count":  burns,
            },
            timeout=120,
        )

    if resp.status_code != 200:
        try:
            err = resp.json().get("error", resp.text)
        except Exception:
            err = resp.text
        click.echo(click.style(f"\n  ✕ Upload failed: {err}", fg="red"))
        sys.exit(1)

    data = resp.json()
    click.echo(click.style("\n  ✓ Drop sealed", fg="green"))
    click.echo(f"\n  Link:  {data['link']}")

    if data.get("passphrase"):
        click.echo(click.style(
            f"\n  ⚠  Passphrase: {data['passphrase']}", fg="yellow"
        ))
        click.echo(click.style(
            "     Send this separately — NEVER in the same channel as the link.",
            fg="yellow"
        ))
    else:
        click.echo(click.style(
            "\n  ℹ  Passphrase embedded in link fragment (not logged by server).",
            fg="cyan"
        ))

    click.echo(f"\n  Expires: {fmt_ts(data['expires_at'])}   Burns: ×{data['burn_count']}")


@cli.command()
@click.argument("url")
@click.option("--pass",   "-p", "passphrase", default="", help="Passphrase (overrides fragment)")
@click.option("--out",    "-o", default=".",  help="Output directory")
@click.option("--server", "-s", default=DEFAULT_SERVER, show_default=True)
def claim(url, passphrase, out, server):
    """Download and decrypt a drop. URL can include #passphrase fragment."""
    print_banner()

    # Parse URL — may have fragment key
    parsed   = urlparse(url)
    fragment = parsed.fragment.strip()
    token    = parsed.path.rstrip("/").split("/")[-1]

    if not passphrase and fragment:
        passphrase = fragment
        click.echo(f"  Key read from URL fragment.")
    elif not passphrase:
        passphrase = getpass.getpass("  Passphrase: ")

    # Reconstruct base URL without fragment
    base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else server

    click.echo(f"\n  Claiming token: {token[:16]}…")

    resp = requests.post(
        f"{base}/api/download/{token}",
        json={"passphrase": passphrase},
        timeout=120,
    )

    if resp.status_code == 403:
        click.echo(click.style("\n  ✕ Wrong passphrase.", fg="red"))
        sys.exit(1)
    elif resp.status_code != 200:
        try:
            err = resp.json().get("error", resp.text)
        except Exception:
            err = resp.text
        click.echo(click.style(f"\n  ✕ Failed: {err}", fg="red"))
        sys.exit(1)

    data     = resp.json()
    filename = data["filename"]
    raw      = base64.b64decode(data["data_b64"])

    out_path = Path(out) / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)

    click.echo(click.style(f"\n  ✓ Decrypted → {out_path}", fg="green"))
    click.echo(f"  Size: {fmt_size(len(raw))}")

    if data.get("burned"):
        click.echo(click.style(
            "  ⚑  Drop burned — permanently deleted from server.", fg="yellow"
        ))


@cli.command()
@click.argument("url")
@click.option("--server", "-s", default=DEFAULT_SERVER)
def status(url, server):
    """Check if a drop is still alive."""
    print_banner()
    parsed = urlparse(url)
    token  = parsed.path.rstrip("/").split("/")[-1]
    base   = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme else server

    resp = requests.get(f"{base}/api/status/{token}", timeout=10)
    data = resp.json()

    if not data.get("alive"):
        click.echo(click.style(f"\n  ✕ Drop is gone: {data.get('reason', 'unknown')}", fg="red"))
        return

    click.echo(click.style("\n  ✓ Drop is alive", fg="green"))
    click.echo(f"  File:      {data['filename']}  ({fmt_size(data['size'])})")
    click.echo(f"  Remaining: {data['remaining']} download(s)")
    click.echo(f"  Expires:   {fmt_ts(data['expires_at'])}")
    click.echo(f"  Password:  {'yes' if data['has_password'] else 'no (key in link)'}")


if __name__ == "__main__":
    cli()

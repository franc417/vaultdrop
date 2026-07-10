"""
vaultdrop v2 CLI — zero-knowledge: all encryption/decryption happens locally.
The server only ever receives/returns ciphertext.

Matches templates/vaultdrop.js exactly:
  - AES-256-GCM
  - PBKDF2-HMAC-SHA256, 600,000 iterations, 16-byte salt, 12-byte nonce
  - envelope = JSON({name, type, size, data: base64}) encrypted as one blob
  - verifier = HMAC-SHA256(derived_key, "vaultdrop-verify-v1") hex digest
"""

import base64
import hmac
import json
import os
import secrets
import sys
from getpass import getpass
from pathlib import Path

import click
import requests
from cryptography.hazmat.primitives import hashes, hmac as crypto_hmac
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

KDF_ITERATIONS = 600_000
VERIFIER_LABEL = b"vaultdrop-verify-v1"


def derive_key(passphrase: str, salt: bytes, iterations: int = KDF_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def compute_verifier(key: bytes) -> str:
    h = crypto_hmac.HMAC(key, hashes.SHA256())
    h.update(VERIFIER_LABEL)
    return h.finalize().hex()


def generate_passphrase() -> str:
    return secrets.token_urlsafe(24)


def encrypt_file(path: Path, passphrase: str):
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = derive_key(passphrase, salt)
    verifier = compute_verifier(key)

    envelope = json.dumps({
        "name": path.name,
        "type": "application/octet-stream",
        "size": path.stat().st_size,
        "data": base64.b64encode(path.read_bytes()).decode(),
    }).encode("utf-8")

    ciphertext = AESGCM(key).encrypt(nonce, envelope, None)
    return {
        "ciphertext": ciphertext,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "kdf_iterations": KDF_ITERATIONS,
        "verifier": verifier,
    }


def decrypt_blob(ciphertext: bytes, salt_b64: str, nonce_b64: str, iterations: int, passphrase: str):
    salt = base64.b64decode(salt_b64)
    nonce = base64.b64decode(nonce_b64)
    key = derive_key(passphrase, salt, iterations)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except Exception:
        raise click.ClickException("Decryption failed — wrong passphrase or corrupted data.")
    envelope = json.loads(plaintext)
    return envelope, key


@click.group()
@click.option("--server", default=os.environ.get("VAULTDROP_SERVER", "http://127.0.0.1:5000"),
              help="vaultdrop server URL")
@click.pass_context
def cli(ctx, server):
    """vaultdrop CLI — zero-knowledge one-time encrypted file sharing."""
    ctx.ensure_object(dict)
    ctx.obj["server"] = server.rstrip("/")


@cli.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--pass", "passphrase_opt", default=None, help="Passphrase (omit to auto-generate)")
@click.option("--prompt-pass", is_flag=True, help="Prompt for a passphrase (hidden input)")
@click.option("--ttl", default=24, help="Hours until expiry (max 168)")
@click.option("--burns", default=1, help="Max downloads before self-destruct (max 10)")
@click.pass_context
def seal(ctx, file, passphrase_opt, prompt_pass, ttl, burns):
    """Encrypt and upload FILE. Nothing unencrypted ever leaves this machine."""
    if prompt_pass:
        passphrase = getpass("Passphrase: ")
        auto = False
    elif passphrase_opt:
        passphrase = passphrase_opt
        auto = False
    else:
        passphrase = generate_passphrase()
        auto = True

    click.echo(f"Encrypting {file.name} locally (AES-256-GCM)…")
    enc = encrypt_file(file, passphrase)

    resp = requests.post(
        f"{ctx.obj['server']}/api/drop",
        files={"blob": ("blob", enc["ciphertext"])},
        data={
            "salt": enc["salt"], "nonce": enc["nonce"],
            "kdf_iterations": enc["kdf_iterations"], "verifier": enc["verifier"],
            "ttl": ttl, "burn_count": burns,
        },
        timeout=60,
    )
    if not resp.ok:
        raise click.ClickException(f"Upload failed: {resp.json().get('error', resp.text)}")

    data = resp.json()
    link = f"{ctx.obj['server']}{data['path']}"
    if auto:
        link += f"#{passphrase}"
        click.echo(click.style("\n⚠️  Passphrase is embedded in this link — the link IS the secret:", fg="yellow"))
    else:
        click.echo(click.style("\n⚠️  Send the link and passphrase over DIFFERENT channels:", fg="yellow"))

    click.echo(f"\n  {click.style(link, fg='green')}\n")
    if not auto:
        click.echo(f"  Passphrase: {passphrase}")
    click.echo(f"  Expires: {ttl}h · Burns after {burns} download(s)")


@cli.command()
@click.argument("link")
@click.option("--out", type=click.Path(path_type=Path), default=None, help="Output path (default: original filename)")
@click.pass_context
def claim(ctx, link, out):
    """Download and decrypt a vaultdrop LINK (full URL, including any #fragment)."""
    if "#" in link:
        base, passphrase = link.split("#", 1)
    else:
        base, passphrase = link, getpass("Passphrase: ")

    token = base.rstrip("/").split("/")[-1]
    server = ctx.obj["server"]

    meta_resp = requests.get(f"{server}/api/meta/{token}", timeout=30)
    if not meta_resp.ok:
        raise click.ClickException(f"Drop unavailable: {meta_resp.json().get('reason', 'unknown')}")
    meta = meta_resp.json()

    key = derive_key(passphrase, base64.b64decode(meta["salt"]), meta["kdf_iterations"])
    verifier = compute_verifier(key)

    dl_resp = requests.post(f"{server}/api/download/{token}", json={"verifier": verifier}, timeout=60)
    if not dl_resp.ok:
        err = dl_resp.json()
        if "attempts_remaining" in err:
            raise click.ClickException(f"Wrong passphrase ({err['attempts_remaining']} attempt(s) left).")
        raise click.ClickException(err.get("error", "Download failed"))

    dl_data = dl_resp.json()
    ciphertext = base64.b64decode(dl_data["blob_b64"])
    envelope, _ = decrypt_blob(ciphertext, meta["salt"], meta["nonce"], meta["kdf_iterations"], passphrase)

    out_path = out or Path(envelope["name"])
    out_path.write_bytes(base64.b64decode(envelope["data"]))
    click.echo(f"✅ Decrypted → {out_path} ({envelope['size']} bytes)")
    if dl_data.get("burned"):
        click.echo("   This drop has now been destroyed.")


@cli.command()
@click.argument("link")
@click.pass_context
def status(ctx, link):
    """Check whether a drop is still alive, without consuming it."""
    token = link.rstrip("/").split("#")[0].split("/")[-1]
    resp = requests.get(f"{ctx.obj['server']}/api/status/{token}", timeout=30)
    data = resp.json()
    if not data.get("alive"):
        click.echo(f"Not available ({data.get('reason', 'unknown')})")
        return
    click.echo(f"Alive — {data['size']} bytes, {data['remaining']} download(s) remaining, "
               f"expires at {data['expires_at']}")


if __name__ == "__main__":
    cli(obj={})

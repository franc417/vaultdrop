"""
vaultdrop — one-time encrypted file sharing server
Usage: python server.py [--host 0.0.0.0] [--port 5000]
"""

import os
import uuid
import time
import json
import hashlib
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask, request, jsonify, send_file, render_template,
    abort, redirect, url_for
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import base64
import click

app = Flask(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR    = Path(os.environ.get("VAULTDROP_DIR", Path.home() / ".vaultdrop"))
DB_PATH     = BASE_DIR / "vault.db"
STORE_PATH  = BASE_DIR / "store"
MAX_BYTES   = int(os.environ.get("VAULTDROP_MAX_MB", 100)) * 1024 * 1024
DEFAULT_TTL = int(os.environ.get("VAULTDROP_TTL_H", 24))       # hours
SECRET_KEY  = os.environ.get("VAULTDROP_SECRET", os.urandom(32).hex())

BASE_DIR.mkdir(parents=True, exist_ok=True)
STORE_PATH.mkdir(parents=True, exist_ok=True)

# ── Database ─────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS drops (
                token       TEXT PRIMARY KEY,
                filename    TEXT NOT NULL,
                size        INTEGER NOT NULL,
                content_type TEXT,
                nonce       BLOB NOT NULL,
                salt        BLOB NOT NULL,
                has_password INTEGER DEFAULT 0,
                burn_count  INTEGER DEFAULT 1,
                download_count INTEGER DEFAULT 0,
                created_at  REAL NOT NULL,
                expires_at  REAL NOT NULL,
                ip_created  TEXT
            )
        """)
        db.commit()

init_db()

# ── Crypto helpers ────────────────────────────────────────────────────────────
def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive AES-256 key from passphrase + salt via PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=260_000,
    )
    return kdf.derive(passphrase.encode())

def encrypt_file(data: bytes, passphrase: str) -> tuple[bytes, bytes, bytes]:
    """Encrypt with AES-256-GCM. Returns (ciphertext, nonce, salt)."""
    salt  = os.urandom(16)
    nonce = os.urandom(12)
    key   = derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, data, None)
    return ct, nonce, salt

def decrypt_file(ciphertext: bytes, nonce: bytes, salt: bytes, passphrase: str) -> bytes:
    """Decrypt AES-256-GCM. Raises ValueError on wrong passphrase."""
    key = derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except Exception:
        raise ValueError("Decryption failed — wrong passphrase or corrupted file.")

def random_passphrase() -> str:
    """Generate a secure random passphrase (hex, 32 bytes = 64 chars)."""
    return base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip("=")

# ── Cleanup thread ────────────────────────────────────────────────────────────
def cleanup_expired():
    while True:
        time.sleep(300)  # every 5 minutes
        now = time.time()
        with get_db() as db:
            expired = db.execute(
                "SELECT token FROM drops WHERE expires_at < ?", (now,)
            ).fetchall()
            for row in expired:
                fp = STORE_PATH / row["token"]
                if fp.exists():
                    fp.unlink()
                db.execute("DELETE FROM drops WHERE token = ?", (row["token"],))
            db.commit()

threading.Thread(target=cleanup_expired, daemon=True).start()

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html",
        max_mb=MAX_BYTES // (1024*1024),
        default_ttl=DEFAULT_TTL)

@app.route("/api/drop", methods=["POST"])
def create_drop():
    """Upload endpoint. Encrypts server-side with caller-supplied or generated key."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    data = f.read()
    if len(data) > MAX_BYTES:
        return jsonify({"error": f"File exceeds {MAX_BYTES//(1024*1024)} MB limit"}), 413

    passphrase  = request.form.get("passphrase", "").strip() or random_passphrase()
    ttl_hours   = min(int(request.form.get("ttl", DEFAULT_TTL)), 168)  # max 7 days
    burn_count  = min(int(request.form.get("burn_count", 1)), 10)
    has_password = bool(request.form.get("passphrase", "").strip())

    ciphertext, nonce, salt = encrypt_file(data, passphrase)

    token = uuid.uuid4().hex
    filepath = STORE_PATH / token
    filepath.write_bytes(ciphertext)

    now = time.time()
    with get_db() as db:
        db.execute("""
            INSERT INTO drops
            (token, filename, size, content_type, nonce, salt,
             has_password, burn_count, download_count, created_at, expires_at, ip_created)
            VALUES (?,?,?,?,?,?,?,?,0,?,?,?)
        """, (
            token, f.filename, len(data),
            f.content_type or "application/octet-stream",
            nonce, salt, int(has_password), burn_count,
            now, now + ttl_hours * 3600,
            request.remote_addr
        ))
        db.commit()

    # Return token + passphrase (if auto-generated, caller must save it)
    scheme = request.scheme
    host   = request.host
    link   = f"{scheme}://{host}/d/{token}"
    if not has_password:
        link += f"#{passphrase}"   # key in fragment — never sent to server on access

    return jsonify({
        "token":       token,
        "link":        link,
        "passphrase":  passphrase if not has_password else None,
        "filename":    f.filename,
        "size":        len(data),
        "expires_at":  now + ttl_hours * 3600,
        "burn_count":  burn_count,
        "has_password": has_password,
    })


@app.route("/d/<token>")
def drop_page(token):
    """Serve the download page. Passphrase may be in the URL fragment (JS reads it)."""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM drops WHERE token = ?", (token,)
        ).fetchone()

    if not row:
        return render_template("gone.html", reason="This drop does not exist or has already been claimed."), 404

    if time.time() > row["expires_at"]:
        return render_template("gone.html", reason="This drop has expired."), 410

    remaining = row["burn_count"] - row["download_count"]
    if remaining <= 0:
        return render_template("gone.html", reason="This drop has already been downloaded."), 410

    expires_str = datetime.fromtimestamp(row["expires_at"]).strftime("%Y-%m-%d %H:%M UTC")
    return render_template("drop.html",
        token=token,
        filename=row["filename"],
        size=row["size"],
        expires=expires_str,
        remaining=remaining,
        has_password=bool(row["has_password"]),
    )


@app.route("/api/download/<token>", methods=["POST"])
def download_drop(token):
    """Decrypt and serve the file. Deletes after burn_count reached."""
    passphrase = request.json.get("passphrase", "").strip() if request.is_json else ""

    with get_db() as db:
        row = db.execute(
            "SELECT * FROM drops WHERE token = ?", (token,)
        ).fetchone()

        if not row:
            return jsonify({"error": "Not found"}), 404

        if time.time() > row["expires_at"]:
            return jsonify({"error": "Expired"}), 410

        if row["download_count"] >= row["burn_count"]:
            return jsonify({"error": "Already downloaded"}), 410

        ciphertext = (STORE_PATH / token).read_bytes()

        try:
            plaintext = decrypt_file(
                ciphertext,
                bytes(row["nonce"]),
                bytes(row["salt"]),
                passphrase
            )
        except ValueError:
            return jsonify({"error": "Wrong passphrase"}), 403

        # Increment counter and maybe delete
        new_count = row["download_count"] + 1
        db.execute(
            "UPDATE drops SET download_count = ? WHERE token = ?",
            (new_count, token)
        )
        db.commit()

        if new_count >= row["burn_count"]:
            (STORE_PATH / token).unlink(missing_ok=True)
            db.execute("DELETE FROM drops WHERE token = ?", (token,))
            db.commit()

    # Return as base64 JSON so JS can trigger download without a page redirect
    return jsonify({
        "filename":     row["filename"],
        "content_type": row["content_type"],
        "data_b64":     base64.b64encode(plaintext).decode(),
        "burned":       new_count >= row["burn_count"],
    })


@app.route("/api/status/<token>")
def drop_status(token):
    """Check if a drop is still alive (no passphrase needed)."""
    with get_db() as db:
        row = db.execute(
            "SELECT token, filename, size, expires_at, burn_count, download_count, has_password "
            "FROM drops WHERE token = ?", (token,)
        ).fetchone()

    if not row:
        return jsonify({"alive": False, "reason": "not_found"}), 404

    if time.time() > row["expires_at"]:
        return jsonify({"alive": False, "reason": "expired"}), 410

    remaining = row["burn_count"] - row["download_count"]
    if remaining <= 0:
        return jsonify({"alive": False, "reason": "burned"}), 410

    return jsonify({
        "alive":        True,
        "filename":     row["filename"],
        "size":         row["size"],
        "expires_at":   row["expires_at"],
        "remaining":    remaining,
        "has_password": bool(row["has_password"]),
    })


# ── CLI entry point ────────────────────────────────────────────────────────────
@click.group()
def cli():
    """vaultdrop — one-time encrypted file sharing"""

@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=5000, show_default=True)
@click.option("--debug", is_flag=True)
def serve(host, port, debug):
    """Start the vaultdrop server."""
    click.echo(f"🔒 vaultdrop server → http://{host}:{port}")
    click.echo(f"   Store: {STORE_PATH}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        sys.argv.pop(1)
        cli()
    else:
        app.run(host="127.0.0.1", port=5000, debug=True)

"""
vaultdrop v2 — zero-knowledge one-time encrypted file sharing server

v1 -> v2 security patches:
  - TRUE end-to-end encryption. The server never receives a plaintext file,
    a passphrase, or a key. All AES-256-GCM encryption/decryption happens
    client-side (browser WebCrypto or the CLI). The server only ever stores
    and relays opaque ciphertext.
  - Key-possession verifier (HMAC-SHA256) gates downloads/burns without the
    server ever learning the key — prevents "download without knowing the
    key still burns the drop" and enables safe attempt-limiting.
  - Per-IP + per-token rate limiting (flask-limiter) on all endpoints.
  - Lockout: N consecutive failed verifier attempts on a token permanently
    destroys the drop (defeats online brute-forcing of the passphrase).
  - MAX_CONTENT_LENGTH enforced by Flask/Werkzeug BEFORE the body is fully
    read, not after (v1 read the whole upload into memory first).
  - debug=True is never the default under any code path.
  - Security headers (HSTS, CSP, X-Frame-Options, etc.) on every response.
  - ProxyFix for correct client IPs behind a reverse proxy (required for
    rate limiting to mean anything once you put this behind nginx/Caddy).
  - Structured logging that never logs secrets (keys, verifiers, passphrases
    never reach the server anyway, but tokens are truncated in logs too).
  - Constant-time verifier comparison (hmac.compare_digest).
Usage: python server.py serve [--host 0.0.0.0] [--port 5000]
"""

from __future__ import annotations

import base64
import hmac
import logging
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import click
from flask import Flask, abort, jsonify, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

# ── Config ────────────────────────────────────────────────────────────────
BASE_DIR = Path(os.environ.get("VAULTDROP_DIR", Path.home() / ".vaultdrop"))
DB_PATH = BASE_DIR / "vault.db"
STORE_PATH = BASE_DIR / "store"
MAX_MB = int(os.environ.get("VAULTDROP_MAX_MB", 100))
MAX_BYTES = MAX_MB * 1024 * 1024
DEFAULT_TTL_H = int(os.environ.get("VAULTDROP_TTL_H", 24))
MAX_TTL_H = 168  # 7 days
MAX_BURNS = 10
MAX_FAILED_ATTEMPTS = 5  # verifier mismatches before the drop self-destructs
TRUST_PROXY = os.environ.get("VAULTDROP_TRUST_PROXY", "0") == "1"

BASE_DIR.mkdir(parents=True, exist_ok=True)
STORE_PATH.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=os.environ.get("VAULTDROP_LOG_LEVEL", "INFO"),
    format="%(asctime)s vaultdrop %(levelname)s %(message)s",
)
log = logging.getLogger("vaultdrop")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES + (256 * 1024)  # + envelope overhead

if TRUST_PROXY:
    # Only enable this if vaultdrop is actually behind a trusted reverse
    # proxy (nginx/Caddy) that sets X-Forwarded-For itself — otherwise a
    # client can spoof this header and defeat IP-based rate limiting.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(get_remote_address, app=app, default_limits=["200/hour"])
    HAVE_LIMITER = True
except ImportError:  # pragma: no cover
    log.warning("flask-limiter not installed — rate limiting is DISABLED. "
                "Run: pip install flask-limiter")
    HAVE_LIMITER = False

    class _NoopLimiter:
        def limit(self, *a, **kw):
            def deco(f):
                return f
            return deco

    limiter = _NoopLimiter()


def short(token: str) -> str:
    """Truncated token for safe logging."""
    return token[:8] + "…"


# ── Security headers ─────────────────────────────────────────────────────
@app.after_request
def set_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
        "img-src 'self' data:;"
    )
    if request.is_secure or TRUST_PROXY:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


# ── Database ──────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS drops (
                token           TEXT PRIMARY KEY,
                blob_size       INTEGER NOT NULL,
                salt            BLOB NOT NULL,
                nonce           BLOB NOT NULL,
                kdf_iterations  INTEGER NOT NULL,
                verifier        TEXT NOT NULL,
                burn_count      INTEGER DEFAULT 1,
                download_count  INTEGER DEFAULT 0,
                failed_attempts INTEGER DEFAULT 0,
                created_at      REAL NOT NULL,
                expires_at      REAL NOT NULL,
                ip_created      TEXT
            )
        """)
        db.commit()


init_db()


# ── Cleanup thread ───────────────────────────────────────────────────────
def cleanup_expired():
    while True:
        time.sleep(300)
        now = time.time()
        with get_db() as db:
            expired = db.execute(
                "SELECT token FROM drops WHERE expires_at < ?", (now,)
            ).fetchall()
            for row in expired:
                (STORE_PATH / row["token"]).unlink(missing_ok=True)
                db.execute("DELETE FROM drops WHERE token = ?", (row["token"],))
            if expired:
                log.info("cleanup: purged %d expired drop(s)", len(expired))
            db.commit()


threading.Thread(target=cleanup_expired, daemon=True).start()


def destroy_drop(db, token: str):
    (STORE_PATH / token).unlink(missing_ok=True)
    db.execute("DELETE FROM drops WHERE token = ?", (token,))
    db.commit()


# ── Routes ────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", max_mb=MAX_MB, default_ttl=DEFAULT_TTL_H,
                            max_ttl=MAX_TTL_H, max_burns=MAX_BURNS)


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/api/drop", methods=["POST"])
@limiter.limit("10/minute")
def create_drop():
    """
    Accepts an already-encrypted blob. The server never sees plaintext,
    the passphrase, or the derived key — only ciphertext + the crypto
    parameters needed to describe it (salt, nonce, iteration count) and
    a verifier that proves *future* key possession without revealing it.
    """
    if "blob" not in request.files:
        return jsonify({"error": "No encrypted blob provided"}), 400

    blob = request.files["blob"]
    data = blob.read()
    if not data:
        return jsonify({"error": "Empty upload"}), 400
    if len(data) > MAX_BYTES:
        return jsonify({"error": f"Encrypted payload exceeds {MAX_MB} MB limit"}), 413

    try:
        salt = base64.b64decode(request.form["salt"])
        nonce = base64.b64decode(request.form["nonce"])
        kdf_iterations = int(request.form["kdf_iterations"])
        verifier = request.form["verifier"].strip().lower()
    except (KeyError, ValueError):
        return jsonify({"error": "Missing or malformed crypto parameters"}), 400

    if not (10_000 <= kdf_iterations <= 5_000_000):
        return jsonify({"error": "kdf_iterations out of acceptable range"}), 400
    if len(verifier) != 64 or any(c not in "0123456789abcdef" for c in verifier):
        return jsonify({"error": "Malformed verifier"}), 400
    if len(salt) != 16 or len(nonce) != 12:
        return jsonify({"error": "Malformed salt/nonce"}), 400

    try:
        ttl_hours = min(max(int(request.form.get("ttl", DEFAULT_TTL_H)), 1), MAX_TTL_H)
        burn_count = min(max(int(request.form.get("burn_count", 1)), 1), MAX_BURNS)
    except ValueError:
        return jsonify({"error": "Invalid ttl/burn_count"}), 400

    token = secrets.token_urlsafe(24)
    (STORE_PATH / token).write_bytes(data)

    now = time.time()
    with get_db() as db:
        db.execute("""
            INSERT INTO drops
            (token, blob_size, salt, nonce, kdf_iterations, verifier,
             burn_count, download_count, failed_attempts, created_at, expires_at, ip_created)
            VALUES (?,?,?,?,?,?,?,0,0,?,?,?)
        """, (
            token, len(data), salt, nonce, kdf_iterations, verifier,
            burn_count, now, now + ttl_hours * 3600,
            get_remote_address() if HAVE_LIMITER else request.remote_addr,
        ))
        db.commit()

    log.info("drop created token=%s size=%d ttl=%dh burns=%d",
              short(token), len(data), ttl_hours, burn_count)

    return jsonify({
        "token": token,
        "path": f"/d/{token}",
        "blob_size": len(data),
        "expires_at": now + ttl_hours * 3600,
        "burn_count": burn_count,
    })


@app.route("/d/<token>")
@limiter.limit("60/minute")
def drop_page(token):
    """Static shell — all decryption happens client-side in JS."""
    with get_db() as db:
        row = db.execute("SELECT * FROM drops WHERE token = ?", (token,)).fetchone()

    if not row:
        return render_template("gone.html", reason="This drop does not exist or has already been claimed."), 404
    if time.time() > row["expires_at"]:
        return render_template("gone.html", reason="This drop has expired."), 410
    remaining = row["burn_count"] - row["download_count"]
    if remaining <= 0:
        return render_template("gone.html", reason="This drop has already been claimed."), 410

    return render_template("drop.html", token=token)


@app.route("/api/meta/<token>")
@limiter.limit("30/minute")
def drop_meta(token):
    """Non-destructive: crypto parameters + status, no verifier required."""
    with get_db() as db:
        row = db.execute(
            "SELECT token, blob_size, salt, nonce, kdf_iterations, burn_count, "
            "download_count, expires_at FROM drops WHERE token = ?", (token,)
        ).fetchone()

    if not row:
        return jsonify({"alive": False, "reason": "not_found"}), 404
    if time.time() > row["expires_at"]:
        return jsonify({"alive": False, "reason": "expired"}), 410
    remaining = row["burn_count"] - row["download_count"]
    if remaining <= 0:
        return jsonify({"alive": False, "reason": "claimed"}), 410

    return jsonify({
        "alive": True,
        "blob_size": row["blob_size"],
        "salt": base64.b64encode(row["salt"]).decode(),
        "nonce": base64.b64encode(row["nonce"]).decode(),
        "kdf_iterations": row["kdf_iterations"],
        "remaining": remaining,
        "expires_at": row["expires_at"],
    })


# Alias kept for the CLI's `status` command (no crypto params, cheap check)
@app.route("/api/status/<token>")
@limiter.limit("30/minute")
def drop_status(token):
    with get_db() as db:
        row = db.execute(
            "SELECT blob_size, burn_count, download_count, expires_at FROM drops WHERE token = ?",
            (token,)
        ).fetchone()
    if not row:
        return jsonify({"alive": False, "reason": "not_found"}), 404
    if time.time() > row["expires_at"]:
        return jsonify({"alive": False, "reason": "expired"}), 410
    remaining = row["burn_count"] - row["download_count"]
    if remaining <= 0:
        return jsonify({"alive": False, "reason": "claimed"}), 410
    return jsonify({
        "alive": True, "size": row["blob_size"], "remaining": remaining,
        "expires_at": row["expires_at"],
    })


@app.route("/api/download/<token>", methods=["POST"])
@limiter.limit("10/minute")
def download_drop(token):
    """
    Releases ciphertext ONLY if the caller proves key possession via the
    HMAC verifier computed client-side. Wrong verifiers count against a
    lockout threshold; the drop self-destructs after MAX_FAILED_ATTEMPTS
    to defeat online brute-forcing of a weak passphrase.
    """
    body = request.get_json(silent=True) or {}
    supplied_verifier = str(body.get("verifier", "")).strip().lower()

    with get_db() as db:
        row = db.execute("SELECT * FROM drops WHERE token = ?", (token,)).fetchone()

        if not row:
            return jsonify({"error": "Not found"}), 404
        if time.time() > row["expires_at"]:
            destroy_drop(db, token)
            return jsonify({"error": "Expired"}), 410
        if row["download_count"] >= row["burn_count"]:
            return jsonify({"error": "Already claimed"}), 410

        valid = hmac.compare_digest(supplied_verifier, row["verifier"])

        if not valid:
            attempts = row["failed_attempts"] + 1
            if attempts >= MAX_FAILED_ATTEMPTS:
                log.warning("token=%s destroyed after %d failed attempts", short(token), attempts)
                destroy_drop(db, token)
                return jsonify({"error": "Too many failed attempts — drop destroyed"}), 403
            db.execute("UPDATE drops SET failed_attempts = ? WHERE token = ?", (attempts, token))
            db.commit()
            return jsonify({
                "error": "Wrong key",
                "attempts_remaining": MAX_FAILED_ATTEMPTS - attempts,
            }), 403

        ciphertext = (STORE_PATH / token).read_bytes()
        new_count = row["download_count"] + 1
        burned = new_count >= row["burn_count"]
        if burned:
            destroy_drop(db, token)
        else:
            db.execute("UPDATE drops SET download_count = ?, failed_attempts = 0 WHERE token = ?",
                       (new_count, token))
            db.commit()

    log.info("drop claimed token=%s burned=%s", short(token), burned)
    return jsonify({
        "blob_b64": base64.b64encode(ciphertext).decode(),
        "burned": burned,
    })


# ── CLI entry point ─────────────────────────────────────────────────────
@click.group()
def cli():
    """vaultdrop — zero-knowledge one-time encrypted file sharing"""


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=5000, show_default=True)
@click.option("--debug", is_flag=True, help="NEVER use in production.")
def serve(host, port, debug):
    """Start the vaultdrop server (Flask dev server — use gunicorn in production)."""
    if debug:
        log.warning("Starting with debug=True — do NOT expose this to the internet.")
    click.echo(f"🔒 vaultdrop v2 → http://{host}:{port}")
    click.echo(f"   Store: {STORE_PATH}")
    click.echo(f"   Rate limiting: {'enabled' if HAVE_LIMITER else 'DISABLED (install flask-limiter)'}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    cli()

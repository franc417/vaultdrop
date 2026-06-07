# 🔒 vaultdrop

> **One-time encrypted file sharing — burn after read, self-hosted.**

Share a file. Someone downloads it. It's gone. Forever.

vaultdrop is a lightweight, self-hosted file-drop server that encrypts every upload with **AES-256-GCM**, generates a one-time link, and permanently deletes the file the moment it is claimed. No cloud. No accounts. No trace.

---

## ✨ Features

| | |
|---|---|
| 🔐 **AES-256-GCM encryption** | Every file is encrypted server-side before it touches disk |
| 🔑 **PBKDF2 key derivation** | 260 000 iterations of SHA-256 — brute-force resistant |
| 🔥 **Burn after read** | File and record are wiped on download (configurable 1–10 burns) |
| ⏱️ **Configurable TTL** | Drops expire automatically — default 24 h, max 7 days |
| 🔗 **Passphrase-in-fragment** | Auto-generated keys live in the URL `#fragment` — never sent to the server |
| 🌐 **Web UI** | Clean browser interface — no client install needed for recipients |
| 💻 **CLI** | `vaultdrop-cli seal / claim / status` for terminal workflows |
| 🤖 **Universal installer** | One script covers Arch, Ubuntu, Fedora, macOS, and **Termux** |
| 🧹 **Auto-cleanup daemon** | Background thread purges expired drops every 5 minutes |
| 📦 **Zero external DB** | SQLite — runs anywhere, zero config |

---

## 📁 Project Structure

```
vaultdrop/
├── server.py           # Flask server — API + web routes + crypto + cleanup
├── vaultdrop_cli.py    # Click-based CLI (seal / claim / status)
├── install.sh          # Universal installer (Linux / macOS / Termux)
├── requirements.txt    # Python dependencies
└── templates/
    ├── index.html      # Upload page
    ├── drop.html       # Download / claim page
    └── gone.html       # Expired / burned drop page
```

---

## 🚀 Quick Install

### One-liner (Linux / macOS / Termux)

```bash
curl -fsSL https://raw.githubusercontent.com/franc417/vaultdrop/main/install.sh | bash
```

The installer auto-detects your environment and handles everything:

| Platform | Package manager | Service |
|---|---|---|
| Arch Linux / Manjaro | `pacman` | systemd |
| Ubuntu / Debian / Mint | `apt` | systemd |
| Fedora / RHEL / CentOS | `dnf` | systemd |
| openSUSE | `zypper` | systemd |
| macOS | Homebrew | launchd |
| Android (Termux) | `pkg` | termux-boot + tmux |

### Local install (from a clone)

```bash
git clone https://github.com/franc417/vaultdrop.git
cd vaultdrop
chmod +x install.sh
./install.sh
```

### Installer options

```bash
./install.sh --dir /opt/vaultdrop   # custom install path
./install.sh --port 8080            # custom port (default: 5000)
./install.sh --max-mb 250           # raise upload limit (default: 100 MB)
./install.sh --start                # start server immediately after install
./install.sh --uninstall            # remove everything (data preserved)
```

### Environment variables

```bash
VAULTDROP_PORT=5000       # server port
VAULTDROP_MAX_MB=100      # max upload size in MB
VAULTDROP_TTL_H=24        # default drop lifetime in hours
VAULTDROP_DIR=~/.vaultdrop  # data directory (DB + encrypted store)
VAULTDROP_SECRET=<hex>    # Flask secret key (auto-generated if unset)
```

---

## 🔧 Manual Setup

If you prefer not to use the installer:

```bash
git clone https://github.com/franc417/vaultdrop.git
cd vaultdrop

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python server.py          # starts on http://127.0.0.1:5000
# or
python server.py serve --host 0.0.0.0 --port 5000
```

---

## 🌐 Web UI Usage

1. Open `http://localhost:5000` in your browser.
2. Drag and drop (or select) a file.
3. Optionally set a passphrase, TTL, and burn count.
4. Hit **Seal** — you get a one-time link.
5. Share the link. When the recipient opens it and clicks **Claim**, the file is decrypted and delivered — then permanently deleted.

---

## 💻 CLI Usage

### `vaultdrop-cli seal` — encrypt and upload a file

```bash
# Auto-generate a passphrase (embedded in the link fragment)
vaultdrop-cli seal report.pdf

# Custom passphrase, 6-hour TTL, 1 burn
vaultdrop-cli seal report.pdf --pass mysecret --ttl 6 --burns 1

# Prompt securely (no passphrase in shell history)
vaultdrop-cli seal report.pdf --prompt-pass

# Target a remote server
vaultdrop-cli seal report.pdf --server https://drop.example.com
```

**Output:**

```
 ╔══════════════════════════════╗
 ║ 🔒 vaultdrop CLI            ║
 ╚══════════════════════════════╝

  Sealing: report.pdf (2.1 MB)
  Server:  http://localhost:5000
  TTL: 24h  Burns: ×1

  ✓ Drop sealed

  Link: http://localhost:5000/d/a3f9b1c2d8e4f7a0#K2pXmNqRvTyWzUjL

  ⚠ Passphrase: K2pXmNqRvTyWzUjL
    Send this separately — NEVER in the same channel as the link.

  Expires: 2026-06-08 14:32  Burns: ×1
```

---

### `vaultdrop-cli claim` — download and decrypt

```bash
# Passphrase read automatically from URL fragment
vaultdrop-cli claim "http://localhost:5000/d/a3f9b1c2d8e4f7a0#K2pXmNqRvTyWzUjL"

# Manual passphrase
vaultdrop-cli claim "http://localhost:5000/d/a3f9b1c2d8e4f7a0" --pass mysecret

# Save to a specific directory
vaultdrop-cli claim "<url>" --out ~/Downloads/
```

---

### `vaultdrop-cli status` — check if a drop is still alive

```bash
vaultdrop-cli status "http://localhost:5000/d/a3f9b1c2d8e4f7a0"
```

```
  ✓ Drop is alive
    File:      report.pdf (2.1 MB)
    Remaining: 1 download(s)
    Expires:   2026-06-08 14:32
    Password:  no (key in link)
```

---

## 🔌 REST API

The server exposes a simple JSON API for programmatic use.

### `POST /api/drop` — upload a file

**Form fields:**

| Field | Type | Default | Description |
|---|---|---|---|
| `file` | file | required | The file to upload |
| `passphrase` | string | auto | Custom passphrase (omit for auto) |
| `ttl` | int | 24 | Lifetime in hours (max 168) |
| `burn_count` | int | 1 | Downloads before deletion (max 10) |

**Response:**

```json
{
  "token": "a3f9b1c2d8e4f7a0",
  "link": "http://localhost:5000/d/a3f9b1c2d8e4f7a0#K2pXmNqRvTyWzUjL",
  "passphrase": "K2pXmNqRvTyWzUjL",
  "filename": "report.pdf",
  "size": 2162688,
  "expires_at": 1749470400.0,
  "burn_count": 1,
  "has_password": false
}
```

> When `has_password` is `false`, the passphrase is returned and embedded in the `link` fragment. It is never transmitted to the server on access — only read by the recipient's browser JavaScript.

---

### `POST /api/download/<token>` — claim and decrypt

```bash
curl -X POST http://localhost:5000/api/download/<token> \
  -H "Content-Type: application/json" \
  -d '{"passphrase": "K2pXmNqRvTyWzUjL"}'
```

**Response:**

```json
{
  "filename": "report.pdf",
  "content_type": "application/pdf",
  "data_b64": "<base64-encoded plaintext>",
  "burned": true
}
```

---

### `GET /api/status/<token>` — check drop state

```bash
curl http://localhost:5000/api/status/<token>
```

```json
{
  "alive": true,
  "filename": "report.pdf",
  "size": 2162688,
  "expires_at": 1749470400.0,
  "remaining": 1,
  "has_password": false
}
```

---

## 🔐 Security Model

```
Sender                          Server                      Recipient
──────                          ──────                      ─────────
                                
File ──→ AES-256-GCM encrypt ──→ Ciphertext on disk
         PBKDF2 (260k SHA-256)
         random nonce + salt
                                
Link = /d/<token>#<passphrase>
                               ← fragment never hits server
                                                        ← passphrase from fragment
                                Decrypt in memory ──────────────→ Plaintext
                                Delete ciphertext
                                Delete DB record
```

**Key design decisions:**

- The **encryption key** is derived from the passphrase via PBKDF2-SHA256 (260 000 iterations). The passphrase itself is never stored.
- When using auto-generated keys, the passphrase lives only in the URL `#fragment`. Fragments are not sent in HTTP requests — the server never sees it.
- Ciphertext and the SQLite record are **deleted immediately** once the burn count is reached. There is no soft-delete.
- A background cleanup thread runs every 5 minutes to purge expired drops even if they were never claimed.
- `VAULTDROP_SECRET` should be set to a stable value in production to avoid session issues across restarts.

> **Note:** vaultdrop is designed for trusted LAN/VPN use or behind a reverse proxy (nginx/caddy) with TLS. Do not expose it directly to the internet without HTTPS — the link fragment provides no protection over plain HTTP.

---

## 🏃 Running on Termux (Android)

vaultdrop runs natively in Termux — no root required.

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/franc417/vaultdrop/main/install.sh | bash

# Start in a tmux background session (survives terminal close)
vaultdrop-bg

# Start in foreground
vaultdrop

# Access from the same phone
http://localhost:5000

# Access from other devices on the same LAN
http://<PHONE_IP>:5000
```

Auto-start on boot requires `termux-boot`:

```bash
pkg install termux-boot
./install.sh   # re-run — will detect and configure boot script
```

---

## 🔄 Service Management

**systemd (Linux):**

```bash
sudo systemctl start vaultdrop
sudo systemctl stop vaultdrop
sudo systemctl status vaultdrop
journalctl -u vaultdrop -f        # live logs
```

**launchd (macOS):**

```bash
launchctl start com.franc417.vaultdrop
launchctl stop com.franc417.vaultdrop
tail -f ~/.vaultdrop/logs/vaultdrop.log
```

**Termux:**

```bash
vaultdrop-bg               # start in tmux session
tmux attach -t vaultdrop   # attach to view logs
```

---

## 🗑️ Uninstall

```bash
./install.sh --uninstall
```

This removes the installed files, CLI wrappers, and service. Your data directory (`~/.vaultdrop/`) is **intentionally preserved**. Remove it manually if needed:

```bash
rm -rf ~/.vaultdrop
```

---

## 📦 Dependencies

```
flask>=3.0
cryptography>=42.0
click>=8.0
requests>=2.31
```

Python 3.10+ recommended. All other dependencies (SQLite, `uuid`, `threading`) are from the standard library.

---

## 📄 License

MIT — do whatever you want, just don't blame me.

---

*Built by [franc417](https://github.com/franc417)*

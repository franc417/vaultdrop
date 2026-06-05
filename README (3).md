# vaultdrop 🔒

A self-hosted, one-time encrypted file sharing tool. Drop a file, get a link. Once downloaded, it's gone.

```
  ╔══════════════════════════════╗
  ║  🔒  vaultdrop               ║
  ║  one-time encrypted sharing  ║
  ╚══════════════════════════════╝
```

## Features

- **AES-256-GCM encryption** — PBKDF2-derived key (260k iterations), file never stored in plaintext
- **Burn after read** — file permanently deleted after N downloads (default: 1)
- **TTL expiry** — auto-delete after 1h / 6h / 24h / 7d
- **Fragment keys** — auto-generated passphrase lives in URL fragment (`#key`), never logged by server
- **Custom passphrase** — recipient needs a separate passphrase you share via a different channel
- **CLI + Web UI** — seal/claim from terminal or browser
- **Termux-friendly** — runs on Android via Termux
- **Zero accounts, zero telemetry, zero cloud**

## Install

```bash
git clone https://github.com/franc417/vaultdrop
cd vaultdrop
pip install -r requirements.txt
```

Or install as a package:
```bash
pip install .
```

## Run the server

```bash
python server.py
# → http://127.0.0.1:5000
```

With options:
```bash
VAULTDROP_DIR=/var/vaultdrop VAULTDROP_MAX_MB=500 python server.py
```

For production (behind nginx):
```bash
gunicorn -w 4 -b 127.0.0.1:5000 server:app
```

## CLI Usage

```bash
# Seal a file (auto-generated passphrase embedded in link)
python vaultdrop_cli.py seal secret.pdf --server http://localhost:5000

# Seal with custom passphrase, 6h TTL, single burn
python vaultdrop_cli.py seal report.xlsx --pass mypassword --ttl 6 --burns 1

# Claim a drop (passphrase from URL fragment)
python vaultdrop_cli.py claim "http://localhost:5000/d/TOKEN#PASSPHRASE"

# Claim with manual passphrase
python vaultdrop_cli.py claim "http://localhost:5000/d/TOKEN" --pass mypassword --out ~/Downloads

# Check if a drop is still alive
python vaultdrop_cli.py status "http://localhost:5000/d/TOKEN"
```

## Security model

```
Sender                          Server                          Recipient
──────                          ──────                          ─────────
1. File + passphrase      →     Encrypt(AES-256-GCM)
2.                              Store ciphertext + nonce
3.                              Return token + link
4. Share link via channel A     (link contains #key in fragment, never logged)
5. Share passphrase via channel B (if custom passphrase used)
                                                        6. Load /d/TOKEN
                                                        7. Enter passphrase
                                                        8. Server decrypts + returns
                                                        9. Browser triggers download
                          DELETE ciphertext ←──────────
```

**Fragment key safety**: When passphrase is auto-generated, it's embedded as `#key` in the URL. URL fragments are not sent to the server in HTTP requests, do not appear in server logs, and are not forwarded by most proxies.

**Separate channel rule**: Never send the passphrase and the link in the same message/email. If the link is intercepted and the passphrase was in the same channel, encryption is useless.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `VAULTDROP_DIR` | `~/.vaultdrop` | Where to store the DB and encrypted files |
| `VAULTDROP_MAX_MB` | `100` | Max upload size in MB |
| `VAULTDROP_TTL_H` | `24` | Default TTL in hours |
| `VAULTDROP_SECRET` | random | Flask secret key (set for persistent sessions) |

## Termux

```bash
pkg install python
pip install flask cryptography click requests
python server.py --host 0.0.0.0 --port 5000
# Access from your LAN at http://PHONE_IP:5000
```

## Requirements

```
flask>=3.0
cryptography>=42.0
click>=8.0
requests>=2.31
```

## License

MIT

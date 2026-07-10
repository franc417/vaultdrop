# vaultdrop

Self-hosted, zero-knowledge, one-time encrypted file sharing. No accounts,
no plaintext ever touching the server, drops that self-destruct after they're
claimed.

Think Firefox Send, but self-hosted and yours.

> **v2.0.0** is a from-scratch security rewrite. Encryption now happens
> entirely in your browser or the CLI — the server only ever sees ciphertext.
> See [`CHANGELOG.md`](CHANGELOG.md) for what changed and
> [`SECURITY.md`](SECURITY.md) for the full threat model.

---

## How it works

1. You pick a file. Your browser (or the CLI) generates a random key,
   encrypts the file locally with **AES-256-GCM**, and uploads only the
   ciphertext.
2. You get a link back. If you didn't set your own passphrase, one is
   auto-generated and embedded in the link itself (`#fragment` — never sent
   to the server).
3. Whoever you send the link to opens it; their browser fetches the
   ciphertext, proves it has the right key (without ever revealing the key
   to the server), and decrypts locally.
4. The drop deletes itself after its download limit, its expiry time, or
   5 wrong-passphrase attempts — whichever comes first.

The server at no point sees your file, your passphrase, or your key.

---

## Quick start (local)

```bash
git clone https://github.com/franc417/vaultdrop.git
cd vaultdrop
pip install -r requirements.txt
python server.py serve --host 127.0.0.1 --port 5000
```

Open **http://127.0.0.1:5000**, drop a file in, copy the link it gives you.

---

## One-line install (Termux / macOS / Arch / Debian / Fedora / openSUSE)

```bash
bash install.sh
```

This installs vaultdrop as a background service appropriate to your platform
(systemd user service on Linux, launchd on macOS, termux-boot on Android)
and adds `vaultdrop` / `vaultdrop-cli` to your `PATH`.

To remove it later:

```bash
bash install.sh --uninstall
```

---

## CLI usage

```bash
# Seal (encrypt + upload) a file — auto-generates a passphrase
python vaultdrop_cli.py --server http://127.0.0.1:5000 seal ./secret.pdf

# Seal with your own passphrase, a 12h expiry, and 3 allowed downloads
python vaultdrop_cli.py --server http://127.0.0.1:5000 seal ./secret.pdf \
    --prompt-pass --ttl 12 --burns 3

# Claim (download + decrypt) a link — paste the FULL link, including #fragment
python vaultdrop_cli.py --server http://127.0.0.1:5000 claim \
    "http://127.0.0.1:5000/d/<token>#<passphrase>"

# Check if a drop is still alive, without consuming it
python vaultdrop_cli.py --server http://127.0.0.1:5000 status \
    "http://127.0.0.1:5000/d/<token>"
```

If you installed via `install.sh`, drop the `python vaultdrop_cli.py` prefix
and just use `vaultdrop-cli seal ...` / `vaultdrop-cli claim ...`.

### Seal options

| Flag             | Default | Description                                    |
|-------------------|---------|-------------------------------------------------|
| `--pass TEXT`      | random  | Use a specific passphrase instead of a random one |
| `--prompt-pass`    | off     | Prompt for a passphrase with hidden input        |
| `--ttl HOURS`       | 24      | Expire after this many hours (max 168 / 7 days) |
| `--burns N`         | 1       | Self-destruct after N downloads (max 10)         |

---

## Web usage

1. Go to the vaultdrop URL.
2. Drag a file in, or click to browse.
3. (Optional) Set your own passphrase, expiry, and download limit — otherwise
   sane defaults are used and a strong passphrase is generated for you.
4. Click **Encrypt & Seal**. Copy the link shown.
5. Send the link to the recipient.
   - If a passphrase was **auto-generated**, it's already embedded in the
     link — just send the link as-is, but treat that link like the file
     itself (whoever has it can open the drop).
   - If you **set your own passphrase**, send the link and the passphrase
     over two different channels (e.g. link over email, passphrase over
     text/Signal) so intercepting one alone isn't enough.
6. The recipient opens the link, and the file downloads automatically once
   decrypted (or after they enter the passphrase, if one wasn't embedded).

---

## Docker

```bash
docker compose up -d --build
```

Serves on `127.0.0.1:5000` by default — put a reverse proxy in front for
public access (see below).

---

## Deploying this publicly

**Do not expose vaultdrop over plain HTTP on the internet.** Zero-knowledge
encryption protects the file from the *server*, not from anyone
eavesdropping on an unencrypted connection. Read
[`DEPLOY.md`](DEPLOY.md) for TLS reverse-proxy setup (Caddy and nginx
configs included) before going live.

Minimal version of what you need:

```bash
# 1. Run vaultdrop behind gunicorn, bound to localhost only
gunicorn -w 2 -b 127.0.0.1:5000 server:app

# 2. Put Caddy or nginx in front of it with a real TLS cert
# 3. Once TLS is confirmed working:
export VAULTDROP_TRUST_PROXY=1
```

---

## Configuration

Environment variables (all optional):

| Variable                | Default          | Meaning                                     |
|---------------------------|------------------|-----------------------------------------------|
| `VAULTDROP_DIR`            | `~/.vaultdrop`   | Where the DB and encrypted blobs are stored |
| `VAULTDROP_MAX_MB`         | `100`            | Max ciphertext size per drop                |
| `VAULTDROP_TTL_H`          | `24`             | Default expiry, in hours                    |
| `VAULTDROP_TRUST_PROXY`    | `0`              | Set to `1` only behind a trusted reverse proxy |
| `VAULTDROP_LOG_LEVEL`      | `INFO`           | Python logging level                        |

---

## Security

- AES-256-GCM, key derived via PBKDF2-HMAC-SHA256 (600,000 iterations)
- Encryption/decryption happen client-side only (browser WebCrypto or the
  Python CLI) — the server never has the key or the plaintext
- Downloads are gated behind proof-of-key-possession (HMAC verifier),
  constant-time compared
- 5 consecutive wrong passphrase attempts self-destructs the drop
- Per-IP rate limiting on every endpoint
- Drops self-delete on TTL expiry or once their download limit is hit

Full details and known limitations: [`SECURITY.md`](SECURITY.md).

Found a vulnerability? Please open a private GitHub security advisory
rather than a public issue.

---

## License

MIT — see [`LICENSE`](LICENSE).

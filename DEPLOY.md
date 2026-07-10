# Deploying vaultdrop v2 publicly

vaultdrop's zero-knowledge design only protects the file/passphrase from the
**server**. It does not protect the connection itself — you still need TLS,
or an attacker on the network path can see ciphertext being requested and,
worse, could serve tampered JS to a client (there's no Subresource Integrity
across a plain-HTTP connection). **Never expose vaultdrop over plain HTTP on
the public internet.**

## 1. Run the app server with gunicorn, not the Flask dev server

```bash
pip install -r requirements.txt
gunicorn -w 2 -b 127.0.0.1:5000 server:app
```

The installer's systemd/launchd/termux-boot units already do this for you.

## 2. Put a TLS-terminating reverse proxy in front of it

### Caddy (simplest — automatic HTTPS via Let's Encrypt)

```
drop.example.com {
    reverse_proxy 127.0.0.1:5000
}
```

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name drop.example.com;

    ssl_certificate     /etc/letsencrypt/live/drop.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/drop.example.com/privkey.pem;

    client_max_body_size 105M;  # match VAULTDROP_MAX_MB + overhead

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 3. Tell vaultdrop to trust the proxy's forwarded headers

Only do this once step 2 is actually in place — otherwise a client can spoof
`X-Forwarded-For` and defeat per-IP rate limiting.

```bash
export VAULTDROP_TRUST_PROXY=1
```

## 4. Environment variables

| Variable                  | Default          | Purpose                                    |
|----------------------------|------------------|---------------------------------------------|
| `VAULTDROP_DIR`             | `~/.vaultdrop`   | Where the DB and encrypted blobs live       |
| `VAULTDROP_MAX_MB`          | `100`            | Max ciphertext size per drop                |
| `VAULTDROP_TTL_H`           | `24`             | Default expiry, in hours                    |
| `VAULTDROP_TRUST_PROXY`     | `0`              | Set `1` only behind a trusted reverse proxy |
| `VAULTDROP_LOG_LEVEL`       | `INFO`           | Python logging level                        |

## 5. Firewall / hosting notes

- Bind gunicorn to `127.0.0.1` only; let the reverse proxy be the only thing
  listening on a public interface.
- Back up `$VAULTDROP_DIR/vault.db` if you care about drop metadata surviving
  a crash — though by design it's all short-lived and self-deleting anyway.
- Set up log rotation for gunicorn/nginx access logs; they will contain
  client IPs and tokens (not keys or plaintext), so treat them as
  moderately sensitive.

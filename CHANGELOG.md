# Changelog

## v2.0.0 — Public release hardening

### Breaking change
- **Encryption moved entirely client-side.** v1 sent the passphrase and
  plaintext file to the server, which encrypted them there — not actually
  zero-knowledge. v2's server API is incompatible with v1 clients: the
  `/api/drop` and `/api/download` contracts changed (ciphertext + crypto
  params in, verifier-gated out). Old v1 links will not work against a v2
  server and vice versa.

### Security fixes
1. **True end-to-end encryption** — server never receives plaintext, the
   passphrase, or the derived key. Both the browser (WebCrypto) and CLI
   (`cryptography`) encrypt/decrypt locally with matching AES-256-GCM +
   PBKDF2-SHA256 (600,000 iterations, up from v1's 260,000).
2. **Key-possession verifier** (HMAC-SHA256, constant-time compared) gates
   every download — fixes the v1 issue where merely downloading (without
   knowing the key) still consumed the burn count and could deny the real
   recipient.
3. **Attempt-limited lockout** — 5 consecutive wrong verifiers now
   self-destructs the drop, closing the online brute-force path that v1
   left completely open (no rate limit, no lockout on repeated wrong
   passphrases).
4. **Rate limiting** on every endpoint via flask-limiter (new dependency),
   scoped per client IP.
5. **`MAX_CONTENT_LENGTH`** now set on the Flask app so oversized uploads
   are rejected by Werkzeug before the body is fully buffered, instead of
   v1's read-everything-then-check approach.
6. **`debug=True` is no longer reachable as a default** under any code
   path — v1's bare `python server.py` fell back to debug mode.
7. **Security headers** (CSP, HSTS when behind TLS, X-Frame-Options,
   X-Content-Type-Options, Referrer-Policy, Permissions-Policy) added to
   every response.
8. **`ProxyFix`** support (opt-in via `VAULTDROP_TRUST_PROXY=1`) so rate
   limiting sees real client IPs when deployed behind a reverse proxy,
   instead of the proxy's IP.
9. **Filename/content-type are now inside the encrypted envelope**, not
   server-visible plaintext fields as in v1.
10. **Dead `SECRET_KEY` config removed** — v1 generated one but never used
    it anywhere.
11. **Structured logging** with truncated tokens; no secrets ever reach the
    server so there's nothing sensitive to accidentally log, but tokens are
    still shortened out of caution.

### Other changes
- Production serving now uses gunicorn (installer + systemd/launchd units
  updated); the Flask dev server is documented as dev-only.
- Added `DEPLOY.md` with Caddy/nginx TLS reverse-proxy examples.
- Added `SECURITY.md` describing the threat model and its limits honestly.
- Added `/healthz` endpoint for uptime monitoring.
- Bumped PBKDF2 iterations from 260k → 600k (OWASP 2023 guidance).

## v1.0.0
Initial release — server-side AES-256-GCM encryption, SQLite metadata,
TTL + burn-count expiry, cross-platform installer (Termux/macOS/Linux).

# vaultdrop v2 — security model

## What's protected

- **The server never sees plaintext, the passphrase, or the derived key.**
  Encryption/decryption happen entirely client-side (browser WebCrypto or
  the CLI, using the same AES-256-GCM + PBKDF2-SHA256/600k-iterations
  scheme). The server only stores/relays ciphertext plus non-secret crypto
  parameters (salt, nonce, iteration count) and an HMAC verifier that
  proves key possession without revealing the key.
- **Downloads are gated on proof of key possession**, not just a token.
  Requesting the ciphertext without the right key doesn't burn the drop or
  reveal anything — the server checks a constant-time HMAC comparison first.
- **Online brute-forcing is rate-limited and capped.** 5 consecutive wrong
  verifiers self-destructs the drop. Per-IP rate limits apply to every
  endpoint via flask-limiter.
- **Filename and content-type are inside the encrypted envelope**, not
  server-visible metadata.
- **Drops self-delete** on TTL expiry, on hitting the burn/download limit,
  or after too many failed attempts.

## What's NOT protected (inherent limits, not bugs)

- **Transport security is your responsibility.** Zero-knowledge encryption
  doesn't help if the connection itself is unencrypted — see `DEPLOY.md`
  and always run this behind TLS in production.
- **Offline brute-forcing of a weak, user-chosen passphrase is not
  preventable** once an attacker has the ciphertext (e.g. because they
  intercepted a share link before the recipient claimed it, or a failed
  drop wasn't cleaned up yet). This is true of any password-based E2E
  scheme. Prefer the auto-generated passphrase (~192 bits of entropy,
  embedded in the link fragment) unless you specifically need a
  human-memorable password.
- **Browser JS integrity.** The client trusts the JS served by this app.
  If the server (or a MITM without TLS) is compromised, it could serve
  malicious JS that exfiltrates keys before encryption. TLS + keeping the
  server patched are the mitigations; this is the same trust model as any
  web-based E2E tool (Signal Desktop's web client, Firefox Send, etc.).
- **Link = secret, when using auto-generated passphrases.** Anyone who
  obtains the full URL (including the `#fragment`) can open the drop.
  Fragments aren't sent to servers or usually logged, but they can leak via
  browser history, shoulder-surfing, or a referrer-less link shared in a
  chat that itself isn't private. Share the link over a channel you trust.
- **Metadata the server does still see:** ciphertext size (rounded up by
  AES-GCM's fixed overhead), upload/claim timestamps, and the uploader's IP
  (used only for rate limiting; not stored beyond that unless you add your
  own request logging).

## Reporting a vulnerability

Open a private security advisory on the GitHub repo rather than a public
issue.

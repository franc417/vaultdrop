/*
 * vaultdrop v2 — client-side crypto (zero-knowledge)
 *
 * Everything here runs in the browser. The server NEVER receives:
 *   - the plaintext file
 *   - the passphrase
 *   - the derived AES key
 *
 * Only the ciphertext, salt, nonce, iteration count, and an HMAC
 * "verifier" (proof of key possession that reveals nothing about the
 * key itself) ever cross the network.
 */

const KDF_ITERATIONS = 600000;   // OWASP 2023 PBKDF2-SHA256 minimum-ish, client-side cost is cheap
const VERIFIER_LABEL = "vaultdrop-verify-v1";

function toB64(bytes) {
  let bin = "";
  const arr = new Uint8Array(bytes);
  for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
  return btoa(bin);
}

function fromB64(str) {
  const bin = atob(str);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}

function toHex(bytes) {
  return Array.from(new Uint8Array(bytes)).map(b => b.toString(16).padStart(2, "0")).join("");
}

/** URL-safe random passphrase, ~192 bits of entropy. Used when the user
 *  doesn't supply their own — this is the recommended default since it
 *  makes offline brute-forcing infeasible (unlike a human-chosen password). */
function generatePassphrase() {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return toB64(bytes).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function deriveKeyMaterial(passphrase, saltBytes, iterations) {
  const enc = new TextEncoder();
  const baseKey = await crypto.subtle.importKey(
    "raw", enc.encode(passphrase), "PBKDF2", false, ["deriveBits"]
  );
  return crypto.subtle.deriveBits(
    { name: "PBKDF2", salt: saltBytes, iterations, hash: "SHA-256" },
    baseKey, 256
  ); // ArrayBuffer, 32 raw bytes
}

async function importAesKey(rawKeyBits) {
  return crypto.subtle.importKey("raw", rawKeyBits, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function importHmacKey(rawKeyBits) {
  return crypto.subtle.importKey(
    "raw", rawKeyBits, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
}

async function computeVerifier(rawKeyBits) {
  const hmacKey = await importHmacKey(rawKeyBits);
  const sig = await crypto.subtle.sign("HMAC", hmacKey, new TextEncoder().encode(VERIFIER_LABEL));
  return toHex(sig);
}

/**
 * Encrypt a File into an opaque ciphertext blob. Filename/type are bundled
 * INSIDE the encrypted envelope so the server never learns them either.
 */
async function encryptFile(file, passphrase, onProgress) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const iterations = KDF_ITERATIONS;

  const rawKeyBits = await deriveKeyMaterial(passphrase, salt, iterations);
  const aesKey = await importAesKey(rawKeyBits);
  const verifier = await computeVerifier(rawKeyBits);

  if (onProgress) onProgress("reading");
  const fileBytes = new Uint8Array(await file.arrayBuffer());

  const envelope = {
    name: file.name,
    type: file.type || "application/octet-stream",
    size: fileBytes.length,
    data: toB64(fileBytes),
  };
  const plaintext = new TextEncoder().encode(JSON.stringify(envelope));

  if (onProgress) onProgress("encrypting");
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: nonce }, aesKey, plaintext
  );

  return {
    ciphertext: new Uint8Array(ciphertext),
    salt: toB64(salt),
    nonce: toB64(nonce),
    kdf_iterations: iterations,
    verifier,
  };
}

/** Decrypt a ciphertext blob back into {name, type, size, bytes}. */
async function decryptBlob(ciphertextBytes, saltB64, nonceB64, iterations, passphrase) {
  const salt = fromB64(saltB64);
  const nonce = fromB64(nonceB64);

  const rawKeyBits = await deriveKeyMaterial(passphrase, salt, iterations);
  const aesKey = await importAesKey(rawKeyBits);
  const verifier = await computeVerifier(rawKeyBits);

  let plaintextBuf;
  try {
    plaintextBuf = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: nonce }, aesKey, ciphertextBytes
    );
  } catch (e) {
    throw new Error("Decryption failed — wrong passphrase or corrupted data.");
  }

  const envelope = JSON.parse(new TextDecoder().decode(plaintextBuf));
  return {
    name: envelope.name,
    type: envelope.type,
    size: envelope.size,
    bytes: fromB64(envelope.data),
    verifier,
  };
}

function fmtSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

function fmtTs(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleString();
}

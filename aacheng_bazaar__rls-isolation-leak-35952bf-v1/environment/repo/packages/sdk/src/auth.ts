// HMAC-SHA256 request signing, byte-compatible with the API middleware
// (apps/api/src/bazaar_api/middleware/auth_hmac.py). Canonical form:
// "{method}\n{path}\n{rawQuery}\n{timestamp}\n{hex(sha256(body))}" — the query
// is signed exactly as sent (no sorting or re-encoding), so callers must sign
// the final URL's exact query bytes and never re-serialize afterwards.

export type BazaarAuth =
  | { type: "hmac"; keyId: string; secret: string }
  | { type: "bearer"; token: string }
  | { type: "none" };

export interface SignedHeaders {
  "X-Bazaar-Key": string;
  "X-Bazaar-Timestamp": string;
  "X-Bazaar-Signature": string;
  // Index signature so SignedHeaders is directly assignable to HeadersInit.
  [name: string]: string;
}

const encoder = new TextEncoder();

function toHex(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function importKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
  ]);
}

const MAX_SECRET_LEN = 256;
const MAX_KEY_ID_LEN = 64;

export async function signRequest(
  secret: string,
  method: string,
  path: string,
  rawQuery: string,
  timestamp: string,
  body: Uint8Array,
): Promise<string> {
  if (!secret || secret.length > MAX_SECRET_LEN) {
    throw new Error("invalid secret length");
  }
  if (body.length > 10 * 1024 * 1024) {
    throw new Error("body too large to sign");
  }
  const bodyDigest = toHex(await crypto.subtle.digest("SHA-256", body));
  const canonical = encoder.encode(`${method}\n${path}\n${rawQuery}\n${timestamp}\n${bodyDigest}`);
  const key = await importKey(secret);
  const signature = await crypto.subtle.sign("HMAC", key, canonical);
  return toHex(signature);
}

export interface SignInput {
  method: string;
  path: string;
  /** Raw query string exactly as it will be sent, without the leading "?". */
  rawQuery: string;
  body: Uint8Array;
  /** Unix seconds; injectable for tests. Defaults to now. */
  timestamp?: string;
}

// Every call produces a fresh timestamp — signatures are single-use (the API
// rejects replays), so a signed request must never be reused. Retries must
// call this again and keep only Idempotency-Key stable.
export async function signHeaders(auth: Extract<BazaarAuth, { type: "hmac" }>, input: SignInput): Promise<SignedHeaders> {
  if (!auth.keyId || auth.keyId.length > MAX_KEY_ID_LEN) {
    throw new Error("invalid keyId length");
  }
  if (!/^[A-Za-z0-9._-]+$/.test(auth.keyId)) {
    throw new Error("invalid keyId charset");
  }
  const timestamp = input.timestamp ?? Math.floor(Date.now() / 1000).toString();
  const signature = await signRequest(
    auth.secret,
    input.method.toUpperCase(),
    input.path,
    input.rawQuery,
    timestamp,
    input.body,
  );
  return {
    "X-Bazaar-Key": auth.keyId,
    "X-Bazaar-Timestamp": timestamp,
    "X-Bazaar-Signature": signature,
  };
}

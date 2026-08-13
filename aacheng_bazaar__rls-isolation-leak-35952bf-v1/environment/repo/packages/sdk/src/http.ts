// Signing fetch: a fetch-compatible wrapper that slots into the generated
// client as its `fetch`. The generated client hands over a fully-built
// Request (final URL with serialized query, serialized body bytes); this
// wrapper signs those exact bytes and forwards the request unchanged — the
// API signs the raw query as sent, so nothing may re-serialize after signing.
//
// Retry contract (middleware/auth_hmac.py): signatures are single-use, so
// every attempt re-signs with a fresh timestamp while the Request's headers
// (notably Idempotency-Key) stay stable. Only 429 (honoring Retry-After) and
// network errors are retried, bounded; other 4xx return immediately.

import { signHeaders, type BazaarAuth } from "./auth.js";
import { BazaarNetworkError } from "./errors.js";

export interface SigningFetchOptions {
  fetchImpl?: typeof fetch | undefined;
  /** Additional attempts after the first. Default 2. */
  maxRetries?: number | undefined;
  /** Injectable for tests. */
  sleep?: ((ms: number) => Promise<void>) | undefined;
}

const DEFAULT_MAX_RETRIES = 2;

// 429 without Retry-After: start at 1s so the re-signed request lands in a
// later unix-second than the consumed signature (same-second re-signs
// reproduce the identical signature and are rejected as replays).
const RETRY_BACKOFF_MS = [1000, 2000];

export function retryAfterToMs(value: string | null): number | undefined {
  if (value === null) {
    return undefined;
  }
  const seconds = Number(value);
  if (Number.isFinite(seconds)) {
    return Math.max(0, seconds * 1000);
  }
  const date = Date.parse(value);
  return Number.isNaN(date) ? undefined : Math.max(0, date - Date.now());
}

export function retryAfterToSeconds(value: string | null): number | undefined {
  if (value === null) {
    return undefined;
  }
  const seconds = Number(value);
  return Number.isFinite(seconds) ? Math.max(0, seconds) : undefined;
}

function backoffMs(attempt: number): number {
  return RETRY_BACKOFF_MS[Math.min(attempt, RETRY_BACKOFF_MS.length - 1)]!;
}

export function createSigningFetch(
  auth: BazaarAuth,
  opts?: SigningFetchOptions,
): typeof fetch {
  const fetchImpl = opts?.fetchImpl ?? globalThis.fetch;
  const maxRetries = opts?.maxRetries ?? DEFAULT_MAX_RETRIES;
  const sleep = opts?.sleep ?? ((ms: number) => new Promise((r) => setTimeout(r, ms)));

  return async (input) => {
    // The generated client always hands over a fully-built Request (final URL
    // with serialized query, serialized body bytes) — assert rather than
    // re-serialize: signing raw input bytes is the whole contract.
    if (!(input instanceof Request)) {
      throw new BazaarNetworkError("signing fetch requires a Request input");
    }
    const request = input;
    const url = new URL(request.url);
    const method = request.method.toUpperCase();
    const body = new Uint8Array(await request.arrayBuffer());

    let attempt = 0;
    for (;;) {
      // Fresh timestamp per attempt — a retry reusing the original signature
      // is rejected as a replay before it reaches the idempotency layer.
      const headers = new Headers(request.headers);
      if (auth.type === "hmac") {
        const signed = await signHeaders(auth, {
          method,
          path: url.pathname,
          rawQuery: url.search.startsWith("?") ? url.search.slice(1) : url.search,
          body,
        });
        for (const [name, value] of Object.entries(signed)) {
          headers.set(name, value);
        }
      } else if (auth.type === "bearer") {
        headers.set("Authorization", `Bearer ${auth.token}`);
      }

      let response: Response;
      try {
        response = await fetchImpl(
          new Request(request.url, {
            method,
            headers,
            body: body.byteLength > 0 ? body : undefined,
          }),
        );
      } catch (cause) {
        if (attempt < maxRetries) {
          await sleep(backoffMs(attempt));
          attempt += 1;
          continue;
        }
        throw new BazaarNetworkError(
          `${method} ${url.pathname} failed after ${attempt + 1} attempts: ${(cause as Error)?.message ?? cause}`,
          { cause },
        );
      }

      if (response.status === 429 && attempt < maxRetries) {
        await sleep(retryAfterToMs(response.headers.get("Retry-After")) ?? backoffMs(attempt));
        attempt += 1;
        continue;
      }

      return response;
    }
  };
}

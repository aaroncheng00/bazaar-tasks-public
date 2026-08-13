// Auth contract: proves the SDK's HMAC signing is byte-compatible with the
// live API middleware (verify_signature + Redis nonce store). A signed
// request that passes auth reaches the (currently stubbed) handler and comes
// back 501 not_implemented — so 501 is the "auth passed" signal.

import { describe, expect, it } from "vitest";

import { signHeaders } from "../../src/auth.js";
import { BazaarAuthError, BazaarError, InvalidSignatureError } from "../../src/errors.js";
import { BASE_URL, KEY_ID, SECRET, makeClient } from "./helpers.js";

async function rawSignedRequest(
  path: string,
  query: string,
  timestamp: string,
): Promise<{ status: number; envelope: { error?: { code?: string } } }> {
  const signed = await signHeaders(
    { type: "hmac", keyId: KEY_ID, secret: SECRET },
    { method: "GET", path, rawQuery: query, body: new Uint8Array(), timestamp },
  );
  const response = await fetch(`${BASE_URL}${path}${query ? `?${query}` : ""}`, {
    headers: new Headers(signed),
  });
  return { status: response.status, envelope: await response.json() };
}

describe("healthz (unauthenticated)", () => {
  it("returns 200 with a spec-shaped body", async () => {
    const health = await makeClient().healthz();
    expect(health.status).toBe("ok");
    expect(health.db).toBeDefined();
    expect(health.redis).toBeDefined();
  });
});

describe("HMAC auth against the live middleware", () => {
  it("a correctly signed request passes auth and reaches the handler (501 stub)", async () => {
    // Unique listing id: the nonce store keys on the signature, which covers
    // method+path+query+timestamp+body — two identical requests signed in the
    // same second are indistinguishable and the second is a replay.
    const err = await makeClient()
      .listings.get("lst_00000000-0000-0000-0000-000000000001")
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BazaarError);
    expect((err as BazaarError).code).toBe("not_implemented");
    expect((err as BazaarError).status).toBe(501);
  });

  it("a wrong secret is rejected as invalid_signature", async () => {
    const err = await makeClient({ secret: "bzs_wrong_secret" })
      .listings.get("lst_00000000-0000-0000-0000-000000000000")
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(InvalidSignatureError);
    expect((err as BazaarError).code).toBe("invalid_signature");
    expect((err as BazaarError).status).toBe(401);
  });

  it("a replayed signature is rejected as replay_detected", async () => {
    const timestamp = Math.floor(Date.now() / 1000).toString();
    // First use of the signature: passes auth, hits the 501 stub.
    const first = await rawSignedRequest("/v1/listings", "limit=1", timestamp);
    expect(first.status).toBe(501);
    // Identical signature again: single-use nonce consumed → replay.
    const second = await rawSignedRequest("/v1/listings", "limit=1", timestamp);
    expect(second.status).toBe(401);
    expect(second.envelope.error?.code).toBe("replay_detected");
  });

  it("a stale timestamp is rejected as stale_timestamp", async () => {
    const stale = (Math.floor(Date.now() / 1000) - 600).toString();
    const { status, envelope } = await rawSignedRequest("/v1/listings", "", stale);
    expect(status).toBe(401);
    expect(envelope.error?.code).toBe("stale_timestamp");
  });

  it("a request without auth headers is rejected as missing_auth_headers", async () => {
    const response = await fetch(`${BASE_URL}/v1/listings`);
    expect(response.status).toBe(401);
    const envelope = await response.json();
    expect(envelope.error?.code).toBe("missing_auth_headers");
  });

  it("an unknown key is rejected as unknown_key", async () => {
    const timestamp = Math.floor(Date.now() / 1000).toString();
    const signed = await signHeaders(
      { type: "hmac", keyId: "bzk_unknown", secret: SECRET },
      { method: "GET", path: "/v1/listings", rawQuery: "", body: new Uint8Array(), timestamp },
    );
    const response = await fetch(`${BASE_URL}/v1/listings`, { headers: new Headers(signed) });
    expect(response.status).toBe(401);
    const envelope = await response.json();
    expect(envelope.error?.code).toBe("unknown_key");
  });

  it("SDK-thrown auth errors carry the request_id from the envelope", async () => {
    const err = await makeClient({ secret: "nope" })
      .listings.browse()
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BazaarAuthError);
    expect((err as BazaarError).requestId).toMatch(/^req_/);
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BazaarAuth } from "../../src/auth.js";
import { BazaarNetworkError } from "../../src/errors.js";
import { createSigningFetch, retryAfterToMs } from "../../src/http.js";

const AUTH: BazaarAuth = { type: "hmac", keyId: "bzk_dev", secret: "bzs_dev_secret" };
const BASE = "http://localhost:8000";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

describe("createSigningFetch", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let sleeps: number[];
  const sleep = (ms: number) => {
    sleeps.push(ms);
    return Promise.resolve();
  };

  beforeEach(() => {
    fetchMock = vi.fn();
    sleeps = [];
    vi.useFakeTimers();
    vi.setSystemTime(1785960000 * 1000);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const signingFetch = (auth: BazaarAuth = AUTH) =>
    createSigningFetch(auth, { fetchImpl: fetchMock as unknown as typeof fetch, sleep });

  it("signs the exact method/path/rawQuery/body bytes of the built Request", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { items: [] }));
    const request = new Request(`${BASE}/v1/listings?category=baby-gear&condition=like-new&limit=20&offset=0`, {
      method: "GET",
      headers: { "Idempotency-Key": "ik_1" },
    });
    const response = await signingFetch()(request);

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const sent = fetchMock.mock.calls[0]![0] as Request;
    expect(sent.url).toBe(request.url);
    // Golden vector 1 from tests/unit/auth.test.ts (timestamp pinned via fake clock).
    expect(sent.headers.get("X-Bazaar-Signature")).toBe(
      "106dc25ee6746f4617085bbaa50ff18920285ff725ac88dfa0bb622c3a27fadd",
    );
    expect(sent.headers.get("X-Bazaar-Key")).toBe("bzk_dev");
    expect(sent.headers.get("X-Bazaar-Timestamp")).toBe("1785960000");
  });

  it("signs the serialized body bytes verbatim", async () => {
    fetchMock.mockResolvedValue(jsonResponse(201, {}));
    // Golden vector 3 from tests/unit/auth.test.ts uses this timestamp.
    vi.setSystemTime(1785960002 * 1000);
    const body = '{"price_cents":3900}';
    const request = new Request(`${BASE}/v1/listings/lst_123`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body,
    });
    await signingFetch()(request);

    const sent = fetchMock.mock.calls[0]![0] as Request;
    expect(await sent.text()).toBe(body);
    // Golden vector 3 from tests/unit/auth.test.ts.
    expect(sent.headers.get("X-Bazaar-Signature")).toBe(
      "63d46a194948d09cb796123afc0e919817dc751b086cc0cbef90fbee58586e05",
    );
  });

  it("429: retries after Retry-After, re-signing with a fresh timestamp, Idempotency-Key stable", async () => {
    fetchMock
      .mockImplementationOnce(async () => {
        // The first attempt is signed before this impl runs; advancing the
        // clock here guarantees the retry re-signs with a fresh timestamp.
        vi.setSystemTime((1785960000 + 2) * 1000);
        return jsonResponse(429, { error: { code: "rate_limited" } }, { "Retry-After": "2" });
      })
      .mockResolvedValueOnce(jsonResponse(201, { id: "lst_1" }));

    const request = new Request(`${BASE}/v1/listings`, {
      method: "POST",
      headers: { "Idempotency-Key": "ik_42", "Content-Type": "application/json" },
      body: '{"title":"x"}',
    });
    const response = await signingFetch()(request);

    expect(response.status).toBe(201);
    expect(sleeps).toEqual([2000]);
    const first = fetchMock.mock.calls[0]![0] as Request;
    const second = fetchMock.mock.calls[1]![0] as Request;
    expect(first.headers.get("Idempotency-Key")).toBe("ik_42");
    expect(second.headers.get("Idempotency-Key")).toBe("ik_42");
    expect(first.headers.get("X-Bazaar-Timestamp")).toBe("1785960000");
    expect(second.headers.get("X-Bazaar-Timestamp")).toBe("1785960002");
    expect(second.headers.get("X-Bazaar-Signature")).not.toBe(first.headers.get("X-Bazaar-Signature"));
  });

  it("never retries other 4xx", async () => {
    fetchMock.mockResolvedValue(jsonResponse(400, { error: { code: "validation_failed" } }));
    const response = await signingFetch()(new Request(`${BASE}/v1/listings`, { method: "POST", body: "{}" }));
    expect(response.status).toBe(400);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sleeps).toEqual([]);
  });

  it("429 retries exhausted: returns the final 429 for the caller to map", async () => {
    fetchMock.mockResolvedValue(jsonResponse(429, { error: { code: "rate_limited" } }, { "Retry-After": "1" }));
    const response = await signingFetch()(new Request(`${BASE}/v1/listings`, { method: "GET" }));
    expect(response.status).toBe(429);
    expect(fetchMock).toHaveBeenCalledTimes(3); // initial + 2 retries
    expect(sleeps).toEqual([1000, 1000]);
  });

  it("network errors retry with backoff and then succeed", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed")).mockResolvedValueOnce(jsonResponse(200, {}));
    const response = await signingFetch()(new Request(`${BASE}/healthz`, { method: "GET" }));
    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(sleeps).toEqual([1000]);
  });

  it("network errors exhausted: throws BazaarNetworkError with the cause", async () => {
    const cause = new TypeError("connection reset");
    fetchMock.mockRejectedValue(cause);
    const err = await signingFetch()(new Request(`${BASE}/healthz`, { method: "GET" })).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BazaarNetworkError);
    expect((err as BazaarNetworkError).code).toBe("network_error");
    expect((err as BazaarNetworkError).status).toBe(0);
    expect((err as BazaarNetworkError).cause).toBe(cause);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("bearer auth sets Authorization and no HMAC headers", async () => {
    fetchMock.mockResolvedValue(jsonResponse(201, {}));
    await signingFetch({ type: "bearer", token: "btok" })(new Request(`${BASE}/v1/apps`, { method: "POST", body: "{}" }));
    const sent = fetchMock.mock.calls[0]![0] as Request;
    expect(sent.headers.get("Authorization")).toBe("Bearer btok");
    expect(sent.headers.get("X-Bazaar-Signature")).toBeNull();
  });

  it("auth none sends no auth headers at all", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, {}));
    await signingFetch({ type: "none" })(new Request(`${BASE}/healthz`, { method: "GET" }));
    const sent = fetchMock.mock.calls[0]![0] as Request;
    expect(sent.headers.get("Authorization")).toBeNull();
    expect(sent.headers.get("X-Bazaar-Key")).toBeNull();
    expect(sent.headers.get("X-Bazaar-Signature")).toBeNull();
  });
});

describe("retryAfterToMs", () => {
  it("parses delta-seconds", () => {
    expect(retryAfterToMs("7")).toBe(7000);
  });

  it("returns undefined for missing or invalid values", () => {
    expect(retryAfterToMs(null)).toBeUndefined();
    expect(retryAfterToMs("soon")).toBeUndefined();
  });
});

import { describe, expect, it, vi } from "vitest";

import { BazaarClient } from "../../src/client.js";
import { BazaarValidationError } from "../../src/validation.js";
import { Category, Condition, Currency } from "../../src/gen/types.gen.js";

const AUTH = { type: "hmac" as const, keyId: "bzk_dev", secret: "bzs_dev_secret" };
const BASE = "http://localhost:8000";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function clientWith(fetchMock: ReturnType<typeof vi.fn>, opts?: { validate?: boolean }) {
  return new BazaarClient({
    baseUrl: BASE,
    auth: AUTH,
    fetch: fetchMock as unknown as typeof fetch,
    validate: opts?.validate,
  });
}

const LISTING = {
  id: "lst_9f1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
  app_id: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  seller_user_id: "u_1",
  title: "Stroller",
  price_cents: 4500,
  currency: Currency.USD,
  category: Category.BABY_GEAR,
  condition: Condition.LIKE_NEW,
  status: "active",
  lat: 37.44,
  lng: -122.14,
  image_keys: [],
  image_urls: [],
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function sentRequest(fetchMock: ReturnType<typeof vi.fn>, index = 0): Request {
  return fetchMock.mock.calls[index]![0] as Request;
}

describe("BazaarClient facade", () => {
  it("unwraps data on success and validates it against the spec schema", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, LISTING));
    const client = clientWith(fetchMock);

    const listing = await client.listings.create(
      {
        title: "Stroller",
        price_cents: 4500,
        currency: Currency.USD,
        category: Category.BABY_GEAR,
        condition: Condition.LIKE_NEW,
        seller_user_id: "u_1",
        lat: 37.44,
        lng: -122.14,
      },
      { idempotencyKey: "9f1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d" },
    );

    expect(listing.id).toBe(LISTING.id);
    const sent = sentRequest(fetchMock);
    expect(sent.method).toBe("POST");
    expect(sent.url).toBe(`${BASE}/v1/listings`);
    expect(sent.headers.get("Idempotency-Key")).toBe("9f1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d");
    expect(sent.headers.get("X-Bazaar-Signature")).toMatch(/^[0-9a-f]{64}$/);
  });

  it("generates Idempotency-Key on listings.create when omitted", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, LISTING));
    const client = clientWith(fetchMock);
    await client.listings.create({
      title: "Stroller",
      price_cents: 4500,
      currency: Currency.USD,
      category: Category.BABY_GEAR,
      condition: Condition.LIKE_NEW,
      seller_user_id: "u_1",
      lat: 37.44,
      lng: -122.14,
    });
    expect(sentRequest(fetchMock).headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("passes browse query params through to the URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { data: [], pagination: { total: 0, limit: 20, offset: 0, has_more: false } }),
    );
    const client = clientWith(fetchMock);
    await client.listings.browse({ category: Category.BABY_GEAR, limit: 20, offset: 0 });
    expect(sentRequest(fetchMock).url).toBe(`${BASE}/v1/listings?category=baby-gear&limit=20&offset=0`);
  });

  it("throws typed errors mapped from the envelope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(404, { error: { code: "listing_not_found", message: "nope", request_id: "req_1" } }),
    );
    const client = clientWith(fetchMock);
    const err = await client.listings.get("lst_missing").catch((e: unknown) => e);
    expect(err).toMatchObject({ code: "listing_not_found", status: 404, requestId: "req_1" });
  });

  it("throws BazaarValidationError when the response drifts from the spec", async () => {
    const drifted = { ...LISTING, price_cents: "45.00" };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, drifted));
    const client = clientWith(fetchMock);
    const err = await client.listings.get("lst_1").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BazaarValidationError);
    expect((err as BazaarValidationError).operation).toBe("getListing");
  });

  it("validate: false skips response validation", async () => {
    const drifted = { ...LISTING, price_cents: "45.00" };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, drifted));
    const client = clientWith(fetchMock, { validate: false });
    const listing = await client.listings.get("lst_1");
    expect(listing.price_cents).toBe("45.00");
  });

  it("reviews.aggregate sends subject_user_id as the query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(200, { subject_user_id: "u_9", avg_rating: null, review_count: 0, rating_counts: {} }),
    );
    const client = clientWith(fetchMock);
    await client.reviews.aggregate("u_9");
    expect(sentRequest(fetchMock).url).toBe(`${BASE}/v1/reviews/aggregate?subject_user_id=u_9`);
  });

  it("apps.createKey templates the path param", async () => {
    const keyCreated = {
      key_id: "bzk_new",
      secret: "bzs_new_secret",
      app_id: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      created_at: "2026-08-01T00:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, keyCreated));
    const client = clientWith(fetchMock);
    await client.apps.createKey("3fa85f64-5717-4562-b3fc-2c963f66afa6");
    const sent = sentRequest(fetchMock);
    expect(sent.method).toBe("POST");
    expect(sent.url).toBe(`${BASE}/v1/apps/3fa85f64-5717-4562-b3fc-2c963f66afa6/keys`);
  });
});

// Listings operation matrix: every SDK listings op against the live API.
// All domain handlers are currently 501 stubs (owned by P2/P3/S1), so these
// tests assert the contract that holds TODAY: the SDK serializes, signs, and
// passes real middleware for every operation, and the envelope comes back
// mapped as not_implemented. When a handler lands, flip its assertion to the
// real success response — the test file is the flip list.

import { describe, expect, it } from "vitest";

import { BazaarError, ValidationFailedError } from "../../src/errors.js";
import { Category, Condition, Currency, SortOrder } from "../../src/gen/types.gen.js";
import { makeClient } from "./helpers.js";

const LISTING_ID = "lst_00000000-0000-0000-0000-000000000000";

const VALID_CREATE = {
  seller_user_id: "u_contract",
  title: "Contract-test stroller",
  price_cents: 4500,
  currency: Currency.USD,
  category: Category.BABY_GEAR,
  condition: Condition.LIKE_NEW,
  lat: 37.44,
  lng: -122.14,
};

async function expectNotImplemented(promise: Promise<unknown>): Promise<void> {
  const err = await promise.catch((e: unknown) => e);
  expect(err).toBeInstanceOf(BazaarError);
  expect((err as BazaarError).code).toBe("not_implemented");
  expect((err as BazaarError).status).toBe(501);
}

describe("listings operations reach the API through the SDK", () => {
  it("browse with the full filter set signs the multi-param query correctly", async () => {
    // The heaviest signing case: many query params, enum values, geo pair.
    await expectNotImplemented(
      makeClient().listings.browse({
        q: "stroller",
        category: Category.BABY_GEAR,
        condition: Condition.LIKE_NEW,
        price_min_cents: 1000,
        price_max_cents: 9000,
        lat: 37.44,
        lng: -122.14,
        radius_km: 10,
        sort: SortOrder.NEWEST,
        limit: 20,
        offset: 0,
      }),
    );
  });

  it("create with a valid body passes auth + idempotency middleware", async () => {
    // The facade auto-generates the spec-required Idempotency-Key; a missing
    // key would surface as a middleware 422/401 instead of the 501 stub.
    await expectNotImplemented(makeClient().listings.create(VALID_CREATE));
  });

  it("create with an explicit Idempotency-Key is accepted by the middleware", async () => {
    // Distinct body from the auto-key test: Idempotency-Key is a header and
    // NOT part of the signed bytes, so an identical body signed in the same
    // second would collide in the single-use nonce store (replay_detected).
    await expectNotImplemented(
      makeClient().listings.create(
        { ...VALID_CREATE, title: "Contract-test stroller (explicit key)" },
        { idempotencyKey: crypto.randomUUID() },
      ),
    );
  });

  it("create with a float price_cents fails request validation", async () => {
    // Pydantic rejects the float before the stub runs. NOTE: the API maps
    // request-validation failures to 422 validation_failed; the spec prose
    // says 400 — the envelope code is the stable contract either way.
    const err = await makeClient()
      .listings.create({ ...VALID_CREATE, price_cents: 45.5 })
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ValidationFailedError);
    expect((err as BazaarError).code).toBe("validation_failed");
  });

  it("get templates the path param", async () => {
    await expectNotImplemented(makeClient().listings.get(LISTING_ID));
  });

  it("update sends the patch body", async () => {
    await expectNotImplemented(
      makeClient().listings.update(LISTING_ID, { acting_user_id: "u_contract", price_cents: 3900 }),
    );
  });

  it("createImageUpload posts the upload request", async () => {
    await expectNotImplemented(
      makeClient().listings.createImageUpload(LISTING_ID, {
        acting_user_id: "u_contract",
        content_type: "image/jpeg",
        content_length: 12345,
      }),
    );
  });

  it("attachImage posts the attach request", async () => {
    await expectNotImplemented(
      makeClient().listings.attachImage(LISTING_ID, {
        acting_user_id: "u_contract",
        image_key: "app-a/listings/lst_00000000-0000-0000-0000-000000000000/0.jpg",
      }),
    );
  });

  it("markSold posts the sale record", async () => {
    // Handler landed (S2, T283279728): the all-zero listing does not exist,
    // so the real contract is 404 listing_not_found — which still proves the
    // SDK serialized, signed, and passed auth/idempotency middleware.
    const err = await makeClient()
      .listings.markSold(LISTING_ID, {
        acting_user_id: "u_contract",
        buyer_user_id: "u_buyer",
      })
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BazaarError);
    expect((err as BazaarError).code).toBe("listing_not_found");
    expect((err as BazaarError).status).toBe(404);
  });

  it("remove posts the removal", async () => {
    await expectNotImplemented(
      makeClient().listings.remove(LISTING_ID, { acting_user_id: "u_contract" }),
    );
  });
});

// Reviews operation matrix — same contract as listings: handlers are 501
// stubs today, so these assert SDK↔middleware coherence per operation and
// flip to real assertions as the handlers land.

import { describe, expect, it } from "vitest";

import { BazaarError } from "../../src/errors.js";
import { makeClient } from "./helpers.js";

const LISTING_ID = "lst_00000000-0000-0000-0000-000000000000";

async function expectNotImplemented(promise: Promise<unknown>): Promise<void> {
  const err = await promise.catch((e: unknown) => e);
  expect(err).toBeInstanceOf(BazaarError);
  expect((err as BazaarError).code).toBe("not_implemented");
  expect((err as BazaarError).status).toBe(501);
}

describe("reviews operations reach the API through the SDK", () => {
  it("create posts the review body", async () => {
    // Handler landed (verified-buyer gate, T282737802): the all-zero listing
    // does not exist, and this op deliberately collapses missing/cross-tenant/
    // not-the-buyer into one 403 review_not_eligible (no existence leak).
    const err = await makeClient()
      .reviews.create({
        author_user_id: "u_buyer",
        listing_id: LISTING_ID,
        rating: 5,
        body: "Smooth handoff",
      })
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BazaarError);
    expect((err as BazaarError).code).toBe("review_not_eligible");
    expect((err as BazaarError).status).toBe(403);
  });

  it("list sends subject_user_id with pagination", async () => {
    await expectNotImplemented(
      makeClient().reviews.list({ subject_user_id: "u_seller", limit: 20, offset: 0 }),
    );
  });

  it("aggregate sends subject_user_id", async () => {
    await expectNotImplemented(makeClient().reviews.aggregate("u_seller"));
  });
});
